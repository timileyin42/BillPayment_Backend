"""Request size limit middleware to prevent large payload attacks."""

import asyncio
from typing import Dict, Optional, Set
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Message
import logging

logger = logging.getLogger(__name__)

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to limit request payload sizes and prevent DoS attacks."""
    
    def __init__(self, 
                 app,
                 default_max_size: int = 10 * 1024 * 1024,  # 10MB default
                 endpoint_limits: Optional[Dict[str, int]] = None,
                 check_content_length: bool = True,
                 check_actual_size: bool = True):
        super().__init__(app)
        self.default_max_size = default_max_size
        self.endpoint_limits = endpoint_limits or self._get_default_endpoint_limits()
        self.check_content_length = check_content_length
        self.check_actual_size = check_actual_size
        
        # Methods that should have size limits
        self.size_limited_methods = {"POST", "PUT", "PATCH"}
        
        # Endpoints with special size requirements
        self.file_upload_endpoints = self._get_file_upload_endpoints()
        self.api_endpoints = self._get_api_endpoints()
    
    def _get_default_endpoint_limits(self) -> Dict[str, int]:
        """Define default size limits for different endpoint types."""
        return {
            # Authentication endpoints - small payloads
            "/api/v1/auth/login": 1024,  # 1KB
            "/api/v1/auth/register": 2048,  # 2KB
            "/api/v1/auth/refresh": 512,  # 512B
            "/api/v1/auth/forgot-password": 1024,  # 1KB
            "/api/v1/auth/reset-password": 1024,  # 1KB
            
            # Payment endpoints - moderate payloads
            "/api/v1/payments/process": 5 * 1024,  # 5KB
            "/api/v1/payments/verify": 2 * 1024,  # 2KB
            "/api/v1/bills/pay": 5 * 1024,  # 5KB
            
            # Wallet endpoints - moderate payloads
            "/api/v1/wallet/transfer": 3 * 1024,  # 3KB
            "/api/v1/wallet/withdraw": 2 * 1024,  # 2KB
            "/api/v1/wallet/deposit": 2 * 1024,  # 2KB
            
            # User profile endpoints - moderate payloads
            "/api/v1/users/profile": 10 * 1024,  # 10KB
            "/api/v1/users/update": 10 * 1024,  # 10KB
            "/api/v1/users/change-password": 1024,  # 1KB
            
            # File upload endpoints - large payloads
            "/api/v1/users/avatar": 5 * 1024 * 1024,  # 5MB
            "/api/v1/documents/upload": 10 * 1024 * 1024,  # 10MB
            "/api/v1/receipts/upload": 2 * 1024 * 1024,  # 2MB
            
            # Admin endpoints - variable sizes
            "/api/v1/admin/users": 50 * 1024,  # 50KB
            "/api/v1/admin/bulk-operations": 1024 * 1024,  # 1MB
            "/api/v1/admin/import": 10 * 1024 * 1024,  # 10MB
            
            # Webhook endpoints - moderate payloads
            "/api/v1/webhooks/payment": 10 * 1024,  # 10KB
            "/api/v1/webhooks/notification": 5 * 1024,  # 5KB
        }
    
    def _get_file_upload_endpoints(self) -> Set[str]:
        """Define endpoints that handle file uploads."""
        return {
            "/api/v1/users/avatar",
            "/api/v1/documents/upload",
            "/api/v1/receipts/upload",
            "/api/v1/admin/import",
        }
    
    def _get_api_endpoints(self) -> Set[str]:
        """Define API endpoints that should have strict size limits."""
        return {
            "/api/v1/auth/",
            "/api/v1/payments/",
            "/api/v1/bills/",
            "/api/v1/wallet/",
            "/api/v1/users/",
            "/api/v1/admin/",
            "/api/v1/webhooks/",
        }
    
    def _get_size_limit_for_endpoint(self, path: str) -> int:
        """Get size limit for a specific endpoint."""
        # Check exact path match first
        if path in self.endpoint_limits:
            return self.endpoint_limits[path]
        
        # Check prefix matches for endpoint categories
        for endpoint_prefix, size_limit in self.endpoint_limits.items():
            if path.startswith(endpoint_prefix):
                return size_limit
        
        # Special handling for file upload endpoints
        for upload_endpoint in self.file_upload_endpoints:
            if path.startswith(upload_endpoint):
                return 10 * 1024 * 1024  # 10MB for file uploads
        
        # Default API endpoint limits
        for api_prefix in self.api_endpoints:
            if path.startswith(api_prefix):
                return 100 * 1024  # 100KB for regular API endpoints
        
        # Default limit
        return self.default_max_size
    
    def _should_check_size(self, request: Request) -> bool:
        """Determine if request should be size-checked."""
        # Only check methods that typically have payloads
        if request.method not in self.size_limited_methods:
            return False
        
        # Skip health checks and documentation
        path = request.url.path
        if path in ["/health", "/docs", "/redoc", "/openapi.json"]:
            return False
        
        return True
    
    def _create_size_limit_error(self, 
                                current_size: int, 
                                max_size: int, 
                                endpoint: str) -> JSONResponse:
        """Create size limit exceeded error response."""
        return JSONResponse(
            status_code=413,
            content={
                "error": "PAYLOAD_TOO_LARGE",
                "message": f"Request payload too large. Maximum allowed: {max_size} bytes, received: {current_size} bytes",
                "code": "REQUEST_SIZE_LIMIT_EXCEEDED",
                "details": {
                    "endpoint": endpoint,
                    "max_size_bytes": max_size,
                    "current_size_bytes": current_size,
                    "max_size_human": self._format_bytes(max_size),
                    "current_size_human": self._format_bytes(current_size)
                }
            },
            headers={
                "X-Content-Length-Limit": str(max_size),
                "X-Request-Size-Exceeded": "true",
                "Retry-After": "60"  # Suggest retry after 60 seconds
            }
        )
    
    def _format_bytes(self, bytes_size: int) -> str:
        """Format bytes into human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} TB"
    
    async def _check_content_length_header(self, request: Request, max_size: int) -> Optional[JSONResponse]:
        """Check Content-Length header if present."""
        content_length = request.headers.get("content-length")
        
        if content_length:
            try:
                size = int(content_length)
                if size > max_size:
                    logger.warning(
                        f"Request size limit exceeded via Content-Length: "
                        f"{size} > {max_size} for {request.method} {request.url.path}"
                    )
                    return self._create_size_limit_error(size, max_size, request.url.path)
            except ValueError:
                logger.warning(f"Invalid Content-Length header: {content_length}")
        
        return None
    
    async def _read_body_with_size_limit(self, request: Request, max_size: int) -> Optional[JSONResponse]:
        """Read request body with size checking."""
        body_size = 0
        body_parts = []
        
        async def receive_with_size_check():
            nonlocal body_size
            
            message = await request._receive()
            
            if message["type"] == "http.request":
                body_chunk = message.get("body", b"")
                body_size += len(body_chunk)
                
                if body_size > max_size:
                    logger.warning(
                        f"Request size limit exceeded during body read: "
                        f"{body_size} > {max_size} for {request.method} {request.url.path}"
                    )
                    raise HTTPException(
                        status_code=413,
                        detail=f"Request payload too large: {body_size} > {max_size} bytes"
                    )
                
                body_parts.append(body_chunk)
            
            return message
        
        # Replace the receive callable temporarily
        original_receive = request._receive
        request._receive = receive_with_size_check
        
        try:
            # Trigger body reading by accessing request.body()
            # This will use our size-checking receive function
            await request.body()
        except HTTPException as e:
            if e.status_code == 413:
                return self._create_size_limit_error(body_size, max_size, request.url.path)
            raise
        finally:
            # Restore original receive function
            request._receive = original_receive
        
        return None
    
    async def dispatch(self, request: Request, call_next):
        """Process request with size limit checking."""
        # Check if size limiting should be applied
        if not self._should_check_size(request):
            return await call_next(request)
        
        # Get size limit for this endpoint
        max_size = self._get_size_limit_for_endpoint(request.url.path)
        
        # Log size limit for debugging
        logger.debug(
            f"Applying size limit {self._format_bytes(max_size)} "
            f"to {request.method} {request.url.path}"
        )
        
        # Check Content-Length header first (if present)
        if self.check_content_length:
            error_response = await self._check_content_length_header(request, max_size)
            if error_response:
                return error_response
        
        # Check actual body size during reading (if enabled)
        if self.check_actual_size:
            error_response = await self._read_body_with_size_limit(request, max_size)
            if error_response:
                return error_response
        
        # Size checks passed - process request
        try:
            response = await call_next(request)
            
            # Add size limit info to response headers
            response.headers["X-Content-Length-Limit"] = str(max_size)
            response.headers["X-Size-Check-Passed"] = "true"
            
            return response
        
        except Exception as e:
            # Check if it's a size-related error
            if "payload too large" in str(e).lower() or "413" in str(e):
                logger.error(f"Size limit error during request processing: {e}")
                return self._create_size_limit_error(0, max_size, request.url.path)
            
            # Re-raise other exceptions
            raise

# Utility functions for request size management
def get_endpoint_size_limit(endpoint: str, 
                           endpoint_limits: Optional[Dict[str, int]] = None) -> int:
    """Get size limit for a specific endpoint."""
    middleware = RequestSizeLimitMiddleware(None, endpoint_limits=endpoint_limits)
    return middleware._get_size_limit_for_endpoint(endpoint)

def format_size_limit(size_bytes: int) -> str:
    """Format size limit in human-readable format."""
    middleware = RequestSizeLimitMiddleware(None)
    return middleware._format_bytes(size_bytes)

class SizeLimitConfig:
    """Configuration class for request size limits."""
    
    def __init__(self,
                 default_max_size: int = 10 * 1024 * 1024,  # 10MB
                 endpoint_limits: Optional[Dict[str, int]] = None,
                 check_content_length: bool = True,
                 check_actual_size: bool = True):
        self.default_max_size = default_max_size
        self.endpoint_limits = endpoint_limits or {}
        self.check_content_length = check_content_length
        self.check_actual_size = check_actual_size
    
    def create_middleware(self, app):
        """Create request size limit middleware with this configuration."""
        return RequestSizeLimitMiddleware(
            app=app,
            default_max_size=self.default_max_size,
            endpoint_limits=self.endpoint_limits,
            check_content_length=self.check_content_length,
            check_actual_size=self.check_actual_size
        )
    
    def add_endpoint_limit(self, endpoint: str, size_limit: int):
        """Add size limit for a specific endpoint."""
        self.endpoint_limits[endpoint] = size_limit
    
    def remove_endpoint_limit(self, endpoint: str):
        """Remove size limit for a specific endpoint."""
        self.endpoint_limits.pop(endpoint, None)

# Decorator for setting custom size limits on routes
def size_limit(max_bytes: int):
    """Decorator to set custom size limit for a route."""
    def decorator(func):
        func._size_limit = max_bytes
        return func
    return decorator

# Common size limit constants
class SizeLimits:
    """Common size limit constants."""
    
    # Small payloads
    TINY = 512  # 512B
    SMALL = 1024  # 1KB
    MEDIUM = 5 * 1024  # 5KB
    LARGE = 10 * 1024  # 10KB
    
    # File uploads
    IMAGE_SMALL = 1024 * 1024  # 1MB
    IMAGE_MEDIUM = 5 * 1024 * 1024  # 5MB
    IMAGE_LARGE = 10 * 1024 * 1024  # 10MB
    
    # Documents
    DOCUMENT_SMALL = 2 * 1024 * 1024  # 2MB
    DOCUMENT_MEDIUM = 10 * 1024 * 1024  # 10MB
    DOCUMENT_LARGE = 50 * 1024 * 1024  # 50MB
    
    # Bulk operations
    BULK_SMALL = 100 * 1024  # 100KB
    BULK_MEDIUM = 1024 * 1024  # 1MB
    BULK_LARGE = 10 * 1024 * 1024  # 10MB