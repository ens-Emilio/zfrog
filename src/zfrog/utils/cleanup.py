"""Job cancellation and cleanup utilities."""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Set

from zfrog.models import JobStatus


# Set of cancelled job IDs
_cancelled_jobs: Set[str] = set()

# Lock for thread-safe access
_cancel_lock = asyncio.Lock()

# One key per cancelled job, so several jobs cancel independently and each expires
# on its own instead of the whole set needing a rewrite on every change.
_REDIS_PREFIX = "zfrog:cancelled:"
_REDIS_TTL = 86400


def _redis():
    """A Redis client for the shared cancel flags, or None when unavailable."""
    try:
        import redis

        from zfrog.config import settings

        client = redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


# The flag has to cross processes: the API receives the cancel request, but the job
# runs in a Celery worker. A module-level set lived only in the API, so the worker
# read `False` forever and "Interromper" stopped nothing. Redis is the shared store,
# same as the webhook registry and the pending SSO logins; the local set stays for
# single-process use.
async def cancel_job(job_id: str) -> bool:
    """Request cancellation of a job.
    
    Args:
        job_id: Job to cancel.
        
    Returns:
        True if job was cancelled, False if not found.
    """
    async with _cancel_lock:
        _cancelled_jobs.add(job_id)
    client = _redis()
    if client is not None:
        try:
            client.set(f"{_REDIS_PREFIX}{job_id}", "1", ex=_REDIS_TTL)
        except Exception:
            pass
    return True


async def is_cancelled(job_id: str) -> bool:
    """Check if a job has been cancelled.
    
    Args:
        job_id: Job to check.
        
    Returns:
        True if job should be cancelled.
    """
    async with _cancel_lock:
        if job_id in _cancelled_jobs:
            return True
    client = _redis()
    if client is not None:
        try:
            return bool(client.get(f"{_REDIS_PREFIX}{job_id}"))
        except Exception:
            pass
    return False


async def clear_cancellation(job_id: str):
    """Clear cancellation flag for a job."""
    async with _cancel_lock:
        _cancelled_jobs.discard(job_id)
    client = _redis()
    if client is not None:
        try:
            client.delete(f"{_REDIS_PREFIX}{job_id}")
        except Exception:
            pass


class CancellationError(Exception):
    """Raised when a job is cancelled."""
    pass


class JobCleanup:
    """Periodic cleanup of old jobs."""
    
    def __init__(
        self,
        max_age_hours: int = 24,
        cleanup_interval_minutes: int = 60,
    ):
        """Initialize cleanup scheduler.
        
        Args:
            max_age_hours: Maximum age of jobs before cleanup.
            cleanup_interval_minutes: How often to run cleanup.
        """
        self.max_age = timedelta(hours=max_age_hours)
        self.cleanup_interval = timedelta(minutes=cleanup_interval_minutes)
        self._last_cleanup = datetime.utcnow()
        self._running = False
        self._task: asyncio.Task | None = None
    
    async def start(self):
        """Start the cleanup scheduler."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
    
    async def stop(self):
        """Stop the cleanup scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
    
    async def _cleanup_loop(self):
        """Main cleanup loop."""
        while self._running:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                now = datetime.utcnow()
                if now - self._last_cleanup >= self.cleanup_interval:
                    await self._cleanup_old_jobs()
                    self._last_cleanup = now
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Cleanup error: {e}")
    
    async def _cleanup_old_jobs(self):
        """Remove old completed/failed jobs."""
        from zfrog.orchestrator import _jobs, _results
        
        now = datetime.utcnow()
        to_remove = []
        
        for job_id, job in _jobs.items():
            # Only cleanup completed or failed jobs
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                if job.updated_at and (now - job.updated_at) > self.max_age:
                    to_remove.append(job_id)
        
        for job_id in to_remove:
            del _jobs[job_id]
            _results.pop(job_id, None)
            
            # Also remove output files
            from zfrog.config import settings
            from pathlib import Path
            output_dir = settings.output_dir / job_id
            if output_dir.exists():
                import shutil
                shutil.rmtree(output_dir, ignore_errors=True)
        
        if to_remove:
            print(f"Cleaned up {len(to_remove)} old jobs")


# Global cleanup instance
_job_cleanup = JobCleanup()


async def start_cleanup_scheduler():
    """Start the job cleanup scheduler."""
    await _job_cleanup.start()


async def stop_cleanup_scheduler():
    """Stop the job cleanup scheduler."""
    await _job_cleanup.stop()
