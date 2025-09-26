"""Comprehensive audit logging middleware for financial transactions and security events."""

import json
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Column, String, DateTime, Text, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.core.database import Base, get_db
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class AuditLog(Base):
    """Audit log model for tracking system events."""
    __tablename__ = "audit_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    session_id = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible
    user_agent = Column(Text, nullable=True)
    
    # Request details
    method = Column(String(10), nullable=False)
    endpoint = Column(String(500), nullable=False)
    request_id = Column(String(255), nullable=True)
    
    # Event classification
    event_type = Column(String(50), nullable=False)  # AUTHENTICATION, PAYMENT, ADMIN, etc.
    event_category = Column(String(50), nullable=False)  # SUCCESS, FAILURE, SUSPICIOUS
    severity = Column(String(20), nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
    
    # Event details
    action = Column(String(100), nullable=False)
    resource = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    
    # Request/Response data (sanitized)
    request_data = Column(JSONB, nullable=True)
    response_status = Column(Integer, nullable=True)
    response_data = Column(JSONB, nullable=True)
    
    # Security context
    risk_score = Column(Integer, default=0)
    flags = Column(JSONB, nullable=True)  # Security flags and alerts
    
    # Performance metrics
    processing_time_ms = Column(Integer, nullable=True)
    
    # Compliance and retention
    retention_period_days = Column(Integer, default=2555)  # 7 years for financial data
    is_pii = Column(Boolean, default=False)
    is_financial = Column(Boolean, default=False)

class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for comprehensive audit logging."""
    
    def __init__(self, app):
        super().__init__(app)
        self.sensitive_endpoints = self._get_sensitive_endpoints()
        self.pii_fields = self._get_pii_fields()
        self.financial_endpoints = self._get_financial_endpoints()
    
    def _get_sensitive_endpoints(self) -> List[str]:
        """Define endpoints that require audit logging."""
        return [
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/api/v1/auth/logout",
            "/api/v1/auth/refresh",
            "/api/v1/auth/forgot-password",
            "/api/v1/auth/reset-password",
            "/api/v1/payments/",
            "/api/v1/bills/pay",
            "/api/v1/wallet/",
            "/api/v1/transactions/",
            "/api/v1/admin/",
            "/api/v1/users/profile",
            "/api/v1/users/update",
            "/api/v1/users/delete",
            "/api/v1/webhooks/",
        ]
    
    def _get_pii_fields(self) -> List[str]:
        """Define fields containing PII that should be sanitized."""
        return [
            "password",
            "email",
            "phone",
            "ssn",
            "account_number",
            "card_number",
            "cvv",
            "pin",
            "token",
            "secret",
            "key",
            "address",
            "full_name",
            "first_name",
            "last_name",
            "date_of_birth",
        ]
    
    def _get_financial_endpoints(self) -> List[str]:
        """Define endpoints handling financial data."""
        return [
            "/api/v1/payments/",
            "/api/v1/bills/pay",
            "/api/v1/wallet/",
            "/api/v1/transactions/",
            "/api/v1/cashback/",
        ]
    
    def _should_audit(self, request: Request) -> bool:
        """Determine if request should be audited."""
        path = request.url.path
        
        # Always audit sensitive endpoints
        for endpoint in self.sensitive_endpoints:
            if path.startswith(endpoint):
                return True
        
        # Audit failed requests (4xx, 5xx)
        # This will be checked in the response phase
        
        # Audit admin operations
        if "/admin/" in path:
            return True
        
        # Skip health checks and docs
        if path in ["/health", "/docs", "/redoc", "/openapi.json"]:
            return False
        
        return False
    
    def _sanitize_data(self, data: Any) -> Any:
        """Sanitize sensitive data for logging."""
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                key_lower = key.lower()
                if any(pii_field in key_lower for pii_field in self.pii_fields):
                    sanitized[key] = "[REDACTED]"
                else:
                    sanitized[key] = self._sanitize_data(value)
            return sanitized
        elif isinstance(data, list):
            return [self._sanitize_data(item) for item in data]
        elif isinstance(data, str) and len(data) > 1000:
            return data[:1000] + "...[TRUNCATED]"
        else:
            return data
    
    def _extract_user_context(self, request: Request) -> Dict[str, Any]:
        """Extract user context from request."""
        context = {
            "user_id": getattr(request.state, 'user_id', None),
            "session_id": getattr(request.state, 'session_id', None),
            "ip_address": self._get_client_ip(request),
            "user_agent": request.headers.get("User-Agent", ""),
        }
        return context
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address considering proxies."""
        # Check for forwarded headers
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"
    
    def _determine_event_type(self, request: Request) -> str:
        """Determine event type based on endpoint."""
        path = request.url.path
        
        if "/auth/" in path:
            return "AUTHENTICATION"
        elif any(endpoint in path for endpoint in self.financial_endpoints):
            return "FINANCIAL"
        elif "/admin/" in path:
            return "ADMIN"
        elif "/users/" in path:
            return "USER_MANAGEMENT"
        elif "/webhooks/" in path:
            return "WEBHOOK"
        else:
            return "API_ACCESS"
    
    def _determine_severity(self, request: Request, response: Response) -> str:
        """Determine event severity."""
        status_code = response.status_code
        path = request.url.path
        
        # Critical for financial operations with errors
        if any(endpoint in path for endpoint in self.financial_endpoints):
            if status_code >= 400:
                return "CRITICAL"
            else:
                return "HIGH"
        
        # High for authentication failures
        if "/auth/" in path and status_code >= 400:
            return "HIGH"
        
        # High for admin operations
        if "/admin/" in path:
            return "HIGH"
        
        # Medium for other client errors
        if 400 <= status_code < 500:
            return "MEDIUM"
        
        # High for server errors
        if status_code >= 500:
            return "HIGH"
        
        return "LOW"
    
    def _calculate_risk_score(self, request: Request, response: Response, user_context: Dict) -> int:
        """Calculate risk score for the event."""
        score = 0
        
        # Base score for different operations
        path = request.url.path
        if any(endpoint in path for endpoint in self.financial_endpoints):
            score += 30
        elif "/auth/" in path:
            score += 20
        elif "/admin/" in path:
            score += 40
        
        # Increase score for failures
        if response.status_code >= 400:
            score += 25
        
        # Increase score for suspicious patterns
        if response.status_code == 429:  # Rate limited
            score += 35
        
        # IP-based risk (simplified)
        ip = user_context.get("ip_address", "")
        if ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("172."):
            score -= 10  # Internal network, lower risk
        
        # Time-based risk (off-hours access)
        current_hour = datetime.utcnow().hour
        if current_hour < 6 or current_hour > 22:  # Outside business hours
            score += 15
        
        return min(score, 100)  # Cap at 100
    
    def _generate_security_flags(self, request: Request, response: Response, risk_score: int) -> List[str]:
        """Generate security flags based on request analysis."""
        flags = []
        
        # High risk score
        if risk_score > 70:
            flags.append("HIGH_RISK")
        
        # Multiple failed attempts (would need session tracking)
        if response.status_code == 401 and "/auth/" in request.url.path:
            flags.append("AUTH_FAILURE")
        
        # Rate limiting triggered
        if response.status_code == 429:
            flags.append("RATE_LIMITED")
        
        # Suspicious user agent
        user_agent = request.headers.get("User-Agent", "").lower()
        if "bot" in user_agent or "crawler" in user_agent or not user_agent:
            flags.append("SUSPICIOUS_USER_AGENT")
        
        # Large request size
        content_length = request.headers.get("Content-Length")
        if content_length and int(content_length) > 1024 * 1024:  # 1MB
            flags.append("LARGE_REQUEST")
        
        return flags
    
    async def _create_audit_log(self, 
                               request: Request, 
                               response: Response, 
                               processing_time: float,
                               request_body: Any = None):
        """Create audit log entry."""
        try:
            user_context = self._extract_user_context(request)
            event_type = self._determine_event_type(request)
            severity = self._determine_severity(request, response)
            risk_score = self._calculate_risk_score(request, response, user_context)
            security_flags = self._generate_security_flags(request, response, risk_score)
            
            # Determine event category
            if response.status_code < 400:
                category = "SUCCESS"
            elif response.status_code < 500:
                category = "FAILURE"
            else:
                category = "ERROR"
            
            if risk_score > 70 or "HIGH_RISK" in security_flags:
                category = "SUSPICIOUS"
            
            # Sanitize request data
            sanitized_request = self._sanitize_data(request_body) if request_body else None
            
            # Create audit log entry
            audit_entry = AuditLog(
                timestamp=datetime.utcnow(),
                user_id=user_context["user_id"],
                session_id=user_context["session_id"],
                ip_address=user_context["ip_address"],
                user_agent=user_context["user_agent"],
                method=request.method,
                endpoint=request.url.path,
                request_id=getattr(request.state, 'request_id', str(uuid.uuid4())),
                event_type=event_type,
                event_category=category,
                severity=severity,
                action=f"{request.method} {request.url.path}",
                resource=request.url.path,
                description=f"{request.method} request to {request.url.path} returned {response.status_code}",
                request_data=sanitized_request,
                response_status=response.status_code,
                risk_score=risk_score,
                flags=security_flags,
                processing_time_ms=int(processing_time * 1000),
                is_pii=any(pii_field in str(request_body).lower() for pii_field in self.pii_fields) if request_body else False,
                is_financial=any(endpoint in request.url.path for endpoint in self.financial_endpoints)
            )
            
            # Save to database (async)
            # Note: This would need proper database session handling
            # For now, we'll log to file/external system
            
            audit_data = {
                "timestamp": audit_entry.timestamp.isoformat(),
                "user_id": str(audit_entry.user_id) if audit_entry.user_id else None,
                "ip_address": audit_entry.ip_address,
                "method": audit_entry.method,
                "endpoint": audit_entry.endpoint,
                "event_type": audit_entry.event_type,
                "event_category": audit_entry.event_category,
                "severity": audit_entry.severity,
                "response_status": audit_entry.response_status,
                "risk_score": audit_entry.risk_score,
                "flags": audit_entry.flags,
                "processing_time_ms": audit_entry.processing_time_ms,
            }
            
            # Log to structured logger
            logger.info(f"AUDIT: {json.dumps(audit_data)}", extra={"audit": True})
            
            # For high-risk events, also log as warning
            if risk_score > 70 or severity in ["HIGH", "CRITICAL"]:
                logger.warning(f"HIGH_RISK_AUDIT: {json.dumps(audit_data)}", extra={"audit": True, "high_risk": True})
        
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")
    
    async def dispatch(self, request: Request, call_next):
        """Process request with audit logging."""
        start_time = time.time()
        
        # Check if this request should be audited
        should_audit = self._should_audit(request)
        
        # Capture request body for auditing (if needed)
        request_body = None
        if should_audit and request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            try:
                body = await request.body()
                if body:
                    content_type = request.headers.get("content-type", "")
                    if "application/json" in content_type:
                        request_body = json.loads(body.decode())
                    else:
                        request_body = {"content_type": content_type, "size": len(body)}
            except Exception as e:
                logger.warning(f"Could not capture request body for audit: {e}")
        
        # Process request
        response = await call_next(request)
        
        # Calculate processing time
        processing_time = time.time() - start_time
        
        # Create audit log if needed
        if should_audit or response.status_code >= 400:
            await self._create_audit_log(request, response, processing_time, request_body)
        
        return response

# Utility functions for audit logging
async def log_security_event(event_type: str, 
                           description: str, 
                           user_id: Optional[str] = None,
                           severity: str = "MEDIUM",
                           additional_data: Optional[Dict] = None):
    """Log a custom security event."""
    try:
        audit_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "description": description,
            "user_id": user_id,
            "severity": severity,
            "additional_data": additional_data or {},
            "source": "manual_log"
        }
        
        logger.info(f"SECURITY_EVENT: {json.dumps(audit_data)}", extra={"security_event": True})
        
        if severity in ["HIGH", "CRITICAL"]:
            logger.warning(f"HIGH_SEVERITY_SECURITY_EVENT: {json.dumps(audit_data)}", 
                         extra={"security_event": True, "high_severity": True})
    
    except Exception as e:
        logger.error(f"Failed to log security event: {e}")

async def log_financial_transaction(transaction_type: str,
                                  amount: float,
                                  user_id: str,
                                  transaction_id: str,
                                  status: str,
                                  additional_data: Optional[Dict] = None):
    """Log financial transaction for compliance."""
    try:
        audit_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": "FINANCIAL_TRANSACTION",
            "transaction_type": transaction_type,
            "amount": amount,
            "user_id": user_id,
            "transaction_id": transaction_id,
            "status": status,
            "additional_data": additional_data or {},
            "compliance": True
        }
        
        logger.info(f"FINANCIAL_AUDIT: {json.dumps(audit_data)}", 
                   extra={"financial_audit": True, "compliance": True})
    
    except Exception as e:
        logger.error(f"Failed to log financial transaction: {e}")