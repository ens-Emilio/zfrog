"""Dashboard sessions: the signed cookie that replaces a key in the browser.

The point of this module is that a logged-in browser carries a credential it
cannot leak to JavaScript and that a reverse proxy never logs — unlike the API
key in a query string it replaced. These tests cover the properties that make
that true, and the failure modes that would silently undo it.
"""

from __future__ import annotations

import time

import pytest

from zfrog import websession
from zfrog.config import settings

SECRET_ID = "u-123"


@pytest.fixture(autouse=True)
def _isolated_key(tmp_path, monkeypatch):
    """Each test gets its own signing key file."""
    monkeypatch.setattr(settings, "websession_key_file", tmp_path / "websession.key")
    monkeypatch.setattr(settings, "websession_ttl_s", 3600)


# ── the key file ──

def test_the_key_is_created_on_first_use_with_owner_only_mode():
    key = websession.load_or_create_key()

    assert key is not None and len(key) == websession.KEY_BYTES
    assert settings.websession_key_file.stat().st_mode & 0o777 == 0o600


def test_the_same_key_is_reused_so_sessions_survive_a_restart():
    """A new key per process would log everyone out on every deploy."""
    first = websession.load_or_create_key()

    assert websession.load_or_create_key() == first


def test_reading_never_creates_the_key():
    """Verification must not write: a read-only deployment still verifies."""
    assert websession.read_key() is None
    assert not settings.websession_key_file.exists()


def test_a_wrong_sized_key_file_is_refused_rather_than_replaced():
    """Overwriting would invalidate every live session, so refuse and report."""
    settings.websession_key_file.write_bytes(b"too-short")

    assert websession.read_key() is None
    assert websession.load_or_create_key() is None
    # Left alone: the operator can look at it.
    assert settings.websession_key_file.read_bytes() == b"too-short"


# ── issuing and verifying ──

def test_a_token_round_trips_to_the_user_id():
    token = websession.issue(SECRET_ID)

    assert token is not None
    assert websession.verify(token) == SECRET_ID


def test_the_user_id_is_not_merely_encoded_but_signed():
    """The id is readable — it is not secret — but a forgery must not verify."""
    token = websession.issue(SECRET_ID)
    version, payload, signature = token.split(".")

    # Swap the payload for another user's, keeping the original signature.
    forged = f"{version}.{payload}.{'A' * len(signature)}"

    assert websession.verify(forged) is None
    assert websession.verify(f"{version}.{payload}x.{signature}") is None


def test_a_token_signed_with_another_key_does_not_verify(tmp_path, monkeypatch):
    """The signature must depend on the key, not just on the payload shape."""
    token = websession.issue(SECRET_ID)

    monkeypatch.setattr(settings, "websession_key_file", tmp_path / "outra.key")

    assert websession.verify(token) is None


def test_an_expired_token_does_not_verify():
    token = websession.issue(SECRET_ID, ttl_s=10, now=time.time() - 100)

    assert websession.verify(token) is None


def test_a_token_verifies_before_its_expiry_and_not_after():
    now = time.time()
    token = websession.issue(SECRET_ID, ttl_s=100, now=now)

    assert websession.verify(token, now=now + 99) == SECRET_ID
    assert websession.verify(token, now=now + 101) is None


@pytest.mark.parametrize(
    "token",
    ["", "garbage", "v1", "v1.only-two", "v2.abc.def", "v1...", "a.b.c.d"],
)
def test_malformed_tokens_are_rejected_without_raising(token):
    assert websession.verify(token) is None


def test_an_empty_user_id_is_refused_at_issue_time():
    with pytest.raises(ValueError):
        websession.issue("   ")


def test_issuing_reports_failure_instead_of_handing_out_a_broken_token():
    """No writable key means no session; the caller must be able to tell."""
    settings.websession_key_file.write_bytes(b"wrong-size")

    assert websession.issue(SECRET_ID) is None


# ── the cookie attributes ──

class _Response:
    """Minimal stand-in that records what `set_cookie` was given."""

    def __init__(self):
        self.cookies = {}
        self.deleted = []

    def set_cookie(self, name, value, **kwargs):
        self.cookies[name] = {"value": value, **kwargs}

    def delete_cookie(self, name, **kwargs):
        self.deleted.append(name)


def test_the_cookie_is_httponly_lax_and_scoped_to_the_whole_site():
    """HttpOnly is what keeps it away from XSS; Lax blocks cross-site POSTs."""
    response = _Response()

    websession.set_session_cookie(response, "token-value", secure=True)

    cookie = response.cookies[websession.SESSION_COOKIE]
    assert cookie["value"] == "token-value"
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "lax"
    assert cookie["secure"] is True
    assert cookie["path"] == "/"
    assert cookie["max_age"] == settings.websession_ttl_s


def test_secure_follows_the_connection_rather_than_being_assumed():
    """A plain-http local login must still be able to set the cookie."""
    response = _Response()

    websession.set_session_cookie(response, "token-value", secure=False)

    assert response.cookies[websession.SESSION_COOKIE]["secure"] is False


def test_clearing_expires_the_same_cookie():
    response = _Response()

    websession.clear_session_cookie(response)

    assert response.deleted == [websession.SESSION_COOKIE]
