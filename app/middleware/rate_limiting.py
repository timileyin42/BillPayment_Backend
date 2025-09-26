"""Redis-based rate limiting middleware with different tiers."""

import time
import json
from typing import Dict, Optional, Tuple
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import redis.asyncio as redis
from app.core.config import settings
from app.core.database import get_redis
import logging

logger = logging.getLogger(__name__)

class RateLimitTier:
    """Rate limit configuration for different endpoint tiers."""
    
    # Tier definitions: (requests_per_minute, requests_per_hour, requests_per_day)
    TIERS = {
        "public": (60, 1000, 10000),      # Public endpoints
        "auth": (30, 500, 5000),          # Authentication endpoints
        "payment": (10, 100, 1000),       # Payment processing
        "admin": (100, 2000, 20000),      # Admin operations
        "webhook": (1000, 10000, 100000), # Webhook endpoints
        "health": (300, 5000, 50000),     # Health check endpoints
    }
    
    @classmethod
    def get_limits(cls, tier: str) -> Tuple[int, int, int]:
        """Get rate limits for a specific tier."""
        return cls.TIERS.get(tier, cls.TIERS["public"])

class RateLimitingMiddleware(BaseHTTPMiddleware):
    """Redis-based rate limiting middleware."""
    
    def __init__(self, app, redis_client: Optional[redis.Redis] = None):
        super().__init__(app)
        self.redis_client = redis_client
        self.endpoint_tiers = self._configure_endpoint_tiers()
    
    def _configure_endpoint_tiers(self) -> Dict[str, str]:
        """Configure which endpoints belong to which tier."""
        return {
            # Authentication endpoints
            "/api/v1/auth/login": "auth",
            "/api/v1/auth/register": "auth",
            "/api/v1/auth/refresh": "auth",
            "/api/v1/auth/logout": "auth",
            "/api/v1/auth/forgot-password": "auth",
            "/api/v1/auth/reset-password": "auth",
            
            # Payment endpoints
            "/api/v1/payments/process": "payment",
            "/api/v1/payments/verify": "payment",
            "/api/v1/bills/pay": "payment",
            "/api/v1/wallet/transfer": "payment",
            "/api/v1/wallet/withdraw": "payment",
            
            # Admin endpoints
            "/api/v1/admin": "admin",
            "/api/v1/users/admin": "admin",
            "/api/v1/transactions/admin": "admin",
            
            # Webhook endpoints
            "/api/v1/webhooks": "webhook",
            "/api/v1/callbacks": "webhook",
            
            # Health endpoints
            "/health": "health",
            "/api/health": "health",
            "/api/v1/health": "health"
        }
    
    def _get_endpoint_tier(self, path: str) -> str:
        """Determine the rate limit tier for an endpoint."""
        # Exact match first
        if path in self.endpoint_tiers:
            return self.endpoint_tiers[path]
        
        # Prefix matching for admin and webhook endpoints
        for endpoint_path, tier in self.endpoint_tiers.items():
            if path.startswith(endpoint_path):
                return tier
        
        # Default to public tier
        return "public"
    
    def _get_client_identifier(self, request: Request) -> str:
        """Get unique identifier for rate limiting."""
        # Try to get user ID from JWT token if available
        user_id = getattr(request.state, 'user_id', None)
        if user_id:
            return f"user:{user_id}"
        
        # Fall back to IP address
        client_ip = "unknown"
        if request.client and request.client.host:
            client_ip = request.client.host
        
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        
        return f"ip:{client_ip}"
    
    async def _check_rate_limit(self, 
                               client_id: str, 
                               tier: str, 
                               path: str) -> Tuple[bool, Dict[str, int]]:
        """Check if request is within rate limits."""
        if not self.redis_client:
            return True, {}
        
        try:
            minute_limit, hour_limit, day_limit = RateLimitTier.get_limits(tier)
            current_time = int(time.time())
            
            # Keys for different time windows
            minute_key = f"rate_limit:{client_id}:{path}:minute:{current_time // 60}"
            hour_key = f"rate_limit:{client_id}:{path}:hour:{current_time // 3600}"
            day_key = f"rate_limit:{client_id}:{path}:day:{current_time // 86400}"
            
            # Use pipeline for atomic operations
            pipe = self.redis_client.pipeline()
            
            # Increment counters
            pipe.incr(minute_key)
            pipe.expire(minute_key, 60)
            pipe.incr(hour_key)
            pipe.expire(hour_key, 3600)
            pipe.incr(day_key)
            pipe.expire(day_key, 86400)
            
            results = await pipe.execute()
            
            minute_count = results[0]
            hour_count = results[2]
            day_count = results[4]
            
            # Check limits
            if minute_count > minute_limit:
                return False, {
                    "limit": minute_limit,
                    "remaining": 0,
                    "reset": (current_time // 60 + 1) * 60,
                    "window": "minute"
                }
            
            if hour_count > hour_limit:
                return False, {
                    "limit": hour_limit,
                    "remaining": max(0, hour_limit - hour_count),
                    "reset": (current_time // 3600 + 1) * 3600,
                    "window": "hour"
                }
            
            if day_count > day_limit:
                return False, {
                    "limit": day_limit,
                    "remaining": max(0, day_limit - day_count),
                    "reset": (current_time // 86400 + 1) * 86400,
                    "window": "day"
                }
            
            # Return success with current usage
            return True, {
                "minute_limit": minute_limit,
                "minute_remaining": max(0, minute_limit - minute_count),
                "hour_limit": hour_limit,
                "hour_remaining": max(0, hour_limit - hour_count),
                "day_limit": day_limit,
                "day_remaining": max(0, day_limit - day_count),
            }
            
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # Fail open - allow request if Redis is down
            return True, {}
    
    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting."""
        # Skip rate limiting for OPTIONS requests
        if request.method == "OPTIONS":
            return await call_next(request)
        
        # Get Redis client if not set
        if not self.redis_client:
            try:
                self.redis_client = await get_redis()
            except Exception as e:
                logger.warning(f"Could not connect to Redis for rate limiting: {e}")
                return await call_next(request)
        
        # Determine rate limit tier and client identifier
        path = request.url.path
        tier = self._get_endpoint_tier(path)
        client_id = self._get_client_identifier(request)
        
        # Check rate limits
        allowed, limit_info = await self._check_rate_limit(client_id, tier, path)
        
        if not allowed:
            # Rate limit exceeded
            headers = {
                "X-RateLimit-Limit": str(limit_info.get("limit", 0)),
                "X-RateLimit-Remaining": str(limit_info.get("remaining", 0)),
                "X-RateLimit-Reset": str(limit_info.get("reset", 0)),
                "X-RateLimit-Window": limit_info.get("window", "unknown"),
                "Retry-After": str(limit_info.get("reset", int(time.time())) - int(time.time()))
            }
            
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests for {tier} tier endpoint",
                    "limit_info": limit_info
                },
                headers=headers
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers to successful responses
        if limit_info:
            response.headers["X-RateLimit-Tier"] = tier
            if "minute_remaining" in limit_info:
                response.headers["X-RateLimit-Minute-Remaining"] = str(limit_info["minute_remaining"])
            if "hour_remaining" in limit_info:
                response.headers["X-RateLimit-Hour-Remaining"] = str(limit_info["hour_remaining"])
            if "day_remaining" in limit_info:
                response.headers["X-RateLimit-Day-Remaining"] = str(limit_info["day_remaining"])
        
        return response

# Utility functions for manual rate limiting
async def check_custom_rate_limit(client_id: str, 
                                 action: str, 
                                 limit: int, 
                                 window_seconds: int,
                                 redis_client: Optional[redis.Redis] = None) -> bool:
    """Check custom rate limit for specific actions."""
    if not redis_client:
        try:
            redis_client = await get_redis()
        except Exception:
            return True  # Fail open
    
    try:
        current_time = int(time.time())
        window_start = current_time // window_seconds
        key = f"custom_rate_limit:{client_id}:{action}:{window_start}"
        
        count = await redis_client.incr(key)
        await redis_client.expire(key, window_seconds)
        
        return count <= limit
    except Exception as e:
        logger.error(f"Custom rate limit check error: {e}")
        return True  # Fail open

async def reset_rate_limit(client_id: str, path: str = None):
    """Reset rate limits for a specific client."""
    try:
        redis_client = await get_redis()
        pattern = f"rate_limit:{client_id}:*"
        if path:
            pattern = f"rate_limit:{client_id}:{path}:*"
        
        keys = await redis_client.keys(pattern)
        if keys:
            await redis_client.delete(*keys)
            logger.info(f"Reset rate limits for {client_id}")
    except Exception as e:
        logger.error(f"Error resetting rate limits: {e}")