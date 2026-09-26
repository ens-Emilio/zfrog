"""Tests for local accounts, organizations and password hashing."""

from __future__ import annotations

import logging
import stat

import pytest

from zfrog.config import settings
from zfrog.users import (
    OrgStore,
    UserStore,
    ensure_default_org,
    hash_password,
    normalize_email,
    redact,
    verify_password,
)

@pytest.fixture(autouse=True)
def _isolated_identity_files(tmp_path, monkeypatch):
    """Every test gets its own user and organization files."""
    monkeypatch.setattr(settings, "users_file", tmp_path / "users.json")
    monkeypatch.setattr(settings, "orgs_file", tmp_path / "orgs.json")
    monkeypatch.setattr(settings, "default_org", "default")

@pytest.fixture
def users():
    return UserStore()

@pytest.fixture
def orgs():
    return OrgStore()

# ── password hashing ──

def test_hash_password_is_pbkdf2_with_a_fresh_salt():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first.startswith("pbkdf2$200000$")
    assert first != second, "o sal deve ser aleatório a cada chamada"
    assert first.split("$")[2] != second.split("$")[2]

def test_verify_password_accepts_the_right_one_and_rejects_the_rest():
    stored = hash_password("s3cret-password")

    assert verify_password("s3cret-password", stored) is True
    assert verify_password("s3cret-passwore", stored) is False
    assert verify_password("", stored) is False

def test_verify_password_returns_false_for_garbage_instead_of_raising():
    for broken in ("garbage", "", "pbkdf2$notanint$aa$bb", "pbkdf2$200000$zz$bb", "a$b$c"):
        assert verify_password("anything", broken) is False

def test_normalize_email_lowercases_and_trims():
    assert normalize_email("  Alice@Example.COM ") == "alice@example.com"

# ── user creation ──

def test_create_rejects_a_duplicate_email(users):
    users.create("ana@example.com", password="uma-senha")

    with pytest.raises(ValueError):
        users.create("Ana@Example.com", password="outra-senha")

def test_create_rejects_an_unknown_role(users):
    with pytest.raises(ValueError):
        users.create("ana@example.com", role="root", password="x")

    assert users.list() == []

def test_create_without_a_password_returns_an_empty_secret(users):
    user, secret = users.create("sso@example.com", name="SSO")

    assert secret == ""
    assert user.password_hash == ""
    assert user.enabled is True

def test_create_with_a_password_returns_it_once_and_stores_only_the_hash(users):
    user, secret = users.create("local@example.com", password="v3ry-secret")

    assert secret == "v3ry-secret"
    assert user.password_hash.startswith("pbkdf2$")
    assert verify_password("v3ry-secret", user.password_hash) is True

# ── authentication ──

def test_authenticate_accepts_the_right_password(users):
    user, _ = users.create("ana@example.com", password="uma-senha")

    found = users.authenticate("ANA@example.com", "uma-senha")

    assert found is not None
    assert found.id == user.id

def test_authenticate_rejects_a_wrong_password(users):
    users.create("ana@example.com", password="uma-senha")

    assert users.authenticate("ana@example.com", "outra-senha") is None
    assert users.authenticate("ninguem@example.com", "uma-senha") is None

def test_authenticate_rejects_a_disabled_user(users):
    user, _ = users.create("ana@example.com", password="uma-senha")
    assert users.set_enabled(user.id, False) is True

    assert users.authenticate("ana@example.com", "uma-senha") is None

def test_authenticate_rejects_an_sso_only_user(users):
    users.create("sso@example.com")

    assert users.authenticate("sso@example.com", "") is None
    assert users.authenticate("sso@example.com", "qualquer") is None

# ── sso upsert ──

def test_upsert_sso_user_is_idempotent_for_the_same_subject(users):
    first = users.upsert_sso_user("sub-1", "ana@example.com", name="Ana")
    second = users.upsert_sso_user("sub-1", "ana@example.com", name="Ana")

    assert first.id == second.id
    assert len(users.list()) == 1

def test_upsert_sso_user_links_an_existing_local_account_by_email(users):
    local, _ = users.create("ana@example.com", password="uma-senha", role="operator")

    linked = users.upsert_sso_user("sub-9", "ANA@example.com", name="Ana")

    assert linked.id == local.id
    assert linked.password_hash == local.password_hash
    assert linked.role == "operator"
    assert len(users.list()) == 1
    assert users.by_sso_subject("sub-9") is not None

def test_upsert_sso_user_creates_a_new_account_when_nothing_matches(users):
    created = users.upsert_sso_user("sub-2", "novo@example.com", name="Novo", role="admin")

    assert created.sso_subject == "sub-2"
    assert created.role == "admin"
    assert created.password_hash == ""

# ── lookups, updates, deletion ──

def test_by_email_and_by_sso_subject_find_what_was_created(users):
    ana, _ = users.create("ana@example.com", password="uma-senha")
    bob = users.upsert_sso_user("sub-bob", "bob@example.com")

    assert users.by_email("  ANA@example.com ").id == ana.id
    assert users.by_email("ninguem@example.com") is None
    assert users.by_sso_subject("sub-bob").id == bob.id
    assert users.by_sso_subject("sub-unknown") is None
    assert users.get(ana.id).email == "ana@example.com"

def test_list_reflects_set_enabled_and_delete(users):
    ana, _ = users.create("ana@example.com", password="uma-senha")
    bob, _ = users.create("bob@example.com", password="uma-senha")

    assert users.set_enabled(ana.id, False) is True
    assert users.set_enabled("nao-existe", False) is False
    assert [user.id for user in users.list()] == [ana.id, bob.id]
    assert users.get(ana.id).enabled is False

    assert users.delete(ana.id) is True
    assert users.delete(ana.id) is False
    assert [user.id for user in users.list()] == [bob.id]

def test_update_persists_a_mutated_copy(users):
    user, _ = users.create("ana@example.com", password="uma-senha")
    user.name = "Ana Silva"
    user.orgs = ["acme"]

    users.update(user)

    assert users.get(user.id).name == "Ana Silva"
    assert users.get(user.id).orgs == ["acme"]

    user.id = "desconhecido"
    with pytest.raises(ValueError):
        users.update(user)

def test_users_file_is_owner_only_and_never_holds_the_plaintext(users):
    user, _ = users.create("ana@example.com", password="plaintext-senha")

    mode = stat.S_IMODE(settings.users_file.stat().st_mode)
    assert mode == 0o600

    raw = settings.users_file.read_bytes()
    assert b"plaintext-senha" not in raw
    assert user.password_hash.encode() in raw

def test_a_corrupt_users_file_starts_empty_with_a_warning(users, caplog):
    settings.users_file.write_text("{ isto não é json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert users.list() == []

    assert "corrompido" in caplog.text

# ── redaction ──

def test_redact_drops_the_password_hash(users):
    user, _ = users.create("ana@example.com", password="uma-senha")

    payload = redact(user)

    assert "password_hash" not in payload
    assert payload["email"] == "ana@example.com"
    assert payload["role"] == "viewer"
    assert payload["enabled"] is True

# ── organizations ──

def test_org_create_slugifies_the_name_and_rejects_a_duplicate(orgs):
    org = orgs.create("Acme Corp.", "user-1")

    assert org.id == "acme-corp"
    assert org.name == "Acme Corp."
    assert org.owner == "user-1"
    assert org.members == {"user-1": "admin"}

    with pytest.raises(ValueError):
        orgs.create("Acme Corp.", "user-2")
    with pytest.raises(ValueError):
        orgs.create("outro", "user-2", org_id="acme-corp")

def test_org_membership_round_trips(orgs):
    org = orgs.create("Acme Corp", "user-1")

    orgs.add_member(org.id, "user-2", "operator")
    assert orgs.role_of(org.id, "user-2") == "operator"
    assert orgs.role_of(org.id, "user-1") == "admin"
    assert orgs.orgs_for("user-2") == ["acme-corp"]
    assert orgs.orgs_for("user-1") == ["acme-corp"]

    orgs.remove_member(org.id, "user-2")
    assert orgs.role_of(org.id, "user-2") is None
    assert orgs.orgs_for("user-2") == []

    assert orgs.remove_member(org.id, "user-2").id == "acme-corp"

def test_org_lookup_and_delete(orgs):
    acme = orgs.create("Acme", "user-1")
    globex = orgs.create("Globex", "user-2")

    assert [org.id for org in orgs.list()] == [acme.id, globex.id]
    assert orgs.get("globex").owner == "user-2"
    assert orgs.get("nao-existe") is None
    assert orgs.role_of("nao-existe", "user-1") is None
    assert orgs.orgs_for("") == []

    assert orgs.delete("globex") is True
    assert orgs.delete("globex") is False
    assert [org.id for org in orgs.list()] == [acme.id]

def test_add_member_on_an_unknown_org_raises(orgs):
    with pytest.raises(ValueError):
        orgs.add_member("nao-existe", "user-1")

    with pytest.raises(ValueError):
        orgs.remove_member("nao-existe", "user-1")

def test_orgs_file_is_owner_only(orgs):
    orgs.create("Acme", "user-1")

    assert stat.S_IMODE(settings.orgs_file.stat().st_mode) == 0o600

def test_ensure_default_org_is_idempotent(orgs):
    first = ensure_default_org(orgs, "user-1")
    second = ensure_default_org(orgs, "user-2")

    assert first.id == "default"
    assert second.id == first.id
    assert len(orgs.list()) == 1
    assert orgs.orgs_for("user-1") == ["default"]

def test_ensure_default_org_keeps_an_existing_one(orgs):
    existing = orgs.create("Default", "user-1", org_id="default")

    assert ensure_default_org(orgs, "user-2").owner == existing.owner
    assert len(orgs.list()) == 1
