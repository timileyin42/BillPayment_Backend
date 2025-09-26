"""Security headers middleware for comprehensive web security."""

from typing import Dict, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add comprehensive security headers."""
    
    def __init__(self, app, custom_headers: Optional[Dict[str, str]] = None):
        super().__init__(app)
        self.custom_headers = custom_headers or {}
        self.security_headers = self._get_security_headers()
    
    def _get_security_headers(self) -> Dict[str, str]:
        """Get comprehensive security headers configuration."""
        headers = {
            # Strict Transport Security - Force HTTPS
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
            
            # Content Security Policy - Prevent XSS and injection attacks
            "Content-Security-Policy": self._get_csp_policy(),
            
            # X-Frame-Options - Prevent clickjacking
            "X-Frame-Options": "DENY",
            
            # X-Content-Type-Options - Prevent MIME sniffing
            "X-Content-Type-Options": "nosniff",
            
            # X-XSS-Protection - Enable XSS filtering
            "X-XSS-Protection": "1; mode=block",
            
            # Referrer Policy - Control referrer information
            "Referrer-Policy": "strict-origin-when-cross-origin",
            
            # Permissions Policy - Control browser features
            "Permissions-Policy": self._get_permissions_policy(),
            
            # Cross-Origin Embedder Policy
            "Cross-Origin-Embedder-Policy": "require-corp",
            
            # Cross-Origin Opener Policy
            "Cross-Origin-Opener-Policy": "same-origin",
            
            # Cross-Origin Resource Policy
            "Cross-Origin-Resource-Policy": "same-origin",
            
            # Cache Control for sensitive endpoints
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            
            # Pragma for HTTP/1.0 compatibility
            "Pragma": "no-cache",
            
            # Expires header
            "Expires": "0",
            
            # Server header obfuscation
            "Server": "VisionFintech-API",
            
            # X-Powered-By removal (handled by removing the header)
            # Custom security headers
            "X-API-Version": "v1",
            "X-Security-Policy": "strict",
        }
        
        # Add custom headers
        headers.update(self.custom_headers)
        
        return headers
    
    def _get_csp_policy(self) -> str:
        """Generate Content Security Policy."""
        # Base CSP for API endpoints
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline'",  # Adjust based on needs
            "style-src 'self' 'unsafe-inline'",   # Adjust based on needs
            "img-src 'self' data: https:",
            "font-src 'self' https:",
            "connect-src 'self' https:",
            "media-src 'self'",
            "object-src 'none'",
            "frame-src 'none'",
            "worker-src 'self'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "base-uri 'self'",
            "upgrade-insecure-requests",
        ]
        
        # Add report URI if configured
        if hasattr(settings, 'CSP_REPORT_URI') and settings.CSP_REPORT_URI:
            csp_directives.append(f"report-uri {settings.CSP_REPORT_URI}")
        
        return "; ".join(csp_directives)
    
    def _get_permissions_policy(self) -> str:
        """Generate Permissions Policy header."""
        permissions = [
            "accelerometer=()",
            "ambient-light-sensor=()",
            "autoplay=()",
            "battery=()",
            "camera=()",
            "cross-origin-isolated=()",
            "display-capture=()",
            "document-domain=()",
            "encrypted-media=()",
            "execution-while-not-rendered=()",
            "execution-while-out-of-viewport=()",
            "fullscreen=()",
            "geolocation=()",
            "gyroscope=()",
            "keyboard-map=()",
            "magnetometer=()",
            "microphone=()",
            "midi=()",
            "navigation-override=()",
            "payment=()",
            "picture-in-picture=()",
            "publickey-credentials-get=()",
            "screen-wake-lock=()",
            "sync-xhr=()",
            "usb=()",
            "web-share=()",
            "xr-spatial-tracking=()",
        ]
        
        return ", ".join(permissions)
    
    def _should_apply_headers(self, request: Request, response: Response) -> bool:
        """Determine if security headers should be applied."""
        # Skip for OPTIONS requests
        if request.method == "OPTIONS":
            return False
        
        # Skip for health check endpoints (optional)
        if request.url.path in ["/health", "/api/health", "/api/v1/health"]:
            return False
        
        # Skip for static files (if serving any)
        if request.url.path.startswith("/static/"):
            return False
        
        return True
    
    def _customize_headers_for_endpoint(self, request: Request) -> Dict[str, str]:
        """Customize headers based on endpoint type."""
        headers = self.security_headers.copy()
        path = request.url.path
        
        # Relax CSP for documentation endpoints
        if "/docs" in path or "/redoc" in path:
            headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https:; "
                "font-src 'self' https://cdn.jsdelivr.net;"
            )
            headers["X-Frame-Options"] = "SAMEORIGIN"
        
        # Stricter headers for payment endpoints
        if "/api/v1/payments/" in path or "/api/v1/bills/pay" in path:
            headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private, max-age=0"
            headers["X-Content-Type-Options"] = "nosniff"
            headers["X-Frame-Options"] = "DENY"
        
        # Authentication endpoints
        if "/api/v1/auth/" in path:
            headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            headers["Clear-Site-Data"] = '"cache", "cookies", "storage"' if "logout" in path else '"cache"'
        
        # Admin endpoints - extra security
        if "/api/v1/admin/" in path:
            headers["X-Admin-Access"] = "restricted"
            headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private, max-age=0"
        
        return headers
    
    async def dispatch(self, request: Request, call_next):
        """Apply security headers to responses."""
        response = await call_next(request)
        
        # Check if headers should be applied
        if not self._should_apply_headers(request, response):
            return response
        
        try:
            # Get customized headers for this endpoint
            headers_to_apply = self._customize_headers_for_endpoint(request)
            
            # Apply security headers
            for header_name, header_value in headers_to_apply.items():
                response.headers[header_name] = header_value
            
            # Remove potentially sensitive headers
            sensitive_headers = ["X-Powered-By", "Server"]
            for header in sensitive_headers:
                if header in response.headers and header != "Server":  # Keep our custom server header
                    del response.headers[header]
            
            # Add security-related response headers based on content type
            content_type = response.headers.get("content-type", "")
            
            if "application/json" in content_type:
                response.headers["X-Content-Type-Options"] = "nosniff"
            
            # Log security header application for monitoring
            if hasattr(settings, 'LOG_SECURITY_HEADERS') and settings.LOG_SECURITY_HEADERS:
                logger.debug(f"Applied security headers to {request.url.path}")
        
        except Exception as e:
            logger.error(f"Error applying security headers: {e}")
            # Continue without failing the request
        
        return response

# Utility functions for custom security header management
def get_csp_nonce() -> str:
    """Generate a cryptographically secure nonce for CSP."""
    import secrets
    import base64
    
    nonce_bytes = secrets.token_bytes(16)
    return base64.b64encode(nonce_bytes).decode('utf-8')

def validate_security_headers(headers: Dict[str, str]) -> Dict[str, bool]:
    """Validate that required security headers are present."""
    required_headers = [
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "X-XSS-Protection",
        "Referrer-Policy"
    ]
    
    validation_results = {}
    for header in required_headers:
        validation_results[header] = header in headers
    
    return validation_results

def create_custom_csp(allowed_sources: Dict[str, list]) -> str:
    """Create a custom CSP policy."""
    directives = []
    
    for directive, sources in allowed_sources.items():
        if sources:
            source_list = " ".join(sources)
            directives.append(f"{directive} {source_list}")
    
    return "; ".join(directives)