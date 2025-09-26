"""OAuth2 implementation for Swagger UI authentication with API key integration."""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List, Union
from datetime import datetime

from app.core.database import get_db
from app.core.security import verify_token, verify_password
from app.database_model.user import User
from app.middleware.api_key_management import APIKeyManager

# Security schemes - these will be imported by main.py
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token",
    scheme_name="OAuth2PasswordBearer"
)

api_key_scheme = APIKeyHeader(
    name="x-api-key",
    scheme_name="ApiKeyAuth"
)

bearer_scheme = HTTPBearer(
    scheme_name="BearerAuth"
)

class TokenResponse(BaseModel):
    """OAuth2 token response model."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    scope: str
    user_id: int
    api_key: Optional[str] = None

class OAuth2Handler:
    """Handler for OAuth2 operations with API key integration."""
    
    def __init__(self):
        self.default_api_key = "vf_demo_key_for_swagger_testing_12345678"  # Default for testing
    
    async def authenticate_user(
        self,
        username: str,
        password: str,
        db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        """Authenticate user with username/password."""
        try:
            user_service = UserService(db)
            
            # Try to find user by email or phone
            user = None
            if "@" in username:
                user = await user_service.get_user_by_email(username)
            else:
                user = await user_service.get_user_by_phone(username)
            
            if not user:
                return None
            
            if not verify_password(password, user.password_hash):
                return None
            
            if not user.is_active:
                return None
            
            return {
                "id": user.id,
                "email": user.email,
                "phone_number": user.phone_number,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_admin": user.is_admin,
                "is_verified": user.is_verified
            }
        
        except Exception:
            return None
    
    async def create_access_token_with_scopes(
        self,
        user_data: Dict[str, Any],
        scopes: list[str] = None
    ) -> TokenResponse:
        """Create access token with scopes for OAuth2."""
        if scopes is None:
            scopes = ["read", "write"]
            if user_data.get("is_admin"):
                scopes.extend(["admin", "payment", "wallet"])
        
        # Create JWT token
        token_data = {
            "sub": str(user_data["id"]),
            "email": user_data["email"],
            "scopes": scopes,
            "type": "access_token"
        }
        
        expires_delta = timedelta(minutes=30)  # 30 minutes
        access_token = create_access_token(token_data, expires_delta)
        
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=1800,  # 30 minutes in seconds
            scope=" ".join(scopes),
            user_id=user_data["id"],
            api_key=self.default_api_key
        )
    
    async def get_current_user_from_token(
        self,
        token: str = Depends(oauth2_scheme),
        db: AsyncSession = Depends(get_database_session)
    ):
        """Get current user from OAuth2 token."""
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
        try:
            payload = verify_token(token)
            if payload is None:
                raise credentials_exception
            
            user_id = payload.get("sub")
            if user_id is None:
                raise credentials_exception
            
            user_service = UserService(db)
            user = await user_service.get_user_by_id(int(user_id))
            
            if user is None:
                raise credentials_exception
            
            return user
        
        except Exception:
            raise credentials_exception
    
    async def verify_api_key(
        self,
        api_key: Optional[str] = Depends(api_key_header),
        db: AsyncSession = Depends(get_database_session)
    ) -> Optional[str]:
        """Verify API key from header."""
        if not api_key:
            # Return default key for testing
            return self.default_api_key
        
        # In production, validate against database
        # For now, accept the default key or any key starting with 'vf_'
        if api_key == self.default_api_key or api_key.startswith('vf_'):
            return api_key
        
        return None
    
    def get_swagger_ui_oauth2_redirect_url(self) -> str:
        """Get OAuth2 redirect URL for Swagger UI."""
        return "/docs/oauth2-redirect"

# Global OAuth2 handler instance
oauth_handler = OAuth2Handler()

# Dependency functions for FastAPI
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_database_session)
):
    """Dependency to get current authenticated user."""
    return await oauth_handler.get_current_user_from_token(token, db)

async def get_current_admin_user(
    current_user = Depends(get_current_user)
):
    """Dependency to get current admin user."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

async def verify_api_key_dependency(
    api_key: Optional[str] = Depends(api_key_header)
) -> str:
    """Dependency to verify API key."""
    verified_key = await oauth_handler.verify_api_key(api_key)
    if not verified_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    return verified_key