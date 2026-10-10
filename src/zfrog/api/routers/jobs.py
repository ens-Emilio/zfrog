"""API router: jobs."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse

from zfrog.api._shared import (
    ACTION_ADMIN,
    ACTION_JOB_CANCEL,
    ACTION_JOB_CREATE,
    ACTION_READ,
    ConfigResponse,
    Job,
    JobCreate,
    JobResponse,
    JobResultResponse,
    ProbeResponse,
    RateLimitUpdate,
    WebhookRequest,
    _audit,
    _caller_org,
    _scoped,
    _workspace,
    auth_dependency,
)  # noqa: F401
from zfrog.auth import AuthDecision
from zfrog.config import redact_url_credentials, settings
from zfrog.orchestrator import (
    clear_jobs,
    get_job,
    get_result,
    list_jobs,
    run_job,
    update_job,
)
from zfrog.probe import probe_url
from zfrog.utils.cleanup import cancel_job
from zfrog.utils.http import create_client
from zfrog.utils.url_guard import BlockedUrlError, check_url
from zfrog.utils.webhooks import WebhookConfig, register_webhook

router = APIRouter()

@router.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Zfrog API",
        "version": "0.2.0",
        "docs": "/docs",
    }

@router.get("/workspace")
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

@router.post("/jobs", response_model=JobResponse)
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
    
    # Check if we should use Celery — pooled singleton, no per-request connection.
    use_celery = False
    try:
        from zfrog.storage.redis_client import get_sync_client
        get_sync_client().ping()
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
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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

@router.get("/jobs/{job_id}", response_model=JobResponse)
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

@router.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str, request: Request,
                              auth: AuthDecision = Depends(auth_dependency(ACTION_JOB_CANCEL))):
    """Cancel a running job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status.value in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail="Job already finished")
    
    await cancel_job(job_id)

    # Reflect the intent on the record now, not only when the orchestrator notices.
    # A worker that had died left the record `running` forever, and since the clear
    # keeps work that is still going, that row could neither be cancelled nor
    # cleared — the list became impossible to empty.
    from zfrog.models import JobStatus

    job.status = JobStatus.CANCELLED
    update_job(job)

    _audit(request, "job.cancel", target=job_id, url=job.url)
    return {"message": f"Job {job_id} cancelled"}

@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
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

@router.get("/jobs/{job_id}/pdf")
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

@router.get("/jobs/{job_id}/download")
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

@router.get("/webhooks")
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

@router.delete("/webhooks/{webhook_id}")
async def delete_webhook_endpoint(webhook_id: str, request: Request,
                                  auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Remove a registered webhook."""
    from zfrog.utils.webhooks import remove_webhook

    if not remove_webhook(webhook_id):
        raise HTTPException(status_code=404, detail="Webhook not found")

    _audit(request, "webhook.delete", target=webhook_id)
    return {"removed": webhook_id}

@router.get("/jobs", response_model=list[JobResponse])
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

@router.delete("/jobs")
async def clear_all_jobs(request: Request,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_JOB_CANCEL))):
    """Clear the job list.

    Removes every job that is not in flight — finished ones and ones still queued
    but not started. A job the process is actively running is kept, because the
    record is the only thing pointing at output being written right now.
    """
    removed = clear_jobs()
    _audit(request, "job.clear", target=f"{removed} job(s)")
    return {"removed": removed}

@router.get("/probe/{url:path}", response_model=ProbeResponse)
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

@router.post("/webhooks")
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

@router.get("/stats")
async def get_stats(
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """Get system statistics."""
    from zfrog.utils.rate_limit import global_concurrency, global_limiter

    jobs = list_jobs()
    completed = sum(1 for j in jobs if j.status.value == "completed")
    failed = sum(1 for j in jobs if j.status.value == "failed")
    running = sum(1 for j in jobs if j.status.value == "running")
    
    return {
        "total_jobs": len(jobs),
        "completed": completed,
        "failed": failed,
        "running": running,
        "concurrent_slots_available": global_concurrency.available,
        "rate_limit_rps": global_limiter.rate,
    }

@router.get("/metrics")
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
        "timestamp": datetime.now(UTC).isoformat(),
    }

@router.get("/health")
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
    # Health probe is the only caller allowed an ephemeral client (called ~1/min,
    # needs short socket timeout); all hot paths use the pooled singleton.
    client = None
    try:
        client = redis_client.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        checks["redis"] = {"ok": True, "url": redact_url_credentials(settings.redis_url)}
    except Exception as e:
        healthy = False
        checks["redis"] = {
            "ok": False,
            "url": redact_url_credentials(settings.redis_url),
            "error": str(e),
        }
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

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
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if not healthy:
        return JSONResponse(status_code=503, content=body)
    return body

@router.get("/config", response_model=ConfigResponse)
async def get_config(
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """Get current configuration."""
    from zfrog.utils.rate_limit import global_limiter
    
    return ConfigResponse(
        redis_url=redact_url_credentials(settings.redis_url),
        output_dir=str(settings.output_dir),
        max_concurrent_jobs=settings.max_concurrent_jobs,
        worker_concurrency=settings.worker_concurrency,
        proxy_url=settings.proxy_url,
        rate_limit_rps=global_limiter.rate,
        http_timeout_connect=settings.http_timeout_connect,
        http_timeout_read=settings.http_timeout_read,
    )

@router.post("/config/rate-limit")
async def set_rate_limit(update: RateLimitUpdate,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Update the global rate limit.

    `global_limiter` is process-wide, so an unauthenticated caller could slow
    the whole instance to a crawl from one request.
    """
    from zfrog.utils.rate_limit import global_limiter
    
    if update.requests_per_second <= 0:
        raise HTTPException(status_code=400, detail="Rate must be positive")
    
    global_limiter.set_rate(update.requests_per_second)
    return {"rate_limit_rps": global_limiter.rate}

@router.websocket("/ws/jobs/{job_id}")
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
