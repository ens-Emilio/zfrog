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
