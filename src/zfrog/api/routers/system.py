"""API router: system."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request

from zfrog.api._shared import (
    ACTION_ADMIN,
    ACTION_KEY_MANAGE,
    ACTION_READ,
    AnnotationRequest,
    AnnotationUpdateRequest,
    DestinationRequest,
    DomainRequest,
    HeartbeatRequest,
    KeyRequest,
    MemberRequest,
    OrgRequest,
    ReplyRequest,
    UserRequest,
    WorkerRequest,
    _audit,
    _consume_login,
    _purge_expired_logins,
    _remember_login,
    _scoped,
    auth_dependency,
)  # noqa: F401
from zfrog.auth import AuthDecision
from zfrog.config import settings

router = APIRouter()

@router.get("/keys")
async def list_keys(
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List API keys (never the secret)."""
    from dataclasses import asdict

    from zfrog.auth import ApiKeyStore

    keys = []
    for key in ApiKeyStore().list():
        payload = asdict(key)
        payload.pop("hash", None)
        keys.append(payload)
    return keys

@router.post("/keys")
async def create_key(request: KeyRequest, http_request: Request,
                     auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """Create an API key; the secret is returned once."""
    from dataclasses import asdict

    from zfrog.auth import ApiKeyStore

    try:
        secret, key = ApiKeyStore().create(request.name, request.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    payload = asdict(key)
    payload.pop("hash", None)
    _audit(http_request, "key.create", target=key.id, role=key.role)
    return {"secret": secret, "key": payload}

@router.delete("/keys/{key_id}")
async def revoke_key(key_id: str, request: Request,
                     auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """Revoke an API key."""
    from zfrog.auth import ApiKeyStore

    if not ApiKeyStore().revoke(key_id):
        raise HTTPException(status_code=404, detail="Key not found")

    _audit(request, "key.revoke", target=key_id)
    return {"removed": key_id}

@router.get("/integrations")
async def list_destinations(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List outbound destinations (tokens redacted)."""
    from zfrog.integrations.base import DestinationStore, redact

    return [
        {"kind": d.kind, "name": d.name, **redact(d)} for d in DestinationStore(root=_scoped(request, "integrations_dir")).list()
    ]

@router.post("/integrations")
async def save_destination(request: DestinationRequest, http_request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Create or replace an outbound destination."""
    from zfrog.integrations.base import Destination, DestinationStore

    destination = Destination(kind=request.kind, name=request.name, config=request.config)
    DestinationStore(root=_scoped(http_request, "integrations_dir")).save(destination)
    _audit(http_request, "integration.save", target=request.name, kind=request.kind)
    return {"kind": destination.kind, "name": destination.name}

@router.delete("/integrations/{name}")
async def delete_destination(name: str, request: Request,
                             auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Delete an outbound destination."""
    from zfrog.integrations.base import DestinationStore

    if not DestinationStore(root=_scoped(request, "integrations_dir")).remove(name):
        raise HTTPException(status_code=404, detail="Destination not found")

    _audit(request, "integration.delete", target=name)
    return {"removed": name}

@router.post("/integrations/{name}/push")
async def push_to_destination(name: str, payload: dict, request: Request,
                              auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Send records to a destination."""
    from zfrog.integrations.base import DestinationStore, client_for

    destination = DestinationStore(root=_scoped(request, "integrations_dir")).get(name)
    if destination is None:
        raise HTTPException(status_code=404, detail="Destination not found")

    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="'rows' must be a list of records")

    _audit(request, "integration.push", target=name, rows=len(rows))
    result = await client_for(destination).push(destination, rows)
    return asdict(result)

@router.get("/regions")
async def list_regions(url: str | None = None,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """List known regions and, for a URL, which one would process it."""
    from zfrog.regions import data_residency_note, known_regions, route

    available = known_regions()
    payload: dict = {"current": settings.region, "regions": [asdict(r) for r in available]}
    if url:
        decision = route(url, available)
        payload["decision"] = {
            "region": decision.region,
            "reason": decision.reason,
            "note": data_residency_note(url, decision.region),
        }
    return payload

@router.get("/users")
async def list_users(auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """List users (never the password hash)."""
    from zfrog.users import UserStore, redact

    return [redact(user) for user in UserStore().list()]

@router.post("/users")
async def create_user(request: UserRequest, http_request: Request,
                      auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """Create a local user."""
    from zfrog.users import UserStore, redact

    try:
        user, password = UserStore().create(
            request.email,
            name=request.name,
            role=request.role,
            password=request.password,
            orgs=request.orgs,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(http_request, "user.create", target=user.email, role=user.role)
    return {"user": redact(user), "password": password}

@router.get("/orgs")
async def list_orgs(auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """List organizations and whether they have data."""
    from dataclasses import asdict

    from zfrog.users import OrgStore
    from zfrog.workspaces import WorkspaceManager

    manager = WorkspaceManager()
    return [
        {**asdict(org), "has_data": manager.exists(org.id)} for org in OrgStore().list()
    ]

@router.post("/orgs")
async def create_org(request: OrgRequest, http_request: Request,
                     auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Create an organization."""
    from dataclasses import asdict

    from zfrog.users import OrgStore

    try:
        org = OrgStore().create(request.name, request.owner)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(http_request, "org.create", target=org.id, owner=request.owner)
    return asdict(org)

@router.post("/orgs/{org_id}/members")
async def add_org_member(org_id: str, request: MemberRequest, http_request: Request,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Add a user to an organization."""
    from dataclasses import asdict

    from zfrog.users import add_member

    try:
        org = add_member(org_id, request.user_id, request.role)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    _audit(http_request, "org.member.add", target=org_id, user=request.user_id, role=request.role)
    return asdict(org)

@router.get("/annotations")
async def list_annotations(request: Request, job_id: str | None = None, resolved: bool | None = None,
                           author: str | None = None, tag: str | None = None,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """List comments on cloned pages."""
    from dataclasses import asdict

    from zfrog.annotations import AnnotationStore

    notes = AnnotationStore(root=_scoped(request, "annotations_dir")).list(job_id=job_id, resolved=resolved, author=author, tag=tag)
    return [asdict(note) for note in notes]

@router.post("/annotations")
async def create_annotation(request: AnnotationRequest, http_request: Request,
                            auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Leave a comment on a cloned page."""
    from dataclasses import asdict

    from zfrog.annotations import AnnotationStore

    try:
        note = AnnotationStore(root=_scoped(http_request, "annotations_dir")).add(
            request.job_id,
            request.path,
            request.text,
            author=request.author,
            selector=request.selector,
            tags=request.tags,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(http_request, "annotation.create", target=f"{request.job_id}:{request.path}")
    return asdict(note)

@router.patch("/annotations/{annotation_id}")
async def update_annotation(annotation_id: str, request: AnnotationUpdateRequest,
                            http_request: Request,
                            auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Edit a comment."""
    from dataclasses import asdict

    from zfrog.annotations import AnnotationStore

    try:
        note = AnnotationStore(root=_scoped(http_request, "annotations_dir")).update(
            annotation_id, text=request.text, selector=request.selector, tags=request.tags
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    _audit(http_request, "annotation.update", target=annotation_id)
    return asdict(note)

@router.post("/annotations/{annotation_id}/resolve")
async def resolve_annotation(annotation_id: str, http_request: Request,
                             resolved: bool = True,
                             auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Mark a comment as resolved (or reopen it)."""
    from dataclasses import asdict

    from zfrog.annotations import AnnotationStore

    try:
        note = AnnotationStore(root=_scoped(http_request, "annotations_dir")).resolve(annotation_id, resolved)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    _audit(http_request, "annotation.resolve", target=annotation_id, resolved=resolved)
    return asdict(note)

@router.post("/annotations/{annotation_id}/replies")
async def reply_annotation(annotation_id: str, request: ReplyRequest, http_request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Reply to a comment."""
    from dataclasses import asdict

    from zfrog.annotations import AnnotationStore

    try:
        note = AnnotationStore(root=_scoped(http_request, "annotations_dir")).reply(annotation_id, request.text, request.author)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    _audit(http_request, "annotation.reply", target=annotation_id)
    return asdict(note)

@router.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str, request: Request,
                            auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Delete a comment."""
    from zfrog.annotations import AnnotationStore

    if not AnnotationStore(root=_scoped(request, "annotations_dir")).remove(annotation_id):
        raise HTTPException(status_code=404, detail="Annotation not found")

    _audit(request, "annotation.delete", target=annotation_id)
    return {"removed": annotation_id}

@router.get("/annotations/export")
async def export_annotations(request: Request, job_id: str,
                             auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Export a clone's comments as Markdown."""
    from zfrog.annotations import AnnotationStore, export_markdown

    notes = AnnotationStore(root=_scoped(request, "annotations_dir")).list(job_id=job_id)
    return {"job_id": job_id, "markdown": export_markdown(notes, job_id)}

@router.get("/domains")
async def list_domains(request: Request, auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """List saved and built-in domain profiles."""
    from dataclasses import asdict

    from zfrog.ai.domains import DomainProfileStore

    store = DomainProfileStore(root=_scoped(request, "domains_dir"))
    return {
        "saved": [asdict(profile) for profile in store.list()],
        "builtin": [asdict(profile) for profile in store.builtin()],
    }

@router.post("/domains")
async def save_domain(request: DomainRequest, http_request: Request,
                      auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Save a domain profile."""
    from dataclasses import asdict

    from zfrog.ai.domains import DomainProfileStore

    try:
        profile = DomainProfileStore(root=_scoped(http_request, "domains_dir")).save(request.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(http_request, "domain.save", target=profile.id)
    return asdict(profile)

@router.delete("/domains/{profile_id}")
async def delete_domain(profile_id: str, request: Request,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Delete a saved domain profile."""
    from zfrog.ai.domains import DomainProfileStore

    if not DomainProfileStore(root=_scoped(request, "domains_dir")).remove(profile_id):
        raise HTTPException(status_code=404, detail="Domain profile not found")

    _audit(request, "domain.delete", target=profile_id)
    return {"removed": profile_id}

@router.get("/workers")
async def list_workers(region: str | None = None,
                       auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """List registered workers."""
    from dataclasses import asdict

    from zfrog.workers import WorkerRegistry

    registry = WorkerRegistry()
    registry.reap()
    return {
        "stats": registry.stats(),
        "workers": [
            {**asdict(worker), "alive": registry.alive(worker.id)}
            for worker in registry.list(region=region, alive_only=False)
        ],
    }

@router.post("/workers")
async def register_worker(request: WorkerRequest, http_request: Request,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Register a worker."""
    from dataclasses import asdict

    from zfrog.workers import WorkerRegistry

    worker = WorkerRegistry().register(
        request.worker_id,
        request.region,
        capacity=request.capacity,
        version=request.version,
        tags=request.tags,
    )
    _audit(http_request, "worker.register", target=request.worker_id, region=request.region)
    return asdict(worker)

@router.post("/workers/heartbeat")
async def worker_heartbeat(request: HeartbeatRequest,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Record a worker heartbeat."""
    from dataclasses import asdict

    from zfrog.workers import WorkerRegistry

    try:
        worker = WorkerRegistry().heartbeat(request.worker_id, request.running)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return asdict(worker)

@router.get("/workers/assign")
async def assign_worker(url: str, region: str | None = None,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Show which worker would take a job."""
    from zfrog.workers import WorkerRegistry

    assignment = WorkerRegistry().assign(url, preferred_region=region)
    return {
        "worker": assignment.worker.id if assignment.worker else None,
        "region": assignment.region,
        "reason": assignment.reason,
    }

@router.get("/auth/config")
async def auth_config():
    """How to log in: whether a credential is required, and whether SSO exists.

    Public on purpose — a client has to learn how to authenticate before it can
    authenticate, so this is what the dashboard reads to decide whether to ask
    for a key.
    """
    from zfrog.sso import config_from_settings, is_configured

    base = {"auth_enabled": settings.auth_enabled}

    if not is_configured():
        return {**base, "sso": False}

    config = config_from_settings()
    return {**base, "sso": True, "issuer": config.issuer, "client_id": config.client_id}

@router.get("/auth/login")
async def auth_login():
    """Start the SSO login: redirect the browser to the provider."""
    from fastapi.responses import RedirectResponse

    from zfrog.sso import (
        authorization_url,
        config_from_settings,
        discover,
        new_nonce,
        new_state,
    )

    try:
        config = config_from_settings()
        discovery = await discover(config.issuer)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _purge_expired_logins()
    state = new_state()
    nonce = new_nonce()
    _remember_login(state, nonce)

    return RedirectResponse(authorization_url(config, discovery, state, nonce), status_code=307)

@router.get("/auth/callback")
async def auth_callback(code: str, state: str = "", http_request: Request = None):
    """Finish the SSO login: exchange the code, verify the token, start a session.

    The `state` is looked up among the logins we started and consumed (so it
    cannot be replayed), and its `nonce` must be the one inside the ID token —
    otherwise a token minted for a different flow would be accepted.

    On success the browser is given the signed session cookie, which is what lets
    the dashboard work without an API key in it.
    """
    from fastapi.responses import JSONResponse, RedirectResponse

    from zfrog import websession
    from zfrog.sso import complete_login, config_from_settings, discover
    from zfrog.users import UserStore, redact

    try:
        nonce = _consume_login(state)
        config = config_from_settings()
        discovery = await discover(config.issuer)
        login = await complete_login(config, discovery, code, nonce=nonce)
    except ValueError as e:
        _audit(http_request, "auth.sso_login", outcome="error", detail=str(e))
        raise HTTPException(status_code=401, detail=str(e))

    user = UserStore().upsert_sso_user(
        login.claims.subject,
        login.user.get("email", ""),
        name=login.user.get("name", ""),
        role=login.role,
    )

    # A disabled account authenticates but must not be handed a session; the
    # cookie would otherwise outlive the revocation.
    if not user.enabled:
        _audit(http_request, "auth.sso_login", target=user.email, outcome="error", detail="account disabled")
        raise HTTPException(status_code=403, detail="account disabled")

    token = websession.issue(user.id)
    if token is None:
        _audit(http_request, "auth.sso_login", target=user.email, outcome="error", detail="session key unavailable")
        raise HTTPException(
            status_code=500,
            detail=(
                "could not create the session: the signing key in "
                "ZFROG_WEBSESSION_KEY_FILE could not be read or created"
            ),
        )

    _audit(http_request, "auth.sso_login", target=user.email, role=login.role)

    # Behind a TLS-terminating proxy the scheme arrives as http unless
    # --proxy-headers is on, which is why the flag exists.
    secure = settings.session_cookie_secure or (
        http_request is not None and http_request.url.scheme == "https"
    )

    target = (settings.post_login_redirect or "").strip()
    if target:
        response = RedirectResponse(target, status_code=303)
    else:
        response = JSONResponse({"user": redact(user), "role": login.role})

    websession.set_session_cookie(response, token, secure=secure)
    return response

@router.post("/auth/logout")
async def auth_logout():
    """Clear the dashboard session cookie.

    Reachable without a credential on purpose: it expires the caller's own cookie
    and nothing else, and requiring a login before logging out would be absurd.
    SameSite=Lax already blocks the cross-site POST that would turn this into a
    forced logout.
    """
    from fastapi.responses import JSONResponse

    from zfrog import websession

    response = JSONResponse({"signed_out": True})
    websession.clear_session_cookie(response)
    return response
