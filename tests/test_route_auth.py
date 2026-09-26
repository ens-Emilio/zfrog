"""Every route that changes something must demand a credential.

The failure this guards against is a new endpoint forgetting its auth
dependency. Nothing about `@app.post(...)` reminds you, and the route works
perfectly in the default `auth_enabled = false` setup — so the omission only
shows up on a public deployment, as an open door nobody notices.

These tests read the real route table instead of a hand-kept list, so the
invariant cannot drift. `auth_dependency()` stamps the action it enforces onto
the closure it returns (`zfrog_action`); that is what makes the table readable
from here.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from zfrog import api as api_module
from zfrog.auth import ApiKeyStore
from zfrog.config import settings

app = api_module.app

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Reachable with no credential, each because it has to be. Every entry is a GET
# or one of FastAPI's own schema routes, and
# `test_the_public_allowlist_cannot_hide_a_mutating_route` keeps it that way so
# this mapping can never be used to silence the invariant below.
PUBLIC = {
    "/": "service banner, no data",
    "/health": "container healthcheck and uptime probes",
    "/auth/config": "the login flow must be discoverable before anyone logs in",
    "/auth/login": "starts the login flow",
    "/auth/callback": "finishes the login flow, called by the identity provider",
}

# Mutating routes that are open on purpose. Kept separate from PUBLIC so the
# GET-only allowlist above cannot be used to smuggle a POST past the invariant:
# anything landing here has to be argued for on its own line.
PUBLIC_MUTATING = {
    "/auth/logout": (
        "expires the caller's own session cookie and nothing else. Requiring a "
        "credential to log out would trap anyone whose cookie is already invalid, "
        "and SameSite=Lax already blocks the cross-site POST that would turn this "
        "into a forced logout"
    ),
}


def _docs_paths() -> set[str]:
    """FastAPI's own schema routes, read from the app rather than assumed.

    Hardcoding them would make this file fail on a FastAPI upgrade that renames
    one, which says nothing about whether an endpoint lost its auth.
    """
    return {
        path
        for path in (
            app.openapi_url,
            app.docs_url,
            app.redoc_url,
            app.swagger_ui_oauth2_redirect_url,
        )
        if path
    }


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Auth enforced, with every file it touches inside tmp_path."""
    monkeypatch.setattr(settings, "api_keys_file", tmp_path / "api_keys.json")
    monkeypatch.setattr(settings, "audit_log", tmp_path / "audit.log")
    monkeypatch.setattr(settings, "sessions_dir", tmp_path / "sessions")
    monkeypatch.setattr(settings, "auth_enabled", True)


def _routes() -> list[APIRoute]:
    return [route for route in app.routes if isinstance(route, APIRoute)]


def _route(method: str, path: str) -> APIRoute | None:
    for route in _routes():
        if route.path == path and method in route.methods:
            return route
    return None


def _required_action(route: APIRoute) -> str | None:
    """The action this route enforces, or None when it enforces nothing."""

    def walk(dependant) -> str | None:
        for dep in dependant.dependencies:
            action = getattr(dep.call, "zfrog_action", None)
            if action:
                return action
            nested = walk(dep)
            if nested:
                return nested
        return None

    return walk(route.dependant)


def test_every_route_is_either_protected_or_declared_public():
    """The stronger invariant: no route is *silently* open.

    The mutating check below would miss a new `GET /export-all` that returned
    everyone's clones. This one does not care what the route does — it only
    insists the decision was made on purpose, by naming the route in PUBLIC or
    PUBLIC_MUTATING.
    """
    exempt = set(PUBLIC) | set(PUBLIC_MUTATING) | _docs_paths()

    open_routes = []
    for route in _routes():
        if route.path in exempt or _required_action(route) is not None:
            continue
        methods = sorted(route.methods - {"HEAD", "OPTIONS"})
        open_routes.append(f"{'/'.join(methods)} {route.path}")

    assert not open_routes, (
        "rotas sem credencial e sem justificativa: "
        + ", ".join(sorted(open_routes))
        + " — adicione auth_dependency(...) ou declare em PUBLIC por quê"
    )


def test_every_mutating_route_requires_a_credential():
    """A new unprotected POST fails here, not in production."""
    exempt = set(PUBLIC) | set(PUBLIC_MUTATING) | _docs_paths()

    missing = []
    for route in _routes():
        if not (route.methods & MUTATING) or route.path in exempt:
            continue
        if _required_action(route) is None:
            missing.append(f"{sorted(route.methods & MUTATING)[0]} {route.path}")

    assert not missing, (
        "rotas que mudam estado sem exigir credencial: "
        + ", ".join(sorted(missing))
        + " — adicione auth_dependency(...) ou justifique em PUBLIC_MUTATING"
    )


def test_the_public_allowlist_cannot_hide_a_mutating_route():
    """Otherwise adding a path to PUBLIC would silence the invariant above.

    A mutating route has to go through PUBLIC_MUTATING, where it needs its own
    written justification — this is what keeps that list from growing by habit.
    """
    for path in PUBLIC:
        for route in _routes():
            if route.path == path:
                assert not (route.methods & MUTATING), (
                    f"{path} está em PUBLIC e muda estado: {route.methods} — "
                    "mova para PUBLIC_MUTATING com justificativa"
                )


def test_the_mutating_allowlist_is_justified_and_not_empty():
    """Each open mutating route must say why, in words."""
    for path, reason in PUBLIC_MUTATING.items():
        assert reason.strip(), f"{path} está em PUBLIC_MUTATING sem justificativa"

    known = {route.path for route in _routes()}
    assert sorted(set(PUBLIC_MUTATING) - known) == []


def test_the_public_allowlist_has_no_stale_path():
    """A recycled path must not inherit an exemption meant for something else."""
    known = {route.path for route in _routes()}
    assert sorted(set(PUBLIC) - known) == []


# The routes whose privilege was a judgement call, pinned so a later edit cannot
# quietly downgrade them: `read:jobs` on any of these would hand a viewer the
# ability to publish a clone or delete someone's session.
REQUIRED_ACTIONS = {
    ("POST", "/ipfs/publish"): api_module.ACTION_ADMIN,
    ("POST", "/webhooks"): api_module.ACTION_ADMIN,
    ("DELETE", "/webhooks/{webhook_id}"): api_module.ACTION_ADMIN,
    ("DELETE", "/sessions/{domain}"): api_module.ACTION_ADMIN,
    ("POST", "/config/rate-limit"): api_module.ACTION_ADMIN,
    ("POST", "/watermark"): api_module.ACTION_VERSION_MANAGE,
    ("POST", "/extract/preview"): api_module.ACTION_READ,
}


@pytest.mark.parametrize(
    "method,path,action",
    [pytest.param(method, path, action, id=f"{method} {path}")
     for (method, path), action in REQUIRED_ACTIONS.items()],
)
def test_the_privilege_is_the_intended_one(method, path, action):
    route = _route(method, path)
    assert route is not None, f"{method} {path} não existe mais: atualize a tabela"

    assert _required_action(route) == action


# An admin-only route, with a body that cannot do damage even if the guard were
# missing: a directory that does not exist fails on its own.
ADMIN_ONLY = (
    ("POST", "/webhooks", {"url": "http://example.invalid/hook", "events": ["job.completed"]}),
    ("DELETE", "/webhooks/nao-existe", None),
    ("POST", "/config/rate-limit", {"requests_per_second": 1.0}),
    ("POST", "/ipfs/publish", {"dir": "/tmp/zfrog-nao-existe"}),
    ("POST", "/watermark", {"dir": "/tmp/zfrog-nao-existe"}),
    ("DELETE", "/sessions/example.invalid", None),
)


@pytest.mark.parametrize(
    "method,path,body",
    [pytest.param(m, p, b, id=f"{m} {p}") for m, p, b in ADMIN_ONLY],
)
def test_an_admin_only_route_rejects_anonymous_and_viewer(method, path, body):
    """End-to-end: the guard runs before the handler, whatever the body says.

    Introspection alone would still pass if someone made the dependency a no-op,
    so this exercises the real request path. A body is supplied anyway, so a
    rejection cannot be mistaken for a validation error.
    """
    client = TestClient(app)
    request = {"json": body} if body is not None else {}

    anonymous = client.request(method, path, **request)
    assert anonymous.status_code == 401, f"{method} {path}: {anonymous.text}"

    viewer_secret, _ = ApiKeyStore().create("leitor", "viewer")
    headers = {"Authorization": f"Bearer {viewer_secret}"}

    viewer = client.request(method, path, headers=headers, **request)
    assert viewer.status_code == 403, f"{method} {path}: {viewer.text}"


def test_a_viewer_can_still_use_the_read_only_preview():
    """The fix must not lock the dashboard out of its own selector preview."""
    viewer_secret, _ = ApiKeyStore().create("leitor", "viewer")

    response = TestClient(app).post(
        "/extract/preview",
        json={"url": "http://127.0.0.1:9/", "selector": "h1"},
        headers={"Authorization": f"Bearer {viewer_secret}"},
    )

    # The guard lets the viewer through; the fetch then fails on its own.
    assert response.status_code == 400


# ── WebSockets ──

# A socket guards its handshake inside `zfrog/ws.py`, where the dependency walk
# above cannot see it. Pinning the set means a new socket has to be added here,
# with a thought about who may connect.
WEBSOCKET_ROUTES = {"/ws/jobs/{job_id}"}


def test_every_websocket_route_is_accounted_for():
    found = {route.path for route in app.routes if isinstance(route, APIWebSocketRoute)}

    assert found == WEBSOCKET_ROUTES


def test_the_websocket_refuses_the_handshake_without_a_credential():
    """Rejection happens before `accept()`, so no event is ever streamed."""
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/jobs/qualquer-um"):
            pass


def test_the_websocket_refuses_a_job_from_another_workspace(monkeypatch):
    """A valid key must not read another organization's job by guessing its id."""
    from zfrog.models import Job

    monkeypatch.setattr(
        "zfrog.orchestrator.get_job",
        lambda job_id: Job(id=job_id, url="https://x.example", mode="mirror", org="org-a"),
    )
    secret, _ = ApiKeyStore().create("outra", "viewer", org="org-b")

    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect(
            "/ws/jobs/job-da-org-a", headers={"Authorization": f"Bearer {secret}"}
        ):
            pass

