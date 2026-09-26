"""The WebSocket handshake: who may open a socket, and with what credential.

Two attacks shape this file:

* **Cross-Site WebSocket Hijacking.** A browser attaches cookies to a WebSocket
  handshake and sends no preflight, so without an `Origin` check any site a
  logged-in user visits could open a socket as them. The API's `Origin` allowlist
  has to be enforced here too.
* **Credential leakage into logs.** A browser cannot set headers on a WebSocket,
  which is why the dashboard used to pass `?api_key=`. A reverse proxy writes query
  strings to its access log, so that put live keys on disk. The subprotocol carries
  the key in a header instead.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from zfrog import api as api_module
from zfrog import websession
from zfrog.api import allowed_origins
from zfrog.auth import ApiKeyStore
from zfrog.config import settings
from zfrog.models import Job
from zfrog.users import UserStore
from zfrog.ws import WS_KEY_PREFIX, WS_SUBPROTOCOL

app = api_module.app


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "api_keys_file", tmp_path / "api_keys.json")
    monkeypatch.setattr(settings, "users_file", tmp_path / "users.json")
    monkeypatch.setattr(settings, "websession_key_file", tmp_path / "websession.key")
    monkeypatch.setattr(settings, "audit_log", tmp_path / "audit.log")
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "cors_origins", "*")


@pytest.fixture(autouse=True)
def _shared_job(monkeypatch):
    """A job in the shared area (no organization).

    The handshake refuses a job it cannot find, so every test about *how* a caller
    authenticates needs one to exist. Tests about workspace scoping or about a
    missing job override this with their own.
    """
    monkeypatch.setattr(
        "zfrog.orchestrator.get_job",
        lambda job_id: Job(id=job_id, url="https://x.example", mode="mirror"),
    )


def _rejected(client: TestClient, path: str, **kwargs) -> None:
    """Assert the handshake is refused before any event is sent."""
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(path, **kwargs):
            pass


# ── credentials ──

def test_an_api_key_in_a_subprotocol_opens_the_socket():
    """The script path, with the key in a header rather than the URL."""
    secret, _ = ApiKeyStore().create("runner", "viewer")

    with TestClient(app).websocket_connect(
        "/ws/jobs/job-1", subprotocols=[WS_SUBPROTOCOL, f"{WS_KEY_PREFIX}{secret}"]
    ) as socket:
        # The server must select one of the offered protocols, or a real browser
        # fails the connection outright.
        assert socket.accepted_subprotocol == WS_SUBPROTOCOL


def test_a_session_cookie_opens_the_socket():
    """The browser path: nothing in the URL, nothing readable by scripts."""
    user, _ = UserStore().create("ana@empresa.com", role="viewer")
    token = websession.issue(user.id)

    with TestClient(app).websocket_connect(
        "/ws/jobs/job-1", cookies={websession.SESSION_COOKIE: token}
    ):
        pass


def test_no_credential_is_refused():
    _rejected(TestClient(app), "/ws/jobs/job-1")


def test_a_forged_subprotocol_key_is_refused():
    _rejected(
        TestClient(app),
        "/ws/jobs/job-1",
        subprotocols=[WS_SUBPROTOCOL, f"{WS_KEY_PREFIX}zk_nao-existe"],
    )


def test_a_disabled_user_cannot_open_a_socket():
    user, _ = UserStore().create("ana@empresa.com", role="viewer")
    token = websession.issue(user.id)
    UserStore().set_enabled(user.id, False)

    _rejected(
        TestClient(app),
        "/ws/jobs/job-1",
        cookies={websession.SESSION_COOKIE: token},
    )


# ── origin (CSWSH) ──

def test_a_foreign_origin_is_refused_when_origins_are_pinned(monkeypatch):
    """A cookie is attached by the browser whatever site asked for the socket."""
    monkeypatch.setattr(settings, "cors_origins", "https://app.exemplo.com")
    user, _ = UserStore().create("ana@empresa.com", role="viewer")
    token = websession.issue(user.id)

    _rejected(
        TestClient(app),
        "/ws/jobs/job-1",
        headers={"Origin": "https://malicioso.example"},
        cookies={websession.SESSION_COOKIE: token},
    )


def test_the_configured_origin_is_accepted(monkeypatch):
    monkeypatch.setattr(settings, "cors_origins", "https://app.exemplo.com")
    user, _ = UserStore().create("ana@empresa.com", role="viewer")
    token = websession.issue(user.id)

    with TestClient(app).websocket_connect(
        "/ws/jobs/job-1",
        headers={"Origin": "https://app.exemplo.com"},
        cookies={websession.SESSION_COOKIE: token},
    ):
        pass


def test_the_default_wildcard_still_accepts_a_browser_origin(monkeypatch):
    """Local use must not break: CORS is open by default, and so is this."""
    monkeypatch.setattr(settings, "cors_origins", "*")
    user, _ = UserStore().create("ana@empresa.com", role="viewer")
    token = websession.issue(user.id)

    with TestClient(app).websocket_connect(
        "/ws/jobs/job-1",
        headers={"Origin": "http://localhost:3000"},
        cookies={websession.SESSION_COOKIE: token},
    ):
        pass


def test_a_client_without_an_origin_is_not_exempt_from_authenticating(monkeypatch):
    """A script sends no Origin; it still has to present a credential."""
    monkeypatch.setattr(settings, "cors_origins", "https://app.exemplo.com")

    _rejected(TestClient(app), "/ws/jobs/job-1")


def test_the_socket_and_the_http_api_share_one_origin_list(monkeypatch):
    """Two lists that could disagree is how a hole gets opened in one of them.

    Pinned behaviourally: for a given configuration, the origins the handshake
    accepts must be exactly what `allowed_origins` reports.
    """
    monkeypatch.setattr(
        settings, "cors_origins", "https://app.exemplo.com, https://admin.exemplo.com"
    )
    user, _ = UserStore().create("ana@empresa.com", role="viewer")
    token = websession.issue(user.id)
    client = TestClient(app)

    assert allowed_origins() == ["https://app.exemplo.com", "https://admin.exemplo.com"]

    for origin in ("https://app.exemplo.com", "https://admin.exemplo.com"):
        with client.websocket_connect(
            "/ws/jobs/job-1",
            headers={"Origin": origin},
            cookies={websession.SESSION_COOKIE: token},
        ):
            pass

    for origin in ("https://malicioso.example", "http://localhost:3000"):
        _rejected(
            client,
            "/ws/jobs/job-1",
            headers={"Origin": origin},
            cookies={websession.SESSION_COOKIE: token},
        )


# ── workspace scoping ──

def _job_in(org: str):
    return lambda job_id: Job(id=job_id, url="https://x.example", mode="mirror", org=org)


def test_a_session_cannot_watch_another_workspace(monkeypatch):
    monkeypatch.setattr("zfrog.orchestrator.get_job", _job_in("org-a"))
    user, _ = UserStore().create("ana@empresa.com", role="viewer", orgs=["org-b"])
    token = websession.issue(user.id)

    _rejected(
        TestClient(app),
        "/ws/jobs/job-de-org-a",
        cookies={websession.SESSION_COOKIE: token},
    )


def test_a_session_can_watch_its_own_workspace(monkeypatch):
    monkeypatch.setattr("zfrog.orchestrator.get_job", _job_in("org-a"))
    user, _ = UserStore().create("ana@empresa.com", role="viewer", orgs=["org-a"])
    token = websession.issue(user.id)

    with TestClient(app).websocket_connect(
        "/ws/jobs/job-de-org-a", cookies={websession.SESSION_COOKIE: token}
    ):
        pass


def test_a_key_scoped_to_one_org_cannot_watch_another(monkeypatch):
    monkeypatch.setattr("zfrog.orchestrator.get_job", _job_in("org-a"))
    secret, _ = ApiKeyStore().create("runner", "viewer", org="org-b")

    _rejected(
        TestClient(app),
        "/ws/jobs/job-de-org-a",
        subprotocols=[WS_SUBPROTOCOL, f"{WS_KEY_PREFIX}{secret}"],
    )


def test_an_unknown_job_is_refused_rather_than_streamed(monkeypatch):
    """Failing closed: a job we cannot find has no provable owner.

    This also covers the case where an unreachable Redis makes `get_job` fall back
    to per-process memory — failing open there would turn "unknown id" into
    "allowed", which is the one direction an authorisation check must not take.
    """
    monkeypatch.setattr("zfrog.orchestrator.get_job", lambda job_id: None)
    secret, _ = ApiKeyStore().create("runner", "viewer", org="org-b")

    _rejected(
        TestClient(app),
        "/ws/jobs/job-inexistente",
        subprotocols=[WS_SUBPROTOCOL, f"{WS_KEY_PREFIX}{secret}"],
    )


# ── the query string is gone ──

def test_the_api_key_is_never_accepted_from_the_query_string():
    """Regression: `?api_key=` put live keys in reverse-proxy access logs."""
    secret, _ = ApiKeyStore().create("runner", "viewer")

    _rejected(TestClient(app), f"/ws/jobs/job-1?api_key={secret}")
