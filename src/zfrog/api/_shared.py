"""FastAPI application for Zfrog."""

import logging
import time
from datetime import UTC, datetime, timezone  # noqa: F401 - re-exported via zfrog.api
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl

from zfrog.auth import AuthDecision
from zfrog.config import settings
from zfrog.models import (  # noqa: F401 - re-exported for routers
    Job,
    JobCreate,
    JobResult,
)
from zfrog.utils.cleanup import start_cleanup_scheduler

app = FastAPI(
    title="Zfrog API",
    description="Design reference engine: capture, organize and adapt web design references",
    version="0.2.0",
)

logger = logging.getLogger(__name__)

# Actions each endpoint requires when ZFROG_AUTH_ENABLED is true. With auth off
# (the default) `authorize` allows everything as "anonymous", so an existing
# deployment keeps working exactly as before.
ACTION_READ = "read:jobs"
ACTION_JOB_CREATE = "job:create"
ACTION_JOB_CANCEL = "job:cancel"
ACTION_KEY_MANAGE = "key:manage"
ACTION_SCHEDULE_MANAGE = "schedule:manage"
ACTION_VERSION_MANAGE = "version:manage"
ACTION_WORKFLOW_MANAGE = "workflow:manage"
ACTION_ADMIN = "admin:all"


def auth_dependency(action: str):
    """Build a FastAPI dependency enforcing `action` when auth is enabled.

    Returns the AuthDecision so handlers can record the actor in the audit log.
    """

    def dependency(request: Request) -> "AuthDecision":
        from zfrog.auth import authorize_request

        # Header (API key) or cookie (dashboard session): both reach the same
        # decision, so no endpoint has to know which one it was given.
        decision = authorize_request(request.headers, request.cookies, action)
        if not decision.allowed:
            status = 401 if decision.role == "" else 403
            raise HTTPException(status_code=status, detail=decision.reason)
        return decision

    # Stamped on the closure so the route table describes itself. The guard in
    # tests/test_route_auth.py reads it to prove no route lost its auth, and to
    # check which action each one demands.
    dependency.zfrog_action = action
    return dependency

# Allow the dashboard (and other browser clients) to call the API.
# ZFROG_CORS_ORIGINS is a comma-separated list; "*" (the default) suits local use,
# while a public deployment lists its real origins.


def allowed_origins() -> list[str]:
    """Origins allowed to call the API from a browser; defaults to local dashboard origins."""
    configured = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if not configured or configured == ["*"]:
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3067",
            "http://127.0.0.1:3067",
        ]
    return configured

_allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Startup/shutdown events
@app.on_event("startup")
async def startup():
    """Start background tasks."""
    await start_cleanup_scheduler()


class JobResponse(BaseModel):
    """Job response schema."""
    id: str
    url: str
    mode: str
    max_depth: int = 3
    status: str
    probe: dict | None = None
    output_path: str | None = None
    created_at: datetime
    updated_at: datetime
    error: str | None = None


class ProbeResponse(BaseModel):
    """Probe response schema."""
    url: str
    is_spa: bool
    has_js_rendering: bool
    robots_restricted: bool
    framework: str | None
    content_type: str
    suggested_engine: str
    status_code: int | None = None
    final_url: str | None = None


class JobResultResponse(BaseModel):
    """Job result response schema."""
    job_id: str
    output_path: str
    files_count: int
    total_size_bytes: int
    engine_used: str
    duration_seconds: float


class WebhookRequest(BaseModel):
    """Webhook registration request."""
    url: HttpUrl
    events: list[str] = ["job.completed", "job.failed"]
    secret: str | None = None




def _caller_org(request: Request | None) -> str:
    """The organization the caller's credential belongs to.

    The organization is a property of the credential, never of the request body:
    a client must not be able to write into someone else's workspace. An API key
    carries one; a dashboard session takes the user's first organization, since
    the request has no way to say which of several it means. No credential means
    the shared output directory.
    """
    if request is None:
        return ""

    from zfrog.auth import identify

    identity = identify(request.headers, request.cookies)
    return identity.org if identity is not None else ""


def _workspace(request: Request | None):
    """The workspace the caller's data lives in, or None for the shared area."""
    org = _caller_org(request)
    if not org:
        return None

    from zfrog.workspaces import WorkspaceManager

    return WorkspaceManager().for_org(org)


def _scoped(request: Request | None, attribute: str):
    """Path for one store, inside the caller's workspace when it has one.

    Returns None for the shared area, which every store reads as "use your
    default" — so a deployment without organizations behaves exactly as before.
    """
    workspace = _workspace(request)
    return getattr(workspace, attribute) if workspace is not None else None















class DiffRequest(BaseModel):
    """Request to diff two snapshots."""
    a: str
    b: str

def _reject_traversal(*parts: str) -> None:
    """Raise 400 when a path parameter could escape the snapshots directory."""
    for part in parts:
        if not part or "/" in part or "\\" in part or ".." in part:
            raise HTTPException(status_code=400, detail="invalid path")




class VersionRollbackRequest(BaseModel):
    """Request to restore a saved version."""
    url: str
    ref: str

class VersionBranchRequest(BaseModel):
    """Request to create a version branch."""
    url: str
    name: str

class ScheduleCreateRequest(BaseModel):
    """Request to schedule a recurring job."""
    cron: str
    url: str
    mode: str = "auto"
    max_depth: int = Field(default=3, ge=0, le=100)
class SearchRequest(BaseModel):
    """Search request."""
    query: str
    mode: str = "fulltext"
    dir: str | None = None

class WorkflowStepRequest(BaseModel):
    """A single workflow step."""
    type: str
    params: dict = {}
    # Stable label ("step-0"); steps refer to each other through it.
    id: str | None = None
    # Omit for the linear default (wait for the previous step); [] runs in parallel.
    needs: list[str] | None = None

class WorkflowCreateRequest(BaseModel):
    """Request to save a workflow."""
    name: str
    steps: list[WorkflowStepRequest]

class WorkflowPreviewRequest(BaseModel):
    """Request to explain a pipeline without saving it."""
    steps: list[WorkflowStepRequest]

class SelectorPreviewRequest(BaseModel):
    """Request to preview a CSS selector against a page."""
    url: str
    selector: str










class CardTagsRequest(BaseModel):
    """Tags to apply to a reference card."""

    tags: list[str] = []
    replace: bool = False


class CardNoteRequest(BaseModel):
    """Free-form note on a reference card."""

    note: str = ""


class CatalogSearchRequest(BaseModel):
    """A descriptive search over the reference catalog."""

    query: str
    limit: int = 20


def _catalog(request: Request):
    """The catalog of the caller's workspace.

    ``_scoped`` returns None for the shared area — every other store reads that as
    "use your default", so the None is translated here rather than pushed into
    :class:`Catalog`, which has no concept of a shared area.
    """
    from zfrog.catalog import Catalog

    scoped = _scoped(request, "catalog_db")
    return Catalog(Path(scoped) if scoped is not None else Path(settings.catalog_db))































class DirRequest(BaseModel):
    """Request carrying a directory to analyse."""
    dir: str

def _audit(request: Request | None, action: str, target: str = "", outcome: str = "ok",
           detail: str = "", **metadata) -> None:
    """Record a mutating action in the audit trail.

    Best-effort by design: `AuditLog.write` never raises, so a broken log file
    cannot turn a successful request into a 500.
    """
    try:
        from zfrog.utils.audit import AuditLog, client_identity

        headers = request.headers if request is not None else None
        AuditLog().write(
            action=action,
            actor=client_identity(headers),
            target=target,
            outcome=outcome,
            detail=detail,
            metadata=metadata,
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("audit log failed: %s", e)






class ChatRequest(BaseModel):
    """A chat question."""
    question: str
    conversation: str | None = None
    sites: list[str] = []

class UrlRequest(BaseModel):
    """A single URL to analyse."""
    url: str

class MarketRateRequest(BaseModel):
    """A rating for a marketplace asset."""
    score: float

class DestinationRequest(BaseModel):
    """An outbound integration destination."""
    kind: str
    name: str
    config: dict = {}

class KeyRequest(BaseModel):
    """An API key to create."""
    name: str
    role: str = "viewer"

class WatermarkRequest(BaseModel):
    """A directory to mark or verify."""
    dir: str
    source: str = ""

class GraphRequest(BaseModel):
    """Pages to build a knowledge graph from."""
    pages: list[dict]


























class UserRequest(BaseModel):
    """A user to create."""
    email: str
    name: str = ""
    role: str = "viewer"
    password: str = ""
    orgs: list[str] = []

class OrgRequest(BaseModel):
    """An organization to create."""
    name: str
    owner: str

class MemberRequest(BaseModel):
    """A user to add to an organization."""
    user_id: str
    role: str = "viewer"

class AnnotationRequest(BaseModel):
    """A comment on a cloned page."""
    job_id: str
    path: str
    text: str
    author: str = ""
    selector: str = ""
    tags: list[str] = []

class AnnotationUpdateRequest(BaseModel):
    """Editable fields of a comment."""
    text: str | None = None
    selector: str | None = None
    tags: list[str] | None = None

class ReplyRequest(BaseModel):
    """A reply to a comment."""
    text: str
    author: str = ""

class DomainRequest(BaseModel):
    """A domain profile to save."""
    id: str = ""
    name: str
    description: str = ""
    instructions: str = ""
    terminology: dict[str, str] = {}
    examples: list[dict] = []
    entity_types: list[str] = []
    tags: list[str] = []

class WorkerRequest(BaseModel):
    """A worker to register."""
    worker_id: str
    region: str
    capacity: int = 1
    version: str = ""
    tags: list[str] = []

class HeartbeatRequest(BaseModel):
    """A worker heartbeat."""
    worker_id: str
    running: int | None = None























# Pending SSO logins: state -> nonce. With more than one API worker the redirect
# and the callback land on different processes, so the map is mirrored to Redis;
# without Redis it stays in memory, which is correct for a single process.
_pending_logins: dict[str, tuple[str, float]] = {}
_LOGIN_TTL_S = 600
_LOGIN_REDIS_PREFIX = "zfrog:sso:state:"


def _login_redis():  # type: ignore[no-untyped-def]
    """A Redis client for the pending SSO logins, or None when unavailable."""
    try:
        from zfrog.storage.redis_client import get_sync_client

        client = get_sync_client()
        client.ping()
        return client
    except Exception:
        return None


def _remember_login(state: str, nonce: str) -> None:
    """Record the nonce of a login we just started."""
    _pending_logins[state] = (nonce, time.time())

    client = _login_redis()
    if client is None:
        return

    try:
        client.setex(f"{_LOGIN_REDIS_PREFIX}{state}", _LOGIN_TTL_S, nonce)
    except Exception:
        pass


def _consume_login(state: str) -> str:
    """Return the nonce for `state` and forget it (single use).

    Raises ValueError when the state was never issued, was already used, or is
    older than the TTL — which is what stops a replayed callback. A state issued
    by another worker is found through Redis, so a multi-worker deployment does
    not fail the login at random.
    """
    entry = _pending_logins.pop(state, None)
    client = _login_redis()

    if entry is not None:
        nonce, created_at = entry
        if time.time() - created_at > _LOGIN_TTL_S:
            raise ValueError("login expirado: reinicie o login")
        if client is not None:
            try:
                client.delete(f"{_LOGIN_REDIS_PREFIX}{state}")
            except Exception:
                pass
        return nonce

    if client is not None:
        try:
            shared = client.getdel(f"{_LOGIN_REDIS_PREFIX}{state}")
        except Exception:
            shared = None
        if shared:
            return shared

    raise ValueError("unknown or already-used state: restart the login")


def _purge_expired_logins() -> None:
    """Drop stale pending logins so the map cannot grow without bound."""
    cutoff = time.time() - _LOGIN_TTL_S
    for state in [s for s, (_, at) in _pending_logins.items() if at < cutoff]:
        _pending_logins.pop(state, None)







class TimelineRequest(BaseModel):
    """A site to browse as it was."""
    url: str
    branch: str = ""
    when: str = ""

class PriceWatchRequest(BaseModel):
    """A URL whose prices should be recorded."""
    url: str

class TotpRequest(BaseModel):
    """A two-factor account to register."""
    name: str
    secret: str
    issuer: str = ""

class DatasetRequest(BaseModel):
    """Pages to turn into a fine-tuning dataset."""
    pages: list[dict]
    kind: str = "extraction"

class CompareRequest(BaseModel):
    """Sites to compare, as label -> directory."""
    sites: dict[str, str]

class TrendsRequest(BaseModel):
    """Terms to track across a site's history."""
    url: str
    terms: list[str]

class DispatchRequest(BaseModel):
    """Jobs to hand to workers."""
    jobs: list[dict]
    preferred_region: str | None = None






































class ConfigResponse(BaseModel):
    """Configuration response schema."""
    redis_url: str
    output_dir: str
    max_concurrent_jobs: int
    worker_concurrency: int
    proxy_url: str | None
    rate_limit_rps: float
    http_timeout_connect: int
    http_timeout_read: int


class RateLimitUpdate(BaseModel):
    """Rate limit update request."""
    requests_per_second: float





