"""Rate limiting and retry utilities."""

import asyncio
import time
from functools import wraps
from typing import Callable, Any


class RateLimiter:
    """Token bucket rate limiter.
    
    Controls request rate to avoid being blocked by target sites.
    """
    
    def __init__(
        self,
        requests_per_second: float = 1.0,
        burst_size: int = 5,
    ):
        """Initialize rate limiter.
        
        Args:
            requests_per_second: Sustained request rate.
            burst_size: Maximum burst size.
        """
        self.rate = requests_per_second
        self.burst = burst_size
        self._tokens = burst_size
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """Wait until a token is available, then consume it."""
        async with self._lock:
            now = time.monotonic()
            
            # Refill tokens based on elapsed time
            elapsed = now - self._last_refill
            self._tokens = min(
                self.burst,
                self._tokens + elapsed * self.rate
            )
            self._last_refill = now
            
            # If no tokens available, calculate wait time
            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self.rate
                await asyncio.sleep(wait_time)
                self._tokens = 0
                self._last_refill = time.monotonic()
            else:
                self._tokens -= 1
    
    def set_rate(self, requests_per_second: float):
        """Update the rate limit."""
        self.rate = requests_per_second


# Global rate limiter instance
_global_limiter = RateLimiter(requests_per_second=1.0, burst_size=5)


def rate_limit(func: Callable) -> Callable:
    """Decorator to apply rate limiting to async functions."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        await _global_limiter.acquire()
        return await func(*args, **kwargs)
    return wrapper


class RetryHandler:
    """Exponential backoff retry handler."""
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retryable_exceptions: tuple = (Exception,),
    ):
        """Initialize retry handler.
        
        Args:
            max_retries: Maximum number of retries.
            base_delay: Initial delay between retries (seconds).
            max_delay: Maximum delay between retries (seconds).
            exponential_base: Base for exponential backoff.
            retryable_exceptions: Tuple of exceptions to retry on.
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_exceptions = retryable_exceptions
    
    async def execute(
        self,
        func: Callable,
        *args,
        on_retry: Callable | None = None,
        **kwargs,
    ) -> Any:
        """Execute function with retry logic.
        
        Args:
            func: Async function to execute.
            *args: Positional arguments.
            on_retry: Callback with (attempt, delay, error) on retry.
            **kwargs: Keyword arguments.
            
        Returns:
            Function result.
            
        Raises:
            Last exception if all retries fail.
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except self.retryable_exceptions as e:
                last_exception = e
                
                if attempt < self.max_retries:
                    # Calculate delay with exponential backoff
                    delay = min(
                        self.base_delay * (self.exponential_base ** attempt),
                        self.max_delay
                    )
                    
                    if on_retry:
                        on_retry(attempt + 1, delay, e)
                    
                    await asyncio.sleep(delay)
        
        raise last_exception


def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
) -> Callable:
    """Decorator to add retry logic to async functions."""
    handler = RetryHandler(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        retryable_exceptions=retryable_exceptions,
    )
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await handler.execute(func, *args, **kwargs)
        return wrapper
    return decorator


class ConcurrencyLimiter:
    """Limits concurrent operations."""
    
    def __init__(self, max_concurrent: int = 5):
        """Initialize concurrency limiter.
        
        Args:
            max_concurrent: Maximum concurrent operations.
        """
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._current = 0
        self._max = max_concurrent
    
    async def acquire(self):
        """Acquire a slot (blocks if at capacity)."""
        await self._semaphore.acquire()
        self._current += 1
    
    def release(self):
        """Release a slot."""
        self._semaphore.release()
        self._current -= 1
    
    @property
    def available(self) -> int:
        """Number of available slots."""
        return self._max - self._current
    
    @property
    def is_full(self) -> bool:
        """Whether at capacity."""
        return self._current >= self._max


# Global concurrency limiter
_global_concurrency = ConcurrencyLimiter(max_concurrent=5)


def concurrency_limit(func: Callable) -> Callable:
    """Decorator to apply concurrency limiting."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        await _global_concurrency.acquire()
        try:
            return await func(*args, **kwargs)
        finally:
            _global_concurrency.release()
    return wrapper
