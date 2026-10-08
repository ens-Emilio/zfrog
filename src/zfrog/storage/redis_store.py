"""Redis-backed storage for jobs and results."""

import json
import logging

from zfrog.models import Job, JobResult
from zfrog.storage.redis_client import _is_cooldown, _mark_failure, get_sync_client

logger = logging.getLogger(__name__)

# Redis key prefixes
JOB_PREFIX = "zfrog:job:"
RESULT_PREFIX = "zfrog:result:"


def _get_redis():  # type: ignore[no-untyped-def]
    """Pooled singleton — kept for backwards compat (tests patch redis.from_url)."""
    return get_sync_client()


def save_job_to_redis(job: Job):
    """Save job to Redis."""
    if _is_cooldown():
        return
    try:
        r = _get_redis()
        key = f"{JOB_PREFIX}{job.id}"
        r.set(key, json.dumps(job.model_dump(mode="json")), ex=86400 * 7)  # 7 day expiry
    except (ConnectionError, ConnectionRefusedError, OSError) as e:
        _mark_failure()
        logger.debug("Redis unavailable while saving job %s: %s", job.id, e)
    except Exception as e:
        import redis.exceptions
        if isinstance(e, (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)):
            _mark_failure()
            logger.debug("Redis unavailable while saving job %s: %s", job.id, e)
        else:
            logger.warning("could not write job %s to Redis: %s", job.id, e)


def list_jobs_from_redis() -> list[Job]:
    """Every job record Redis holds."""
    if _is_cooldown():
        return []
    jobs: list[Job] = []
    try:
        r = _get_redis()
        for key in r.scan_iter(f"{JOB_PREFIX}*"):
            data = r.get(key)
            if data:
                jobs.append(Job.model_validate_json(data))
    except (ConnectionError, ConnectionRefusedError, OSError) as e:
        _mark_failure()
        logger.debug("Redis unavailable while listing jobs: %s", e)
        return []
    except Exception as e:
        import redis.exceptions
        if isinstance(e, (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)):
            _mark_failure()
            logger.debug("Redis unavailable while listing jobs: %s", e)
            return []
        logger.warning("could not list jobs from Redis: %s", e)
    return jobs


def delete_job_from_redis(job_id: str):
    """Drop a job record and its result from Redis."""
    if _is_cooldown():
        return
    try:
        r = _get_redis()
        r.delete(f"{JOB_PREFIX}{job_id}", f"{RESULT_PREFIX}{job_id}")
    except (ConnectionError, ConnectionRefusedError, OSError):
        _mark_failure()
    except Exception as e:
        import redis.exceptions
        if isinstance(e, (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)):
            _mark_failure()
        else:
            logger.warning("could not delete job %s from Redis: %s", job_id, e)


def get_job_from_redis(job_id: str) -> Job | None:
    """Get job from Redis."""
    if _is_cooldown():
        return None
    try:
        r = _get_redis()
        key = f"{JOB_PREFIX}{job_id}"
        data = r.get(key)
        if data:
            return Job.model_validate_json(data)
    except (ConnectionError, ConnectionRefusedError, OSError):
        _mark_failure()
    except Exception as e:
        import redis.exceptions
        if isinstance(e, (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)):
            _mark_failure()
    return None


def save_result_to_redis(result: JobResult):
    """Save result to Redis."""
    if _is_cooldown():
        return
    try:
        r = _get_redis()
        key = f"{RESULT_PREFIX}{result.job_id}"
        data = result.model_dump(mode="json")
        r.set(key, json.dumps(data), ex=86400 * 7)  # 7 day expiry
    except (ConnectionError, ConnectionRefusedError, OSError):
        _mark_failure()
    except Exception as e:
        import redis.exceptions
        if isinstance(e, (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)):
            _mark_failure()


def get_result_from_redis(job_id: str) -> JobResult | None:
    """Get result from Redis."""
    if _is_cooldown():
        return None
    try:
        r = _get_redis()
        key = f"{RESULT_PREFIX}{job_id}"
        data = r.get(key)
        if data:
            return JobResult.model_validate_json(data)
    except (ConnectionError, ConnectionRefusedError, OSError):
        _mark_failure()
    except Exception as e:
        import redis.exceptions
        if isinstance(e, (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)):
            _mark_failure()
    return None
