"""BrowserPool lifecycle tests WITHOUT launching a real browser.

A fake browser/context pair stands in for Chromium so pool bookkeeping
(acquire reuse, max-size eviction, age eviction, close) is exercised with no
browser binary, no network, and no external services.
"""

import asyncio

from zfrog.config import settings
from zfrog.engines.playwright import BrowserPool
from zfrog.utils.stealth import LOCALE, USER_AGENT, VIEWPORT, locale, user_agent, viewport


class _FakeContext:
    def __init__(self):
        self.pages = []
        self.closed = False

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self):
        self.created = 0
        self.closed = False
        self.last_kwargs = None

    def is_connected(self):
        return True

    async def new_context(self, **kwargs):
        self.created += 1
        self.last_kwargs = kwargs
        return _FakeContext()

    async def close(self):
        self.closed = True


def _pooled(pool_size=2):
    pool = BrowserPool(pool_size=pool_size, max_pages=10, max_age_s=60)
    pool._browser = _FakeBrowser()
    return pool


async def test_pool_defaults_come_from_settings():
    pool = BrowserPool()
    assert pool.pool_size == settings.browser_pool_size
    assert pool.max_pages == settings.browser_context_max_pages
    assert pool.max_age_s == settings.browser_context_max_age_s
    await pool.close()  # never started: must be a graceful no-op


async def test_pool_reuses_healthy_context():
    pool = _pooled()
    try:
        first = await pool.get_context()
        second = await pool.get_context()
        assert second is first
        assert len(pool._contexts) == 1
    finally:
        await pool.close()


async def test_pool_respects_max_size():
    pool = _pooled(pool_size=2)
    try:
        c1 = await pool.get_context(storage_state="/tmp/a.json")
        c2 = await pool.get_context(storage_state="/tmp/b.json")
        assert len(pool._contexts) == 2
        # Pool full: oldest entry is evicted to make room.
        await pool.get_context(storage_state="/tmp/c.json")
        assert len(pool._contexts) == 2
        assert c1.closed
        assert not c2.closed
    finally:
        await pool.close()


async def test_pool_evicts_expired_context():
    """A context older than max_age_s is recycled instead of reused."""
    pool = _pooled()
    try:
        old = await pool.get_context()
        pool._contexts[0]["created_at"] -= 3600
        fresh = await pool.get_context()
        assert fresh is not old
        assert old.closed
    finally:
        await pool.close()


async def test_pool_close_clears_state():
    pool = _pooled()
    await pool.get_context()
    await pool.close()
    assert pool._contexts == []


async def test_pool_missing_browser_raises_on_use_but_close_is_safe():
    """Without start() there is no browser: using the pool fails loudly (so a
    misconfiguration is never silent), while close() stays a graceful no-op."""
    pool = BrowserPool(pool_size=1)
    try:
        await pool.get_context()
    except Exception:
        pass
    else:
        raise AssertionError("expected get_context without start() to fail")
    await pool.close()


async def test_new_context_uses_the_stable_identity():
    """One user-agent, one viewport, one locale — no per-request rotation."""
    pool = _pooled()
    try:
        await pool.get_context()
        kwargs = pool._browser.last_kwargs
        assert kwargs["user_agent"] == USER_AGENT == user_agent()
        assert kwargs["viewport"] == VIEWPORT == viewport()
        assert kwargs["locale"] == LOCALE == locale()
    finally:
        await pool.close()


async def test_identity_is_stable_across_contexts():
    """Two contexts get the same identity: rotating it would be evasion."""
    first = (user_agent(), viewport(), locale())
    second = (user_agent(), viewport(), locale())
    assert first == second
    # viewport() returns a copy so callers cannot mutate the shared default.
    assert viewport() is not viewport()
