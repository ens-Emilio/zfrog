"""API router: workspaces."""

import asyncio
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from zfrog.api._shared import (
    ACTION_ADMIN,
    ACTION_KEY_MANAGE,
    ACTION_READ,
    ACTION_SCHEDULE_MANAGE,
    ACTION_VERSION_MANAGE,
    CompareRequest,
    DatasetRequest,
    DiffRequest,
    DirRequest,
    DispatchRequest,
    JobCreate,
    PriceWatchRequest,
    ScheduleCreateRequest,
    TotpRequest,
    TrendsRequest,
    VersionBranchRequest,
    VersionRollbackRequest,
    _audit,
    _reject_traversal,
    _scoped,
    auth_dependency,
    logger,
)  # noqa: F401
from zfrog.auth import AuthDecision
from zfrog.config import settings
from zfrog.diff import (
    diff_snapshots,
    list_snapshots,
    report_to_dict,
    resolve_snapshot,
    snapshots_dir,
)
from zfrog.orchestrator import run_job

router = APIRouter()

@router.get("/snapshots")
async def list_snapshots_endpoint(url: str | None = None,
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

@router.get("/snapshots/{slug}/{filename}")
async def get_snapshot_file(slug: str, filename: str,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Serve a raw snapshot JSON file."""
    _reject_traversal(slug, filename)

    path = snapshots_dir() / slug / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Snapshot not found")

    return FileResponse(path, media_type="application/json", filename=path.name)

@router.post("/diff")
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

@router.get("/versions")
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

@router.post("/versions/rollback")
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

@router.post("/versions/branches")
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

@router.get("/schedules")
async def list_schedules(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List scheduled jobs."""
    from zfrog.scheduler import ScheduleStore

    return [asdict(schedule) for schedule in ScheduleStore(path=_scoped(request, "schedules_file")).list()]

@router.post("/schedules")
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

@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, request: Request,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_SCHEDULE_MANAGE))):
    """Remove a scheduled job."""
    from zfrog.scheduler import ScheduleStore

    if not ScheduleStore(path=_scoped(request, "schedules_file")).remove(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")

    _audit(request, "schedule.delete", target=schedule_id)
    return {"removed": schedule_id}

@router.post("/schedules/{schedule_id}/run")
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

@router.get("/marketplace/index")
async def marketplace_index(source: str = "",
                            auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """The local marketplace as a publishable index."""
    from zfrog.marketplace_index import index_from_marketplace

    return index_from_marketplace(source=source)

@router.get("/timeline")
async def get_timeline(url: str, branch: str | None = None, request: Request = None,
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

@router.get("/timeline/resolve")
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
        raise HTTPException(status_code=404, detail="No version saved on or before that date")

    for entry in machine.timeline():
        if entry.ref == ref:
            return {"ref": entry.ref, "captured_at": entry.captured_at, "message": entry.message}

    raise HTTPException(status_code=404, detail="Version not found")

@router.get("/timeline/pages")
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

@router.get("/timeline/page")
async def timeline_page(url: str, ref: str, path: str, request: Request = None,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """One archived page's metadata."""
    from dataclasses import asdict

    from zfrog.timemachine import TimeMachine

    page = TimeMachine(url, root=_scoped(request, "versions_dir")).page(ref, path)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found in that version")

    return asdict(page)

@router.get("/timeline/content")
async def timeline_content(url: str, ref: str, path: str, request: Request = None,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """The raw archived HTML of one page, for the viewer iframe."""
    from fastapi.responses import HTMLResponse

    from zfrog.timemachine import TimeMachine

    html = TimeMachine(url, root=_scoped(request, "versions_dir")).content(ref, path)
    if html is None:
        raise HTTPException(status_code=404, detail="Content not found")

    return HTMLResponse(html)

@router.get("/prices")
async def list_prices(url: str, request: Request = None,
                      auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """The recorded price history of a site."""
    from zfrog.pricing import PriceTracker

    return PriceTracker(root=_scoped(request, "analysis_dir")).history(url)

@router.get("/prices/changes")
async def price_changes(url: str, request: Request = None,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Price movements worth looking at."""
    from dataclasses import asdict

    from zfrog.pricing import PriceTracker

    changes = PriceTracker(root=_scoped(request, "analysis_dir")).changes(url)
    return [asdict(change) for change in changes]

@router.post("/prices/watch")
async def watch_prices(body: PriceWatchRequest, request: Request,
                       auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Read the latest snapshot of a URL and record its prices."""
    from zfrog.pricing import PriceTracker, watch_url

    return watch_url(body.url, PriceTracker(root=_scoped(request, "analysis_dir")))

@router.get("/roi")
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

@router.get("/totp")
async def list_totp(auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """List registered two-factor accounts (never the secrets)."""
    from zfrog.totp import TotpStore

    return TotpStore().list()

@router.post("/totp")
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

@router.get("/totp/{name}/code")
async def totp_code(name: str, auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """The current code for an account (for logging into your own account)."""
    from zfrog.totp import TotpStore, seconds_remaining

    try:
        code = TotpStore().code(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"code": code, "seconds_remaining": seconds_remaining()}

@router.delete("/totp/{name}")
async def delete_totp(name: str, request: Request,
                      auth: AuthDecision = Depends(auth_dependency(ACTION_KEY_MANAGE))):
    """Remove a two-factor account."""
    from zfrog.totp import TotpStore

    if not TotpStore().remove(name):
        raise HTTPException(status_code=404, detail="Account not found")

    _audit(request, "totp.delete", target=name)
    return {"removed": name}

@router.post("/datasets")
async def build_dataset(body: DatasetRequest, request: Request,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Build a fine-tuning dataset from pages."""
    from zfrog.finetune import DatasetBuilder

    builder = DatasetBuilder(root=_scoped(request, "finetune_dir"))
    added = builder.add_pages(body.pages, kind=body.kind)
    return {"added": added, **builder.stats()}

@router.post("/datasets/export")
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

@router.post("/analysis/competitive")
async def competitive_analysis(body: CompareRequest, request: Request,
                               auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Compare several cloned sites side by side."""
    from dataclasses import asdict

    from zfrog.analysis.competitive import compare_directories

    sites = {label: Path(path) for label, path in body.sites.items()}
    for label, path in sites.items():
        if not path.is_dir():
            raise HTTPException(status_code=404, detail=f"directory not found: {label}")

    return asdict(await compare_directories(sites))

@router.post("/analysis/trends")
async def analysis_trends(body: TrendsRequest, request: Request,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Track terms across a site's history."""
    from dataclasses import asdict

    from zfrog.analysis.trends import summarize, trends

    found = trends(body.url, body.terms)
    return {"url": body.url, "trends": [asdict(trend) for trend in found], "summary": summarize(found)}

@router.get("/dispatch/plan")
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

@router.post("/dispatch")
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

@router.get("/arweave/status")
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

@router.get("/browsers/status")
async def browsers_status(auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Whether a Playwright-capable browser is available on this host.

    The desktop app shows a fallback progress UI when no system browser is
    found and the bundled Chromium has not yet been downloaded to
    ``PLAYWRIGHT_BROWSERS_PATH`` (``~/.cache/zfrog/browsers`` in the
    Tauri sidecar; ``~/.cache/ms-playwright`` otherwise). This is the signal
    for that UI.
    """
    import os

    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "") or None
    available = False
    detail = ""
    try:
        if browsers_path:
            detail = browsers_path
            available = any((Path(browsers_path) / d).exists() for d in os.listdir(browsers_path)) if Path(browsers_path).exists() else False
        else:
            from pathlib import Path as _P
            candidates = [
                _P.home() / ".cache" / "ms-playwright",
                _P("/ms-playwright"),
            ]
            for c in candidates:
                if c.exists() and any(c.iterdir()):
                    available = True
                    detail = str(c)
                    break
    except Exception as e:
        detail = str(e)
    has_system_channel = False
    for bin_name in ("google-chrome", "chromium-browser", "chromium", "msedge", "microsoft-edge"):
        if shutil.which(bin_name):
            has_system_channel = True
            break
    return {
        "available": available or has_system_channel,
        "browsers_path": browsers_path or detail or None,
        "has_system_channel": has_system_channel,
        "detail": detail,
    }

@router.post("/browsers/install")
async def browsers_install(request: Request, auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Download Chromium for Playwright into ``PLAYWRIGHT_BROWSERS_PATH``.

    Runs ``playwright install chromium`` as a background task and returns
    immediately; progress via ``GET /browsers/status``.
    """
    import os

    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    env = os.environ.copy()

    async def _run() -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "playwright", "install", "chromium",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception as e:
            logger.warning("browsers/install failed: %s", e)

    asyncio.create_task(_run())
    _audit(request, "browsers.install", target=browsers_path or "default")
    return {"status": "installing", "browsers_path": browsers_path or None}

@router.post("/arweave/publish")
async def arweave_publish(body: DirRequest, request: Request,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Publish a clone to Arweave for permanent archiving."""
    from zfrog.storage.arweave import publish_clone

    target = Path(body.dir)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"directory not found: {body.dir}")

    try:
        result = await publish_clone(target)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(request, "arweave.publish", target=body.dir, item=result.get("item_id", ""))
    return result
