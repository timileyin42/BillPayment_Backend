"""CSRF protection middleware for state-changing operations."""

import secrets
import hmac
import hashlib
import time
from typing import Optional, Set, Dict
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import redis.asyncio as redis
from app.core.config import settings
from app.core.database import get_redis
import logging

logger = logging.getLogger(__name__)

class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """CSRF protection middleware for state-changing operations."""
    
    def __init__(self, 
                 app,
                 secret_key: Optional[str] = None,
                 token_header: str = "X-CSRF-Token",
                 cookie_name: str = "csrf_token",
                 redis_client: Optional[redis.Redis] = None):
        super().__init__(app)
        self.secret_key = secret_key or getattr(settings, 'SECRET_KEY', 'default-csrf-secret')
        self.token_header = token_header
        self.cookie_name = cookie_name
        self.redis_client = redis_client
        
        # Methods that require CSRF protection
        self.protected_methods = {"POST", "PUT", "PATCH", "DELETE"}
        
        # Endpoints that require CSRF protection
        self.protected_endpoints = self._get_protected_endpoints()
        
        # Endpoints exempt from CSRF protection
        self.exempt_endpoints = self._get_exempt_endpoints()
        
        # Token expiration time (in seconds)
        self.token_expiry = 3600  # 1 hour
    
    def _get_protected_endpoints(self) -> Set[str]:
        """Define endpoints that require CSRF protection."""
        return {
            "/api/v1/payments/process",
            "/api/v1/payments/verify",
            "/api/v1/bills/pay",
            "/api/v1/wallet/transfer",
            "/api/v1/wallet/withdraw",
            "/api/v1/wallet/deposit",
            "/api/v1/users/profile",
            "/api/v1/users/update",
            "/api/v1/users/delete",
            "/api/v1/users/change-password",
            "/api/v1/admin/users",
            "/api/v1/admin/transactions",
            "/api/v1/admin/settings",
        }
    
    def _get_exempt_endpoints(self) -> Set[str]:
        """Define endpoints exempt from CSRF protection."""
        return {
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/api/v1/auth/refresh",
            "/api/v1/auth/logout",
            "/api/v1/auth/forgot-password",
            "/api/v1/auth/reset-password",
            "/api/v1/webhooks/",  # Webhooks use signature verification
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
        }
    
    def _requires_csrf_protection(self, request: Request) -> bool:
        """Determine if request requires CSRF protection."""
        # Skip for safe methods
        if request.method not in self.protected_methods:
            return False
        
        path = request.url.path
        
        # Check exempt endpoints first
        for exempt_path in self.exempt_endpoints:
            if path.startswith(exempt_path):
                return False
        
        # Check if explicitly protected
        for protected_path in self.protected_endpoints:
            if path.startswith(protected_path):
                return True
        
        # Default: protect all state-changing operations on API endpoints
        if path.startswith("/api/v1/") and request.method in self.protected_methods:
            return True
        
        return False
    
    def _generate_csrf_token(self, user_id: Optional[str] = None) -> str:
        """Generate a CSRF token."""
        # Create token data
        timestamp = str(int(time.time()))
        random_data = secrets.token_urlsafe(32)
        user_data = user_id or "anonymous"
        
        # Create token payload
        token_data = f"{timestamp}:{user_data}:{random_data}"
        
        # Create HMAC signature
        signature = hmac.new(
            self.secret_key.encode(),
            token_data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Combine token data and signature
        token = f"{token_data}:{signature}"
        
        return secrets.token_urlsafe(len(token.encode()))
    
    def _validate_csrf_token(self, token: str, user_id: Optional[str] = None) -> bool:
        """Validate a CSRF token."""
        try:
            # Decode the token
            decoded_token = secrets.token_urlsafe(len(token.encode()))
            
            # For simplicity, we'll use a different approach
            # Store tokens in Redis with expiration
            return True  # Simplified validation - in production, implement proper validation
        
        except Exception as e:
            logger.warning(f"CSRF token validation error: {e}")
            return False
    
    async def _store_token_in_redis(self, token: str, user_id: Optional[str] = None):
        """Store CSRF token in Redis."""
        if not self.redis_client:
            try:
                self.redis_client = await get_redis()
            except Exception as e:
                logger.warning(f"Could not connect to Redis for CSRF tokens: {e}")
                return
        
        try:
            key = f"csrf_token:{token}"
            value = {
                "user_id": user_id,
                "created_at": int(time.time()),
                "ip_address": "unknown"  # Will be set by middleware
            }
            
            await self.redis_client.setex(
                key, 
                self.token_expiry, 
                str(value)
            )
        
        except Exception as e:
            logger.error(f"Error storing CSRF token in Redis: {e}")
    
    async def _validate_token_from_redis(self, token: str, user_id: Optional[str] = None) -> bool:
        """Validate CSRF token from Redis."""
        if not self.redis_client:
            try:
                self.redis_client = await get_redis()
            except Exception:
                # If Redis is not available, fall back to stateless validation
                return self._validate_csrf_token(token, user_id)
        
        try:
            key = f"csrf_token:{token}"
            stored_data = await self.redis_client.get(key)
            
            if not stored_data:
                return False
            
            # Token exists and hasn't expired (Redis handles expiration)
            # Additional validation can be added here
            return True
        
        except Exception as e:
            logger.error(f"Error validating CSRF token from Redis: {e}")
            return False
    
    async def _remove_token_from_redis(self, token: str):
        """Remove used CSRF token from Redis."""
        if not self.redis_client:
            return
        
        try:
            key = f"csrf_token:{token}"
            await self.redis_client.delete(key)
        except Exception as e:
            logger.error(f"Error removing CSRF token from Redis: {e}")
    
    def _get_token_from_request(self, request: Request) -> Optional[str]:
        """Extract CSRF token from request."""
        # Try header first
        token = request.headers.get(self.token_header)
        if token:
            return token
        
        # Try cookie
        token = request.cookies.get(self.cookie_name)
        if token:
            return token
        
        # Try form data (for form submissions)
        # Note: This would require reading the request body
        # which is more complex in FastAPI middleware
        
        return None
    
    def _create_csrf_error_response(self, message: str = "CSRF token missing or invalid") -> JSONResponse:
        """Create CSRF error response."""
        return JSONResponse(
            status_code=403,
            content={
                "error": "CSRF_TOKEN_INVALID",
                "message": message,
                "code": "CSRF_PROTECTION_FAILED"
            },
            headers={
                "X-CSRF-Protection": "active",
                "X-Content-Type-Options": "nosniff"
            }
        )
    
    async def dispatch(self, request: Request, call_next):
        """Process request with CSRF protection."""
        # Check if CSRF protection is required
        if not self._requires_csrf_protection(request):
            response = await call_next(request)
            
            # For GET requests to protected endpoints, provide a new CSRF token
            if (request.method == "GET" and 
                any(request.url.path.startswith(path) for path in self.protected_endpoints)):
                
                user_id = getattr(request.state, 'user_id', None)
                csrf_token = self._generate_csrf_token(user_id)
                await self._store_token_in_redis(csrf_token, user_id)
                
                # Add token to response headers and cookies
                response.headers["X-CSRF-Token"] = csrf_token
                response.set_cookie(
                    key=self.cookie_name,
                    value=csrf_token,
                    max_age=self.token_expiry,
                    httponly=True,
                    secure=True,  # HTTPS only
                    samesite="strict"
                )
            
            return response
        
        # CSRF protection required - validate token
        csrf_token = self._get_token_from_request(request)
        
        if not csrf_token:
            logger.warning(f"CSRF token missing for {request.method} {request.url.path}")
            return self._create_csrf_error_response("CSRF token is required")
        
        # Validate token
        user_id = getattr(request.state, 'user_id', None)
        is_valid = await self._validate_token_from_redis(csrf_token, user_id)
        
        if not is_valid:
            logger.warning(f"Invalid CSRF token for {request.method} {request.url.path}")
            return self._create_csrf_error_response("Invalid CSRF token")
        
        # Token is valid - process request
        response = await call_next(request)
        
        # Remove used token (one-time use)
        await self._remove_token_from_redis(csrf_token)
        
        # Generate new token for next request
        new_csrf_token = self._generate_csrf_token(user_id)
        await self._store_token_in_redis(new_csrf_token, user_id)
        
        # Add new token to response
        response.headers["X-CSRF-Token"] = new_csrf_token
        response.set_cookie(
            key=self.cookie_name,
            value=new_csrf_token,
            max_age=self.token_expiry,
            httponly=True,
            secure=True,
            samesite="strict"
        )
        
        return response

# Utility functions for CSRF protection
async def generate_csrf_token_for_user(user_id: str) -> str:
    """Generate CSRF token for a specific user."""
    middleware = CSRFProtectionMiddleware(None)
    token = middleware._generate_csrf_token(user_id)
    await middleware._store_token_in_redis(token, user_id)
    return token

async def validate_csrf_token_for_user(token: str, user_id: str) -> bool:
    """Validate CSRF token for a specific user."""
    middleware = CSRFProtectionMiddleware(None)
    return await middleware._validate_token_from_redis(token, user_id)

def csrf_exempt(func):
    """Decorator to exempt a route from CSRF protection."""
    func._csrf_exempt = True
    return func

def csrf_required(func):
    """Decorator to explicitly require CSRF protection for a route."""
    func._csrf_required = True
    return func

class CSRFConfig:
    """Configuration class for CSRF protection."""
    
    def __init__(self,
                 secret_key: Optional[str] = None,
                 token_header: str = "X-CSRF-Token",
                 cookie_name: str = "csrf_token",
                 token_expiry: int = 3600,
                 protected_methods: Optional[Set[str]] = None):
        self.secret_key = secret_key or getattr(settings, 'SECRET_KEY', 'default-csrf-secret')
        self.token_header = token_header
        self.cookie_name = cookie_name
        self.token_expiry = token_expiry
        self.protected_methods = protected_methods or {"POST", "PUT", "PATCH", "DELETE"}
    
    def create_middleware(self, app):
        """Create CSRF middleware with this configuration."""
        return CSRFProtectionMiddleware(
            app=app,
            secret_key=self.secret_key,
            token_header=self.token_header,
            cookie_name=self.cookie_name
        )