"""IP filtering middleware for whitelisting and blacklisting."""

import ipaddress
import time
from typing import Set, List, Optional, Dict, Union
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import redis.asyncio as redis
from app.core.config import settings
from app.core.database import get_redis
import logging

logger = logging.getLogger(__name__)

class IPFilteringMiddleware(BaseHTTPMiddleware):
    """IP filtering middleware with whitelist/blacklist support."""
    
    def __init__(self, 
                 app,
                 whitelist: Optional[List[str]] = None,
                 blacklist: Optional[List[str]] = None,
                 redis_client: Optional[redis.Redis] = None,
                 enable_dynamic_blocking: bool = True,
                 max_requests_per_minute: int = 100,
                 block_duration: int = 3600,  # 1 hour
                 trust_proxy_headers: bool = True):
        super().__init__(app)
        self.redis_client = redis_client
        self.enable_dynamic_blocking = enable_dynamic_blocking
        self.max_requests_per_minute = max_requests_per_minute
        self.block_duration = block_duration
        self.trust_proxy_headers = trust_proxy_headers
        
        # Initialize IP lists
        self.whitelist_networks = self._parse_ip_list(whitelist or self._get_default_whitelist())
        self.blacklist_networks = self._parse_ip_list(blacklist or self._get_default_blacklist())
        
        # Endpoints that require stricter IP filtering
        self.admin_endpoints = self._get_admin_endpoints()
        self.payment_endpoints = self._get_payment_endpoints()
        self.auth_endpoints = self._get_auth_endpoints()
        
        # Country-based restrictions (if needed)
        self.restricted_countries = self._get_restricted_countries()
        
        # Trusted proxy networks
        self.trusted_proxies = self._get_trusted_proxies()
    
    def _get_default_whitelist(self) -> List[str]:
        """Get default whitelist IPs/networks."""
        return [
            "127.0.0.1/32",  # Localhost
            "::1/128",       # IPv6 localhost
            "10.0.0.0/8",    # Private network
            "172.16.0.0/12", # Private network
            "192.168.0.0/16", # Private network
            # the server IPs will be added here
        ]
    
    def _get_default_blacklist(self) -> List[str]:
        """Get default blacklist IPs/networks."""
        return [
            # Known malicious networks
            "0.0.0.0/32",     # Invalid IP
            "169.254.0.0/16", # Link-local
            "224.0.0.0/4",    # Multicast
            "240.0.0.0/4",    # Reserved
            # Any known malicious IPs/networks will be added here
        ]
    
    def _get_admin_endpoints(self) -> Set[str]:
        """Get admin endpoints that require stricter IP filtering."""
        return {
            "/api/v1/admin/",
            "/api/v1/admin/users",
            "/api/v1/admin/transactions",
            "/api/v1/admin/settings",
            "/api/v1/admin/reports",
            "/api/v1/admin/audit",
        }
    
    def _get_payment_endpoints(self) -> Set[str]:
        """Get payment endpoints that require IP filtering."""
        return {
            "/api/v1/payments/process",
            "/api/v1/payments/verify",
            "/api/v1/bills/pay",
            "/api/v1/wallet/transfer",
            "/api/v1/wallet/withdraw",
        }
    
    def _get_auth_endpoints(self) -> Set[str]:
        """Get authentication endpoints."""
        return {
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/api/v1/auth/refresh",
            "/api/v1/auth/reset-password",
        }
    
    def _get_restricted_countries(self) -> Set[str]:
        """Get list of restricted country codes."""
        # Add country codes that should be blocked
        # This would typically be configured based on compliance requirements
        return set()
    
    def _get_trusted_proxies(self) -> List[str]:
        """Get trusted proxy networks."""
        return [
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            #load balancer/proxy IPs will be added here
        ]
    
    def _parse_ip_list(self, ip_list: List[str]) -> List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]]:
        """Parse list of IP addresses/networks."""
        networks = []
        for ip_str in ip_list:
            try:
                # Handle single IPs and networks
                if '/' not in ip_str:
                    # Single IP - determine if IPv4 or IPv6
                    ip = ipaddress.ip_address(ip_str)
                    if isinstance(ip, ipaddress.IPv4Address):
                        networks.append(ipaddress.IPv4Network(f"{ip_str}/32"))
                    else:
                        networks.append(ipaddress.IPv6Network(f"{ip_str}/128"))
                else:
                    # Network notation
                    networks.append(ipaddress.ip_network(ip_str, strict=False))
            except ValueError as e:
                logger.warning(f"Invalid IP/network in list: {ip_str} - {e}")
        return networks
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request."""
        # Check proxy headers if trusted
        if self.trust_proxy_headers:
            # Check X-Forwarded-For header
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                # Take the first IP (original client)
                client_ip = forwarded_for.split(',')[0].strip()
                try:
                    ipaddress.ip_address(client_ip)
                    return client_ip
                except ValueError:
                    pass
            
            # Check X-Real-IP header
            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                try:
                    ipaddress.ip_address(real_ip)
                    return real_ip
                except ValueError:
                    pass
            
            # Check CF-Connecting-IP (Cloudflare)
            cf_ip = request.headers.get("CF-Connecting-IP")
            if cf_ip:
                try:
                    ipaddress.ip_address(cf_ip)
                    return cf_ip
                except ValueError:
                    pass
        
        # Fall back to direct connection IP
        return request.client.host if request.client else "unknown"
    
    def _is_ip_in_networks(self, ip_str: str, networks: List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]]) -> bool:
        """Check if IP is in any of the given networks."""
        try:
            ip = ipaddress.ip_address(ip_str)
            for network in networks:
                if ip in network:
                    return True
        except ValueError:
            logger.warning(f"Invalid IP address: {ip_str}")
        return False
    
    def _is_whitelisted(self, ip: str) -> bool:
        """Check if IP is whitelisted."""
        return self._is_ip_in_networks(ip, self.whitelist_networks)
    
    def _is_blacklisted(self, ip: str) -> bool:
        """Check if IP is blacklisted."""
        return self._is_ip_in_networks(ip, self.blacklist_networks)
    
    async def _is_dynamically_blocked(self, ip: str) -> bool:
        """Check if IP is dynamically blocked in Redis."""
        if not self.enable_dynamic_blocking or not self.redis_client:
            return False
        
        try:
            if not self.redis_client:
                self.redis_client = await get_redis()
            
            blocked_key = f"ip_blocked:{ip}"
            is_blocked = await self.redis_client.get(blocked_key)
            return bool(is_blocked)
        
        except Exception as e:
            logger.error(f"Error checking dynamic IP block for {ip}: {e}")
            return False
    
    async def _track_request_rate(self, ip: str) -> bool:
        """Track request rate and return True if rate limit exceeded."""
        if not self.enable_dynamic_blocking or not self.redis_client:
            return False
        
        try:
            if not self.redis_client:
                self.redis_client = await get_redis()
            
            # Use sliding window rate limiting
            current_time = int(time.time())
            window_start = current_time - 60  # 1 minute window
            
            rate_key = f"ip_rate:{ip}"
            
            # Remove old entries
            await self.redis_client.zremrangebyscore(rate_key, 0, window_start)
            
            # Count current requests
            current_count = await self.redis_client.zcard(rate_key)
            
            if current_count >= self.max_requests_per_minute:
                # Block the IP
                blocked_key = f"ip_blocked:{ip}"
                await self.redis_client.setex(blocked_key, self.block_duration, "rate_limit_exceeded")
                
                logger.warning(
                    f"IP {ip} blocked for {self.block_duration}s due to rate limit exceeded: "
                    f"{current_count} requests in 1 minute"
                )
                return True
            
            # Add current request
            await self.redis_client.zadd(rate_key, {str(current_time): current_time})
            await self.redis_client.expire(rate_key, 60)  # Expire after 1 minute
            
            return False
        
        except Exception as e:
            logger.error(f"Error tracking request rate for {ip}: {e}")
            return False
    
    def _requires_strict_filtering(self, request: Request) -> bool:
        """Check if endpoint requires strict IP filtering."""
        path = request.url.path
        
        # Admin endpoints require strict filtering
        for admin_endpoint in self.admin_endpoints:
            if path.startswith(admin_endpoint):
                return True
        
        # Payment endpoints in production
        if hasattr(settings, 'ENVIRONMENT') and settings.ENVIRONMENT == 'production':
            for payment_endpoint in self.payment_endpoints:
                if path.startswith(payment_endpoint):
                    return True
        
        return False
    
    def _create_ip_blocked_response(self, ip: str, reason: str) -> JSONResponse:
        """Create IP blocked response."""
        return JSONResponse(
            status_code=403,
            content={
                "error": "IP_BLOCKED",
                "message": f"Access denied from IP address {ip}",
                "code": "IP_FILTERING_BLOCKED",
                "reason": reason,
                "details": {
                    "blocked_ip": ip,
                    "block_reason": reason,
                    "contact": "Please contact support if you believe this is an error"
                }
            },
            headers={
                "X-IP-Blocked": "true",
                "X-Block-Reason": reason,
                "Retry-After": str(self.block_duration) if reason == "rate_limit_exceeded" else "86400"
            }
        )
    
    async def dispatch(self, request: Request, call_next):
        """Process request with IP filtering."""
        # Get client IP
        client_ip = self._get_client_ip(request)
        
        # Skip filtering for unknown IPs in development
        if client_ip == "unknown":
            if hasattr(settings, 'ENVIRONMENT') and settings.ENVIRONMENT != 'production':
                logger.debug("Skipping IP filtering for unknown client IP in development")
                return await call_next(request)
            else:
                logger.warning("Unknown client IP in production - blocking")
                return self._create_ip_blocked_response(client_ip, "unknown_ip")
        
        # Store client IP in request state for other middleware
        request.state.client_ip = client_ip
        
        # Check whitelist first (whitelist overrides everything)
        if self._is_whitelisted(client_ip):
            logger.debug(f"IP {client_ip} is whitelisted - allowing")
            response = await call_next(request)
            response.headers["X-IP-Status"] = "whitelisted"
            return response
        
        # Check blacklist
        if self._is_blacklisted(client_ip):
            logger.warning(f"IP {client_ip} is blacklisted - blocking")
            return self._create_ip_blocked_response(client_ip, "blacklisted")
        
        # Check dynamic blocking
        if await self._is_dynamically_blocked(client_ip):
            logger.warning(f"IP {client_ip} is dynamically blocked - blocking")
            return self._create_ip_blocked_response(client_ip, "rate_limit_exceeded")
        
        # Track request rate and check for abuse
        if await self._track_request_rate(client_ip):
            return self._create_ip_blocked_response(client_ip, "rate_limit_exceeded")
        
        # Check if strict filtering is required for this endpoint
        if self._requires_strict_filtering(request):
            # For admin endpoints, only allow whitelisted IPs
            path = request.url.path
            for admin_endpoint in self.admin_endpoints:
                if path.startswith(admin_endpoint):
                    logger.warning(f"Non-whitelisted IP {client_ip} attempting to access admin endpoint - blocking")
                    return self._create_ip_blocked_response(client_ip, "admin_access_restricted")
        
        # IP filtering passed - process request
        try:
            response = await call_next(request)
            
            # Add IP status to response headers
            response.headers["X-IP-Status"] = "allowed"
            response.headers["X-Client-IP"] = client_ip
            
            return response
        
        except Exception as e:
            logger.error(f"Error processing request from IP {client_ip}: {e}")
            raise

# Utility functions for IP management
async def add_ip_to_whitelist(ip: str, redis_client: Optional[redis.Redis] = None):
    """Add IP to dynamic whitelist."""
    if not redis_client:
        redis_client = await get_redis()
    
    try:
        await redis_client.sadd("ip_whitelist_dynamic", ip)
        logger.info(f"Added {ip} to dynamic whitelist")
    except Exception as e:
        logger.error(f"Error adding {ip} to whitelist: {e}")

async def add_ip_to_blacklist(ip: str, duration: int = 86400, redis_client: Optional[redis.Redis] = None):
    """Add IP to dynamic blacklist."""
    if not redis_client:
        redis_client = await get_redis()
    
    try:
        blocked_key = f"ip_blocked:{ip}"
        await redis_client.setex(blocked_key, duration, "manually_blocked")
        logger.info(f"Added {ip} to blacklist for {duration} seconds")
    except Exception as e:
        logger.error(f"Error adding {ip} to blacklist: {e}")

async def remove_ip_from_blacklist(ip: str, redis_client: Optional[redis.Redis] = None):
    """Remove IP from dynamic blacklist."""
    if not redis_client:
        redis_client = await get_redis()
    
    try:
        blocked_key = f"ip_blocked:{ip}"
        await redis_client.delete(blocked_key)
        logger.info(f"Removed {ip} from blacklist")
    except Exception as e:
        logger.error(f"Error removing {ip} from blacklist: {e}")

async def get_blocked_ips(redis_client: Optional[redis.Redis] = None) -> List[Dict[str, str]]:
    """Get list of currently blocked IPs."""
    if not redis_client:
        redis_client = await get_redis()
    
    try:
        blocked_ips = []
        async for key in redis_client.scan_iter(match="ip_blocked:*"):
            ip = key.decode().replace("ip_blocked:", "")
            reason = await redis_client.get(key)
            ttl = await redis_client.ttl(key)
            
            blocked_ips.append({
                "ip": ip,
                "reason": reason.decode() if reason else "unknown",
                "ttl": ttl
            })
        
        return blocked_ips
    except Exception as e:
        logger.error(f"Error getting blocked IPs: {e}")
        return []

class IPFilterConfig:
    """Configuration class for IP filtering."""
    
    def __init__(self,
                 whitelist: Optional[List[str]] = None,
                 blacklist: Optional[List[str]] = None,
                 enable_dynamic_blocking: bool = True,
                 max_requests_per_minute: int = 100,
                 block_duration: int = 3600,
                 trust_proxy_headers: bool = True):
        self.whitelist = whitelist or []
        self.blacklist = blacklist or []
        self.enable_dynamic_blocking = enable_dynamic_blocking
        self.max_requests_per_minute = max_requests_per_minute
        self.block_duration = block_duration
        self.trust_proxy_headers = trust_proxy_headers
    
    def create_middleware(self, app):
        """Create IP filtering middleware with this configuration."""
        return IPFilteringMiddleware(
            app=app,
            whitelist=self.whitelist,
            blacklist=self.blacklist,
            enable_dynamic_blocking=self.enable_dynamic_blocking,
            max_requests_per_minute=self.max_requests_per_minute,
            block_duration=self.block_duration,
            trust_proxy_headers=self.trust_proxy_headers
        )