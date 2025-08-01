from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr, validator
import re

from ..core.database import get_database_session
from ..core.security import verify_token
from ..core.errors import (
    AuthenticationError,
    ValidationError,
    DuplicateError,
    NotFoundError
)
from ..services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()

# Pydantic models for request/response
class UserRegistrationRequest(BaseModel):
    email: EmailStr
    phone_number: str
    password: str
    first_name: str
    last_name: str
    referral_code: str = None
    
    @validator('phone_number')
    def validate_phone_number(cls, v):
        # Nigerian phone number validation
        pattern = r'^(\+234|234|0)?[789][01]\d{8}$'
        if not re.match(pattern, v):
            raise ValueError('Invalid Nigerian phone number format')
        
        # Normalize to international format
        if v.startswith('0'):
            v = '+234' + v[1:]
        elif v.startswith('234'):
            v = '+' + v
        elif not v.startswith('+234'):
            v = '+234' + v
        
        return v
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        return v

class UserLoginRequest(BaseModel):
    email_or_phone: str
    password: str

class TokenRefreshRequest(BaseModel):
    refresh_token: str

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
    
    @validator('new_password')
    def validate_new_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        return v

class UserProfileUpdateRequest(BaseModel):
    first_name: str = None
    last_name: str = None
    email: EmailStr = None
    phone_number: str = None
    
    @validator('phone_number')
    def validate_phone_number(cls, v):
        if v is None:
            return v
        
        # Nigerian phone number validation
        pattern = r'^(\+234|234|0)?[789][01]\d{8}$'
        if not re.match(pattern, v):
            raise ValueError('Invalid Nigerian phone number format')
        
        # Normalize to international format
        if v.startswith('0'):
            v = '+234' + v[1:]
        elif v.startswith('234'):
            v = '+' + v
        elif not v.startswith('+234'):
            v = '+234' + v
        
        return v

# Response models
class UserResponse(BaseModel):
    id: int
    email: str
    phone_number: str
    first_name: str
    last_name: str
    is_verified: bool
    is_admin: bool

class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    user: UserResponse

class RegistrationResponse(BaseModel):
    user_id: int
    email: str
    phone_number: str
    first_name: str
    last_name: str
    referral_code: str
    created_at: str
    message: str = "User registered successfully"

# Dependency to get current user
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_database_session)
):
    """Get current authenticated user."""
    try:
        token = credentials.credentials
        payload = verify_token(token)
        user_id = int(payload.get("sub"))
        
        user_service = UserService(db)
        user = await user_service.get_user_by_id(user_id)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated"
            )
        
        return user
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

# Optional dependency for admin users
async def get_current_admin_user(
    current_user = Depends(get_current_user)
):
    """Get current authenticated admin user."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

@router.post("/register", response_model=RegistrationResponse)
async def register_user(
    user_data: UserRegistrationRequest,
    db: AsyncSession = Depends(get_database_session)
):
    """Register a new user account."""
    try:
        user_service = UserService(db)
        
        result = await user_service.create_user(
            email=user_data.email,
            phone_number=user_data.phone_number,
            password=user_data.password,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            referral_code=user_data.referral_code
        )
        
        return RegistrationResponse(**result)
        
    except DuplicateError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed"
        )

@router.post("/login", response_model=AuthResponse)
async def login_user(
    login_data: UserLoginRequest,
    db: AsyncSession = Depends(get_database_session)
):
    """Authenticate user and return access tokens."""
    try:
        user_service = UserService(db)
        
        result = await user_service.authenticate_user(
            email_or_phone=login_data.email_or_phone,
            password=login_data.password
        )
        
        return AuthResponse(**result)
        
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )

@router.post("/refresh", response_model=Dict[str, str])
async def refresh_token(
    token_data: TokenRefreshRequest,
    db: AsyncSession = Depends(get_database_session)
):
    """Refresh access token using refresh token."""
    try:
        from ..core.security import create_access_token
        
        # Verify refresh token
        payload = verify_token(token_data.refresh_token)
        user_id = int(payload.get("sub"))
        
        # Verify user still exists and is active
        user_service = UserService(db)
        user = await user_service.get_user_by_id(user_id)
        
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        # Generate new access token
        new_access_token = create_access_token(data={"sub": str(user_id)})
        
        return {
            "access_token": new_access_token,
            "token_type": "bearer"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user = Depends(get_current_user)
):
    """Get current user information."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        phone_number=current_user.phone_number,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        is_verified=current_user.is_verified,
        is_admin=current_user.is_admin
    )

@router.put("/profile", response_model=Dict[str, Any])
async def update_user_profile(
    profile_data: UserProfileUpdateRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Update user profile information."""
    try:
        user_service = UserService(db)
        
        # Filter out None values
        update_data = {k: v for k, v in profile_data.dict().items() if v is not None}
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No data provided for update"
            )
        
        result = await user_service.update_user_profile(
            user_id=current_user.id,
            **update_data
        )
        
        return {
            "message": "Profile updated successfully",
            "user": result
        }
        
    except DuplicateError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Profile update failed"
        )

@router.post("/change-password", response_model=Dict[str, str])
async def change_password(
    password_data: PasswordChangeRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Change user password."""
    try:
        user_service = UserService(db)
        
        await user_service.change_password(
            user_id=current_user.id,
            current_password=password_data.current_password,
            new_password=password_data.new_password
        )
        
        return {"message": "Password changed successfully"}
        
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed"
        )

@router.get("/dashboard", response_model=Dict[str, Any])
async def get_user_dashboard(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Get user dashboard data."""
    try:
        user_service = UserService(db)
        
        dashboard_data = await user_service.get_user_dashboard_data(current_user.id)
        
        return dashboard_data
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load dashboard data"
        )

@router.post("/verify/{user_id}", response_model=Dict[str, str])
async def verify_user(
    user_id: int,
    current_admin = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Verify a user account (Admin only)."""
    try:
        user_service = UserService(db)
        
        await user_service.verify_user(user_id)
        
        return {"message": f"User {user_id} verified successfully"}
        
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User verification failed"
        )

@router.post("/deactivate/{user_id}", response_model=Dict[str, str])
async def deactivate_user(
    user_id: int,
    current_admin = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Deactivate a user account (Admin only)."""
    try:
        user_service = UserService(db)
        
        await user_service.deactivate_user(user_id)
        
        return {"message": f"User {user_id} deactivated successfully"}
        
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User deactivation failed"
        )