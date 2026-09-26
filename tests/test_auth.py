"""Tests for API key storage and role-based authorisation."""

from __future__ import annotations

import logging
import stat

import pytest

from zfrog.auth import (
    ApiKeyStore,
    authorize,
    extract_credential,
    generate_key,
    hash_key,
    require,
)
from zfrog.config import settings


@pytest.fixture(autouse=True)
def _isolated_keys(tmp_path, monkeypatch):
    """Every test gets its own key file, with auth enforced."""
    monkeypatch.setattr(settings, "api_keys_file", tmp_path / "api_keys.json")
    monkeypatch.setattr(settings, "auth_enabled", True)


@pytest.fixture
def store():
    return ApiKeyStore()


# ── key material ──


def test_generate_key_prefixes_secret_and_matches_its_hash():
    secret, digest = generate_key()

    assert secret.startswith("zk_")
    assert digest == hash_key(secret)
    assert secret != generate_key()[0]


def test_hash_key_is_a_sha256_hex_digest():
    digest = hash_key("zk_example")

    assert len(digest) == 64
    assert int(digest, 16) >= 0
    assert digest != hash_key("zk_examplf")


# ── storage ──


def test_create_then_verify_round_trips(store):
    secret, key = store.create("cli", "operator")

    found = store.verify(secret)
    assert found is not None
    assert found.id == key.id
    assert found.name == "cli"
    assert found.role == "operator"
    assert store.verify("zk_not-a-real-key") is None


def test_key_file_holds_the_hash_and_never_the_secret(store):
    secret, _ = store.create("ci", "viewer")

    raw = settings.api_keys_file.read_bytes()
    assert secret.encode() not in raw
    assert hash_key(secret).encode() in raw
    assert secret not in settings.api_keys_file.read_text(encoding="utf-8")


def test_key_file_is_owner_only(store):
    store.create("ci", "viewer")

    mode = stat.S_IMODE(settings.api_keys_file.stat().st_mode)
    assert mode == 0o600


def test_verify_stamps_last_used_at_on_success(store):
    secret, key = store.create("ci", "viewer")
    assert key.last_used_at is None

    store.verify(secret)

    assert store.get(key.id).last_used_at is not None
    assert ApiKeyStore().get(key.id).last_used_at is not None


def test_failed_verify_leaves_last_used_at_alone(store):
    secret, key = store.create("ci", "viewer")

    assert store.verify("zk_wrong") is None

    assert store.get(key.id).last_used_at is None


def test_disabled_key_does_not_verify_and_set_enabled_toggles_it(store):
    secret, key = store.create("ci", "viewer")

    assert store.set_enabled(key.id, False) is True
    assert store.verify(secret) is None

    assert store.set_enabled(key.id, True) is True
    assert store.verify(secret) is not None
    assert store.set_enabled("nao-existe", False) is False


def test_revoke_removes_the_key(store):
    secret, key = store.create("ci", "viewer")
    store.create("outra", "admin")

    assert store.revoke(key.id) is True
    assert store.verify(secret) is None
    assert store.get(key.id) is None
    assert [item.name for item in store.list()] == ["outra"]
    assert store.revoke(key.id) is False


def test_create_rejects_an_unknown_role(store):
    with pytest.raises(ValueError):
        store.create("ci", "root")

    assert not settings.api_keys_file.exists()


def test_corrupt_key_file_is_reported(store):
    settings.api_keys_file.write_text("{nao é json", encoding="utf-8")

    with pytest.raises(ValueError):
        store.list()


# ── credentials in headers ──


def test_extract_credential_reads_both_headers_case_insensitively():
    assert extract_credential({"authorization": "Bearer zk_abc"}) == "zk_abc"
    assert extract_credential({"Authorization": "bearer zk_abc"}) == "zk_abc"
    assert extract_credential({"X-API-Key": "zk_def"}) == "zk_def"
    assert extract_credential({"x-api-key": "zk_def"}) == "zk_def"
    assert extract_credential({"X-API-KEY": "zk_def"}) == "zk_def"
    assert extract_credential({"Authorization": "Bearer zk_abc", "X-API-Key": "zk_def"}) == "zk_abc"


def test_extract_credential_returns_none_when_absent():
    assert extract_credential(None) is None
    assert extract_credential({}) is None
    assert extract_credential({"X-API-Key": "   "}) is None
    assert extract_credential({"Authorization": "Basic zk_abc"}) is None


# ── authorisation ──


def test_authorize_allows_everything_while_auth_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)

    for action in ("read:jobs", "job:create", "key:manage"):
        decision = authorize(None, action)
        assert decision.allowed is True
        assert decision.actor == "anonymous"


def test_authorize_denies_requests_without_a_secret(store):
    decision = authorize(None, "read:jobs", store)

    assert decision.allowed is False
    assert decision.actor == "anonymous"


def test_authorize_denies_unknown_and_disabled_keys(store):
    secret, key = store.create("ci", "admin")

    assert authorize("zk_desconhecida", "read:jobs", store).allowed is False

    store.set_enabled(key.id, False)
    assert authorize(secret, "read:jobs", store).allowed is False


def test_viewer_reads_but_cannot_create_jobs(store):
    secret, _ = store.create("painel", "viewer")

    allowed = authorize(secret, "read:jobs", store)
    assert allowed.allowed is True
    assert allowed.actor == "painel"
    assert allowed.role == "viewer"

    denied = authorize(secret, "job:create", store)
    assert denied.allowed is False
    assert denied.role == "viewer"
    assert "viewer" in denied.reason


def test_operator_creates_and_cancels_jobs(store):
    secret, _ = store.create("runner", "operator")

    assert authorize(secret, "read:jobs", store).allowed is True
    assert authorize(secret, "job:create", store).allowed is True
    assert authorize(secret, "job:cancel", store).allowed is True
    assert authorize(secret, "key:manage", store).allowed is False


def test_admin_manages_keys_schedules_and_versions(store):
    secret, _ = store.create("chefe", "admin")

    assert authorize(secret, "key:manage", store).allowed is True
    assert authorize(secret, "schedule:manage", store).allowed is True
    assert authorize(secret, "version:manage", store).allowed is True


def test_denials_are_logged_with_actor_and_action(store, caplog):
    secret, _ = store.create("painel", "viewer")

    with caplog.at_level(logging.WARNING, logger="zfrog.auth"):
        authorize(None, "read:jobs", store)
        authorize(secret, "job:create", store)

    messages = [record.getMessage() for record in caplog.records]
    assert any("job:create" in message and "painel" in message for message in messages)
    assert any("read:jobs" in message and "anonymous" in message for message in messages)


# ── FastAPI dependency ──


def test_require_dependency_answers_401_and_403(store):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/jobs")
    def list_jobs(auth=Depends(require("read:jobs"))):
        return {"actor": auth.actor}

    @app.post("/jobs")
    def create_job(auth=Depends(require("job:create"))):
        return {"actor": auth.actor}

    client = TestClient(app)
    assert client.get("/jobs").status_code == 401

    secret, _ = store.create("painel", "viewer")
    headers = {"Authorization": f"Bearer {secret}"}
    assert client.get("/jobs", headers=headers).json() == {"actor": "painel"}
    assert client.post("/jobs", headers=headers).status_code == 403

    admin_secret, _ = store.create("chefe", "admin")
    assert client.post("/jobs", headers={"X-API-Key": admin_secret}).status_code == 200
