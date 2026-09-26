"""Tests for saved login sessions (SessionStore + browser-pool wiring)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zfrog.config import settings
from zfrog.engines.playwright import BrowserPool, session_state_for
from zfrog.session import SessionStore, domain_for


@pytest.fixture(autouse=True)
def sessions_dir(tmp_path, monkeypatch) -> Path:
    """Keep every state file inside tmp_path — never the repo's sessions/."""
    root = tmp_path / "sessions"
    monkeypatch.setattr(settings, "sessions_dir", root)
    return root


def _state(cookie_count: int = 1) -> dict:
    return {
        "cookies": [
            {"name": f"sid{i}", "value": f"secret{i}", "domain": "example.com", "path": "/"}
            for i in range(cookie_count)
        ],
        "origins": [{"origin": "https://example.com", "localStorage": [{"name": "t", "value": "1"}]}],
    }


# ── domain_for ──────────────────────────────────────────────────────


def test_domain_for_strips_port_and_www_and_lowercases():
    assert domain_for("https://WWW.Example.com:8443/docs?x=1") == "example.com"
    assert domain_for("http://example.com:80/") == "example.com"
    assert domain_for("https://Example.COM") == "example.com"
    assert domain_for("example.com/path") == "example.com"


def test_domain_for_keeps_subdomains_and_drops_bare_www():
    assert domain_for("https://app.example.com:443/x") == "app.example.com"
    assert domain_for("https://www.www.example.com") == "www.example.com"


# ── SessionStore ────────────────────────────────────────────────────


def test_save_load_has_list_delete_round_trip(sessions_dir):
    store = SessionStore()
    assert store.list() == []
    assert store.has("example.com") is False
    assert store.load("example.com") is None

    state = _state(cookie_count=2)
    path = store.save("Example.com", state)

    assert path == sessions_dir / "example.com.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["domain"] == "example.com"
    assert payload["saved_at"]
    # The payload is sealed whenever a key is available, so it is only readable
    # through `load` — the raw file must never carry the cookie values.
    if payload["encrypted"]:
        assert payload["state"] != state
        assert "secret0" not in path.read_text(encoding="utf-8")
    else:
        assert payload["state"] == state

    assert store.has("example.com") is True
    assert store.load("example.com") == state
    assert store.load("EXAMPLE.COM") == state

    store.save("other.test", _state())
    entries = store.list()
    assert [entry["domain"] for entry in entries] == ["example.com", "other.test"]
    assert entries[0]["cookies"] == 2
    assert entries[1]["cookies"] == 1
    assert entries[0]["saved_at"] == payload["saved_at"]

    assert store.delete("example.com") is True
    assert store.delete("example.com") is False
    assert store.has("example.com") is False
    assert store.load("example.com") is None
    assert [entry["domain"] for entry in store.list()] == ["other.test"]


def test_save_writes_state_file_with_owner_only_mode(sessions_dir):
    path = SessionStore().save("example.com", _state())
    assert path.stat().st_mode & 0o777 == 0o600


def test_save_tightens_mode_of_a_preexisting_loose_file(sessions_dir):
    sessions_dir.mkdir(parents=True)
    path = sessions_dir / "example.com.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o644)

    SessionStore().save("example.com", _state())

    assert path.stat().st_mode & 0o777 == 0o600


def test_save_rejects_empty_domain(sessions_dir):
    store = SessionStore()
    with pytest.raises(ValueError):
        store.save("", _state())
    with pytest.raises(ValueError):
        store.save("   ", _state())
    assert not sessions_dir.exists()


def test_load_returns_none_for_corrupt_or_misshaped_file(sessions_dir):
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "broken.test.json").write_text("{not json", encoding="utf-8")
    (sessions_dir / "shapeless.test.json").write_text(json.dumps({"domain": "shapeless.test"}), encoding="utf-8")

    store = SessionStore()
    assert store.load("broken.test") is None
    assert store.load("shapeless.test") is None
    assert store.list() == []


def test_store_uses_explicit_root(tmp_path):
    root = tmp_path / "elsewhere"
    store = SessionStore(root)
    assert store.save("example.com", _state()) == root / "example.com.json"
    assert store.load("example.com") == _state()


# ── state_path / engine helper ──────────────────────────────────────


def test_state_path_is_none_without_session_and_path_with_one(sessions_dir):
    store = SessionStore()
    assert store.state_path("https://www.example.com/a/b") is None
    assert session_state_for("https://www.example.com/a/b") is None

    store.save("example.com", _state())

    expected = sessions_dir / "example.com.json"
    assert store.state_path("https://www.example.com/a/b") == expected
    assert store.state_path("http://example.com:8080/") == expected
    assert session_state_for("https://www.example.com/a/b") == str(expected)
    assert session_state_for("https://unrelated.test/") is None


# ── BrowserPool forwarding ──────────────────────────────────────────


class _FakeContext:
    """Minimal BrowserContext stand-in: the pool only needs .pages and .close()."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.pages: list = []
        self.closed = False

    async def close(self):
        self.closed = True


class _FakeBrowser:
    """Records the kwargs every new_context call received."""

    def __init__(self):
        self.created: list[_FakeContext] = []

    def is_connected(self) -> bool:
        return True

    async def new_context(self, **kwargs) -> _FakeContext:
        context = _FakeContext(**kwargs)
        self.created.append(context)
        return context


def _pool(pool_size: int = 2) -> tuple[BrowserPool, _FakeBrowser]:
    pool = BrowserPool(pool_size=pool_size, max_pages=10, max_age_s=3600)
    browser = _FakeBrowser()
    pool._browser = browser
    return pool, browser


async def test_new_context_forwards_storage_state():
    pool, browser = _pool()

    context = await pool._new_context(storage_state="/tmp/state.json")

    assert browser.created == [context]
    assert context.kwargs["storage_state"] == "/tmp/state.json"
    assert context.kwargs["java_script_enabled"] is True


async def test_new_context_without_storage_state_keeps_default_kwargs():
    pool, _ = _pool()

    context = await pool._new_context()

    assert "storage_state" not in context.kwargs
    assert context.kwargs["viewport"]
    assert context.kwargs["user_agent"]
    assert context.kwargs["locale"]


async def test_get_context_without_storage_state_reuses_healthy_context():
    pool, browser = _pool()

    first = await pool.get_context()
    second = await pool.get_context()

    assert second is first
    assert len(browser.created) == 1


async def test_get_context_with_storage_state_never_reuses_plain_context():
    pool, browser = _pool(pool_size=3)

    plain = await pool.get_context()
    session = await pool.get_context(storage_state="state.json")

    assert session is not plain
    assert session.kwargs["storage_state"] == "state.json"
    assert "storage_state" not in plain.kwargs
    assert plain.closed is False
    assert len(browser.created) == 2


async def test_get_context_with_storage_state_evicts_oldest_when_pool_is_full():
    pool, _ = _pool(pool_size=1)

    plain = await pool.get_context()
    session = await pool.get_context(storage_state="state.json")

    assert session is not plain
    assert plain.closed is True
    assert len(pool._contexts) == 1
    assert pool._contexts[0]["context"] is session


async def test_get_context_with_storage_state_always_builds_a_fresh_context():
    pool, browser = _pool(pool_size=1)

    first = await pool.get_context(storage_state="state.json")
    second = await pool.get_context(storage_state="state.json")

    assert second is not first
    assert first.closed is True
    assert len(browser.created) == 2
