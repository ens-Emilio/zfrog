"""Singleton Redis clients — shared pooled connections."""

from __future__ import annotations

import time
import logging

from zfrog.config import settings

logger = logging.getLogger(__name__)

_sync_client = None  # type: ignore[no-redef]
_async_client = None  # type: ignore[no-redef]
_sync_url: str | None = None
_async_url: str | None = None

_last_failure: float = 0.0
_COOLDOWN_S: float = 5.0


def _is_cooldown() -> bool:
    return (time.monotonic() - _last_failure) < _COOLDOWN_S


def _mark_failure() -> None:
    global _last_failure
    _last_failure = time.monotonic()


def get_sync_client():  # type: ignore[no-untyped-def]
    """Pooled sync client; reuses pool when URL unchanged."""
    global _sync_client, _sync_url
    url = settings.redis_url
    if _sync_client is not None and _sync_url == url:
        return _sync_client
    import redis

    if _sync_client is not None:
        try:
            _sync_client.close()
        except Exception:
            pass
        _sync_client = None
    _sync_client = redis.from_url(url, decode_responses=True)
    _sync_url = url
    return _sync_client


def get_async_client():  # type: ignore[no-untyped-def]
    """Pooled async client; reuses pool when URL unchanged."""
    global _async_client, _async_url
    url = settings.redis_url
    if _async_client is not None and _async_url == url:
        return _async_client
    from redis import asyncio as aioredis

    if _async_client is not None:
        try:
            # fire-and-forget close of old pool is best-effort (no loop here)
            pass
        except Exception:
            pass
        _async_client = None
    _async_client = aioredis.from_url(url, decode_responses=True)
    _async_url = url
    return _async_client


def close_sync_client() -> None:
    global _sync_client, _sync_url
    if _sync_client is not None:
        try:
            _sync_client.close()
        except Exception:
            pass
        _sync_client = None
        _sync_url = None


async def close_async_client() -> None:
    global _async_client, _async_url
    if _async_client is not None:
        try:
            await _async_client.close()
        except Exception:
            pass
        _async_client = None
        _async_url = None
