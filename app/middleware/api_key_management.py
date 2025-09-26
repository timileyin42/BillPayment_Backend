"""API key management system with database storage and rotation."""

import secrets
import hashlib
import hmac
from typing import Dict, List, Optional, Set, Any, Tuple
from datetime import datetime, timedelta
from enum import Enum
from fastapi import Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import Column, String, DateTime, Boolean, Integer, Text, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session
import redis
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()

class APIKeyStatus(str, Enum):
    """API key status enumeration."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    REVOKED = "revoked"
    EXPIRED = "expired"
    SUSPENDED = "suspended"

class APIKeyScope(str, Enum):
    """API key scope enumeration."""
    READ_ONLY = "read_only"
    WRITE_ONLY = "write_only"
    READ_WRITE = "read_write"
    ADMIN = "admin"
    WEBHOOK = "webhook"
    PAYMENT = "payment"
    BILLING = "billing"
    USER_MANAGEMENT = "user_management"

class APIKey(Base):
    """API key model for database storage."""
    __tablename__ = "api_keys"
    
    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    key_hash = Column(String(128), nullable=False, unique=True)
    key_prefix = Column(String(16), nullable=False)
    user_id = Column(String(36), nullable=True)  # Optional user association
    client_id = Column(String(255), nullable=True)  # Client/application identifier
    
    # Status and permissions
    status = Column(String(20), nullable=False, default=APIKeyStatus.ACTIVE)
    scopes = Column(Text, nullable=False)  # JSON array of scopes
    
    # Rate limiting
    rate_limit_per_minute = Column(Integer, default=60)
    rate_limit_per_hour = Column(Integer, default=1000)
    rate_limit_per_day = Column(Integer, default=10000)
    
    # IP restrictions
    allowed_ips = Column(Text, nullable=True)  # JSON array of allowed IPs
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    
    # Usage tracking
    total_requests = Column(Integer, default=0)
    last_request_ip = Column(String(45), nullable=True)
    
    # Security
    is_rotatable = Column(Boolean, default=True)
    rotation_interval_days = Column(Integer, default=90)
    last_rotated_at = Column(DateTime, nullable=True)
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_api_keys_hash', 'key_hash'),
        Index('idx_api_keys_prefix', 'key_prefix'),
        Index('idx_api_keys_user_id', 'user_id'),
        Index('idx_api_keys_status', 'status'),
        Index('idx_api_keys_expires_at', 'expires_at'),
    )

class APIKeyManager:
    """Manager for API key operations."""
    
    def __init__(self, 
                 db_session: Session,
                 redis_client: Optional[redis.Redis] = None,
                 default_rate_limits: Optional[Dict[str, int]] = None):
        self.db = db_session
        self.redis = redis_client
        self.default_rate_limits = default_rate_limits or {
            "per_minute": 60,
            "per_hour": 1000,
            "per_day": 10000
        }
        
        # Cache settings
        self.cache_ttl = 300  # 5 minutes
        self.cache_prefix = "api_key:"
    
    def generate_api_key(self, 
                        name: str,
                        scopes: List[APIKeyScope],
                        user_id: Optional[str] = None,
                        client_id: Optional[str] = None,
                        expires_in_days: Optional[int] = None,
                        rate_limits: Optional[Dict[str, int]] = None,
                        allowed_ips: Optional[List[str]] = None) -> Tuple[str, APIKey]:
        """Generate a new API key."""
        try:
            # Generate secure random key
            key_bytes = secrets.token_bytes(32)
            api_key = f"vf_{secrets.token_urlsafe(32)}"
            
            # Create key hash
            key_hash = self._hash_api_key(api_key)
            key_prefix = api_key[:8]
            
            # Set expiration
            expires_at = None
            if expires_in_days:
                expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
            
            # Set rate limits
            rate_limits = rate_limits or self.default_rate_limits
            
            # Create API key record
            api_key_record = APIKey(
                id=secrets.token_urlsafe(16),
                name=name,
                key_hash=key_hash,
                key_prefix=key_prefix,
                user_id=user_id,
                client_id=client_id,
                status=APIKeyStatus.ACTIVE,
                scopes=self._serialize_scopes(scopes),
                rate_limit_per_minute=rate_limits.get("per_minute", 60),
                rate_limit_per_hour=rate_limits.get("per_hour", 1000),
                rate_limit_per_day=rate_limits.get("per_day", 10000),
                allowed_ips=self._serialize_ips(allowed_ips) if allowed_ips else None,
                expires_at=expires_at
            )
            
            # Save to database
            self.db.add(api_key_record)
            self.db.commit()
            
            # Cache the key
            if self.redis:
                self._cache_api_key(api_key_record)
            
            logger.info(f"API key generated: {key_prefix}... for {name}")
            
            return api_key, api_key_record
        
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error generating API key: {e}")
            raise
    
    def validate_api_key(self, 
                        api_key: str, 
                        required_scopes: Optional[List[APIKeyScope]] = None,
                        client_ip: Optional[str] = None) -> Optional[APIKey]:
        """Validate an API key and return key record if valid."""
        try:
            # Hash the provided key
            key_hash = self._hash_api_key(api_key)
            
            # Try to get from cache first
            api_key_record = None
            if self.redis:
                api_key_record = self._get_cached_api_key(key_hash)
            
            # If not in cache, get from database
            if not api_key_record:
                api_key_record = self.db.query(APIKey).filter(
                    APIKey.key_hash == key_hash
                ).first()
                
                if api_key_record and self.redis:
                    self._cache_api_key(api_key_record)
            
            if not api_key_record:
                return None
            
            # Check status
            if api_key_record.status != APIKeyStatus.ACTIVE:
                return None
            
            # Check expiration
            if api_key_record.expires_at and api_key_record.expires_at < datetime.utcnow():
                self._update_key_status(api_key_record.id, APIKeyStatus.EXPIRED)
                return None
            
            # Check IP restrictions
            if api_key_record.allowed_ips and client_ip:
                allowed_ips = self._deserialize_ips(api_key_record.allowed_ips)
                if client_ip not in allowed_ips:
                    logger.warning(f"API key {api_key_record.key_prefix}... used from unauthorized IP: {client_ip}")
                    return None
            
            # Check scopes
            if required_scopes:
                key_scopes = self._deserialize_scopes(api_key_record.scopes)
                if not self._has_required_scopes(key_scopes, required_scopes):
                    return None
            
            # Check rate limits
            if not self._check_rate_limits(api_key_record, client_ip):
                return None
            
            # Update usage statistics
            self._update_usage_stats(api_key_record, client_ip)
            
            return api_key_record
        
        except Exception as e:
            logger.error(f"Error validating API key: {e}")
            return None
    
    def rotate_api_key(self, key_id: str) -> Optional[Tuple[str, APIKey]]:
        """Rotate an existing API key."""
        try:
            # Get existing key
            existing_key = self.db.query(APIKey).filter(APIKey.id == key_id).first()
            if not existing_key or not existing_key.is_rotatable:
                return None
            
            # Generate new key
            new_api_key = f"vf_{secrets.token_urlsafe(32)}"
            new_key_hash = self._hash_api_key(new_api_key)
            new_key_prefix = new_api_key[:8]
            
            # Update existing record
            existing_key.key_hash = new_key_hash
            existing_key.key_prefix = new_key_prefix
            existing_key.last_rotated_at = datetime.utcnow()
            existing_key.updated_at = datetime.utcnow()
            
            self.db.commit()
            
            # Update cache
            if self.redis:
                self._invalidate_cached_api_key(existing_key.key_hash)
                self._cache_api_key(existing_key)
            
            logger.info(f"API key rotated: {existing_key.name} ({new_key_prefix}...)")
            
            return new_api_key, existing_key
        
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error rotating API key {key_id}: {e}")
            return None
    
    def revoke_api_key(self, key_id: str) -> bool:
        """Revoke an API key."""
        try:
            api_key_record = self.db.query(APIKey).filter(APIKey.id == key_id).first()
            if not api_key_record:
                return False
            
            api_key_record.status = APIKeyStatus.REVOKED
            api_key_record.updated_at = datetime.utcnow()
            
            self.db.commit()
            
            # Remove from cache
            if self.redis:
                self._invalidate_cached_api_key(api_key_record.key_hash)
            
            logger.info(f"API key revoked: {api_key_record.name} ({api_key_record.key_prefix}...)")
            
            return True
        
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error revoking API key {key_id}: {e}")
            return False
    
    def list_api_keys(self, 
                     user_id: Optional[str] = None,
                     status: Optional[APIKeyStatus] = None,
                     limit: int = 100) -> List[Dict[str, Any]]:
        """List API keys with optional filtering."""
        try:
            query = self.db.query(APIKey)
            
            if user_id:
                query = query.filter(APIKey.user_id == user_id)
            
            if status:
                query = query.filter(APIKey.status == status)
            
            api_keys = query.limit(limit).all()
            
            # Return safe representation (no sensitive data)
            return [
                {
                    "id": key.id,
                    "name": key.name,
                    "key_prefix": key.key_prefix,
                    "status": key.status,
                    "scopes": self._deserialize_scopes(key.scopes),
                    "created_at": key.created_at.isoformat(),
                    "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
                    "expires_at": key.expires_at.isoformat() if key.expires_at else None,
                    "total_requests": key.total_requests,
                    "rate_limits": {
                        "per_minute": key.rate_limit_per_minute,
                        "per_hour": key.rate_limit_per_hour,
                        "per_day": key.rate_limit_per_day
                    }
                }
                for key in api_keys
            ]
        
        except Exception as e:
            logger.error(f"Error listing API keys: {e}")
            return []
    
    def get_api_key_stats(self, key_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed statistics for an API key."""
        try:
            api_key_record = self.db.query(APIKey).filter(APIKey.id == key_id).first()
            if not api_key_record:
                return None
            
            # Get rate limit usage from Redis
            rate_limit_usage = {}
            if self.redis:
                rate_limit_usage = self._get_rate_limit_usage(api_key_record)
            
            return {
                "id": api_key_record.id,
                "name": api_key_record.name,
                "status": api_key_record.status,
                "total_requests": api_key_record.total_requests,
                "last_used_at": api_key_record.last_used_at.isoformat() if api_key_record.last_used_at else None,
                "last_request_ip": api_key_record.last_request_ip,
                "rate_limit_usage": rate_limit_usage,
                "days_until_expiry": (
                    (api_key_record.expires_at - datetime.utcnow()).days 
                    if api_key_record.expires_at else None
                ),
                "needs_rotation": self._needs_rotation(api_key_record)
            }
        
        except Exception as e:
            logger.error(f"Error getting API key stats for {key_id}: {e}")
            return None
    
    def _hash_api_key(self, api_key: str) -> str:
        """Create secure hash of API key."""
        return hashlib.sha256(api_key.encode()).hexdigest()
    
    def _serialize_scopes(self, scopes: List[APIKeyScope]) -> str:
        """Serialize scopes to JSON string."""
        import json
        return json.dumps([scope.value for scope in scopes])
    
    def _deserialize_scopes(self, scopes_json: str) -> List[APIKeyScope]:
        """Deserialize scopes from JSON string."""
        import json
        try:
            scope_values = json.loads(scopes_json)
            return [APIKeyScope(scope) for scope in scope_values]
        except (json.JSONDecodeError, ValueError):
            return []
    
    def _serialize_ips(self, ips: List[str]) -> str:
        """Serialize IP addresses to JSON string."""
        import json
        return json.dumps(ips)
    
    def _deserialize_ips(self, ips_json: str) -> List[str]:
        """Deserialize IP addresses from JSON string."""
        import json
        try:
            return json.loads(ips_json)
        except json.JSONDecodeError:
            return []
    
    def _has_required_scopes(self, key_scopes: List[APIKeyScope], required_scopes: List[APIKeyScope]) -> bool:
        """Check if key has all required scopes."""
        # Admin scope grants all permissions
        if APIKeyScope.ADMIN in key_scopes:
            return True
        
        # Check if all required scopes are present
        return all(scope in key_scopes for scope in required_scopes)
    
    def _check_rate_limits(self, api_key_record: APIKey, client_ip: Optional[str]) -> bool:
        """Check if API key is within rate limits."""
        if not self.redis:
            return True  # No rate limiting without Redis
        
        try:
            current_time = datetime.utcnow()
            key_id = api_key_record.id
            
            # Check per-minute limit
            minute_key = f"rate_limit:minute:{key_id}:{current_time.strftime('%Y%m%d%H%M')}"
            minute_count = self.redis.get(minute_key)
            if minute_count and int(minute_count) >= api_key_record.rate_limit_per_minute:
                return False
            
            # Check per-hour limit
            hour_key = f"rate_limit:hour:{key_id}:{current_time.strftime('%Y%m%d%H')}"
            hour_count = self.redis.get(hour_key)
            if hour_count and int(hour_count) >= api_key_record.rate_limit_per_hour:
                return False
            
            # Check per-day limit
            day_key = f"rate_limit:day:{key_id}:{current_time.strftime('%Y%m%d')}"
            day_count = self.redis.get(day_key)
            if day_count and int(day_count) >= api_key_record.rate_limit_per_day:
                return False
            
            # Increment counters
            pipe = self.redis.pipeline()
            pipe.incr(minute_key)
            pipe.expire(minute_key, 60)
            pipe.incr(hour_key)
            pipe.expire(hour_key, 3600)
            pipe.incr(day_key)
            pipe.expire(day_key, 86400)
            pipe.execute()
            
            return True
        
        except Exception as e:
            logger.error(f"Error checking rate limits for API key {api_key_record.id}: {e}")
            return True  # Allow request on error
    
    def _update_usage_stats(self, api_key_record: APIKey, client_ip: Optional[str]):
        """Update API key usage statistics."""
        try:
            api_key_record.total_requests += 1
            api_key_record.last_used_at = datetime.utcnow()
            if client_ip:
                api_key_record.last_request_ip = client_ip
            
            self.db.commit()
        
        except Exception as e:
            logger.error(f"Error updating usage stats for API key {api_key_record.id}: {e}")
    
    def _update_key_status(self, key_id: str, status: APIKeyStatus):
        """Update API key status."""
        try:
            api_key_record = self.db.query(APIKey).filter(APIKey.id == key_id).first()
            if api_key_record:
                api_key_record.status = status
                api_key_record.updated_at = datetime.utcnow()
                self.db.commit()
        
        except Exception as e:
            logger.error(f"Error updating status for API key {key_id}: {e}")
    
    def _cache_api_key(self, api_key_record: APIKey):
        """Cache API key record in Redis."""
        try:
            import json
            cache_key = f"{self.cache_prefix}{api_key_record.key_hash}"
            cache_data = {
                "id": api_key_record.id,
                "name": api_key_record.name,
                "status": api_key_record.status,
                "scopes": api_key_record.scopes,
                "expires_at": api_key_record.expires_at.isoformat() if api_key_record.expires_at else None,
                "allowed_ips": api_key_record.allowed_ips,
                "rate_limit_per_minute": api_key_record.rate_limit_per_minute,
                "rate_limit_per_hour": api_key_record.rate_limit_per_hour,
                "rate_limit_per_day": api_key_record.rate_limit_per_day
            }
            
            self.redis.setex(cache_key, self.cache_ttl, json.dumps(cache_data))
        
        except Exception as e:
            logger.error(f"Error caching API key: {e}")
    
    def _get_cached_api_key(self, key_hash: str) -> Optional[APIKey]:
        """Get API key from cache."""
        try:
            import json
            cache_key = f"{self.cache_prefix}{key_hash}"
            cached_data = self.redis.get(cache_key)
            
            if not cached_data:
                return None
            
            data = json.loads(cached_data)
            
            # Create APIKey object from cached data
            api_key = APIKey()
            api_key.id = data["id"]
            api_key.name = data["name"]
            api_key.key_hash = key_hash
            api_key.status = data["status"]
            api_key.scopes = data["scopes"]
            api_key.expires_at = datetime.fromisoformat(data["expires_at"]) if data["expires_at"] else None
            api_key.allowed_ips = data["allowed_ips"]
            api_key.rate_limit_per_minute = data["rate_limit_per_minute"]
            api_key.rate_limit_per_hour = data["rate_limit_per_hour"]
            api_key.rate_limit_per_day = data["rate_limit_per_day"]
            
            return api_key
        
        except Exception as e:
            logger.error(f"Error getting cached API key: {e}")
            return None
    
    def _invalidate_cached_api_key(self, key_hash: str):
        """Remove API key from cache."""
        try:
            cache_key = f"{self.cache_prefix}{key_hash}"
            self.redis.delete(cache_key)
        
        except Exception as e:
            logger.error(f"Error invalidating cached API key: {e}")
    
    def _get_rate_limit_usage(self, api_key_record: APIKey) -> Dict[str, Any]:
        """Get current rate limit usage for API key."""
        try:
            current_time = datetime.utcnow()
            key_id = api_key_record.id
            
            minute_key = f"rate_limit:minute:{key_id}:{current_time.strftime('%Y%m%d%H%M')}"
            hour_key = f"rate_limit:hour:{key_id}:{current_time.strftime('%Y%m%d%H')}"
            day_key = f"rate_limit:day:{key_id}:{current_time.strftime('%Y%m%d')}"
            
            minute_count = int(self.redis.get(minute_key) or 0)
            hour_count = int(self.redis.get(hour_key) or 0)
            day_count = int(self.redis.get(day_key) or 0)
            
            return {
                "per_minute": {
                    "used": minute_count,
                    "limit": api_key_record.rate_limit_per_minute,
                    "remaining": max(0, api_key_record.rate_limit_per_minute - minute_count)
                },
                "per_hour": {
                    "used": hour_count,
                    "limit": api_key_record.rate_limit_per_hour,
                    "remaining": max(0, api_key_record.rate_limit_per_hour - hour_count)
                },
                "per_day": {
                    "used": day_count,
                    "limit": api_key_record.rate_limit_per_day,
                    "remaining": max(0, api_key_record.rate_limit_per_day - day_count)
                }
            }
        
        except Exception as e:
            logger.error(f"Error getting rate limit usage: {e}")
            return {}
    
    def _needs_rotation(self, api_key_record: APIKey) -> bool:
        """Check if API key needs rotation."""
        if not api_key_record.is_rotatable or not api_key_record.rotation_interval_days:
            return False
        
        last_rotated = api_key_record.last_rotated_at or api_key_record.created_at
        rotation_due = last_rotated + timedelta(days=api_key_record.rotation_interval_days)
        
        return datetime.utcnow() >= rotation_due

class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware for API key authentication and authorization."""
    
    def __init__(self, 
                 app,
                 api_key_manager: APIKeyManager,
                 protected_endpoints: Optional[Set[str]] = None,
                 scope_requirements: Optional[Dict[str, List[APIKeyScope]]] = None):
        super().__init__(app)
        self.api_key_manager = api_key_manager
        self.protected_endpoints = protected_endpoints or self._get_default_protected_endpoints()
        self.scope_requirements = scope_requirements or self._get_default_scope_requirements()
    
    def _get_default_protected_endpoints(self) -> Set[str]:
        """Get default endpoints that require API key authentication."""
        return {
            "/api/v1/admin/",
            "/api/v1/webhooks/",
            "/api/v1/external/"
        }
    
    def _get_default_scope_requirements(self) -> Dict[str, List[APIKeyScope]]:
        """Get default scope requirements for endpoints."""
        return {
            "/api/v1/admin/": [APIKeyScope.ADMIN],
            "/api/v1/payments/": [APIKeyScope.PAYMENT],
            "/api/v1/bills/": [APIKeyScope.BILLING],
            "/api/v1/webhooks/": [APIKeyScope.WEBHOOK],
            "/api/v1/users/": [APIKeyScope.USER_MANAGEMENT]
        }
    
    def _requires_api_key(self, request: Request) -> bool:
        """Check if endpoint requires API key authentication."""
        path = request.url.path
        
        for endpoint in self.protected_endpoints:
            if path.startswith(endpoint):
                return True
        
        return False
    
    def _get_required_scopes(self, request: Request) -> List[APIKeyScope]:
        """Get required scopes for endpoint."""
        path = request.url.path
        
        for endpoint, scopes in self.scope_requirements.items():
            if path.startswith(endpoint):
                return scopes
        
        return []
    
    def _create_api_key_error_response(self, message: str, status_code: int = 401) -> JSONResponse:
        """Create API key authentication error response."""
        return JSONResponse(
            status_code=status_code,
            content={
                "error": "API_KEY_ERROR",
                "message": message,
                "code": "INVALID_API_KEY"
            },
            headers={
                "X-API-Key-Status": "invalid",
                "WWW-Authenticate": "Bearer"
            }
        )
    
    async def dispatch(self, request: Request, call_next):
        """Process request with API key authentication."""
        # Check if endpoint requires API key
        if not self._requires_api_key(request):
            return await call_next(request)
        
        # Extract API key from headers
        api_key = None
        auth_header = request.headers.get("authorization")
        api_key_header = request.headers.get("x-api-key")
        
        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header[7:]
        elif api_key_header:
            api_key = api_key_header
        
        if not api_key:
            return self._create_api_key_error_response("API key required")
        
        # Get client IP
        client_ip = getattr(request.state, 'client_ip', 
                          request.client.host if request.client else None)
        
        # Get required scopes
        required_scopes = self._get_required_scopes(request)
        
        # Validate API key
        api_key_record = self.api_key_manager.validate_api_key(
            api_key, required_scopes, client_ip
        )
        
        if not api_key_record:
            return self._create_api_key_error_response("Invalid or unauthorized API key", 403)
        
        # Add API key info to request state
        request.state.api_key_id = api_key_record.id
        request.state.api_key_scopes = self.api_key_manager._deserialize_scopes(api_key_record.scopes)
        request.state.api_key_user_id = api_key_record.user_id
        
        try:
            response = await call_next(request)
            
            # Add API key headers to response
            response.headers["X-API-Key-ID"] = api_key_record.id
            response.headers["X-API-Key-Status"] = "valid"
            
            return response
        
        except Exception as e:
            logger.error(f"Error processing request with API key authentication: {e}")
            raise

# Security scheme for FastAPI documentation
api_key_scheme = HTTPBearer(scheme_name="API Key")

# Dependency for API key authentication
def get_api_key_auth(credentials: HTTPAuthorizationCredentials = Depends(api_key_scheme)):
    """FastAPI dependency for API key authentication."""
    # This would be implemented with the actual API key manager instance
    # The middleware handles the actual validation
    return credentials.credentials

# Utility functions
def require_api_key_scopes(*scopes: APIKeyScope):
    """Decorator to require specific API key scopes."""
    def decorator(func):
        func._required_api_key_scopes = list(scopes)
        return func
    return decorator

def get_api_key_from_request(request: Request) -> Optional[str]:
    """Get API key ID from request state."""
    return getattr(request.state, 'api_key_id', None)

def get_api_key_scopes_from_request(request: Request) -> List[APIKeyScope]:
    """Get API key scopes from request state."""
    return getattr(request.state, 'api_key_scopes', [])