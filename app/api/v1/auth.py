from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.oauth import (
    OAuth2Handler,
    Token,
    UserResponse,
    get_current_user,
    oauth2_scheme,
    api_key_scheme,
    bearer_scheme
)
from app.core.security import (
    verify_password,
    create_access_token,
    create_refresh_token
)
from app.middleware.api_key_management import APIKeyManager
from app.database_model.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])
oauth_handler = OAuth2Handler()
api_key_manager = APIKeyManager()


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db)
):
    """
    OAuth2 compatible token login, get an access token for future requests.
    
    This endpoint is used by Swagger UI for OAuth2 authentication.
    It validates user credentials and returns JWT tokens along with API key information.
    """
    # Authenticate user
    user = await oauth_handler.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(
        data={"sub": user.email, "user_id": str(user.id)},
        expires_delta=access_token_expires
    )
    
    # Create refresh token
    refresh_token = create_refresh_token(
        data={"sub": user.email, "user_id": str(user.id)}
    )
    
    # Generate or get existing API key for the user
    api_key = await api_key_manager.generate_api_key(
        user_id=str(user.id),
        scopes=["read", "write"],
        expires_in_days=30
    )
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 1800,  # 30 minutes
        "api_key": api_key,
        "user_id": str(user.id)
    }


@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    current_user: User = Depends(get_current_user)
):
    """
    Refresh access token using the current user context.
    """
    # Create new access token
    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(
        data={"sub": current_user.email, "user_id": str(current_user.id)},
        expires_delta=access_token_expires
    )
    
    # Get existing API key
    api_key = await api_key_manager.get_user_api_key(str(current_user.id))
    
    return {
        "access_token": access_token,
        "refresh_token": None,  # Don't refresh the refresh token
        "token_type": "bearer",
        "expires_in": 1800,
        "api_key": api_key,
        "user_id": str(current_user.id)
    }


@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: User = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
    api_key: str = Depends(api_key_scheme)
):
    """
    Get current user information.
    Requires both OAuth2 token and API key authentication.
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        username=current_user.username,
        is_active=current_user.is_active,
        created_at=current_user.created_at
    )


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user)
):
    """
    Logout current user (invalidate tokens).
    Note: In a stateless JWT system, this would typically involve
    adding the token to a blacklist or reducing its expiry time.
    """
    return {"message": "Successfully logged out"}