"""Encryption-at-rest tests for saved login sessions.

``cryptography`` is an *optional* dependency of Zfrog, so the encryption code
path is exercised two ways:

* when the real package is importable, the tests use it directly;
* when it is not (the default dev environment), :func:`_install_cipher_stand_in`
  registers a stdlib stand-in under the ``cryptography.hazmat...aead`` module
  names so the *real* ``zfrog.session`` code path runs against a real
  authenticated cipher (SHA-256 keystream + encrypt-then-MAC). That is the only
  way to prove "no plaintext in the file" and "tampering is detected" on a host
  without the package — the assertions are on the bytes Zfrog wrote, not on the
  stand-in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import sys
import types
from pathlib import Path

import pytest

from zfrog.config import settings
from zfrog import session

# ── cipher stand-in (used only when `cryptography` is missing) ──────


class _InvalidTag(Exception):
    """Raised by the stand-in when authentication fails."""


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """SHA-256 counter-mode keystream (stand-in only, never used in production)."""
    blocks = bytearray()
    counter = 0
    while len(blocks) < length:
        blocks += hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(blocks[:length])


class _AESGCMStandIn:
    """Drop-in for ``cryptography...aead.AESGCM`` built from hashlib/hmac."""

    TAG_BYTES = 32

    def __init__(self, key: bytes):
        key = bytes(key)
        if len(key) not in (16, 24, 32):
            raise ValueError("Invalid key size")
        self._key = key

    def _tag(self, nonce: bytes, aad: bytes | None, ciphertext: bytes) -> bytes:
        mac = hmac.new(self._key, b"zfrog-test-mac", hashlib.sha256)
        mac.update(bytes(nonce))
        mac.update(b"" if aad is None else bytes(aad))
        mac.update(ciphertext)
        return mac.digest()

    def encrypt(self, nonce, data, associated_data=None):
        ciphertext = bytes(
            a ^ b for a, b in zip(bytes(data), _keystream(self._key, bytes(nonce), len(data)))
        )
        return ciphertext + self._tag(nonce, associated_data, ciphertext)

    def decrypt(self, nonce, data, associated_data=None):
        data = bytes(data)
        if len(data) < self.TAG_BYTES:
            raise _InvalidTag("ciphertext too short")
        ciphertext, tag = data[: -self.TAG_BYTES], data[-self.TAG_BYTES :]
        if not hmac.compare_digest(tag, self._tag(nonce, associated_data, ciphertext)):
            raise _InvalidTag("authentication failed")
        return bytes(
            a ^ b for a, b in zip(ciphertext, _keystream(self._key, bytes(nonce), len(ciphertext)))
        )


def _real_cryptography_importable() -> bool:
    try:
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
    except Exception:
        return False
    return True


def _install_cipher_stand_in(monkeypatch) -> None:
    """Register the stand-in under the ``cryptography`` module names."""
    aead = types.ModuleType("cryptography.hazmat.primitives.ciphers.aead")
    aead.AESGCM = _AESGCMStandIn  # type: ignore[attr-defined]
    ciphers = types.ModuleType("cryptography.hazmat.primitives.ciphers")
    ciphers.aead = aead  # type: ignore[attr-defined]
    primitives = types.ModuleType("cryptography.hazmat.primitives")
    primitives.ciphers = ciphers  # type: ignore[attr-defined]
    hazmat = types.ModuleType("cryptography.hazmat")
    hazmat.primitives = primitives  # type: ignore[attr-defined]
    root = types.ModuleType("cryptography")
    root.hazmat = hazmat  # type: ignore[attr-defined]

    for name, module in (
        ("cryptography", root),
        ("cryptography.hazmat", hazmat),
        ("cryptography.hazmat.primitives", primitives),
        ("cryptography.hazmat.primitives.ciphers", ciphers),
        ("cryptography.hazmat.primitives.ciphers.aead", aead),
    ):
        monkeypatch.setitem(sys.modules, name, module)


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_sessions(tmp_path, monkeypatch) -> Path:
    """Keep state files *and* the key file inside tmp_path."""
    root = tmp_path / "sessions"
    monkeypatch.setattr(settings, "sessions_dir", root)
    monkeypatch.setattr(settings, "sessions_key_file", root / ".key")
    monkeypatch.setattr(session, "_plaintext_warning_emitted", False)
    return root


@pytest.fixture
def encrypted_sessions(monkeypatch) -> None:
    """Make the encryption path runnable on this host."""
    if not _real_cryptography_importable():
        _install_cipher_stand_in(monkeypatch)
    assert session.encryption_available() is True


def _state(cookie_count: int = 1) -> dict:
    return {
        "cookies": [
            {
                "name": "sessionid" if index == 0 else f"sid{index}",
                "value": "sup3r-s3cret" if index == 0 else f"secret{index}",
                "domain": "example.com",
                "path": "/",
                "httpOnly": True,
            }
            for index in range(cookie_count)
        ],
        "origins": [
            {
                "origin": "https://example.com",
                "localStorage": [{"name": "token", "value": "abc"}],
            }
        ],
    }


def _read_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── availability + key management ───────────────────────────────────


def test_encryption_available_reports_whether_cryptography_imports():
    available = session.encryption_available()

    assert isinstance(available, bool)
    assert available is _real_cryptography_importable()


def test_load_or_create_key_returns_none_when_encryption_is_unavailable(
    isolated_sessions, monkeypatch
):
    monkeypatch.setattr(session, "encryption_available", lambda: False)

    assert session.load_or_create_key() is None
    # No key file — and no key directory — is created in that case.
    assert not isolated_sessions.exists()


def test_load_or_create_key_creates_a_32_byte_owner_only_key(encrypted_sessions, isolated_sessions):
    key_path = isolated_sessions / "nested" / "session.key"

    key = session.load_or_create_key(key_path)

    assert key is not None and len(key) == 32
    assert key_path.read_bytes() == key
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert key_path.parent.is_dir()


def test_load_or_create_key_reuses_an_existing_key(encrypted_sessions, isolated_sessions):
    first = session.load_or_create_key()
    raw = isolated_sessions.joinpath(".key").read_bytes()

    second = session.load_or_create_key()

    assert second == first
    assert isolated_sessions.joinpath(".key").read_bytes() == raw


def test_load_or_create_key_refuses_a_short_key_file(encrypted_sessions, isolated_sessions, caplog):
    isolated_sessions.mkdir(parents=True, exist_ok=True)
    key_path = isolated_sessions / ".key"
    key_path.write_bytes(b"short")

    with caplog.at_level(logging.WARNING, logger="zfrog.session"):
        assert session.load_or_create_key() is None

    assert "Ignoring session key" in caplog.text
    assert key_path.read_bytes() == b"short"  # left untouched, not silently replaced


# ── encrypted storage ───────────────────────────────────────────────


def test_encrypted_save_load_round_trips_the_state_exactly(encrypted_sessions):
    store = session.SessionStore()
    state = _state(cookie_count=3)

    path = store.save("Example.com", state)
    payload = _read_payload(path)

    assert payload["domain"] == "example.com"
    assert payload["saved_at"]
    assert payload["encrypted"] is True
    assert isinstance(payload["state"], str)
    assert store.load("example.com") == state
    assert store.load("EXAMPLE.COM") == state


def test_encrypted_file_contains_no_plaintext_cookie_value(encrypted_sessions, isolated_sessions):
    store = session.SessionStore()
    state = _state()

    path = store.save("example.com", state)
    raw = path.read_bytes()

    assert b"sessionid" not in raw
    assert b"sup3r-s3cret" not in raw
    assert b"localStorage" not in raw
    assert path.stat().st_mode & 0o777 == 0o600
    assert (isolated_sessions / ".key").stat().st_mode & 0o777 == 0o600

    assert store.load("example.com") == state
    assert store.has("example.com") is True
    assert store.state_path("https://www.example.com/deep/link") == path


def test_fixed_key_patches_still_hide_the_cookies(encrypted_sessions, monkeypatch):
    """Contract mirror: patch availability + key, the cipher stays real."""
    key = bytes(range(32))
    monkeypatch.setattr(session, "encryption_available", lambda: True)
    monkeypatch.setattr(session, "load_or_create_key", lambda path=None: key)
    store = session.SessionStore()
    state = _state()

    path = store.save("example.com", state)
    raw = path.read_bytes()

    assert b"sessionid" not in raw
    assert b"sup3r-s3cret" not in raw
    assert store.load("example.com") == state
    assert path.stat().st_mode & 0o777 == 0o600


def test_tampered_ciphertext_fails_authentication_and_returns_none(encrypted_sessions, caplog):
    store = session.SessionStore()
    path = store.save("example.com", _state())
    payload = _read_payload(path)
    blob = bytearray(base64.b64decode(payload["state"]))
    assert len(blob) > session.NONCE_BYTES

    for index in (session.NONCE_BYTES + 4, len(blob) - 1):
        tampered = bytearray(blob)
        tampered[index] ^= 0x01
        payload["state"] = base64.b64encode(bytes(tampered)).decode("ascii")
        path.write_text(json.dumps(payload), encoding="utf-8")

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="zfrog.session"):
            assert store.load("example.com") is None

        assert "authentication failed" in caplog.text
        assert store.list() == []


def test_encrypted_state_needs_the_matching_key(encrypted_sessions, isolated_sessions):
    store = session.SessionStore()
    store.save("example.com", _state())

    (isolated_sessions / ".key").write_bytes(bytes(range(32)))

    assert store.load("example.com") is None


def test_missing_key_file_does_not_resurrect_an_encrypted_session(encrypted_sessions, isolated_sessions):
    store = session.SessionStore()
    store.save("example.com", _state())

    (isolated_sessions / ".key").unlink()

    assert store.load("example.com") is None  # a fresh key cannot open it


# ── plaintext storage (no usable key) ───────────────────────────────


def test_save_without_a_key_stores_plaintext_and_round_trips(isolated_sessions, monkeypatch, caplog):
    monkeypatch.setattr(session, "load_or_create_key", lambda path=None: None)
    store = session.SessionStore()
    state = _state()

    with caplog.at_level(logging.WARNING, logger="zfrog.session"):
        path = store.save("example.com", state)
        store.save("other.test", _state())

    payload = _read_payload(path)
    assert payload["encrypted"] is False
    assert payload["state"] == state
    assert store.load("example.com") == state
    assert path.stat().st_mode & 0o777 == 0o600
    assert not (isolated_sessions / ".key").exists()

    plaintext_warnings = [r for r in caplog.records if "PLAINTEXT" in r.getMessage()]
    assert len(plaintext_warnings) == 1  # told once per process, not per save


def test_unusable_cipher_degrades_to_plaintext_without_raising(isolated_sessions, monkeypatch, caplog):
    """``encryption_available()`` is optimistic; a broken stack must not crash."""

    def _broken_seal(state: dict, key: bytes) -> str:
        raise RuntimeError("cipher is broken")

    monkeypatch.setattr(session, "encryption_available", lambda: True)
    monkeypatch.setattr(session, "load_or_create_key", lambda path=None: b"k" * 32)
    monkeypatch.setattr(session, "_encrypt_state", _broken_seal)
    store = session.SessionStore()
    state = _state()

    with caplog.at_level(logging.WARNING, logger="zfrog.session"):
        path = store.save("example.com", state)

    assert _read_payload(path)["encrypted"] is False
    assert store.load("example.com") == state
    assert "Could not encrypt session" in caplog.text


# ── list() keeps its shape in both modes ────────────────────────────


def test_list_reports_domain_saved_at_and_cookies_for_encrypted_store(encrypted_sessions):
    store = session.SessionStore()
    store.save("b.test", _state(cookie_count=2))
    store.save("a.test", _state(cookie_count=1))

    entries = store.list()

    assert [entry["domain"] for entry in entries] == ["a.test", "b.test"]
    assert all(set(entry) == {"domain", "saved_at", "cookies"} for entry in entries)
    assert [entry["cookies"] for entry in entries] == [1, 2]
    assert all(entry["saved_at"] for entry in entries)


def test_list_reports_domain_saved_at_and_cookies_for_plaintext_store(isolated_sessions, monkeypatch):
    monkeypatch.setattr(session, "load_or_create_key", lambda path=None: None)
    store = session.SessionStore(isolated_sessions / "plain")
    store.save("b.test", _state(cookie_count=2))
    store.save("a.test", _state(cookie_count=1))

    entries = store.list()

    assert [entry["domain"] for entry in entries] == ["a.test", "b.test"]
    assert all(set(entry) == {"domain", "saved_at", "cookies"} for entry in entries)
    assert [entry["cookies"] for entry in entries] == [1, 2]
    assert all(entry["saved_at"] for entry in entries)


# ── the real package, when present ──────────────────────────────────


@pytest.mark.skipif(not _real_cryptography_importable(), reason="cryptography is not installed")
def test_real_aesgcm_encrypts_and_rejects_tampering(isolated_sessions):
    store = session.SessionStore()
    state = _state()

    path = store.save("example.com", state)

    assert session.encryption_available() is True
    assert _read_payload(path)["encrypted"] is True
    assert b"sup3r-s3cret" not in path.read_bytes()
    assert store.load("example.com") == state

    payload = _read_payload(path)
    blob = bytearray(base64.b64decode(payload["state"]))
    blob[session.NONCE_BYTES] ^= 0x01
    payload["state"] = base64.b64encode(bytes(blob)).decode("ascii")
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert store.load("example.com") is None
