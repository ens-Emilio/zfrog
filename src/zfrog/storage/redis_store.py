"""Redis-backed storage for jobs and results."""

import json
from datetime import datetime
from zfrog.config import settings
from zfrog.models import Job, JobResult

# Redis key prefixes
JOB_PREFIX = "zfrog:job:"
RESULT_PREFIX = "zfrog:result:"


def _get_redis():
    """Get Redis connection."""
    import redis
    return redis.from_url(settings.redis_url, decode_responses=True)


def save_job_to_redis(job: Job):
    """Save job to Redis."""
    try:
        r = _get_redis()
        key = f"{JOB_PREFIX}{job.id}"
        data = job.model_dump(mode="json")
        # Serialize datetime to string
        data["created_at"] = data["created_at"].isoformat() if data.get("created_at") else None
        data["updated_at"] = data["updated_at"].isoformat() if data.get("updated_at") else None
        r.set(key, json.dumps(data), ex=86400 * 7)  # 7 day expiry
    except Exception:
        pass


def get_job_from_redis(job_id: str) -> Job | None:
    """Get job from Redis."""
    try:
        r = _get_redis()
        key = f"{JOB_PREFIX}{job_id}"
        data = r.get(key)
        if data:
            return Job.model_validate_json(data)
    except Exception:
        pass
    return None


def save_result_to_redis(result: JobResult):
    """Save result to Redis."""
    try:
        r = _get_redis()
        key = f"{RESULT_PREFIX}{result.job_id}"
        data = result.model_dump(mode="json")
        r.set(key, json.dumps(data), ex=86400 * 7)  # 7 day expiry
    except Exception:
        pass


def get_result_from_redis(job_id: str) -> JobResult | None:
    """Get result from Redis."""
    try:
        r = _get_redis()
        key = f"{RESULT_PREFIX}{job_id}"
        data = r.get(key)
        if data:
            return JobResult.model_validate_json(data)
    except Exception:
        pass
    return None
