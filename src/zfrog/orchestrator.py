"""Core orchestrator for job execution."""

import asyncio
import logging
import time
import uuid
from pathlib import Path

from zfrog.config import settings
from zfrog.models import (
    Job,
    JobCreate,
    JobResult,
    JobStatus,
)
from zfrog.probe import probe_url
from zfrog.engines import get_engine, get_engine_for_probe
from zfrog.pipeline.link_rewriter import rewrite_links
from zfrog.pipeline.privacy_cleaner import clean_privacy
from zfrog.pipeline.packager import package_zip
from zfrog.pipeline.reference import DESIGN_MODES, register_reference
from zfrog.pipeline.screenshot import take_screenshots
from zfrog.storage.local import get_output_dir
from zfrog.utils.http import create_client
from zfrog.utils.rate_limit import _global_limiter, _global_concurrency
from zfrog.utils.cleanup import is_cancelled, CancellationError
from zfrog.utils.url_guard import check_url
from zfrog.utils.webhooks import notify_job_completed, notify_job_failed
from zfrog.queue import publish_job_event

logger = logging.getLogger(__name__)


# In-memory job storage (fallback when Redis unavailable)
_jobs: dict[str, Job] = {}
_results: dict[str, JobResult] = {}


def get_job(job_id: str) -> Job | None:
    """Get job by ID. Tries Redis first, falls back to memory."""
    # Try Redis
    try:
        from zfrog.storage.redis_store import get_job_from_redis
        job = get_job_from_redis(job_id)
        if job:
            return job
    except Exception:
        pass
    return _jobs.get(job_id)


def get_result(job_id: str) -> JobResult | None:
    """Get job result by ID. Tries Redis first, falls back to memory."""
    try:
        from zfrog.storage.redis_store import get_result_from_redis
        result = get_result_from_redis(job_id)
        if result:
            return result
    except Exception:
        pass
    return _results.get(job_id)


def list_jobs() -> list[Job]:
    """List all jobs from memory."""
    return list(_jobs.values())


def update_job(job: Job):
    """Update job in storage."""
    _jobs[job.id] = job
    try:
        from zfrog.storage.redis_store import save_job_to_redis
        save_job_to_redis(job)
    except Exception:
        pass


def update_result(result: JobResult):
    """Update result in storage."""
    _results[result.job_id] = result
    try:
        from zfrog.storage.redis_store import save_result_to_redis
        save_result_to_redis(result)
    except Exception:
        pass


async def run_job(job: JobCreate) -> JobResult:
    """Execute a complete extraction job.
    
    Flow: Probe → Route → Execute → Pipeline → Package
    
    Args:
        job: Job configuration.
        
    Returns:
        JobResult with output details.
        
    Raises:
        Exception: If job execution fails.
    """
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Create job record
    job_record = Job(
        id=job_id,
        url=str(job.url),
        mode=job.mode,
        max_depth=job.max_depth,
        status=JobStatus.PROBING,
        org=job.org,
    )
    update_job(job_record)
    
    start_time = time.time()
    client = None

    # Same check as the API, for callers that bypass it (the CLI, a Celery task
    # re-run by hand). Engines that shell out or drive a browser do not go through
    # the httpx hook, so this is the only place that covers all of them.
    check_url(str(job.url))

    try:
        # Acquire concurrency slot
        await _global_concurrency.acquire()
        
        try:
            # Get output directory. An org-scoped job writes inside its own
            # workspace so one organization's clones never mix with another's.
            output_dir = get_output_dir(job_id, org=job.org)
            job_record.output_path = str(output_dir)
            
            # Create HTTP client
            client = create_client(proxy=settings.proxy_url)
            
            # Step 1: Probe the URL
            job_record.status = JobStatus.PROBING
            update_job(job_record)
            await publish_job_event(job_id, "status", {"status": "probing", "url": str(job.url)})
            
            # Apply rate limiting
            await _global_limiter.acquire()
            
            probe_result = await probe_url(str(job.url), client)
            job_record.probe = probe_result
            await publish_job_event(job_id, "status", {"status": "probed", "probe_result": probe_result.model_dump() if hasattr(probe_result, 'model_dump') else str(probe_result)})
            
            # Check for cancellation
            if await is_cancelled(job_id):
                raise CancellationError(f"Job {job_id} was cancelled")
            
            # Step 2: Route to appropriate engine
            job_record.status = JobStatus.RUNNING
            update_job(job_record)
            
            # Determine engine based on mode or probe suggestion.
            # "auto" is the default: the probe picked the motor above. The capture
            # modes map to the motors by role: jump captures a reference card
            # (screenshot + tokens), tongue extracts one component, mirror is the
            # assets motor, singlepage the light motor, scrape the visual capture
            # motor, extract the discovery motor.
            if job.mode == "jump":
                engine = get_engine("jump")
            elif job.mode == "tongue":
                engine = get_engine("tongue")
            elif job.mode == "mirror":
                engine = get_engine("wget")
            elif job.mode == "singlepage":
                engine = get_engine("static_file")
            elif job.mode == "scrape":
                engine = get_engine("playwright")
            elif job.mode == "extract":
                engine = get_engine("scrapy")
            elif job.mode == "analyze":
                engine = get_engine("analyze")
            elif job.mode == "compare":
                engine = get_engine("compare")
            elif job.mode == "ask":
                engine = get_engine("ask")
            elif job.mode == "pdf":
                engine = get_engine("pdf")
            elif job.mode == "summarize":
                engine = get_engine("summarize")
            elif job.mode == "delta":
                engine = get_engine("delta")
            elif job.mode == "entities":
                engine = get_engine("entities")
            elif job.mode in ("enrich", "sentiment", "tags"):
                # One engine, three entry points: the job's mode says which
                # question the user asked, the engine answers both at once.
                engine = get_engine("enrich")
            elif job.mode == "translate":
                engine = get_engine("translate")
            elif job.mode == "video":
                engine = get_engine("video")
            elif job.mode == "api_discovery":
                engine = get_engine("api_discovery")
            else:
                # Auto-detect based on probe
                engine = get_engine_for_probe(probe_result)
            
            await publish_job_event(job_id, "status", {"status": "running", "engine": engine.name})
            
            # Step 3: Execute engine with rate limiting
            def on_progress(msg: str):
                # Emit WebSocket events for progress updates
                asyncio.create_task(publish_job_event(job_id, "progress", {"message": msg}))
            
            # Apply rate limit before engine execution
            await _global_limiter.acquire()
            
            engine_result = await engine.execute(job, output_dir, on_progress)
            
            # Check for cancellation
            if await is_cancelled(job_id):
                raise CancellationError(f"Job {job_id} was cancelled")
            
            # Step 4: Post-processing pipeline
            job_record.status = JobStatus.PROCESSING
            update_job(job_record)
            await publish_job_event(job_id, "status", {"status": "processing"})
            
            # Rewrite links to be relative
            links_rewritten = await rewrite_links(output_dir)
            await publish_job_event(job_id, "progress", {"message": "Links rewritten"})
            
            # Remove tracking scripts
            trackers_removed = await clean_privacy(output_dir)
            await publish_job_event(job_id, "progress", {"message": "Privacy cleaned"})

            # Visit every HTML page in a browser: a screenshot of each, and — for the
            # modes that are about design — the tokens of the entry page. Both come
            # out of the same visit, so the browser opens once.
            if on_progress:
                on_progress("Capturando telas...")
            wants_design = job.mode in DESIGN_MODES
            capture = await take_screenshots(output_dir, design=wants_design)
            await publish_job_event(job_id, "progress", {"message": "Screenshots taken"})

            # A capture that knows its own design becomes a reference in the catalog.
            if wants_design and capture.tokens is not None:
                card = register_reference(
                    url=str(job.url),
                    mode=job.mode,
                    engine=engine.name,
                    tokens=capture.tokens,
                    screenshot=capture.entry_screenshot,
                    job_id=job_id,
                    tags=job.card_tags,
                )
                if card is not None:
                    await publish_job_event(
                        job_id, "progress", {"message": f"Referência registrada: {card.id[:8]}"}
                    )

            # Scan cloned content for malware/phishing indicators.
            # A scan failure must never fail the job.
            if settings.safety_enabled:
                try:
                    from zfrog.pipeline.safety import scan_directory

                    report = scan_directory(output_dir, str(job.url))
                    if report.findings:
                        logger.warning(
                            "safety scan: %s (%d achado(s)) em %s",
                            report.risk,
                            len(report.findings),
                            job.url,
                        )
                        await publish_job_event(
                            job_id,
                            "progress",
                            {"message": f"Segurança: risco {report.risk} ({len(report.findings)} achado(s))"},
                        )
                except Exception as e:
                    logger.warning("varredura de segurança falhou: %s", e)

            # Package output as ZIP (includes screenshots)
            zip_path = output_dir / "archive.zip"
            await package_zip(output_dir, zip_path)
            await publish_job_event(job_id, "progress", {"message": "Packaged as ZIP"})
            
            # Calculate results
            duration = time.time() - start_time
            total_bytes = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file())
            files_count = len([f for f in output_dir.rglob("*") if f.is_file()])
            
            # Create result
            result = JobResult(
                job_id=job_id,
                output_path=str(zip_path),
                files_count=files_count,
                total_size_bytes=total_bytes,
                engine_used=engine.name,
                duration_seconds=duration,
            )
            
            update_result(result)

            # Record per-engine metrics (success rate, throughput, timing).
            # Metrics must never break a job.
            try:
                from zfrog.analytics import MetricsStore

                MetricsStore().record(
                    engine=engine.name,
                    status="completed",
                    duration_s=duration,
                    total_bytes=total_bytes,
                    files=files_count,
                    url=str(job.url),
                    mode=job.mode,
                )
            except Exception as e:
                logger.warning("registro de métricas falhou: %s", e)

            
            # Step 5: Record a versioned snapshot for change detection.
            # A snapshot failure must never fail the job.
            if job.mode in ("auto", "mirror", "scrape", "delta"):
                try:
                    from zfrog.diff import capture_snapshot, maybe_alert

                    new_snap, prev_snap = capture_snapshot(output_dir, str(job.url), engine.name)
                    await maybe_alert(str(job.url), new_snap, prev_snap)
                    await publish_job_event(job_id, "progress", {"message": "Snapshot salvo"})

                    # Content-aware second opinion: a footer date bump and a price
                    # change both count as "changed pages" above, but only one of
                    # them is worth waking someone up for.
                    if prev_snap is not None:
                        from zfrog.ai.significance import significant_change

                        verdict = await significant_change(str(job.url), prev_snap, new_snap)
                        if verdict and verdict.get("significant"):
                            logger.info(
                                "mudança significativa em %s (%.2f): %s",
                                job.url,
                                verdict.get("score", 0.0),
                                verdict.get("summary", ""),
                            )
                            await publish_job_event(
                                job_id,
                                "progress",
                                {"message": f"Mudança relevante: {verdict.get('summary', '')}"[:200]},
                            )

                    if job.versioned:
                        from zfrog.versioning import VersionStore

                        version = VersionStore().commit(
                            str(job.url),
                            new_snap,
                            output_dir,
                            message=f"{engine.name} run",
                        )
                        await publish_job_event(
                            job_id, "progress", {"message": f"Versão {version.id} salva"}
                        )
                except Exception as e:
                    logger.warning("snapshot falhou: %s", e)
            
            # Update job status
            job_record.status = JobStatus.COMPLETED
            update_job(job_record)
            await publish_job_event(job_id, "completed", {
                "output_path": result.output_path,
                "files_count": result.files_count,
                "total_size_bytes": result.total_size_bytes,
                "duration_seconds": result.duration_seconds,
            })
            
            # Send webhook notification
            await notify_job_completed(result)
            
            return result
            
        finally:
            # Release concurrency slot
            _global_concurrency.release()
        
    except CancellationError as e:
        job_record.status = JobStatus.CANCELLED
        job_record.error = str(e)
        update_job(job_record)
        await publish_job_event(job_id, "cancelled", {"error": str(e)})
        await notify_job_failed(job_id, str(e))
        raise
    except Exception as e:
        job_record.status = JobStatus.FAILED
        job_record.error = str(e)
        update_job(job_record)
        await publish_job_event(job_id, "error", {"error": str(e)})
        await notify_job_failed(job_id, str(e))
        raise
    finally:
        if client:
            await client.aclose()


def create_and_run_job_sync(job: JobCreate) -> JobResult:
    """Synchronous wrapper for run_job (for Celery tasks)."""
    return asyncio.run(run_job(job))
