from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError, jwt
from datetime import datetime

from app.core.config import settings
from app.core.database import get_db
from app.database_model.user import User
from app.core.errors import AuthenticationError, AuthorizationError

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token.
    
    Args:
        credentials: HTTP authorization credentials containing JWT token
        db: Database session
        
    Returns:
        User: Current authenticated user
        
    Raises:
        HTTPException: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decode JWT token
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=[settings.algorithm]
        )
        
        # Extract email from token
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
            
        # Check token expiration
        exp = payload.get("exp")
        if exp is None or datetime.utcnow().timestamp() > exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
    except JWTError:
        raise credentials_exception
    
    # Get user from database
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated"
        )
    
    # Update last login time
    user.last_login = datetime.utcnow()
    await db.commit()
    
    return user


async def get_current_verified_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Get current authenticated and verified user.
    
    Args:
        current_user: Current authenticated user
        
    Returns:
        User: Current verified user
        
    Raises:
        HTTPException: If user is not verified
    """
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not verified"
        )
    
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_verified_user)
) -> User:
    """Get current authenticated admin user.
    
    Args:
        current_user: Current authenticated and verified user
        
    Returns:
        User: Current admin user
        
    Raises:
        HTTPException: If user is not an admin
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    return current_user


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Get current user if authenticated, otherwise return None.
    
    This dependency is useful for endpoints that can work with or without
    authentication, providing different functionality based on auth status.
    
    Args:
        credentials: Optional HTTP authorization credentials
        db: Database session
        
    Returns:
        Optional[User]: Current user if authenticated, None otherwise
    """
    if credentials is None:
        return None
    
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


def require_permissions(*permissions: str):
    """Decorator factory for requiring specific permissions.
    
    This can be extended in the future to support role-based permissions.
    
    Args:
        *permissions: List of required permissions
        
    Returns:
        Dependency function that checks permissions
    """
    async def permission_checker(
        current_user: User = Depends(get_current_verified_user)
    ) -> User:
        # For now, we only have admin/non-admin distinction
        # This can be extended with a proper permission system
        if "admin" in permissions and not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        
        return current_user
    
    return permission_checker


async def validate_api_key(
    api_key: str,
    db: AsyncSession = Depends(get_db)
) -> bool:
    """Validate API key for external integrations.
    
    This can be used for webhook endpoints or external service integrations.
    
    Args:
        api_key: API key to validate
        db: Database session
        
    Returns:
        bool: True if API key is valid
        
    Raises:
        HTTPException: If API key is invalid
    """
    # For now, check against a configured API key
    # In production, this should check against a database of API keys
    if api_key != settings.webhook_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return True


class RateLimitChecker:
    """Rate limiting dependency.
    
    This can be used to implement rate limiting on specific endpoints.
    """
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
    
    async def __call__(
        self,
        current_user: User = Depends(get_current_user)
    ) -> User:
        """Check rate limit for current user.
        
        Args:
            current_user: Current authenticated user
            
        Returns:
            User: Current user if within rate limit
            
        Raises:
            HTTPException: If rate limit exceeded
        """
        # This is a placeholder implementation
        # In production, this should use Redis or another cache
        # to track request counts per user
        
        # For now, just return the user
        # TODO: Implement actual rate limiting logic
        return current_user


# Pre-configured rate limiters
rate_limit_strict = RateLimitChecker(max_requests=10, window_seconds=60)
rate_limit_moderate = RateLimitChecker(max_requests=100, window_seconds=3600)
rate_limit_lenient = RateLimitChecker(max_requests=1000, window_seconds=3600)