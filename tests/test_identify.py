"""Who the caller is, when two kinds of credential can say so.

`identify` is the single place that resolves an API key or a dashboard session
cookie into one notion of a caller. The tests here pin the properties the rest of
the API now relies on: that a cookie is not trusted for role or organization, that
a disabled user stops being recognised, and that a browser carrying both kinds of
credential is treated as the more explicit one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from zfrog import api as api_module
from zfrog import websession
from zfrog.auth import ApiKeyStore, authorize_request, identify
from zfrog.config import settings
from zfrog.users import UserStore

app = api_module.app


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "api_keys_file", tmp_path / "api_keys.json")
    monkeypatch.setattr(settings, "users_file", tmp_path / "users.json")
    monkeypatch.setattr(settings, "websession_key_file", tmp_path / "websession.key")
    monkeypatch.setattr(settings, "audit_log", tmp_path / "audit.log")
    monkeypatch.setattr(settings, "auth_enabled", True)


def _session_cookie_for(user_id: str) -> dict[str, str]:
    token = websession.issue(user_id)
    assert token is not None
    return {websession.SESSION_COOKIE: token}


# ── identify ──

def test_an_api_key_is_recognised_with_its_role_and_org():
    secret, _ = ApiKeyStore().create("runner", "operator", org="acme")

    identity = identify({"Authorization": f"Bearer {secret}"})

    assert identity is not None
    assert identity.actor == "runner"
    assert identity.role == "operator"
    assert identity.org == "acme"
    assert identity.via == "key"


def test_a_session_cookie_is_recognised_from_the_user_store():
    user, _ = UserStore().create("ana@empresa.com", name="Ana", role="admin")

    identity = identify({}, _session_cookie_for(user.id))

    assert identity is not None
    assert identity.actor == "ana@empresa.com"
    assert identity.role == "admin"
    assert identity.via == "session"


def test_the_cookie_carries_no_authority_of_its_own():
    """Role and org come from the store, so a role change applies immediately.

    The token is signed but not encrypted, so a hand-edited payload is worth
    testing: even a validly signed one must not be believed about the role.
    """
    user, _ = UserStore().create("ana@empresa.com", role="viewer")
    cookie = _session_cookie_for(user.id)

    # Promote in the store: the same cookie must now be admin.
    store = UserStore()
    promoted = store.get(user.id)
    assert promoted is not None
    promoted.role = "admin"
    store.update(promoted)

    identity = identify({}, cookie)
    assert identity is not None
    assert identity.role == "admin"


def test_a_disabled_user_stops_being_recognised():
    """Revocation must not wait for the cookie to expire."""
    user, _ = UserStore().create("ana@empresa.com", role="admin")
    cookie = _session_cookie_for(user.id)

    UserStore().set_enabled(user.id, False)

    assert identify({}, cookie) is None


def test_an_api_key_wins_when_a_browser_carries_both():
    """The explicit header is the more deliberate credential."""
    secret, _ = ApiKeyStore().create("script", "operator")
    user, _ = UserStore().create("ana@empresa.com", role="viewer")

    identity = identify({"Authorization": f"Bearer {secret}"}, _session_cookie_for(user.id))

    assert identity is not None and identity.via == "key"


def test_an_unknown_user_id_in_a_valid_cookie_is_not_a_caller():
    """A token signed for a user that was since deleted must not authenticate."""
    assert identify({}, _session_cookie_for("usuario-que-nao-existe")) is None


def test_no_credential_at_all_identifies_nobody():
    assert identify({}, {}) is None
    assert identify(None, None) is None


# ── authorize_request ──

def test_a_session_is_held_to_the_same_role_matrix_as_a_key():
    user, _ = UserStore().create("ana@empresa.com", role="viewer")
    cookie = _session_cookie_for(user.id)

    assert authorize_request({}, cookie, "read:jobs").allowed is True

    denied = authorize_request({}, cookie, "admin:all")
    assert denied.allowed is False
    assert denied.role == "viewer"
    assert denied.via == "session"


def test_a_disabled_auth_setup_allows_everything_as_before(monkeypatch):
    """The default local posture must not change."""
    monkeypatch.setattr(settings, "auth_enabled", False)

    decision = authorize_request({}, {}, "admin:all")

    assert decision.allowed is True
    assert decision.actor == "anonymous"


def test_a_missing_credential_is_denied_when_auth_is_on():
    decision = authorize_request({}, {}, "read:jobs")

    assert decision.allowed is False
    assert decision.role == ""


# ── through the API ──

def test_the_session_cookie_alone_opens_a_protected_route():
    """The whole point: no API key in the browser, and the dashboard still works."""
    user, _ = UserStore().create("ana@empresa.com", role="operator")

    response = TestClient(app).get("/config", cookies=_session_cookie_for(user.id))

    assert response.status_code == 200


def test_a_viewer_session_cannot_reach_an_admin_route():
    user, _ = UserStore().create("ana@empresa.com", role="viewer")

    response = TestClient(app).post(
        "/config/rate-limit",
        json={"requests_per_second": 1.0},
        cookies=_session_cookie_for(user.id),
    )

    assert response.status_code == 403


def test_the_organization_of_a_session_scopes_its_workspace():
    """A session must land in its user's organization, not the shared area."""
    user, _ = UserStore().create("ana@empresa.com", role="operator", orgs=["acme"])

    response = TestClient(app).get("/workspace", cookies=_session_cookie_for(user.id))

    assert response.status_code == 200
    assert response.json()["org"] == "acme"
    assert response.json()["shared"] is False


def test_logout_expires_the_cookie_without_needing_a_credential():
    response = TestClient(app).post("/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"signed_out": True}
    assert websession.SESSION_COOKIE in response.headers["set-cookie"]


def test_a_tampered_session_cookie_does_not_authenticate():
    user, _ = UserStore().create("ana@empresa.com", role="admin")
    cookie = _session_cookie_for(user.id)

    forged = {websession.SESSION_COOKIE: cookie[websession.SESSION_COOKIE].split(".")[0] + ".x.y"}
    response = TestClient(app).get("/config", cookies=forged)

    assert response.status_code == 401
