"""Session management middleware with Redis for tracking active sessions."""

import json
import time
import uuid
from typing import Dict, List, Optional, Set, Any
from datetime import datetime, timedelta
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import redis
import logging
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

class SessionManager:
    """Redis-based session manager for tracking active sessions."""
    
    def __init__(self, 
                 redis_client: redis.Redis,
                 session_timeout: int = 3600,  # 1 hour
                 max_concurrent_sessions: int = 5,
                 cleanup_interval: int = 300):  # 5 minutes
        self.redis = redis_client
        self.session_timeout = session_timeout
        self.max_concurrent_sessions = max_concurrent_sessions
        self.cleanup_interval = cleanup_interval
        self.last_cleanup = time.time()
        
        # Redis key prefixes
        self.session_prefix = "session:"
        self.user_sessions_prefix = "user_sessions:"
        self.session_data_prefix = "session_data:"
        self.active_sessions_prefix = "active_sessions:"
    
    def _get_session_key(self, session_id: str) -> str:
        """Get Redis key for session."""
        return f"{self.session_prefix}{session_id}"
    
    def _get_user_sessions_key(self, user_id: str) -> str:
        """Get Redis key for user's active sessions."""
        return f"{self.user_sessions_prefix}{user_id}"
    
    def _get_session_data_key(self, session_id: str) -> str:
        """Get Redis key for session data."""
        return f"{self.session_data_prefix}{session_id}"
    
    def _get_active_sessions_key(self) -> str:
        """Get Redis key for active sessions set."""
        return f"{self.active_sessions_prefix}all"
    
    def create_session(self, 
                      user_id: str, 
                      user_data: Dict[str, Any],
                      device_info: Optional[Dict[str, str]] = None,
                      ip_address: Optional[str] = None) -> Dict[str, Any]:
        """Create a new session for user."""
        try:
            # Check concurrent session limit
            if not self._check_concurrent_sessions(user_id):
                raise HTTPException(
                    status_code=429,
                    detail="Maximum concurrent sessions exceeded"
                )
            
            # Generate session ID
            session_id = str(uuid.uuid4())
            current_time = time.time()
            
            # Session metadata
            session_data = {
                "session_id": session_id,
                "user_id": user_id,
                "created_at": current_time,
                "last_activity": current_time,
                "expires_at": current_time + self.session_timeout,
                "ip_address": ip_address,
                "device_info": device_info or {},
                "user_data": user_data,
                "is_active": True,
                "login_count": self._get_user_login_count(user_id) + 1
            }
            
            # Store session data
            session_key = self._get_session_key(session_id)
            session_data_key = self._get_session_data_key(session_id)
            user_sessions_key = self._get_user_sessions_key(user_id)
            active_sessions_key = self._get_active_sessions_key()
            
            # Use Redis pipeline for atomic operations
            pipe = self.redis.pipeline()
            
            # Store session metadata
            pipe.hset(session_key, mapping={
                "user_id": user_id,
                "created_at": current_time,
                "last_activity": current_time,
                "expires_at": current_time + self.session_timeout,
                "ip_address": ip_address or "",
                "is_active": "true"
            })
            pipe.expire(session_key, self.session_timeout)
            
            # Store detailed session data
            pipe.set(session_data_key, json.dumps(session_data), ex=self.session_timeout)
            
            # Add to user's active sessions
            pipe.sadd(user_sessions_key, session_id)
            pipe.expire(user_sessions_key, self.session_timeout)
            
            # Add to global active sessions
            pipe.sadd(active_sessions_key, session_id)
            
            # Execute pipeline
            pipe.execute()
            
            logger.info(f"Session created for user {user_id}: {session_id}")
            
            return session_data
        
        except Exception as e:
            logger.error(f"Error creating session for user {user_id}: {e}")
            raise
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data by session ID."""
        try:
            session_data_key = self._get_session_data_key(session_id)
            session_data = self.redis.get(session_data_key)
            
            if not session_data:
                return None
            
            session = json.loads(session_data)
            
            # Check if session is expired
            if session.get("expires_at", 0) < time.time():
                self.invalidate_session(session_id)
                return None
            
            return session
        
        except Exception as e:
            logger.error(f"Error getting session {session_id}: {e}")
            return None
    
    def update_session_activity(self, session_id: str) -> bool:
        """Update session last activity timestamp."""
        try:
            current_time = time.time()
            new_expires_at = current_time + self.session_timeout
            
            session_key = self._get_session_key(session_id)
            session_data_key = self._get_session_data_key(session_id)
            
            # Check if session exists
            if not self.redis.exists(session_key):
                return False
            
            # Update session metadata
            pipe = self.redis.pipeline()
            pipe.hset(session_key, mapping={
                "last_activity": current_time,
                "expires_at": new_expires_at
            })
            pipe.expire(session_key, self.session_timeout)
            
            # Update detailed session data
            session_data = self.get_session(session_id)
            if session_data:
                session_data["last_activity"] = current_time
                session_data["expires_at"] = new_expires_at
                pipe.set(session_data_key, json.dumps(session_data), ex=self.session_timeout)
            
            pipe.execute()
            
            return True
        
        except Exception as e:
            logger.error(f"Error updating session activity {session_id}: {e}")
            return False
    
    def invalidate_session(self, session_id: str) -> bool:
        """Invalidate a specific session."""
        try:
            session_data = self.get_session(session_id)
            if not session_data:
                return False
            
            user_id = session_data.get("user_id")
            
            session_key = self._get_session_key(session_id)
            session_data_key = self._get_session_data_key(session_id)
            user_sessions_key = self._get_user_sessions_key(user_id) if user_id else None
            active_sessions_key = self._get_active_sessions_key()
            
            # Use Redis pipeline for atomic operations
            pipe = self.redis.pipeline()
            
            # Delete session data
            pipe.delete(session_key)
            pipe.delete(session_data_key)
            
            # Remove from user's active sessions
            if user_sessions_key:
                pipe.srem(user_sessions_key, session_id)
            
            # Remove from global active sessions
            pipe.srem(active_sessions_key, session_id)
            
            pipe.execute()
            
            logger.info(f"Session invalidated: {session_id}")
            
            return True
        
        except Exception as e:
            logger.error(f"Error invalidating session {session_id}: {e}")
            return False
    
    def invalidate_user_sessions(self, user_id: str, except_session_id: Optional[str] = None) -> int:
        """Invalidate all sessions for a user except optionally one."""
        try:
            user_sessions_key = self._get_user_sessions_key(user_id)
            session_ids = self.redis.smembers(user_sessions_key)
            
            invalidated_count = 0
            
            for session_id_bytes in session_ids:
                session_id = session_id_bytes.decode('utf-8')
                
                if except_session_id and session_id == except_session_id:
                    continue
                
                if self.invalidate_session(session_id):
                    invalidated_count += 1
            
            logger.info(f"Invalidated {invalidated_count} sessions for user {user_id}")
            
            return invalidated_count
        
        except Exception as e:
            logger.error(f"Error invalidating user sessions for {user_id}: {e}")
            return 0
    
    def get_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all active sessions for a user."""
        try:
            user_sessions_key = self._get_user_sessions_key(user_id)
            session_ids = self.redis.smembers(user_sessions_key)
            
            sessions = []
            for session_id_bytes in session_ids:
                session_id = session_id_bytes.decode('utf-8')
                session_data = self.get_session(session_id)
                
                if session_data:
                    # Remove sensitive data for listing
                    safe_session = {
                        "session_id": session_data["session_id"],
                        "created_at": session_data["created_at"],
                        "last_activity": session_data["last_activity"],
                        "ip_address": session_data.get("ip_address", ""),
                        "device_info": session_data.get("device_info", {}),
                        "is_active": session_data["is_active"]
                    }
                    sessions.append(safe_session)
            
            return sessions
        
        except Exception as e:
            logger.error(f"Error getting user sessions for {user_id}: {e}")
            return []
    
    def _check_concurrent_sessions(self, user_id: str) -> bool:
        """Check if user can create a new session (within concurrent limit)."""
        try:
            user_sessions_key = self._get_user_sessions_key(user_id)
            active_sessions_count = self.redis.scard(user_sessions_key)
            
            return active_sessions_count < self.max_concurrent_sessions
        
        except Exception as e:
            logger.error(f"Error checking concurrent sessions for {user_id}: {e}")
            return False
    
    def _get_user_login_count(self, user_id: str) -> int:
        """Get user's total login count."""
        try:
            login_count_key = f"login_count:{user_id}"
            count = self.redis.get(login_count_key)
            return int(count) if count else 0
        
        except Exception as e:
            logger.error(f"Error getting login count for {user_id}: {e}")
            return 0
    
    def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions."""
        try:
            current_time = time.time()
            
            # Skip if cleanup was done recently
            if current_time - self.last_cleanup < self.cleanup_interval:
                return 0
            
            active_sessions_key = self._get_active_sessions_key()
            session_ids = self.redis.smembers(active_sessions_key)
            
            expired_count = 0
            
            for session_id_bytes in session_ids:
                session_id = session_id_bytes.decode('utf-8')
                session_data = self.get_session(session_id)
                
                if not session_data or session_data.get("expires_at", 0) < current_time:
                    if self.invalidate_session(session_id):
                        expired_count += 1
            
            self.last_cleanup = current_time
            
            if expired_count > 0:
                logger.info(f"Cleaned up {expired_count} expired sessions")
            
            return expired_count
        
        except Exception as e:
            logger.error(f"Error during session cleanup: {e}")
            return 0
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        try:
            active_sessions_key = self._get_active_sessions_key()
            total_active_sessions = self.redis.scard(active_sessions_key)
            
            # Get user session counts
            user_session_keys = self.redis.keys(f"{self.user_sessions_prefix}*")
            users_with_sessions = len(user_session_keys)
            
            return {
                "total_active_sessions": total_active_sessions,
                "users_with_active_sessions": users_with_sessions,
                "max_concurrent_sessions_per_user": self.max_concurrent_sessions,
                "session_timeout_seconds": self.session_timeout,
                "last_cleanup": self.last_cleanup
            }
        
        except Exception as e:
            logger.error(f"Error getting session stats: {e}")
            return {}

class SessionManagementMiddleware(BaseHTTPMiddleware):
    """Middleware for session management and tracking."""
    
    def __init__(self, 
                 app,
                 session_manager: SessionManager,
                 jwt_secret_key: str,
                 jwt_algorithm: str = "HS256",
                 require_session_endpoints: Optional[Set[str]] = None):
        super().__init__(app)
        self.session_manager = session_manager
        self.jwt_secret_key = jwt_secret_key
        self.jwt_algorithm = jwt_algorithm
        self.require_session_endpoints = require_session_endpoints or self._get_default_session_endpoints()
    
    def _get_default_session_endpoints(self) -> Set[str]:
        """Get default endpoints that require active sessions."""
        return {
            "/api/v1/payments/",
            "/api/v1/bills/",
            "/api/v1/wallet/",
            "/api/v1/users/profile",
            "/api/v1/users/update",
            "/api/v1/admin/"
        }
    
    def _extract_session_from_token(self, token: str) -> Optional[str]:
        """Extract session ID from JWT token."""
        try:
            payload = jwt.decode(token, self.jwt_secret_key, algorithms=[self.jwt_algorithm])
            return payload.get("session_id")
        except JWTError:
            return None
    
    def _get_client_info(self, request: Request) -> Dict[str, str]:
        """Extract client information from request."""
        return {
            "user_agent": request.headers.get("user-agent", ""),
            "accept_language": request.headers.get("accept-language", ""),
            "platform": request.headers.get("sec-ch-ua-platform", ""),
            "mobile": request.headers.get("sec-ch-ua-mobile", "")
        }
    
    def _requires_session(self, request: Request) -> bool:
        """Check if endpoint requires active session."""
        path = request.url.path
        
        for endpoint in self.require_session_endpoints:
            if path.startswith(endpoint):
                return True
        
        return False
    
    def _create_session_error_response(self, message: str, status_code: int = 401) -> JSONResponse:
        """Create session-related error response."""
        return JSONResponse(
            status_code=status_code,
            content={
                "error": "SESSION_ERROR",
                "message": message,
                "code": "INVALID_SESSION"
            },
            headers={
                "X-Session-Status": "invalid",
                "X-Require-Login": "true"
            }
        )
    
    async def dispatch(self, request: Request, call_next):
        """Process request with session management."""
        # Periodic cleanup of expired sessions
        self.session_manager.cleanup_expired_sessions()
        
        # Extract authorization token
        auth_header = request.headers.get("authorization")
        token = None
        session_id = None
        
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            session_id = self._extract_session_from_token(token)
        
        # Check if endpoint requires session
        requires_session = self._requires_session(request)
        
        if requires_session:
            if not session_id:
                return self._create_session_error_response("Session required for this endpoint")
            
            # Validate session
            session_data = self.session_manager.get_session(session_id)
            if not session_data:
                return self._create_session_error_response("Invalid or expired session")
            
            # Update session activity
            self.session_manager.update_session_activity(session_id)
            
            # Add session data to request state
            request.state.session_id = session_id
            request.state.session_data = session_data
            request.state.user_id = session_data.get("user_id")
        
        # Add client info to request state
        request.state.client_info = self._get_client_info(request)
        request.state.client_ip = getattr(request.state, 'client_ip', 
                                        request.client.host if request.client else 'unknown')
        
        try:
            response = await call_next(request)
            
            # Add session headers to response
            if session_id:
                response.headers["X-Session-ID"] = session_id
                response.headers["X-Session-Status"] = "active"
            
            return response
        
        except Exception as e:
            logger.error(f"Error processing request with session management: {e}")
            raise

# Utility functions for session management
def create_session_token(session_data: Dict[str, Any], 
                        secret_key: str, 
                        algorithm: str = "HS256",
                        expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT token with session information."""
    to_encode = {
        "session_id": session_data["session_id"],
        "user_id": session_data["user_id"],
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + (expires_delta or timedelta(hours=1))
    }
    
    return jwt.encode(to_encode, secret_key, algorithm=algorithm)

def get_session_from_request(request: Request) -> Optional[Dict[str, Any]]:
    """Get session data from request state."""
    return getattr(request.state, 'session_data', None)

def get_user_id_from_request(request: Request) -> Optional[str]:
    """Get user ID from request state."""
    return getattr(request.state, 'user_id', None)

class SessionConfig:
    """Configuration class for session management."""
    
    def __init__(self,
                 redis_url: str = "redis://localhost:6379",
                 session_timeout: int = 3600,
                 max_concurrent_sessions: int = 5,
                 cleanup_interval: int = 300,
                 jwt_secret_key: str = "your-secret-key",
                 jwt_algorithm: str = "HS256"):
        self.redis_url = redis_url
        self.session_timeout = session_timeout
        self.max_concurrent_sessions = max_concurrent_sessions
        self.cleanup_interval = cleanup_interval
        self.jwt_secret_key = jwt_secret_key
        self.jwt_algorithm = jwt_algorithm
    
    def create_session_manager(self) -> SessionManager:
        """Create session manager with this configuration."""
        redis_client = redis.from_url(self.redis_url)
        
        return SessionManager(
            redis_client=redis_client,
            session_timeout=self.session_timeout,
            max_concurrent_sessions=self.max_concurrent_sessions,
            cleanup_interval=self.cleanup_interval
        )
    
    def create_middleware(self, app, session_manager: SessionManager):
        """Create session management middleware with this configuration."""
        return SessionManagementMiddleware(
            app=app,
            session_manager=session_manager,
            jwt_secret_key=self.jwt_secret_key,
            jwt_algorithm=self.jwt_algorithm
        )