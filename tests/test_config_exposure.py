"""What `GET /config` is allowed to hand back.

The endpoint needs only `read:jobs`, so a `viewer` key can call it. That is fine
for the timeouts and the directory it reports, but `settings.redis_url`
routinely carries the broker's password — and in the common
`redis://:secret@host:6379/0` form the password is the only part that must not
travel.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from zfrog import api as api_module
from zfrog.auth import ApiKeyStore
from zfrog.config import redact_url_credentials, settings

app = api_module.app

SECRET = "sup3r-s3cret-broker-password"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "api_keys_file", tmp_path / "api_keys.json")
    monkeypatch.setattr(settings, "audit_log", tmp_path / "audit.log")
    monkeypatch.setattr(settings, "auth_enabled", True)


def test_the_password_is_replaced_and_the_rest_is_kept():
    """The dashboard shows this string, so the useful parts must survive."""
    redacted = redact_url_credentials(f"redis://:{SECRET}@valkey:6379/0")

    assert SECRET not in redacted
    assert redacted == "redis://:********@valkey:6379/0"


def test_a_user_with_a_password_keeps_the_user():
    redacted = redact_url_credentials(f"redis://admin:{SECRET}@valkey:6379/0")

    assert SECRET not in redacted
    assert redacted == "redis://admin:********@valkey:6379/0"


def test_a_url_without_a_password_is_returned_unchanged():
    """The common local case: nothing to hide, so nothing is rewritten."""
    assert redact_url_credentials("redis://localhost:6379/0") == "redis://localhost:6379/0"
    assert redact_url_credentials("redis://127.0.0.1:6379/1") == "redis://127.0.0.1:6379/1"


def test_a_hostile_value_cannot_break_the_response():
    """The value comes from the environment, so it must not raise."""
    assert redact_url_credentials("") == ""
    assert redact_url_credentials("not-a-url") == "not-a-url"

    # Whatever `urlsplit` makes of a malformed netloc, the secret must not come
    # back out — failing closed is the only acceptable direction here.
    assert SECRET not in redact_url_credentials(f"redis://:{SECRET}@[")


def test_the_api_never_returns_the_broker_password(monkeypatch):
    """The end-to-end guarantee, through the real request path."""
    monkeypatch.setattr(settings, "redis_url", f"redis://:{SECRET}@valkey:6379/0")

    secret, _ = ApiKeyStore().create("painel", "viewer")

    response = TestClient(app).get("/config", headers={"Authorization": f"Bearer {secret}"})

    assert response.status_code == 200
    assert SECRET not in response.text
    assert response.json()["redis_url"] == "redis://:********@valkey:6379/0"
