"""Redis-backed storage for jobs and results."""

import json
import logging
from zfrog.config import settings
from zfrog.models import Job, JobResult

logger = logging.getLogger(__name__)

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
        # `model_dump(mode="json")` already renders the datetimes as ISO strings.
        # This used to call `.isoformat()` on them, which raises AttributeError on a
        # `str`; the bare `except` swallowed it, so no job record ever reached Redis
        # and the API kept answering from its own memory.
        r.set(key, json.dumps(job.model_dump(mode="json")), ex=86400 * 7)  # 7 day expiry
    except Exception:
        # Swallowing this silently is what hid the bug above, so the failure is
        # logged: Redis being down is a normal state, an unwritable record is not.
        logger.warning("não deu para gravar o job %s no Redis", job.id, exc_info=True)

def list_jobs_from_redis() -> list[Job]:
    """Every job record Redis holds.

    `scan_iter` rather than `keys`: `keys` walks the whole keyspace in one blocking
    call, fine on a dev box and not on a server with a real dataset.
    """
    jobs: list[Job] = []
    try:
        r = _get_redis()
        for key in r.scan_iter(f"{JOB_PREFIX}*"):
            data = r.get(key)
            if data:
                jobs.append(Job.model_validate_json(data))
    except Exception:
        logger.warning("não deu para listar os jobs do Redis", exc_info=True)
    return jobs

def delete_job_from_redis(job_id: str):
    """Drop a job record and its result from Redis."""
    try:
        r = _get_redis()
        r.delete(f"{JOB_PREFIX}{job_id}", f"{RESULT_PREFIX}{job_id}")
    except Exception:
        logger.warning("não deu para apagar o job %s do Redis", job_id, exc_info=True)


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
