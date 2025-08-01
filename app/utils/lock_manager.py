import asyncio
import time
import uuid
from typing import Optional, Any, AsyncContextManager
from contextlib import asynccontextmanager
import redis.asyncio as redis
from redis.asyncio import Redis
from redis.exceptions import RedisError, LockError

from app.core.config import settings
from app.core.errors import LockAcquisitionError, LockReleaseError


class DistributedLock:
    """Distributed lock implementation using Redis."""
    
    def __init__(
        self,
        redis_client: Redis,
        key: str,
        timeout: float = 30.0,
        blocking_timeout: Optional[float] = None,
        thread_local: bool = True
    ):
        """
        Initialize distributed lock.
        
        Args:
            redis_client: Redis client instance
            key: Lock key name
            timeout: Lock timeout in seconds
            blocking_timeout: Maximum time to wait for lock acquisition
            thread_local: Whether to use thread-local storage
        """
        self.redis = redis_client
        self.key = f"lock:{key}"
        self.timeout = timeout
        self.blocking_timeout = blocking_timeout
        self.thread_local = thread_local
        self.identifier = str(uuid.uuid4())
        self.acquired = False
    
    async def acquire(self, blocking: bool = True) -> bool:
        """Acquire the lock.
        
        Args:
            blocking: Whether to block until lock is acquired
            
        Returns:
            bool: True if lock was acquired, False otherwise
            
        Raises:
            LockAcquisitionError: If lock cannot be acquired
        """
        if self.acquired:
            return True
        
        timeout = self.blocking_timeout if blocking else 0
        end_time = time.time() + (timeout or 0)
        
        while True:
            try:
                # Try to acquire lock with SET NX EX
                result = await self.redis.set(
                    self.key,
                    self.identifier,
                    nx=True,  # Only set if key doesn't exist
                    ex=int(self.timeout)  # Set expiration
                )
                
                if result:
                    self.acquired = True
                    return True
                
                if not blocking or (timeout and time.time() >= end_time):
                    return False
                
                # Wait a bit before retrying
                await asyncio.sleep(0.01)
                
            except RedisError as e:
                raise LockAcquisitionError(f"Failed to acquire lock: {e}")
    
    async def release(self) -> bool:
        """Release the lock.
        
        Returns:
            bool: True if lock was released, False if not owned
            
        Raises:
            LockReleaseError: If lock cannot be released
        """
        if not self.acquired:
            return False
        
        try:
            # Use Lua script to ensure atomic check-and-delete
            lua_script = """
            if redis.call("GET", KEYS[1]) == ARGV[1] then
                return redis.call("DEL", KEYS[1])
            else
                return 0
            end
            """
            
            result = await self.redis.eval(
                lua_script,
                1,
                self.key,
                self.identifier
            )
            
            if result:
                self.acquired = False
                return True
            
            return False
            
        except RedisError as e:
            raise LockReleaseError(f"Failed to release lock: {e}")
    
    async def extend(self, additional_time: float) -> bool:
        """Extend the lock timeout.
        
        Args:
            additional_time: Additional time in seconds
            
        Returns:
            bool: True if lock was extended, False otherwise
        """
        if not self.acquired:
            return False
        
        try:
            # Use Lua script to extend expiration atomically
            lua_script = """
            if redis.call("GET", KEYS[1]) == ARGV[1] then
                return redis.call("EXPIRE", KEYS[1], ARGV[2])
            else
                return 0
            end
            """
            
            result = await self.redis.eval(
                lua_script,
                1,
                self.key,
                self.identifier,
                int(self.timeout + additional_time)
            )
            
            if result:
                self.timeout += additional_time
                return True
            
            return False
            
        except RedisError as e:
            return False
    
    async def is_locked(self) -> bool:
        """Check if the lock is currently held.
        
        Returns:
            bool: True if lock is held, False otherwise
        """
        try:
            value = await self.redis.get(self.key)
            return value is not None
        except RedisError:
            return False
    
    async def is_owned(self) -> bool:
        """Check if the lock is owned by this instance.
        
        Returns:
            bool: True if lock is owned by this instance
        """
        try:
            value = await self.redis.get(self.key)
            return value == self.identifier.encode() if value else False
        except RedisError:
            return False
    
    async def __aenter__(self):
        """Async context manager entry."""
        acquired = await self.acquire()
        if not acquired:
            raise LockAcquisitionError(f"Could not acquire lock: {self.key}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.release()


class LockManager:
    """Manager for distributed locks."""
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize lock manager.
        
        Args:
            redis_url: Redis connection URL
        """
        self.redis_url = redis_url or settings.redis_url
        self._redis_client: Optional[Redis] = None
    
    async def get_redis_client(self) -> Redis:
        """Get Redis client instance.
        
        Returns:
            Redis: Redis client
        """
        if self._redis_client is None:
            self._redis_client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._redis_client
    
    async def close(self):
        """Close Redis connection."""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None
    
    def create_lock(
        self,
        key: str,
        timeout: float = 30.0,
        blocking_timeout: Optional[float] = None
    ) -> DistributedLock:
        """Create a new distributed lock.
        
        Args:
            key: Lock key name
            timeout: Lock timeout in seconds
            blocking_timeout: Maximum time to wait for lock acquisition
            
        Returns:
            DistributedLock: Lock instance
        """
        return DistributedLock(
            redis_client=self._redis_client,
            key=key,
            timeout=timeout,
            blocking_timeout=blocking_timeout
        )
    
    @asynccontextmanager
    async def lock(
        self,
        key: str,
        timeout: float = 30.0,
        blocking_timeout: Optional[float] = None
    ) -> AsyncContextManager[DistributedLock]:
        """Context manager for acquiring and releasing locks.
        
        Args:
            key: Lock key name
            timeout: Lock timeout in seconds
            blocking_timeout: Maximum time to wait for lock acquisition
            
        Yields:
            DistributedLock: Acquired lock instance
        """
        redis_client = await self.get_redis_client()
        lock = DistributedLock(
            redis_client=redis_client,
            key=key,
            timeout=timeout,
            blocking_timeout=blocking_timeout
        )
        
        try:
            async with lock:
                yield lock
        finally:
            pass
    
    async def cleanup_expired_locks(self, pattern: str = "lock:*") -> int:
        """Clean up expired locks (for maintenance).
        
        Args:
            pattern: Key pattern to match
            
        Returns:
            int: Number of locks cleaned up
        """
        redis_client = await self.get_redis_client()
        
        try:
            keys = await redis_client.keys(pattern)
            if not keys:
                return 0
            
            # Check which keys are expired and remove them
            pipeline = redis_client.pipeline()
            for key in keys:
                pipeline.ttl(key)
            
            ttls = await pipeline.execute()
            expired_keys = [key for key, ttl in zip(keys, ttls) if ttl == -1]
            
            if expired_keys:
                await redis_client.delete(*expired_keys)
                return len(expired_keys)
            
            return 0
            
        except RedisError:
            return 0


# Global lock manager instance
_lock_manager: Optional[LockManager] = None


async def get_lock_manager() -> LockManager:
    """Get global lock manager instance.
    
    Returns:
        LockManager: Global lock manager
    """
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = LockManager()
    return _lock_manager


async def acquire_lock(
    key: str,
    timeout: float = 30.0,
    blocking_timeout: Optional[float] = None
) -> AsyncContextManager[DistributedLock]:
    """Convenience function to acquire a distributed lock.
    
    Args:
        key: Lock key name
        timeout: Lock timeout in seconds
        blocking_timeout: Maximum time to wait for lock acquisition
        
    Returns:
        AsyncContextManager[DistributedLock]: Lock context manager
    """
    lock_manager = await get_lock_manager()
    return lock_manager.lock(key, timeout, blocking_timeout)


# Common lock patterns
class LockPatterns:
    """Common lock key patterns."""
    
    @staticmethod
    def user_wallet(user_id: int) -> str:
        """Lock pattern for user wallet operations."""
        return f"wallet:user:{user_id}"
    
    @staticmethod
    def transaction_processing(transaction_id: int) -> str:
        """Lock pattern for transaction processing."""
        return f"transaction:process:{transaction_id}"
    
    @staticmethod
    def payment_processing(user_id: int, biller_code: str) -> str:
        """Lock pattern for payment processing."""
        return f"payment:user:{user_id}:biller:{biller_code}"
    
    @staticmethod
    def cashback_calculation(user_id: int) -> str:
        """Lock pattern for cashback calculations."""
        return f"cashback:user:{user_id}"
    
    @staticmethod
    def recurring_payment(recurring_payment_id: int) -> str:
        """Lock pattern for recurring payment processing."""
        return f"recurring:payment:{recurring_payment_id}"
    
    @staticmethod
    def biller_status_update(biller_code: str) -> str:
        """Lock pattern for biller status updates."""
        return f"biller:status:{biller_code}"
    
    @staticmethod
    def user_registration(email: str) -> str:
        """Lock pattern for user registration."""
        return f"registration:email:{email.lower()}"
    
    @staticmethod
    def referral_processing(referral_code: str) -> str:
        """Lock pattern for referral processing."""
        return f"referral:code:{referral_code}"


# Decorator for automatic locking
def with_lock(lock_key_func, timeout: float = 30.0, blocking_timeout: Optional[float] = None):
    """Decorator to automatically acquire locks for function execution.
    
    Args:
        lock_key_func: Function that generates lock key from function arguments
        timeout: Lock timeout in seconds
        blocking_timeout: Maximum time to wait for lock acquisition
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            lock_key = lock_key_func(*args, **kwargs)
            async with acquire_lock(lock_key, timeout, blocking_timeout):
                return await func(*args, **kwargs)
        return wrapper
    return decorator


# Example usage decorators
def lock_user_wallet(timeout: float = 30.0):
    """Decorator to lock user wallet operations."""
    def get_lock_key(*args, **kwargs):
        # Assume first argument or 'user_id' kwarg contains user ID
        user_id = kwargs.get('user_id') or (args[0] if args else None)
        if hasattr(user_id, 'id'):
            user_id = user_id.id
        return LockPatterns.user_wallet(user_id)
    
    return with_lock(get_lock_key, timeout)


def lock_transaction_processing(timeout: float = 60.0):
    """Decorator to lock transaction processing."""
    def get_lock_key(*args, **kwargs):
        transaction_id = kwargs.get('transaction_id') or (args[1] if len(args) > 1 else args[0])
        if hasattr(transaction_id, 'id'):
            transaction_id = transaction_id.id
        return LockPatterns.transaction_processing(transaction_id)
    
    return with_lock(get_lock_key, timeout)