"""Resource management utilities."""

import os


class MemoryLimiter:
    """Limits memory usage for processes."""
    
    def __init__(self, max_memory_mb: int = 512):
        """Initialize memory limiter.
        
        Args:
            max_memory_mb: Maximum memory in MB per process.
        """
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self._processes: dict[int, float] = {}
    
    def check_memory(self) -> bool:
        """Check if current process is within memory limits."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            return memory_info.rss < self.max_memory_bytes
        except ImportError:
            # If psutil not available, skip check
            return True
    
    def get_memory_usage(self) -> dict:
        """Get current memory usage."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            return {
                "rss_mb": memory_info.rss / (1024 * 1024),
                "vms_mb": memory_info.vms / (1024 * 1024),
                "percent": process.memory_percent(),
            }
        except ImportError:
            return {"error": "psutil not installed"}
    
    async def enforce_limit(self):
        """Enforce memory limit, raise if exceeded."""
        if not self.check_memory():
            usage = self.get_memory_usage()
            raise MemoryError(
                f"Memory limit exceeded: {usage.get('rss_mb', 0):.1f} MB "
                f"> {self.max_memory_bytes / (1024 * 1024):.1f} MB"
            )

# Global instances
_memory_limiter = MemoryLimiter(max_memory_mb=512)

def get_memory_limiter() -> MemoryLimiter:
    """Get global memory limiter."""
    return _memory_limiter
