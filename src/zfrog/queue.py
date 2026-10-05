"""Celery task queue configuration."""

import asyncio
import json
from datetime import datetime, timezone
from celery import Celery
from redis import asyncio as aioredis

from zfrog.config import settings

# Configure Celery
celery_app = Celery(
    "zfrog",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3000,  # 50 min soft limit
    worker_max_tasks_per_child=100,
    worker_prefetch_multiplier=1,
)


@celery_app.task(bind=True, max_retries=3)
def run_job_task(self, job_data: dict):
    """Execute a job via Celery.
    
    Args:
        job_data: Serialized JobCreate data.
        
    Returns:
        Serialized JobResult.
    """
    from zfrog.models import JobCreate
    from zfrog.orchestrator import run_job, get_job, update_job, update_result

    # Read before the try so the failure path below can always name the record.
    job_id = job_data.get("job_id")

    try:
        # Get existing job record (created by API)
        job_record = get_job(job_id) if job_id else None
        
        if job_record:
            # Update status to running
            from zfrog.models import JobStatus
            job_record.status = JobStatus.RUNNING
            update_job(job_record)
        
        # Rebuild the job from the full serialized payload (`job_id` is
        # bookkeeping for the job record, not a JobCreate field).
        job = JobCreate(**{k: v for k, v in job_data.items() if k != "job_id"})
        
        # Run under the id the API already created, so its `pending` record is the
        # one that ends up `completed` instead of a second record appearing while
        # the first one stays pending forever.
        result = asyncio.run(run_job(job, job_id=job_id))
        
        return {
            "status": "completed",
            "job_id": result.job_id,
            "output_path": result.output_path,
            "files_count": result.files_count,
            "total_size_bytes": result.total_size_bytes,
            "engine_used": result.engine_used,
            "duration_seconds": result.duration_seconds,
        }
    except Exception as e:
        # A crash has to land on the record too: otherwise the job sits in
        # `running` forever and the screen keeps promising progress that stopped.
        if job_id:
            from zfrog.models import JobStatus
            failed = get_job(job_id)
            if failed:
                failed.status = JobStatus.FAILED
                failed.error = str(e)
                update_job(failed)
        return {
            "status": "failed",
            "job_id": job_id,
            "error": str(e),
        }


async def publish_job_event(job_id: str, event_type: str, data: dict):
    """Publish a job event to Redis pub/sub channel.
    
    This function sends real-time events for job progress tracking.
    Each event is published to the channel `job:{job_id}:events` and
    can be consumed by WebSocket clients.
    
    Args:
        job_id: The job ID.
        event_type: Event type (e.g., "progress", "status", "error", "completed").
        data: Event data dictionary.
    """
    channel = f"job:{job_id}:events"
    
    event = {
        "type": event_type,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    try:
        redis_client = aioredis.from_url(settings.redis_url)
        await redis_client.publish(channel, json.dumps(event))
        await redis_client.close()
    except Exception:
        # If Redis is unavailable, fail silently - events are best-effort
        pass
