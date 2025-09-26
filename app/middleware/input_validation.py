"""Enhanced input validation middleware with XSS and SQL injection prevention."""

import re
import html
import json
import urllib.parse
from typing import Dict, List, Set, Optional, Any, Union
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger(__name__)

class InputValidationMiddleware(BaseHTTPMiddleware):
    """Enhanced input validation middleware with security checks."""
    
    def __init__(self, 
                 app,
                 enable_xss_protection: bool = True,
                 enable_sql_injection_protection: bool = True,
                 enable_command_injection_protection: bool = True,
                 enable_path_traversal_protection: bool = True,
                 max_string_length: int = 10000,
                 max_array_length: int = 1000,
                 max_nesting_depth: int = 10):
        super().__init__(app)
        self.enable_xss_protection = enable_xss_protection
        self.enable_sql_injection_protection = enable_sql_injection_protection
        self.enable_command_injection_protection = enable_command_injection_protection
        self.enable_path_traversal_protection = enable_path_traversal_protection
        self.max_string_length = max_string_length
        self.max_array_length = max_array_length
        self.max_nesting_depth = max_nesting_depth
        
        # Compile regex patterns for performance
        self._compile_security_patterns()
        
        # Define sensitive endpoints that need extra validation
        self.sensitive_endpoints = self._get_sensitive_endpoints()
        
        # Define endpoints that should skip validation
        self.skip_validation_endpoints = self._get_skip_validation_endpoints()
        
        # Define allowed file extensions for uploads
        self.allowed_file_extensions = self._get_allowed_file_extensions()
    
    def _compile_security_patterns(self):
        """Compile regex patterns for security checks."""
        # XSS patterns
        self.xss_patterns = [
            re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL),
            re.compile(r'javascript:', re.IGNORECASE),
            re.compile(r'vbscript:', re.IGNORECASE),
            re.compile(r'onload\s*=', re.IGNORECASE),
            re.compile(r'onerror\s*=', re.IGNORECASE),
            re.compile(r'onclick\s*=', re.IGNORECASE),
            re.compile(r'onmouseover\s*=', re.IGNORECASE),
            re.compile(r'<iframe[^>]*>', re.IGNORECASE),
            re.compile(r'<object[^>]*>', re.IGNORECASE),
            re.compile(r'<embed[^>]*>', re.IGNORECASE),
            re.compile(r'<link[^>]*>', re.IGNORECASE),
            re.compile(r'<meta[^>]*>', re.IGNORECASE),
            re.compile(r'expression\s*\(', re.IGNORECASE),
            re.compile(r'url\s*\(\s*["\']?\s*javascript:', re.IGNORECASE),
        ]
        
        # SQL injection patterns
        self.sql_patterns = [
            re.compile(r'(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|EXECUTE)\b)', re.IGNORECASE),
            re.compile(r'(\b(UNION|JOIN)\b.*\b(SELECT|FROM)\b)', re.IGNORECASE),
            re.compile(r'(\b(OR|AND)\b\s+\d+\s*=\s*\d+)', re.IGNORECASE),
            re.compile(r'(\b(OR|AND)\b\s+["\']\w+["\']\s*=\s*["\']\w+["\'])', re.IGNORECASE),
            re.compile(r'(--|#|/\*|\*/)', re.IGNORECASE),
            re.compile(r'(\bxp_cmdshell\b)', re.IGNORECASE),
            re.compile(r'(\bsp_executesql\b)', re.IGNORECASE),
            re.compile(r'(\bINTO\s+OUTFILE\b)', re.IGNORECASE),
            re.compile(r'(\bLOAD_FILE\b)', re.IGNORECASE),
            re.compile(r'(\bINTO\s+DUMPFILE\b)', re.IGNORECASE),
            re.compile(r'(\bSLEEP\s*\()', re.IGNORECASE),
            re.compile(r'(\bBENCHMARK\s*\()', re.IGNORECASE),
        ]
        
        # Command injection patterns
        self.command_patterns = [
            re.compile(r'[;&|`$(){}\[\]<>]'),
            re.compile(r'\b(cat|ls|pwd|whoami|id|uname|ps|netstat|ifconfig|ping|wget|curl|nc|telnet|ssh|ftp)\b', re.IGNORECASE),
            re.compile(r'\b(cmd|powershell|bash|sh|zsh|csh|tcsh)\b', re.IGNORECASE),
            re.compile(r'\b(eval|exec|system|shell_exec|passthru|popen)\b', re.IGNORECASE),
        ]
        
        # Path traversal patterns
        self.path_traversal_patterns = [
            re.compile(r'\.\./'),
            re.compile(r'\.\.\\'),
            re.compile(r'%2e%2e%2f', re.IGNORECASE),
            re.compile(r'%2e%2e%5c', re.IGNORECASE),
            re.compile(r'\.\.%2f', re.IGNORECASE),
            re.compile(r'\.\.%5c', re.IGNORECASE),
        ]
    
    def _get_sensitive_endpoints(self) -> Set[str]:
        """Define endpoints that require extra validation."""
        return {
            "/api/v1/payments/",
            "/api/v1/bills/",
            "/api/v1/wallet/",
            "/api/v1/admin/",
            "/api/v1/users/profile",
            "/api/v1/users/update",
        }
    
    def _get_skip_validation_endpoints(self) -> Set[str]:
        """Define endpoints that should skip validation."""
        return {
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/webhooks/",  # Webhooks have their own validation
        }
    
    def _get_allowed_file_extensions(self) -> Set[str]:
        """Define allowed file extensions for uploads."""
        return {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',  # Images
            '.pdf', '.doc', '.docx', '.txt', '.rtf',  # Documents
            '.csv', '.xlsx', '.xls',  # Spreadsheets
        }
    
    def _should_validate_request(self, request: Request) -> bool:
        """Determine if request should be validated."""
        path = request.url.path
        
        # Skip validation for certain endpoints
        for skip_path in self.skip_validation_endpoints:
            if path.startswith(skip_path):
                return False
        
        # Only validate requests with payloads
        if request.method in ['POST', 'PUT', 'PATCH']:
            return True
        
        # Validate query parameters for GET requests to sensitive endpoints
        if request.method == 'GET':
            for sensitive_path in self.sensitive_endpoints:
                if path.startswith(sensitive_path):
                    return True
        
        return False
    
    def _check_xss(self, value: str) -> List[str]:
        """Check for XSS patterns in string value."""
        threats = []
        
        if not self.enable_xss_protection:
            return threats
        
        # Decode URL encoding
        decoded_value = urllib.parse.unquote(value)
        
        # Check against XSS patterns
        for pattern in self.xss_patterns:
            if pattern.search(decoded_value):
                threats.append(f"XSS pattern detected: {pattern.pattern}")
        
        return threats
    
    def _check_sql_injection(self, value: str) -> List[str]:
        """Check for SQL injection patterns in string value."""
        threats = []
        
        if not self.enable_sql_injection_protection:
            return threats
        
        # Decode URL encoding
        decoded_value = urllib.parse.unquote(value)
        
        # Check against SQL injection patterns
        for pattern in self.sql_patterns:
            if pattern.search(decoded_value):
                threats.append(f"SQL injection pattern detected: {pattern.pattern}")
        
        return threats
    
    def _check_command_injection(self, value: str) -> List[str]:
        """Check for command injection patterns in string value."""
        threats = []
        
        if not self.enable_command_injection_protection:
            return threats
        
        # Decode URL encoding
        decoded_value = urllib.parse.unquote(value)
        
        # Check against command injection patterns
        for pattern in self.command_patterns:
            if pattern.search(decoded_value):
                threats.append(f"Command injection pattern detected: {pattern.pattern}")
        
        return threats
    
    def _check_path_traversal(self, value: str) -> List[str]:
        """Check for path traversal patterns in string value."""
        threats = []
        
        if not self.enable_path_traversal_protection:
            return threats
        
        # Decode URL encoding
        decoded_value = urllib.parse.unquote(value)
        
        # Check against path traversal patterns
        for pattern in self.path_traversal_patterns:
            if pattern.search(decoded_value):
                threats.append(f"Path traversal pattern detected: {pattern.pattern}")
        
        return threats
    
    def _validate_string_value(self, value: str, field_name: str = "unknown") -> List[str]:
        """Validate a string value for security threats."""
        threats = []
        
        # Check string length
        if len(value) > self.max_string_length:
            threats.append(f"String too long: {len(value)} > {self.max_string_length}")
        
        # Check for security threats
        threats.extend(self._check_xss(value))
        threats.extend(self._check_sql_injection(value))
        threats.extend(self._check_command_injection(value))
        threats.extend(self._check_path_traversal(value))
        
        return threats
    
    def _validate_data_structure(self, data: Any, depth: int = 0, field_path: str = "root") -> List[str]:
        """Recursively validate data structure for security threats."""
        threats = []
        
        # Check nesting depth
        if depth > self.max_nesting_depth:
            threats.append(f"Nesting depth exceeded: {depth} > {self.max_nesting_depth}")
            return threats
        
        if isinstance(data, str):
            threats.extend(self._validate_string_value(data, field_path))
        
        elif isinstance(data, dict):
            # Check dictionary size
            if len(data) > 1000:  # Reasonable limit for dict size
                threats.append(f"Dictionary too large: {len(data)} keys")
            
            for key, value in data.items():
                # Validate key
                if isinstance(key, str):
                    key_threats = self._validate_string_value(key, f"{field_path}.{key}")
                    threats.extend(key_threats)
                
                # Validate value recursively
                value_threats = self._validate_data_structure(
                    value, depth + 1, f"{field_path}.{key}"
                )
                threats.extend(value_threats)
        
        elif isinstance(data, list):
            # Check array length
            if len(data) > self.max_array_length:
                threats.append(f"Array too large: {len(data)} > {self.max_array_length}")
            
            for i, item in enumerate(data):
                item_threats = self._validate_data_structure(
                    item, depth + 1, f"{field_path}[{i}]"
                )
                threats.extend(item_threats)
        
        return threats
    
    def _validate_query_params(self, request: Request) -> List[str]:
        """Validate query parameters."""
        threats = []
        
        for key, value in request.query_params.items():
            # Validate parameter name
            key_threats = self._validate_string_value(key, f"query.{key}")
            threats.extend(key_threats)
            
            # Validate parameter value
            value_threats = self._validate_string_value(value, f"query.{key}")
            threats.extend(value_threats)
        
        return threats
    
    def _validate_headers(self, request: Request) -> List[str]:
        """Validate request headers for security threats."""
        threats = []
        
        # Headers to validate
        headers_to_check = {
            'user-agent', 'referer', 'x-forwarded-for', 
            'x-real-ip', 'x-custom-header'
        }
        
        for header_name, header_value in request.headers.items():
            if header_name.lower() in headers_to_check:
                header_threats = self._validate_string_value(
                    header_value, f"header.{header_name}"
                )
                threats.extend(header_threats)
        
        return threats
    
    async def _validate_request_body(self, request: Request) -> List[str]:
        """Validate request body for security threats."""
        threats = []
        
        try:
            # Get request body
            body = await request.body()
            
            if not body:
                return threats
            
            # Try to parse as JSON
            content_type = request.headers.get('content-type', '').lower()
            
            if 'application/json' in content_type:
                try:
                    json_data = json.loads(body.decode('utf-8'))
                    threats.extend(self._validate_data_structure(json_data))
                except json.JSONDecodeError:
                    threats.append("Invalid JSON format")
                except UnicodeDecodeError:
                    threats.append("Invalid UTF-8 encoding")
            
            elif 'application/x-www-form-urlencoded' in content_type:
                # Parse form data
                form_data = urllib.parse.parse_qs(body.decode('utf-8'))
                for key, values in form_data.items():
                    key_threats = self._validate_string_value(key, f"form.{key}")
                    threats.extend(key_threats)
                    
                    for value in values:
                        value_threats = self._validate_string_value(value, f"form.{key}")
                        threats.extend(value_threats)
            
            elif 'multipart/form-data' in content_type:
                # For file uploads, we'll do basic validation
                # More detailed validation would require parsing multipart data
                body_str = body.decode('utf-8', errors='ignore')
                if len(body_str) > 0:
                    threats.extend(self._validate_string_value(body_str[:1000], "multipart"))
        
        except Exception as e:
            logger.error(f"Error validating request body: {e}")
            threats.append(f"Body validation error: {str(e)}")
        
        return threats
    
    def _create_validation_error_response(self, threats: List[str], endpoint: str) -> JSONResponse:
        """Create validation error response."""
        return JSONResponse(
            status_code=400,
            content={
                "error": "INPUT_VALIDATION_FAILED",
                "message": "Request contains potentially malicious content",
                "code": "SECURITY_VALIDATION_ERROR",
                "details": {
                    "endpoint": endpoint,
                    "threats_detected": len(threats),
                    "threat_types": list(set([threat.split(':')[0] for threat in threats])),
                    "security_notice": "This request has been logged for security review"
                }
            },
            headers={
                "X-Validation-Failed": "true",
                "X-Threats-Detected": str(len(threats)),
                "X-Content-Type-Options": "nosniff"
            }
        )
    
    def _sanitize_value(self, value: str) -> str:
        """Sanitize string value by removing/escaping dangerous content."""
        # HTML escape
        sanitized = html.escape(value)
        
        # Remove null bytes
        sanitized = sanitized.replace('\x00', '')
        
        # Limit length
        if len(sanitized) > self.max_string_length:
            sanitized = sanitized[:self.max_string_length]
        
        return sanitized
    
    async def dispatch(self, request: Request, call_next):
        """Process request with input validation."""
        # Check if validation is needed
        if not self._should_validate_request(request):
            return await call_next(request)
        
        threats = []
        
        # Validate query parameters
        threats.extend(self._validate_query_params(request))
        
        # Validate headers
        threats.extend(self._validate_headers(request))
        
        # Validate request body for POST/PUT/PATCH requests
        if request.method in ['POST', 'PUT', 'PATCH']:
            body_threats = await self._validate_request_body(request)
            threats.extend(body_threats)
        
        # If threats detected, log and block
        if threats:
            client_ip = getattr(request.state, 'client_ip', request.client.host if request.client else 'unknown')
            
            logger.warning(
                f"Security threats detected from IP {client_ip} on {request.method} {request.url.path}: "
                f"{len(threats)} threats - {', '.join(threats[:3])}{'...' if len(threats) > 3 else ''}"
            )
            
            return self._create_validation_error_response(threats, request.url.path)
        
        # Validation passed - process request
        try:
            response = await call_next(request)
            
            # Add validation status to response headers
            response.headers["X-Input-Validation"] = "passed"
            response.headers["X-Security-Check"] = "completed"
            
            return response
        
        except Exception as e:
            logger.error(f"Error processing validated request: {e}")
            raise

# Utility functions for input validation
def validate_string_input(value: str, 
                         max_length: int = 10000,
                         check_xss: bool = True,
                         check_sql: bool = True) -> Dict[str, Any]:
    """Validate a single string input."""
    middleware = InputValidationMiddleware(None)
    threats = middleware._validate_string_value(value)
    
    return {
        "is_valid": len(threats) == 0,
        "threats": threats,
        "sanitized_value": middleware._sanitize_value(value)
    }

def sanitize_user_input(data: Union[str, Dict, List]) -> Union[str, Dict, List]:
    """Sanitize user input data."""
    middleware = InputValidationMiddleware(None)
    
    if isinstance(data, str):
        return middleware._sanitize_value(data)
    elif isinstance(data, dict):
        return {key: sanitize_user_input(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [sanitize_user_input(item) for item in data]
    else:
        return data

class ValidationConfig:
    """Configuration class for input validation."""
    
    def __init__(self,
                 enable_xss_protection: bool = True,
                 enable_sql_injection_protection: bool = True,
                 enable_command_injection_protection: bool = True,
                 enable_path_traversal_protection: bool = True,
                 max_string_length: int = 10000,
                 max_array_length: int = 1000,
                 max_nesting_depth: int = 10):
        self.enable_xss_protection = enable_xss_protection
        self.enable_sql_injection_protection = enable_sql_injection_protection
        self.enable_command_injection_protection = enable_command_injection_protection
        self.enable_path_traversal_protection = enable_path_traversal_protection
        self.max_string_length = max_string_length
        self.max_array_length = max_array_length
        self.max_nesting_depth = max_nesting_depth
    
    def create_middleware(self, app):
        """Create input validation middleware with this configuration."""
        return InputValidationMiddleware(
            app=app,
            enable_xss_protection=self.enable_xss_protection,
            enable_sql_injection_protection=self.enable_sql_injection_protection,
            enable_command_injection_protection=self.enable_command_injection_protection,
            enable_path_traversal_protection=self.enable_path_traversal_protection,
            max_string_length=self.max_string_length,
            max_array_length=self.max_array_length,
            max_nesting_depth=self.max_nesting_depth
        )