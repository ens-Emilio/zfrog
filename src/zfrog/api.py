"""FastAPI application for Zfrog."""

import asyncio
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl

from zfrog.models import JobCreate, Job, JobResult
from zfrog.auth import AuthDecision
from zfrog.orchestrator import get_job, get_result, run_job, list_jobs, update_job
from zfrog.probe import probe_url
from zfrog.utils.http import create_client
from zfrog.utils.cleanup import cancel_job, start_cleanup_scheduler
from zfrog.utils.webhooks import register_webhook, WebhookConfig
from zfrog.utils.url_guard import BlockedUrlError, check_url
from zfrog.diff import diff_snapshots, list_snapshots, report_to_dict, resolve_snapshot, snapshots_dir
from zfrog.config import settings, redact_url_credentials

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
        from zfrog.auth import AuthDecision, authorize_request

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
    """Origins allowed to call the API from a browser; ``["*"]`` means any.

    Read from settings on each call rather than captured at import, so this stays
    the single source of truth for the check the WebSocket handshake performs. The
    CORS middleware is built from the same list, but Starlette fixes its
    configuration at startup — so a runtime change here would tighten the socket
    without loosening the middleware, never the other way round.
    """
    configured = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    return configured or ["*"]

# A browser only attaches the session cookie when the response names its exact
# origin, and the specification forbids pairing credentials with "*". So cookie
# logins need an explicit list; with the default "*" the API still works, but only
# through an API key.
_allow_credentials = bool(allowed_origins()) and "*" not in allowed_origins()

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
    probe: Optional[dict] = None
    output_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None


class ProbeResponse(BaseModel):
    """Probe response schema."""
    url: str
    is_spa: bool
    has_js_rendering: bool
    robots_restricted: bool
    framework: Optional[str]
    content_type: str
    suggested_engine: str
    status_code: Optional[int] = None
    final_url: Optional[str] = None


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
    secret: Optional[str] = None


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Zfrog API",
        "version": "0.2.0",
        "docs": "/docs",
    }


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


@app.get("/workspace")
async def get_workspace_info(request: Request,
                             auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Show where the caller's data lives (its organization and paths)."""
    from zfrog.workspaces import store_paths

    workspace = _workspace(request)
    if workspace is None:
        return {"org": None, "shared": True, "output_dir": str(settings.output_dir)}

    return {
        "org": workspace.org,
        "shared": False,
        "root": str(workspace.root),
        "paths": {
            name: {key: str(value) for key, value in kwargs.items()}
            for name, kwargs in store_paths(workspace).items()
        },
    }


@app.post("/jobs", response_model=JobResponse)
async def create_job(job: JobCreate, request: Request,
                     auth: AuthDecision = Depends(auth_dependency(ACTION_JOB_CREATE))):
    """Create and start a new extraction job."""
    import uuid
    from zfrog.models import JobStatus

    # Overwrite whatever the body said: the workspace comes from the credential.
    job.org = _caller_org(request) or None

    # Validate the target BEFORE anything is dispatched or run. The client hook in
    # utils/http.py only covers httpx requests, and two engines do not use it: the
    # wget engine shells out to the wget binary and Playwright renders in a
    # browser. Checking here is what makes the guard hold for every engine, and it
    # also stops a blocked URL from being queued for a Celery worker.
    try:
        check_url(str(job.url))
    except BlockedUrlError as e:
        _audit(request, "job.create", target=str(job.url), outcome="error", detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    _audit(
        request,
        "job.create",
        target=str(job.url),
        mode=job.mode,
        depth=job.max_depth,
        org=job.org or "",
    )
    
    # Check if we should use Celery
    use_celery = False
    try:
        import redis
        r = redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        use_celery = True
    except Exception:
        pass
    
    if use_celery:
        # Create job record first
        job_id = str(uuid.uuid4())
        job_record = Job(
            id=job_id,
            url=str(job.url),
            mode=job.mode,
            max_depth=job.max_depth,
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            org=job.org,
        )
        update_job(job_record)
        
        # Dispatch to Celery. The whole JobCreate is serialized so a new field
        # can never be silently dropped by a hand-maintained key list here.
        from zfrog.queue import run_job_task
        run_job_task.delay({"job_id": job_id, **job.model_dump(mode="json")})
        
        return JobResponse(
            id=job_record.id,
            url=job_record.url,
            mode=job_record.mode,
            max_depth=job_record.max_depth,
            status=job_record.status.value,
            created_at=job_record.created_at,
            updated_at=job_record.updated_at,
        )
    else:
        # Run synchronously
        try:
            result = await run_job(job)
            job_record = get_job(result.job_id)
            
            return JobResponse(
                id=job_record.id,
                url=job_record.url,
                mode=job_record.mode,
                max_depth=job_record.max_depth,
                status=job_record.status.value,
                probe=job_record.probe.model_dump() if job_record.probe else None,
                output_path=job_record.output_path,
                created_at=job_record.created_at,
                updated_at=job_record.updated_at,
                error=job_record.error,
            )
        except NotImplementedError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except BlockedUrlError as e:
            # A URL the guard refuses is a bad request, not a server fault.
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Get job status."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobResponse(
        id=job.id,
        url=job.url,
        mode=job.mode,
        max_depth=job.max_depth,
        status=job.status.value,
        probe=job.probe.model_dump() if job.probe else None,
        output_path=job.output_path,
        created_at=job.created_at,
        updated_at=job.updated_at,
        error=job.error,
    )


@app.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str, request: Request,
                              auth: AuthDecision = Depends(auth_dependency(ACTION_JOB_CANCEL))):
    """Cancel a running job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status.value in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail="Job already finished")
    
    await cancel_job(job_id)
    _audit(request, "job.cancel", target=job_id, url=job.url)
    return {"message": f"Job {job_id} marked for cancellation"}


@app.get("/jobs/{job_id}/result", response_model=JobResultResponse)
async def get_job_result(job_id: str,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Get job result."""
    result = get_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    
    return JobResultResponse(
        job_id=result.job_id,
        output_path=result.output_path,
        files_count=result.files_count,
        total_size_bytes=result.total_size_bytes,
        engine_used=result.engine_used,
        duration_seconds=result.duration_seconds,
    )


@app.get("/jobs/{job_id}/pdf")
async def download_job_pdf(job_id: str,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Serve the PDF generated by a `pdf` mode job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.output_path:
        raise HTTPException(status_code=404, detail="No PDF for this job")

    output_dir = Path(job.output_path)
    pdf_path = next(iter(sorted(output_dir.rglob("*.pdf"))), None) if output_dir.is_dir() else None
    if pdf_path is None:
        raise HTTPException(status_code=404, detail="No PDF for this job")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
    )

@app.get("/jobs/{job_id}/download")
async def download_job(job_id: str,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Download job output as ZIP."""
    result = get_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    
    import os
    if not os.path.exists(result.output_path):
        raise HTTPException(status_code=404, detail="Output file not found")
    
    return FileResponse(
        result.output_path,
        media_type="application/zip",
        filename=f"zfrog-{job_id[:8]}.zip",
    )


class DiffRequest(BaseModel):
    """Request to diff two snapshots."""
    a: str
    b: str

def _reject_traversal(*parts: str) -> None:
    """Raise 400 when a path parameter could escape the snapshots directory."""
    for part in parts:
        if not part or "/" in part or "\\" in part or ".." in part:
            raise HTTPException(status_code=400, detail="invalid path")

@app.get("/snapshots")
async def list_snapshots_endpoint(url: Optional[str] = None,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """List captured snapshots, newest last."""
    import json

    entries = []
    for path in list_snapshots(url):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        entries.append(
            {
                "slug": path.parent.name,
                "file": path.name,
                "url": data.get("url", ""),
                "captured_at": data.get("captured_at", ""),
                "pages": len(data.get("pages", [])),
            }
        )
    return entries

@app.get("/snapshots/{slug}/{filename}")
async def get_snapshot_file(slug: str, filename: str,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Serve a raw snapshot JSON file."""
    _reject_traversal(slug, filename)

    path = snapshots_dir() / slug / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Snapshot not found")

    return FileResponse(path, media_type="application/json", filename=path.name)

@app.post("/diff")
async def diff_snapshots_endpoint(request: DiffRequest,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Compare two snapshots.

    `a` and `b` accept either a filesystem path or a `<slug>/<filename>`
    reference relative to the snapshots directory.
    """
    resolved: list[Path] = []
    for ref in (request.a, request.b):
        path = resolve_snapshot(ref)
        if path is None:
            raise HTTPException(status_code=404, detail=f"snapshot not found: {ref}")
        resolved.append(path)

    try:
        report = diff_snapshots(resolved[0], resolved[1])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return report_to_dict(report)

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
    max_depth: int = 1

class SearchRequest(BaseModel):
    """Search request."""
    query: str
    mode: str = "fulltext"
    dir: Optional[str] = None

class WorkflowStepRequest(BaseModel):
    """A single workflow step."""
    type: str
    params: dict = {}
    # Stable label ("step-0"); steps refer to each other through it.
    id: Optional[str] = None
    # Omit for the linear default (wait for the previous step); [] runs in parallel.
    needs: Optional[list[str]] = None

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

@app.get("/versions")
async def list_versions(request: Request, url: str, branch: str = "main",
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """List saved versions of a site."""
    from zfrog.versioning import VersionStore

    store = VersionStore(root=_scoped(request, "versions_dir"))
    log = store.log(url, branch)
    return {
        "url": url,
        "branch": branch,
        "branches": store.branches(url),
        "versions": [asdict(version) for version in log],
    }

@app.post("/versions/rollback")
async def rollback_version(request: VersionRollbackRequest, http_request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_VERSION_MANAGE))):
    """Restore the files of a saved version."""
    from zfrog.versioning import VersionStore

    try:
        restored = VersionStore(root=_scoped(http_request, "versions_dir")).rollback(request.url, request.ref)
    except ValueError as e:
        _audit(http_request, "version.rollback", target=request.url, outcome="error", detail=str(e))
        raise HTTPException(status_code=404, detail=str(e))

    files = [f for f in restored.rglob("*") if f.is_file()]
    _audit(
        http_request,
        "version.rollback",
        target=request.url,
        detail=request.ref,
        restored=str(restored),
        files=len(files),
    )
    return {"restored": str(restored), "files": len(files)}

@app.post("/versions/branches")
async def create_version_branch(request: VersionBranchRequest, http_request: Request,
                                auth: AuthDecision = Depends(auth_dependency(ACTION_VERSION_MANAGE))):
    """Create a version branch."""
    from zfrog.versioning import VersionStore

    store = VersionStore(root=_scoped(http_request, "versions_dir"))
    try:
        store.create_branch(request.url, request.name)
    except ValueError as e:
        _audit(http_request, "version.branch", target=request.url, outcome="error", detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    _audit(http_request, "version.branch", target=request.url, detail=request.name)
    return {"branches": store.branches(request.url)}

@app.get("/schedules")
async def list_schedules(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List scheduled jobs."""
    from zfrog.scheduler import ScheduleStore

    return [asdict(schedule) for schedule in ScheduleStore(path=_scoped(request, "schedules_file")).list()]

@app.post("/schedules")
async def create_schedule(request: ScheduleCreateRequest, http_request: Request,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_SCHEDULE_MANAGE))):
    """Schedule a recurring job."""
    from zfrog.scheduler import ScheduleStore

    try:
        schedule = ScheduleStore(path=_scoped(http_request, "schedules_file")).add(
            request.cron, request.url, mode=request.mode, max_depth=request.max_depth
        )
    except ValueError as e:
        _audit(http_request, "schedule.create", target=request.url, outcome="error", detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    _audit(
        http_request,
        "schedule.create",
        target=request.url,
        detail=request.cron,
        schedule=schedule.id,
    )
    return asdict(schedule)

@app.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, request: Request,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_SCHEDULE_MANAGE))):
    """Remove a scheduled job."""
    from zfrog.scheduler import ScheduleStore

    if not ScheduleStore(path=_scoped(request, "schedules_file")).remove(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")

    _audit(request, "schedule.delete", target=schedule_id)
    return {"removed": schedule_id}

@app.post("/schedules/{schedule_id}/run")
async def run_schedule(schedule_id: str, request: Request,
                       auth: AuthDecision = Depends(auth_dependency(ACTION_SCHEDULE_MANAGE))):
    """Run a scheduled job immediately."""
    from zfrog.scheduler import ScheduleStore

    schedule = ScheduleStore(path=_scoped(request, "schedules_file")).get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    _audit(request, "schedule.run", target=schedule.url, detail=schedule_id)
    job = JobCreate(url=schedule.url, mode=schedule.mode, max_depth=schedule.max_depth)
    try:
        result = await run_job(job)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"job_id": result.job_id}

@app.post("/search")
async def search_content(body: SearchRequest, request: Request,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Search inside cloned content (full-text or semantic)."""
    from zfrog.search import SearchIndex

    if body.mode not in ("fulltext", "semantic"):
        raise HTTPException(status_code=400, detail="mode must be 'fulltext' or 'semantic'")

    index = SearchIndex(db_path=_scoped(request, "search_db"))
    if body.dir:
        target = Path(body.dir)
        if not target.is_dir():
            raise HTTPException(status_code=404, detail=f"directory not found: {body.dir}")
        index.index_directory(target)

    hits = index.search(body.query, mode=body.mode)
    return {
        "query": body.query,
        "mode": body.mode,
        "hits": [asdict(hit) for hit in hits],
    }


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


@app.get("/catalog")
async def list_catalog(
    request: Request,
    tag: Optional[str] = None,
    color: Optional[str] = None,
    site: Optional[str] = None,
    since: Optional[float] = None,
    until: Optional[float] = None,
    query: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List captured design references, newest first. All filters combine with AND."""
    catalog = _catalog(request)
    cards = catalog.list(
        tag=tag, color=color, site=site, since=since, until=until,
        query=query, limit=limit, offset=offset,
    )
    return {
        "total": catalog.count(),
        "cards": [card.to_dict() for card in cards],
    }


@app.get("/catalog/tags")
async def catalog_tags(request: Request,
                       auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Every tag in the catalog with how many references use it."""
    return [{"tag": tag, "count": count} for tag, count in _catalog(request).tags()]


@app.get("/catalog/colors")
async def catalog_colors(request: Request, limit: int = 60,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Every colour in the catalog with how many references carry it."""
    return [{"hex": hex_color, "count": count} for hex_color, count in _catalog(request).colors(limit)]


@app.get("/catalog/sites")
async def catalog_sites(request: Request,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Every captured site with its reference count."""
    return [{"site": site, "count": count} for site, count in _catalog(request).sites()]


@app.post("/catalog/search")
async def catalog_search(body: CatalogSearchRequest, request: Request,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Search the catalog by description ("layouts escuros com cards arredondados")."""
    from zfrog.visual_search import search_descriptive

    hits = await search_descriptive(_catalog(request), body.query, limit=body.limit)
    return {
        "query": body.query,
        "hits": [
            {"score": round(hit.score, 4), **hit.card.to_dict()} for hit in hits
        ],
    }


@app.get("/catalog/{card_id}")
async def get_catalog_card(card_id: str, request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """One reference, by id or by an unambiguous id prefix."""
    catalog = _catalog(request)
    card = catalog.get(card_id)
    if card is None:
        matches = [c for c in catalog.list(limit=1000) if c.id.startswith(card_id)]
        if len(matches) == 1:
            card = matches[0]
        elif len(matches) > 1:
            raise HTTPException(status_code=409, detail=f"prefixo ambíguo: {len(matches)} referências")
    if card is None:
        raise HTTPException(status_code=404, detail="Referência não encontrada")
    return card.to_dict()


@app.get("/catalog/{card_id}/screenshot")
async def catalog_screenshot(card_id: str, request: Request,
                             auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Serve the screenshot of a reference.

    The stored path is relative to the media root and is resolved against it with the
    result checked to stay inside — a catalog row is data, and data must not be able
    to name a file outside the tree it belongs to.
    """
    card = _catalog(request).get(card_id)
    if card is None or not card.screenshot:
        raise HTTPException(status_code=404, detail="Screenshot não encontrado")

    root = Path(settings.catalog_media_dir).resolve()
    target = (root / card.screenshot).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Screenshot não encontrado")

    return FileResponse(target)


@app.post("/catalog/{card_id}/tags")
async def catalog_set_tags(card_id: str, body: CardTagsRequest, request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_VERSION_MANAGE))):
    """Add tags to a reference, or replace the whole list."""
    catalog = _catalog(request)
    if catalog.get(card_id) is None:
        raise HTTPException(status_code=404, detail="Referência não encontrada")
    tags = catalog.tag(card_id, body.tags, replace=body.replace)
    _audit(request, "catalog.tag", target=card_id, detail=",".join(tags))
    return {"id": card_id, "tags": tags}


@app.post("/catalog/{card_id}/note")
async def catalog_set_note(card_id: str, body: CardNoteRequest, request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_VERSION_MANAGE))):
    """Set the note of a reference."""
    catalog = _catalog(request)
    if catalog.get(card_id) is None:
        raise HTTPException(status_code=404, detail="Referência não encontrada")
    catalog.note(card_id, body.note)
    return {"id": card_id, "note": body.note}


@app.delete("/catalog/{card_id}")
async def catalog_delete(card_id: str, request: Request,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_VERSION_MANAGE))):
    """Remove a reference from the catalog. The captured files stay on disk."""
    if not _catalog(request).delete(card_id):
        raise HTTPException(status_code=404, detail="Referência não encontrada")
    _audit(request, "catalog.delete", target=card_id)
    return {"id": card_id, "deleted": True}

@app.get("/sessions")
async def list_sessions(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List saved login sessions."""
    from zfrog.session import SessionStore

    return SessionStore(root=_scoped(request, "sessions_dir")).list()

@app.delete("/sessions/{domain}")
async def delete_session(request: Request, domain: str,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Delete a saved login session.

    A session file holds live cookies for a site, so removing one is credential
    management: listing them stays on `read:jobs`, deleting needs an admin.
    """
    from zfrog.session import SessionStore

    if not SessionStore(root=_scoped(request, "sessions_dir")).delete(domain):
        raise HTTPException(status_code=404, detail="Session not found")

    return {"removed": domain}

@app.get("/workflows")
async def list_workflows(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List saved workflows."""
    from zfrog.workflows import WorkflowStore

    return [asdict(workflow) for workflow in WorkflowStore(root=_scoped(request, "workflows_dir")).list()]

@app.post("/workflows")
async def save_workflow(request: WorkflowCreateRequest, http_request: Request,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_WORKFLOW_MANAGE))):
    """Create or replace a workflow."""
    from zfrog.workflows import WorkflowStore

    steps = [
        {
            "type": step.type,
            "params": step.params,
            **({"id": step.id} if step.id else {}),
            **({"needs": step.needs} if step.needs is not None else {}),
        }
        for step in request.steps
    ]
    try:
        workflow = WorkflowStore(root=_scoped(http_request, "workflows_dir")).save(request.name, steps)
    except ValueError as e:
        _audit(http_request, "workflow.save", target=request.name, outcome="error", detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    _audit(
        http_request,
        "workflow.save",
        target=request.name,
        workflow=workflow.id,
        steps=len(workflow.steps),
    )
    return asdict(workflow)

@app.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str, request: Request,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_WORKFLOW_MANAGE))):
    """Delete a workflow."""
    from zfrog.workflows import WorkflowStore

    if not WorkflowStore(root=_scoped(request, "workflows_dir")).remove(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")

    _audit(request, "workflow.delete", target=workflow_id)
    return {"removed": workflow_id}

@app.post("/workflows/{workflow_id}/run")
async def run_saved_workflow(workflow_id: str, request: Request,
                             auth: AuthDecision = Depends(auth_dependency(ACTION_WORKFLOW_MANAGE))):
    """Run a saved workflow."""
    from zfrog.workflows import WorkflowStore, run_workflow

    workflow = WorkflowStore(root=_scoped(request, "workflows_dir")).get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    _audit(request, "workflow.run", target=workflow.name, workflow=workflow_id)
    result = await run_workflow(workflow)
    return asdict(result)

@app.get("/extract/page")
async def extract_page(url: str,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Fetch a page, sanitised for rendering in the dashboard iframe."""
    from zfrog.selector import fetch_page

    try:
        return await fetch_page(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/extract/preview")
async def extract_preview(request: SelectorPreviewRequest,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Preview what a CSS selector matches on a page."""
    from zfrog.selector import fetch_page, build_selector_preview

    try:
        page = await fetch_page(request.url)
        preview = build_selector_preview(page["html"], request.selector)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"url": request.url, "selector": request.selector, **preview}

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
        logger.warning("auditoria falhou: %s", e)

@app.get("/analytics/engines")
async def analytics_engines(request: Request, engine: Optional[str] = None,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Per-engine success rate and throughput."""
    from zfrog.analytics import MetricsStore

    return [asdict(stats) for stats in MetricsStore(db_path=_scoped(request, "metrics_db")).engine_stats(engine)]

@app.get("/analytics/totals")
async def analytics_totals(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """Overall run totals."""
    from zfrog.analytics import MetricsStore

    return MetricsStore(db_path=_scoped(request, "metrics_db")).totals()

@app.get("/audit")
async def audit_entries(limit: int = 50, action: Optional[str] = None, actor: Optional[str] = None,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Recent audit entries, newest first."""
    from zfrog.utils.audit import AuditLog

    return [asdict(entry) for entry in AuditLog().read(limit=limit, action=action, actor=actor)]

@app.post("/safety/scan")
async def safety_scan(request: DirRequest,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Scan cloned content for malware and phishing indicators."""
    from zfrog.pipeline.safety import scan_directory

    target = Path(request.dir)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"directory not found: {request.dir}")

    return asdict(scan_directory(target))

@app.post("/ipfs/publish")
async def ipfs_publish(request: DirRequest,
                       auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Publish a clone to IPFS.

    Sends the content to a third party: a clone leaving the machine is an
    admin decision, like the Arweave equivalent.
    """
    from zfrog.storage.ipfs import publish_output

    target = Path(request.dir)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"directory not found: {request.dir}")

    try:
        result = await publish_output(target)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return asdict(result)

class ChatRequest(BaseModel):
    """A chat question."""
    question: str
    conversation: Optional[str] = None
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

@app.post("/graphql")
async def graphql_endpoint(payload: dict,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Execute a read-only GraphQL query."""
    from zfrog.graphql_api import GraphQLError, execute

    query = payload.get("query") or ""
    if not query.strip():
        raise HTTPException(status_code=400, detail="missing 'query'")

    result = await execute(query, payload.get("variables"))
    return {"data": result.data, "errors": result.errors}

@app.get("/graphql/schema")
async def graphql_schema(
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """The GraphQL schema as SDL."""
    from zfrog.graphql_api import schema_sdl

    return {"sdl": schema_sdl()}

@app.post("/chat")
async def chat_endpoint(request: ChatRequest, http_request: Request,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Ask a question, keeping conversation context."""
    from zfrog.ai.chat import ChatSession

    session = ChatSession(history_dir=_scoped(http_request, "chats_dir"))
    if request.conversation and session.load(request.conversation) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    for entry in request.sites:
        label, _, raw_path = entry.partition("=")
        if not raw_path:
            label, raw_path = Path(entry).name, entry
        path = Path(raw_path)
        if not path.is_dir():
            raise HTTPException(status_code=404, detail=f"directory not found: {path}")
        session.add_site(label, path)

    if not session.index.sites():
        raise HTTPException(status_code=400, detail="no sites indexed")

    _audit(http_request, "chat.ask", target=request.conversation or "new")
    result = await session.ask(request.question)
    saved = session.save()
    return {**result, "conversation": saved.stem}

@app.get("/chat")
async def chat_list(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List saved conversations."""
    from zfrog.ai.chat import ChatSession

    session = ChatSession(history_dir=_scoped(request, "chats_dir"))
    directory = session.history_dir
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    conversations = []
    for path in files:
        conversation = session.load(path.stem)
        if conversation is None:
            continue
        conversations.append(
            {
                "id": conversation.id,
                "sites": conversation.sites,
                "turns": len(conversation.turns),
                "created_at": conversation.created_at,
            }
        )
    return conversations

@app.get("/chat/{conversation_id}")
async def chat_get(request: Request, conversation_id: str,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Read a saved conversation."""
    from dataclasses import asdict

    from zfrog.ai.chat import ChatSession

    conversation = ChatSession(history_dir=_scoped(request, "chats_dir")).load(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {
        "id": conversation.id,
        "sites": conversation.sites,
        "created_at": conversation.created_at,
        "turns": [asdict(turn) for turn in conversation.turns],
    }

@app.post("/tos/check")
async def tos_check(request: UrlRequest,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Check a site's robots.txt and Terms for restrictions."""
    from zfrog.ai.tos import check_site

    return asdict(await check_site(request.url))

@app.post("/watermark")
async def watermark_mark(request: WatermarkRequest,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_VERSION_MANAGE))):
    """Mark a clone with provenance metadata.

    Writes into the stored clone, so `version:manage` — verification stays
    readable, marking does not.
    """
    from zfrog.pipeline.watermark import make_mark, watermark_directory

    target = Path(request.dir)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"directory not found: {request.dir}")

    mark = make_mark(request.source or request.dir)
    return await watermark_directory(target, mark, request.source)

@app.post("/watermark/verify")
async def watermark_verify(request: WatermarkRequest,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Report what provenance metadata a directory carries."""
    from zfrog.pipeline.watermark import verify_directory

    target = Path(request.dir)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"directory not found: {request.dir}")

    return await verify_directory(target)

@app.post("/graph")
async def graph_endpoint(request: GraphRequest,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Build a knowledge graph from entity-annotated pages."""
    from zfrog.ai.graph import build_graph, to_json

    return to_json(build_graph(request.pages))

@app.get("/analytics/cost")
async def analytics_cost(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """Estimated cost per engine."""
    from zfrog.analytics import MetricsStore, rates_from_settings

    rates = rates_from_settings()
    return {"currency": rates.currency, "engines": MetricsStore(db_path=_scoped(request, "metrics_db")).cost_by_engine(rates)}

@app.get("/webhooks")
async def list_webhooks_endpoint(
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List registered webhooks (never the secret)."""
    from zfrog.utils.webhooks import list_webhooks

    return [
        {
            "id": hook.id,
            "url": str(hook.url),
            "events": hook.events,
            "has_secret": hook.secret is not None,
        }
        for hook in list_webhooks()
    ]

@app.delete("/webhooks/{webhook_id}")
async def delete_webhook_endpoint(webhook_id: str, request: Request,
                                  auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Remove a registered webhook."""
    from zfrog.utils.webhooks import remove_webhook

    if not remove_webhook(webhook_id):
        raise HTTPException(status_code=404, detail="Webhook not found")

    _audit(request, "webhook.delete", target=webhook_id)
    return {"removed": webhook_id}

@app.post("/workflows/preview")
async def preview_workflow(request: WorkflowPreviewRequest,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Explain a pipeline and warn about steps that cannot run."""
    from zfrog.workflows import preview_steps

    try:
        return preview_steps([step.model_dump() for step in request.steps])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/marketplace")
async def marketplace_list(request: Request, 
    kind: Optional[str] = None,
    query: Optional[str] = None,
    tag: Optional[str] = None,
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List published marketplace assets."""
    from zfrog.marketplace import Marketplace

    return [asdict(asset) for asset in Marketplace(root=_scoped(request, "marketplace_dir")).list(kind=kind, query=query, tag=tag)]

@app.post("/marketplace/{asset_id}/install")
async def marketplace_install(asset_id: str, request: Request,
                              auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Install a published asset."""
    from zfrog.marketplace import Marketplace

    try:
        result = Marketplace(root=_scoped(request, "marketplace_dir")).install(asset_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(request, "marketplace.install", target=asset_id, kind=result.get("kind", ""))
    return result

@app.delete("/marketplace/{asset_id}/install")
async def marketplace_uninstall(asset_id: str, request: Request,
                                auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Remove an installed asset (the published copy stays)."""
    from zfrog.marketplace import Marketplace

    removed = Marketplace(root=_scoped(request, "marketplace_dir")).uninstall(asset_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Nothing installed for this asset")

    _audit(request, "marketplace.uninstall", target=asset_id)
    return {"removed": True}

@app.post("/marketplace/{asset_id}/rate")
async def marketplace_rate(asset_id: str, request: MarketRateRequest, http_request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Rate a marketplace asset."""
    from zfrog.marketplace import Marketplace

    try:
        asset = Marketplace(root=_scoped(http_request, "marketplace_dir")).rate(asset_id, request.score)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(http_request, "marketplace.rate", target=asset_id, score=request.score)
    return asdict(asset)

@app.get("/keys")
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

@app.post("/keys")
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

@app.delete("/keys/{key_id}")
async def revoke_key(key_id: str, request: Request,
                     auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """Revoke an API key."""
    from zfrog.auth import ApiKeyStore

    if not ApiKeyStore().revoke(key_id):
        raise HTTPException(status_code=404, detail="Key not found")

    _audit(request, "key.revoke", target=key_id)
    return {"removed": key_id}

@app.get("/integrations")
async def list_destinations(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List outbound destinations (tokens redacted)."""
    from zfrog.integrations.base import DestinationStore, redact

    return [
        {"kind": d.kind, "name": d.name, **redact(d)} for d in DestinationStore(root=_scoped(request, "integrations_dir")).list()
    ]

@app.post("/integrations")
async def save_destination(request: DestinationRequest, http_request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Create or replace an outbound destination."""
    from zfrog.integrations.base import Destination, DestinationStore

    destination = Destination(kind=request.kind, name=request.name, config=request.config)
    DestinationStore(root=_scoped(http_request, "integrations_dir")).save(destination)
    _audit(http_request, "integration.save", target=request.name, kind=request.kind)
    return {"kind": destination.kind, "name": destination.name}

@app.delete("/integrations/{name}")
async def delete_destination(name: str, request: Request,
                             auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Delete an outbound destination."""
    from zfrog.integrations.base import DestinationStore

    if not DestinationStore(root=_scoped(request, "integrations_dir")).remove(name):
        raise HTTPException(status_code=404, detail="Destination not found")

    _audit(request, "integration.delete", target=name)
    return {"removed": name}

@app.post("/integrations/{name}/push")
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

@app.get("/regions")
async def list_regions(url: Optional[str] = None,
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
    text: Optional[str] = None
    selector: Optional[str] = None
    tags: Optional[list[str]] = None

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
    running: Optional[int] = None

@app.get("/users")
async def list_users(auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """List users (never the password hash)."""
    from zfrog.users import UserStore, redact

    return [redact(user) for user in UserStore().list()]

@app.post("/users")
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

@app.get("/orgs")
async def list_orgs(auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """List organizations and whether they have data."""
    from dataclasses import asdict

    from zfrog.users import OrgStore
    from zfrog.workspaces import WorkspaceManager

    manager = WorkspaceManager()
    return [
        {**asdict(org), "has_data": manager.exists(org.id)} for org in OrgStore().list()
    ]

@app.post("/orgs")
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

@app.post("/orgs/{org_id}/members")
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

@app.get("/annotations")
async def list_annotations(request: Request, job_id: Optional[str] = None, resolved: Optional[bool] = None,
                           author: Optional[str] = None, tag: Optional[str] = None,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """List comments on cloned pages."""
    from dataclasses import asdict

    from zfrog.annotations import AnnotationStore

    notes = AnnotationStore(root=_scoped(request, "annotations_dir")).list(job_id=job_id, resolved=resolved, author=author, tag=tag)
    return [asdict(note) for note in notes]

@app.post("/annotations")
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

@app.patch("/annotations/{annotation_id}")
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

@app.post("/annotations/{annotation_id}/resolve")
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

@app.post("/annotations/{annotation_id}/replies")
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

@app.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str, request: Request,
                            auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Delete a comment."""
    from zfrog.annotations import AnnotationStore

    if not AnnotationStore(root=_scoped(request, "annotations_dir")).remove(annotation_id):
        raise HTTPException(status_code=404, detail="Annotation not found")

    _audit(request, "annotation.delete", target=annotation_id)
    return {"removed": annotation_id}

@app.get("/annotations/export")
async def export_annotations(request: Request, job_id: str,
                             auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Export a clone's comments as Markdown."""
    from zfrog.annotations import AnnotationStore, export_markdown

    notes = AnnotationStore(root=_scoped(request, "annotations_dir")).list(job_id=job_id)
    return {"job_id": job_id, "markdown": export_markdown(notes, job_id)}

@app.get("/domains")
async def list_domains(request: Request, auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """List saved and built-in domain profiles."""
    from dataclasses import asdict

    from zfrog.ai.domains import DomainProfileStore

    store = DomainProfileStore(root=_scoped(request, "domains_dir"))
    return {
        "saved": [asdict(profile) for profile in store.list()],
        "builtin": [asdict(profile) for profile in store.builtin()],
    }

@app.post("/domains")
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

@app.delete("/domains/{profile_id}")
async def delete_domain(profile_id: str, request: Request,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Delete a saved domain profile."""
    from zfrog.ai.domains import DomainProfileStore

    if not DomainProfileStore(root=_scoped(request, "domains_dir")).remove(profile_id):
        raise HTTPException(status_code=404, detail="Domain profile not found")

    _audit(request, "domain.delete", target=profile_id)
    return {"removed": profile_id}

@app.get("/workers")
async def list_workers(region: Optional[str] = None,
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

@app.post("/workers")
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

@app.post("/workers/heartbeat")
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

@app.get("/workers/assign")
async def assign_worker(url: str, region: Optional[str] = None,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Show which worker would take a job."""
    from zfrog.workers import WorkerRegistry

    assignment = WorkerRegistry().assign(url, preferred_region=region)
    return {
        "worker": assignment.worker.id if assignment.worker else None,
        "region": assignment.region,
        "reason": assignment.reason,
    }

@app.get("/marketplace/index")
async def marketplace_index(source: str = "",
                            auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """The local marketplace as a publishable index."""
    from zfrog.marketplace_index import index_from_marketplace

    return index_from_marketplace(source=source)

@app.post("/marketplace/sync")
async def marketplace_sync(payload: dict, http_request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Import the assets of a remote index."""
    from dataclasses import asdict

    from zfrog.marketplace_index import fetch_index, merge_index

    index_url = payload.get("index_url")
    index = payload.get("index")
    if not index_url and not isinstance(index, dict):
        raise HTTPException(status_code=400, detail="provide 'index_url' or 'index'")

    try:
        remote = index if isinstance(index, dict) else await fetch_index(index_url)
        result = merge_index(remote)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(http_request, "marketplace.sync", target=index_url or "inline")
    return asdict(result)

@app.get("/auth/config")
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

# Pending SSO logins: state -> nonce. With more than one API worker the redirect
# and the callback land on different processes, so the map is mirrored to Redis;
# without Redis it stays in memory, which is correct for a single process.
_pending_logins: dict[str, tuple[str, float]] = {}
_LOGIN_TTL_S = 600
_LOGIN_REDIS_PREFIX = "zfrog:sso:state:"


def _login_redis():
    """A Redis client for the pending SSO logins, or None when unavailable."""
    try:
        import redis

        client = redis.from_url(settings.redis_url, decode_responses=True)
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

    raise ValueError("state desconhecido ou já usado: reinicie o login")


def _purge_expired_logins() -> None:
    """Drop stale pending logins so the map cannot grow without bound."""
    cutoff = time.time() - _LOGIN_TTL_S
    for state in [s for s, (_, at) in _pending_logins.items() if at < cutoff]:
        _pending_logins.pop(state, None)


@app.get("/auth/login")
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


@app.get("/auth/callback")
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
        _audit(http_request, "auth.sso_login", target=user.email, outcome="error", detail="conta desativada")
        raise HTTPException(status_code=403, detail="conta desativada")

    token = websession.issue(user.id)
    if token is None:
        _audit(http_request, "auth.sso_login", target=user.email, outcome="error", detail="chave de sessão indisponível")
        raise HTTPException(
            status_code=500,
            detail=(
                "não foi possível criar a sessão: a chave de assinatura em "
                "ZFROG_WEBSESSION_KEY_FILE não pôde ser lida nem criada"
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


@app.post("/auth/logout")
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
    preferred_region: Optional[str] = None

@app.get("/timeline")
async def get_timeline(url: str, branch: Optional[str] = None, request: Request = None,
                       auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Every saved version of a site, oldest first."""
    from dataclasses import asdict

    from zfrog.timemachine import TimeMachine, timeline_summary

    machine = TimeMachine(url, root=_scoped(request, "versions_dir"))
    entries = machine.timeline(branch or None)
    return {
        "url": url,
        "branch": branch or "main",
        "entries": [asdict(entry) for entry in entries],
        "summary": timeline_summary(entries),
    }

@app.get("/timeline/resolve")
async def resolve_timeline(url: str, when: str, request: Request = None,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Find the version captured on or before a moment."""
    from zfrog.timemachine import TimeMachine

    machine = TimeMachine(url, root=_scoped(request, "versions_dir"))
    try:
        ref = machine.resolve_date(when)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if ref is None:
        raise HTTPException(status_code=404, detail="Nenhuma versão guardada até essa data")

    for entry in machine.timeline():
        if entry.ref == ref:
            return {"ref": entry.ref, "captured_at": entry.captured_at, "message": entry.message}

    raise HTTPException(status_code=404, detail="Versão não encontrada")

@app.get("/timeline/pages")
async def timeline_pages(url: str, ref: str, request: Request = None,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """The pages of one archived version."""
    from dataclasses import asdict

    from zfrog.timemachine import TimeMachine

    try:
        pages = TimeMachine(url, root=_scoped(request, "versions_dir")).at(ref)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return [asdict(page) for page in pages]

@app.get("/timeline/page")
async def timeline_page(url: str, ref: str, path: str, request: Request = None,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """One archived page's metadata."""
    from dataclasses import asdict

    from zfrog.timemachine import TimeMachine

    page = TimeMachine(url, root=_scoped(request, "versions_dir")).page(ref, path)
    if page is None:
        raise HTTPException(status_code=404, detail="Página não encontrada nessa versão")

    return asdict(page)

@app.get("/timeline/content")
async def timeline_content(url: str, ref: str, path: str, request: Request = None,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """The raw archived HTML of one page, for the viewer iframe."""
    from fastapi.responses import HTMLResponse

    from zfrog.timemachine import TimeMachine

    html = TimeMachine(url, root=_scoped(request, "versions_dir")).content(ref, path)
    if html is None:
        raise HTTPException(status_code=404, detail="Conteúdo não encontrado")

    return HTMLResponse(html)

@app.get("/prices")
async def list_prices(url: str, request: Request = None,
                      auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """The recorded price history of a site."""
    from zfrog.pricing import PriceTracker

    return PriceTracker(root=_scoped(request, "analysis_dir")).history(url)

@app.get("/prices/changes")
async def price_changes(url: str, request: Request = None,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Price movements worth looking at."""
    from dataclasses import asdict

    from zfrog.pricing import PriceTracker

    changes = PriceTracker(root=_scoped(request, "analysis_dir")).changes(url)
    return [asdict(change) for change in changes]

@app.post("/prices/watch")
async def watch_prices(body: PriceWatchRequest, request: Request,
                       auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Read the latest snapshot of a URL and record its prices."""
    from zfrog.pricing import PriceTracker, watch_url

    return watch_url(body.url, PriceTracker(root=_scoped(request, "analysis_dir")))

@app.get("/roi")
async def get_roi(request: Request = None,
                 auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """What the automation saved versus what it cost."""
    from dataclasses import asdict

    from zfrog.analytics import MetricsStore
    from zfrog.roi import inputs_from_settings, roi_from_metrics

    result = roi_from_metrics(
        inputs_from_settings(),
        store=MetricsStore(db_path=_scoped(request, "metrics_db")),
    )
    return asdict(result)

@app.get("/totp")
async def list_totp(auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """List registered two-factor accounts (never the secrets)."""
    from zfrog.totp import TotpStore

    return TotpStore().list()

@app.post("/totp")
async def add_totp(body: TotpRequest, request: Request,
                   auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """Register a two-factor account."""
    from zfrog.totp import TotpStore, redact

    try:
        account = TotpStore().add(body.name, body.secret, body.issuer)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(request, "totp.add", target=body.name)
    return redact(account)

@app.get("/totp/{name}/code")
async def totp_code(name: str, auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """The current code for an account (for logging into your own account)."""
    from zfrog.totp import TotpStore, seconds_remaining

    try:
        code = TotpStore().code(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"code": code, "seconds_remaining": seconds_remaining()}

@app.delete("/totp/{name}")
async def delete_totp(name: str, request: Request,
                      auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """Remove a two-factor account."""
    from zfrog.totp import TotpStore

    if not TotpStore().remove(name):
        raise HTTPException(status_code=404, detail="Conta não encontrada")

    _audit(request, "totp.delete", target=name)
    return {"removed": name}

@app.post("/datasets")
async def build_dataset(body: DatasetRequest, request: Request,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Build a fine-tuning dataset from pages."""
    from zfrog.finetune import DatasetBuilder

    builder = DatasetBuilder(root=_scoped(request, "finetune_dir"))
    added = builder.add_pages(body.pages, kind=body.kind)
    return {"added": added, **builder.stats()}

@app.post("/datasets/export")
async def export_dataset(request: Request, fmt: str = "chat",
                         auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Write the built dataset to a JSONL file."""
    from zfrog.finetune import DatasetBuilder, dataset_summary

    builder = DatasetBuilder(root=_scoped(request, "finetune_dir"))
    try:
        path = builder.export(fmt=fmt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"path": str(path), "summary": dataset_summary(path), **builder.stats()}

@app.post("/analysis/competitive")
async def competitive_analysis(body: CompareRequest, request: Request,
                               auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Compare several cloned sites side by side."""
    from dataclasses import asdict

    from zfrog.analysis.competitive import compare_directories

    sites = {label: Path(path) for label, path in body.sites.items()}
    for label, path in sites.items():
        if not path.is_dir():
            raise HTTPException(status_code=404, detail=f"diretório não encontrado: {label}")

    return asdict(await compare_directories(sites))

@app.post("/analysis/trends")
async def analysis_trends(body: TrendsRequest, request: Request,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Track terms across a site's history."""
    from dataclasses import asdict

    from zfrog.analysis.trends import summarize, trends

    found = trends(body.url, body.terms)
    return {"url": body.url, "trends": [asdict(trend) for trend in found], "summary": summarize(found)}

@app.get("/dispatch/plan")
async def dispatch_plan(url: str, mode: str = "auto", request: Request = None,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Which worker would take a job, without sending it."""
    from zfrog.dispatch import plan_dispatch
    from zfrog.workers import WorkerRegistry

    return plan_dispatch(
        [{"url": url, "mode": mode}],
        registry=WorkerRegistry(path=_scoped(request, "output_dir") / "workers.json")
        if _scoped(request, "output_dir")
        else None,
    )

@app.post("/dispatch")
async def dispatch_jobs(body: DispatchRequest, request: Request,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Hand jobs to workers."""
    from dataclasses import asdict

    from zfrog.dispatch import Dispatcher, dispatch_summary
    from zfrog.workers import WorkerRegistry

    scoped_output = _scoped(request, "output_dir")
    registry = WorkerRegistry(path=scoped_output / "workers.json") if scoped_output else None

    dispatcher = Dispatcher(registry=registry)
    try:
        results = await dispatcher.send_many(body.jobs, preferred_region=body.preferred_region)
    finally:
        await dispatcher.aclose()

    _audit(request, "dispatch.send", target=f"{len(body.jobs)} job(s)")
    return {
        "results": [asdict(result) for result in results],
        "summary": dispatch_summary(results),
    }

@app.get("/arweave/status")
async def arweave_status(auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Whether permanent archiving is configured.

    Reports deployment configuration (gateway, whether a wallet is loaded), so it
    needs the same `read:jobs` as `GET /config` rather than answering anonymous
    callers.
    """
    from zfrog.storage.arweave import wallet_configured

    return {
        "enabled": settings.arweave_enabled,
        "gateway": settings.arweave_gateway,
        "wallet": wallet_configured(),
    }

@app.post("/arweave/publish")
async def arweave_publish(body: DirRequest, request: Request,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Publish a clone to Arweave for permanent archiving."""
    from zfrog.storage.arweave import publish_clone

    target = Path(body.dir)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"diretório não encontrado: {body.dir}")

    try:
        result = await publish_clone(target)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(request, "arweave.publish", target=body.dir, item=result.get("item_id", ""))
    return result

@app.get("/jobs", response_model=list[JobResponse])
async def list_all_jobs(
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List all jobs."""
    jobs = list_jobs()
    
    return [
        JobResponse(
            id=job.id,
            url=job.url,
            mode=job.mode,
            max_depth=job.max_depth,
            status=job.status.value,
            probe=job.probe.model_dump() if job.probe else None,
            output_path=job.output_path,
            created_at=job.created_at,
            updated_at=job.updated_at,
            error=job.error,
        )
        for job in jobs
    ]


@app.get("/probe/{url:path}", response_model=ProbeResponse)
async def probe_url_endpoint(url: str,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Probe a URL to detect its type."""
    # Ensure URL has scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    try:
        async with create_client() as client:
            result = await probe_url(url, client)
        
        return ProbeResponse(
            url=result.url,
            is_spa=result.is_spa,
            has_js_rendering=result.has_js_rendering,
            robots_restricted=result.robots_restricted,
            framework=result.framework,
            content_type=result.content_type,
            suggested_engine=result.suggested_engine,
            status_code=result.status_code,
            final_url=result.final_url,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhooks")
async def register_webhook_endpoint(config: WebhookRequest, request: Request,
                                    auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Register a webhook for job notifications.

    The registry is global and shared across workers, and every event is POSTed
    to the URL given here — so registering one both redirects other people's
    job events to a host the caller chooses and makes the server fetch it.
    Admin only.
    """
    webhook = WebhookConfig(
        url=config.url,
        events=config.events,
        secret=config.secret,
    )
    register_webhook(webhook)
    _audit(request, "webhook.register", target=str(config.url), events=",".join(config.events))

    return {
        "id": webhook.id,
        "url": str(webhook.url),
        "events": webhook.events,
        "has_secret": webhook.secret is not None,
    }


@app.get("/stats")
async def get_stats(
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """Get system statistics."""
    from zfrog.utils.rate_limit import _global_concurrency, _global_limiter

    jobs = list_jobs()
    completed = sum(1 for j in jobs if j.status.value == "completed")
    failed = sum(1 for j in jobs if j.status.value == "failed")
    running = sum(1 for j in jobs if j.status.value == "running")
    
    return {
        "total_jobs": len(jobs),
        "completed": completed,
        "failed": failed,
        "running": running,
        "concurrent_slots_available": _global_concurrency.available,
        "rate_limit_rps": _global_limiter.rate,
    }


@app.get("/metrics")
async def get_metrics_endpoint(
    request: Request,
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """Per-engine metrics, read from the analytics store.

    This used to report an in-process `MetricsCollector` whose counters nothing
    ever incremented, so it always answered `{}` — observability that observed
    nothing. `analytics.py` records a real row per engine run in SQLite, so this
    reports that instead of maintaining a second, empty system.
    """
    from zfrog.analytics import MetricsStore, rates_from_settings

    store = MetricsStore(db_path=_scoped(request, "metrics_db"))
    rates = rates_from_settings()

    return {
        "totals": store.totals(),
        "engines": store.cost_by_engine(rates),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
async def health_check():
    """Report whether this instance can actually do its job.

    Deliberately not "always healthy": the container healthcheck polls this, so a
    fixed `{"status": "healthy"}` would keep a broken instance in the load
    balancer. Two things are checked because both break every request — the job
    store (Redis, or per-process memory when it is down) and the state volume
    (a read-only or full mount silently loses keys, sessions and versions).

    Answers 503 when either fails, which is what makes the probe meaningful.
    """
    import redis as redis_client
    from fastapi.responses import JSONResponse

    from zfrog.utils.resources import get_memory_limiter

    checks: dict[str, dict] = {}
    healthy = True

    # The broker backs job state, pub/sub for the progress socket, and the SSO
    # login handshake. Unreachable means jobs and live updates are degraded.
    try:
        client = redis_client.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        client.close()
        checks["redis"] = {"ok": True, "url": redact_url_credentials(settings.redis_url)}
    except Exception as e:
        healthy = False
        checks["redis"] = {
            "ok": False,
            "url": redact_url_credentials(settings.redis_url),
            "error": str(e),
        }

    # Every store lives under data_dir. A mount that went read-only, or filled up,
    # is invisible until something tries to write.
    try:
        probe = Path(settings.data_dir) / ".health"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks["data_dir"] = {"ok": True, "path": str(settings.data_dir)}
    except OSError as e:
        healthy = False
        checks["data_dir"] = {"ok": False, "path": str(settings.data_dir), "error": str(e)}

    body = {
        "status": "healthy" if healthy else "degraded",
        "checks": checks,
        "memory": get_memory_limiter().get_memory_usage(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if not healthy:
        return JSONResponse(status_code=503, content=body)
    return body


class ConfigResponse(BaseModel):
    """Configuration response schema."""
    redis_url: str
    output_dir: str
    max_concurrent_jobs: int
    worker_concurrency: int
    proxy_url: Optional[str]
    rate_limit_rps: float
    http_timeout_connect: int
    http_timeout_read: int


class RateLimitUpdate(BaseModel):
    """Rate limit update request."""
    requests_per_second: float


@app.get("/config", response_model=ConfigResponse)
async def get_config(
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """Get current configuration."""
    from zfrog.utils.rate_limit import _global_limiter
    
    return ConfigResponse(
        redis_url=redact_url_credentials(settings.redis_url),
        output_dir=str(settings.output_dir),
        max_concurrent_jobs=settings.max_concurrent_jobs,
        worker_concurrency=settings.worker_concurrency,
        proxy_url=settings.proxy_url,
        rate_limit_rps=_global_limiter.rate,
        http_timeout_connect=settings.http_timeout_connect,
        http_timeout_read=settings.http_timeout_read,
    )


@app.post("/config/rate-limit")
async def set_rate_limit(update: RateLimitUpdate,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Update the global rate limit.

    `_global_limiter` is process-wide, so an unauthenticated caller could slow
    the whole instance to a crawl from one request.
    """
    from zfrog.utils.rate_limit import _global_limiter
    
    if update.requests_per_second <= 0:
        raise HTTPException(status_code=400, detail="Rate must be positive")
    
    _global_limiter.set_rate(update.requests_per_second)
    return {"rate_limit_rps": _global_limiter.rate}


@app.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job progress updates.
    
    Provides live streaming of job events including progress updates,
    status changes, and errors. Sends a heartbeat ping every 30s.
    
    Args:
        websocket: WebSocket connection.
        job_id: Job ID to subscribe to events for.
    """
    from zfrog.ws import job_progress_ws as ws_handler
    await ws_handler(websocket, job_id)
