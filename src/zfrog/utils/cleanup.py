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


async def cancel_job(job_id: str) -> bool:
    """Request cancellation of a job.
    
    Args:
        job_id: Job to cancel.
        
    Returns:
        True if job was cancelled, False if not found.
    """
    async with _cancel_lock:
        _cancelled_jobs.add(job_id)
    return True


async def is_cancelled(job_id: str) -> bool:
    """Check if a job has been cancelled.
    
    Args:
        job_id: Job to check.
        
    Returns:
        True if job should be cancelled.
    """
    async with _cancel_lock:
        return job_id in _cancelled_jobs


async def clear_cancellation(job_id: str):
    """Clear cancellation flag for a job."""
    async with _cancel_lock:
        _cancelled_jobs.discard(job_id)


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
