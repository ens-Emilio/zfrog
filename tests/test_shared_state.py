"""Tests for state shared across processes.

A deployment runs more than one process: several API workers, plus Celery
workers. State kept in a plain module dict is per-process, so a webhook
registered by one worker never fires and an SSO login started by one worker fails
at random in another. Redis is the shared store; the in-memory path stays for
single-process (local) use.

The tests use a real Redis when one is reachable and skip otherwise, so this file
is honest about what it actually verified.
"""

import os
import uuid

import pytest

from zfrog.config import settings


def _redis_available() -> bool:
    try:
        import redis

        client = redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(
    not _redis_available(),
    reason="no Redis reachable at ZFROG_REDIS_URL; the shared-state path is not exercised",
)


@pytest.fixture
def shared_redis():
    """Point the settings at a real Redis and clean up the keys this test makes."""
    import redis

    client = redis.from_url(settings.redis_url, decode_responses=True)
    prefix = f"test-{uuid.uuid4().hex[:8]}"
    yield client, prefix
    for key in client.scan_iter(match="zfrog:webhooks"):
        client.delete(key)
    for key in client.scan_iter(match="zfrog:sso:state:*"):
        client.delete(key)
    for key in client.scan_iter(match="zfrog:job:*"):
        client.delete(key)
    for key in client.scan_iter(match="zfrog:result:*"):
        client.delete(key)
    for key in client.scan_iter(match="zfrog:cancelled:*"):
        client.delete(key)


# ── webhooks ────────────────────────────────────────────────────────────────

def test_webhooks_work_without_redis(monkeypatch):
    """The local path must keep working: that is what `zfrog` alone relies on."""
    from zfrog.utils import webhooks as w

    monkeypatch.setattr(w, "_redis", lambda: None)
    w.clear_webhooks()
    hook = w.WebhookConfig(url="http://local.test/hook", events=["job.completed"])
    w.register_webhook(hook)

    assert [str(h.url) for h in w.list_webhooks()] == ["http://local.test/hook"]
    assert w.remove_webhook(hook.id) is True
    assert w.list_webhooks() == []


@requires_redis
def test_a_webhook_registered_in_one_process_is_visible_in_another(shared_redis):
    """Regression: the registry was a module dict, so worker B saw zero hooks."""
    from zfrog.utils import webhooks as w

    w.clear_webhooks()
    hook = w.WebhookConfig(url="http://shared.test/hook", events=["site.changed"])
    w.register_webhook(hook)

    # Simulate a different process: the module list is empty, Redis is the link.
    w._webhooks.clear()

    assert [str(h.url) for h in w.list_webhooks()] == ["http://shared.test/hook"]


@requires_redis
def test_removal_is_shared_too(shared_redis):
    from zfrog.utils import webhooks as w

    w.clear_webhooks()
    hook = w.WebhookConfig(url="http://gone.test/h", events=["job.completed"])
    w.register_webhook(hook)
    hook_id = w.list_webhooks()[0].id

    # Another process removes it.
    w._webhooks.clear()
    assert w.remove_webhook(hook_id) is True

    w._webhooks.clear()
    assert w.list_webhooks() == []


@requires_redis
def test_removing_an_unknown_webhook_reports_false(shared_redis):
    from zfrog.utils import webhooks as w

    w.clear_webhooks()

    assert w.remove_webhook("nao-existe") is False


# ── SSO pending logins ──────────────────────────────────────────────────────

def test_sso_login_works_without_redis(monkeypatch):
    from zfrog import api

    monkeypatch.setattr(api, "_login_redis", lambda: None)
    api._pending_logins.clear()

    api._remember_login("state-local", "nonce-local")

    assert api._consume_login("state-local") == "nonce-local"


def test_sso_login_is_single_use_without_redis(monkeypatch):
    from zfrog import api

    monkeypatch.setattr(api, "_login_redis", lambda: None)
    api._pending_logins.clear()
    api._remember_login("state-once", "n")

    api._consume_login("state-once")

    with pytest.raises(ValueError):
        api._consume_login("state-once")


def test_sso_login_expires(monkeypatch):
    from zfrog import api

    monkeypatch.setattr(api, "_login_redis", lambda: None)
    api._pending_logins.clear()
    api._pending_logins["state-old"] = ("n", 0.0)  # epoch: certainly stale

    with pytest.raises(ValueError):
        api._consume_login("state-old")


@requires_redis
def test_sso_login_started_in_one_process_finishes_in_another(shared_redis):
    """Regression: the redirect and the callback hit different workers."""
    from zfrog import api

    api._pending_logins.clear()
    api._remember_login("state-shared", "nonce-shared")

    # Another process: it has no local entry, only Redis.
    api._pending_logins.clear()

    assert api._consume_login("state-shared") == "nonce-shared"


@requires_redis
def test_sso_state_cannot_be_replayed_across_processes(shared_redis):
    from zfrog import api

    api._pending_logins.clear()
    api._remember_login("state-replay", "n")

    api._pending_logins.clear()
    api._consume_login("state-replay")

    api._pending_logins.clear()
    with pytest.raises(ValueError):
        api._consume_login("state-replay")

# ── job records ─────────────────────────────────────────────────────────────

def _job(job_id: str, status=None):
    from datetime import datetime, timezone

    from zfrog.models import Job, JobStatus

    return Job(
        id=job_id,
        url="https://example.com/",
        mode="scrape",
        max_depth=1,
        status=status or JobStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

@requires_redis
def test_a_job_record_survives_a_round_trip(shared_redis):
    """Regression: the write raised and a bare `except` hid it.

    `model_dump(mode="json")` already renders datetimes as ISO strings, and the
    store called `.isoformat()` on them — AttributeError on a `str`, swallowed, so
    no job record ever reached Redis. Every job stayed `pending` on screen while
    the extraction had in fact finished.
    """
    from zfrog.models import JobStatus
    from zfrog.storage.redis_store import get_job_from_redis, save_job_to_redis

    save_job_to_redis(_job("round-trip", JobStatus.COMPLETED))

    back = get_job_from_redis("round-trip")
    assert back is not None
    assert back.status is JobStatus.COMPLETED
    assert back.created_at.tzinfo is not None or back.created_at.year > 2000

@requires_redis
def test_a_job_created_by_one_process_is_visible_to_another(shared_redis):
    """The API and the Celery worker are separate processes.

    The API creates the record and dispatches; the worker writes the new status.
    Reading only the local dict meant the API answered `pending` forever.
    """
    from zfrog.models import JobStatus
    from zfrog.orchestrator import _jobs, clear_jobs, list_jobs, update_job

    update_job(_job("cross-process", JobStatus.COMPLETED))
    # Another process: same Redis, empty memory.
    _jobs.clear()

    assert "cross-process" in [j.id for j in list_jobs()]

    # And the clear reaches the shared store too, not just local memory.
    assert clear_jobs() >= 1
    _jobs.clear()
    assert "cross-process" not in [j.id for j in list_jobs()]

def test_clear_jobs_keeps_work_that_has_not_finished(monkeypatch):
    """Clearing must not drop a job that is still going to run.

    A queued job removed from the list and then executed reappears on its own, and
    a list that refills itself right after "clear" reads as a bug.
    """
    from zfrog.models import JobStatus
    from zfrog.orchestrator import _jobs, _results, clear_jobs, list_jobs

    monkeypatch.setattr("zfrog.storage.redis_store.save_job_to_redis", lambda job: None)
    monkeypatch.setattr("zfrog.storage.redis_store.delete_job_from_redis", lambda job_id: None)
    monkeypatch.setattr("zfrog.storage.redis_store.list_jobs_from_redis", lambda: [])

    _jobs.clear()
    _results.clear()
    _jobs["done"] = _job("done", JobStatus.COMPLETED)
    _jobs["failed"] = _job("failed", JobStatus.FAILED)
    _jobs["queued"] = _job("queued", JobStatus.PENDING)
    _jobs["running"] = _job("running", JobStatus.RUNNING)

    assert clear_jobs() == 2
    assert sorted(j.id for j in list_jobs()) == ["queued", "running"]
    _jobs.clear()

# ── job cancellation ────────────────────────────────────────────────────────

def test_cancelling_works_without_redis(monkeypatch):
    """The local path must keep working: that is what `zfrog` alone relies on."""
    import asyncio

    from zfrog.utils import cleanup

    monkeypatch.setattr(cleanup, "_redis", lambda: None)
    cleanup._cancelled_jobs.clear()

    asyncio.run(cleanup.cancel_job("local-cancel"))
    assert asyncio.run(cleanup.is_cancelled("local-cancel")) is True

    asyncio.run(cleanup.clear_cancellation("local-cancel"))
    assert asyncio.run(cleanup.is_cancelled("local-cancel")) is False

@requires_redis
def test_a_cancellation_from_one_process_reaches_another(shared_redis):
    """Regression: the flag was a module set living in the API process.

    The job runs in a Celery worker, so the worker read `False` forever and
    "Interromper" stopped nothing at all.
    """
    import asyncio

    from zfrog.utils import cleanup

    asyncio.run(cleanup.clear_cancellation("cross-cancel"))
    cleanup._cancelled_jobs.clear()

    asyncio.run(cleanup.cancel_job("cross-cancel"))
    # Another process: same Redis, empty memory.
    cleanup._cancelled_jobs.clear()

    assert asyncio.run(cleanup.is_cancelled("cross-cancel")) is True

    asyncio.run(cleanup.clear_cancellation("cross-cancel"))
    cleanup._cancelled_jobs.clear()
    assert asyncio.run(cleanup.is_cancelled("cross-cancel")) is False

def test_a_cancelled_job_is_not_recorded_as_a_failure(monkeypatch):
    """Regression: the task's crash handler overwrote CANCELLED with FAILED.

    `CancellationError` is an `Exception`, so the broad handler caught the user's
    own "stop" and the row showed "Falha" for something they had asked for.
    """
    from zfrog.models import JobStatus
    from zfrog.orchestrator import _jobs, get_job, update_job
    from zfrog.queue import run_job_task
    from zfrog.utils.cleanup import CancellationError

    monkeypatch.setattr("zfrog.storage.redis_store.save_job_to_redis", lambda job: None)
    monkeypatch.setattr("zfrog.storage.redis_store.get_job_from_redis", lambda job_id: None)
    _jobs.clear()
    update_job(_job("cancelled-run", JobStatus.RUNNING))

    async def _cancel_and_raise(job, job_id=None):
        # What `run_job` does when it notices the cancellation flag.
        record = get_job(job_id)
        record.status = JobStatus.CANCELLED
        record.error = f"Job {job_id} was cancelled"
        update_job(record)
        raise CancellationError(record.error)

    monkeypatch.setattr("zfrog.orchestrator.run_job", _cancel_and_raise)

    out = run_job_task.apply(
        args=[{"job_id": "cancelled-run", "url": "https://example.com/", "mode": "scrape", "max_depth": 1}]
    ).get()

    assert out["status"] == "cancelled"
    assert _jobs["cancelled-run"].status is JobStatus.CANCELLED
    _jobs.clear()
