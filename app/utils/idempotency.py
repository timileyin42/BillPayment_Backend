import hashlib
import json
from typing import Any, Dict, Optional, Union
from datetime import datetime, timedelta
from fastapi import Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, DateTime, Text, Integer

from app.core.database import Base
from app.core.config import settings


class IdempotencyKey(Base):
    """Model to store idempotency keys and their responses."""
    __tablename__ = "idempotency_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, index=True, nullable=False)
    user_id = Column(Integer, nullable=True)  # Optional user association
    endpoint = Column(String(255), nullable=False)
    request_hash = Column(String(64), nullable=False)
    response_data = Column(Text, nullable=True)
    status_code = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class IdempotencyManager:
    """Manager for handling idempotency keys and request deduplication."""
    
    def __init__(self, db: AsyncSession, default_ttl_hours: int = 24):
        self.db = db
        self.default_ttl_hours = default_ttl_hours
    
    def generate_request_hash(self, request_data: Dict[str, Any]) -> str:
        """Generate a hash of the request data for comparison.
        
        Args:
            request_data: Dictionary containing request data
            
        Returns:
            str: SHA-256 hash of the request data
        """
        # Sort the dictionary to ensure consistent hashing
        sorted_data = json.dumps(request_data, sort_keys=True, default=str)
        return hashlib.sha256(sorted_data.encode()).hexdigest()
    
    async def get_or_create_idempotency_record(
        self,
        idempotency_key: str,
        user_id: Optional[int],
        endpoint: str,
        request_data: Dict[str, Any],
        ttl_hours: Optional[int] = None
    ) -> tuple[IdempotencyKey, bool]:
        """Get existing idempotency record or create a new one.
        
        Args:
            idempotency_key: Unique idempotency key
            user_id: Optional user ID
            endpoint: API endpoint path
            request_data: Request data for hashing
            ttl_hours: Time to live in hours
            
        Returns:
            tuple: (IdempotencyKey record, is_new)
        """
        ttl_hours = ttl_hours or self.default_ttl_hours
        request_hash = self.generate_request_hash(request_data)
        
        # Check if idempotency key already exists
        result = await self.db.execute(
            select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
        )
        existing_record = result.scalar_one_or_none()
        
        if existing_record:
            # Check if the record has expired
            if existing_record.expires_at < datetime.utcnow():
                # Delete expired record
                await self.db.delete(existing_record)
                await self.db.commit()
                existing_record = None
            else:
                # Verify request hash matches
                if existing_record.request_hash != request_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency key conflict: request data differs from original"
                    )
                return existing_record, False
        
        # Create new record
        new_record = IdempotencyKey(
            key=idempotency_key,
            user_id=user_id,
            endpoint=endpoint,
            request_hash=request_hash,
            expires_at=datetime.utcnow() + timedelta(hours=ttl_hours)
        )
        
        self.db.add(new_record)
        await self.db.commit()
        await self.db.refresh(new_record)
        
        return new_record, True
    
    async def store_response(
        self,
        idempotency_key: str,
        response_data: Dict[str, Any],
        status_code: int
    ) -> None:
        """Store the response data for an idempotency key.
        
        Args:
            idempotency_key: Unique idempotency key
            response_data: Response data to store
            status_code: HTTP status code
        """
        result = await self.db.execute(
            select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
        )
        record = result.scalar_one_or_none()
        
        if record:
            record.response_data = json.dumps(response_data, default=str)
            record.status_code = status_code
            await self.db.commit()
    
    async def get_stored_response(
        self,
        idempotency_key: str
    ) -> Optional[tuple[Dict[str, Any], int]]:
        """Get stored response for an idempotency key.
        
        Args:
            idempotency_key: Unique idempotency key
            
        Returns:
            Optional tuple of (response_data, status_code)
        """
        result = await self.db.execute(
            select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
        )
        record = result.scalar_one_or_none()
        
        if record and record.response_data:
            response_data = json.loads(record.response_data)
            return response_data, record.status_code
        
        return None
    
    async def cleanup_expired_keys(self) -> int:
        """Clean up expired idempotency keys.
        
        Returns:
            int: Number of expired keys deleted
        """
        result = await self.db.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.expires_at < datetime.utcnow()
            )
        )
        await self.db.commit()
        return result.rowcount


def generate_idempotency_key(
    user_id: Optional[int] = None,
    operation: str = "transaction",
    additional_data: Optional[str] = None
) -> str:
    """Generate a unique idempotency key.
    
    Args:
        user_id: Optional user ID
        operation: Type of operation
        additional_data: Additional data to include in key
        
    Returns:
        str: Generated idempotency key
    """
    timestamp = datetime.utcnow().isoformat()
    components = [operation, timestamp]
    
    if user_id:
        components.append(str(user_id))
    
    if additional_data:
        components.append(additional_data)
    
    key_string = "|".join(components)
    return hashlib.sha256(key_string.encode()).hexdigest()[:32]


class IdempotencyMiddleware:
    """Middleware for handling idempotency automatically."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.manager = IdempotencyManager(db)
    
    async def process_request(
        self,
        request: Request,
        idempotency_key: str,
        user_id: Optional[int] = None,
        ttl_hours: Optional[int] = None
    ) -> Optional[tuple[Dict[str, Any], int]]:
        """Process request with idempotency checking.
        
        Args:
            request: FastAPI request object
            idempotency_key: Idempotency key from header
            user_id: Optional user ID
            ttl_hours: Optional TTL in hours
            
        Returns:
            Optional tuple of (response_data, status_code) if duplicate request
        """
        # Extract request data
        request_data = {
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "query_params": dict(request.query_params)
        }
        
        # Add body if present
        if hasattr(request, "_body"):
            request_data["body"] = request._body.decode() if request._body else ""
        
        # Check for existing response
        stored_response = await self.manager.get_stored_response(idempotency_key)
        if stored_response:
            return stored_response
        
        # Create or get idempotency record
        record, is_new = await self.manager.get_or_create_idempotency_record(
            idempotency_key=idempotency_key,
            user_id=user_id,
            endpoint=str(request.url.path),
            request_data=request_data,
            ttl_hours=ttl_hours
        )
        
        return None
    
    async def store_response(
        self,
        idempotency_key: str,
        response_data: Dict[str, Any],
        status_code: int
    ) -> None:
        """Store response for future idempotency checks.
        
        Args:
            idempotency_key: Idempotency key
            response_data: Response data
            status_code: HTTP status code
        """
        await self.manager.store_response(
            idempotency_key=idempotency_key,
            response_data=response_data,
            status_code=status_code
        )


def extract_idempotency_key(request: Request) -> Optional[str]:
    """Extract idempotency key from request headers.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Optional[str]: Idempotency key if present
    """
    return request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key")


def validate_idempotency_key(key: str) -> bool:
    """Validate idempotency key format.
    
    Args:
        key: Idempotency key to validate
        
    Returns:
        bool: True if key is valid
    """
    if not key:
        return False
    
    # Key should be between 1 and 255 characters
    if len(key) < 1 or len(key) > 255:
        return False
    
    # Key should contain only alphanumeric characters, hyphens, and underscores
    import re
    pattern = r'^[a-zA-Z0-9_-]+$'
    return bool(re.match(pattern, key))


async def require_idempotency_key(
    request: Request,
    db: AsyncSession,
    user_id: Optional[int] = None
) -> str:
    """Dependency that requires and validates an idempotency key.
    
    Args:
        request: FastAPI request object
        db: Database session
        user_id: Optional user ID
        
    Returns:
        str: Valid idempotency key
        
    Raises:
        HTTPException: If idempotency key is missing or invalid
    """
    idempotency_key = extract_idempotency_key(request)
    
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required for this operation"
        )
    
    if not validate_idempotency_key(idempotency_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid idempotency key format"
        )
    
    return idempotency_key