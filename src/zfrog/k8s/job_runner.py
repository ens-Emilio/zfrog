"""Entry point for child Jobs created by the operator.

The operator's ``build_job_manifest`` injects ZFROG_JOB_* env vars into each
Job. Without a command the container would start the Dockerfile CMD
(``uvicorn zfrog.api``) and never run the crawl. This module is the command:
``python -m zfrog.k8s.job_runner`` reads those env vars and runs the job
via the orchestrator.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    return v.strip()


def main() -> int:
    url = _env("ZFROG_JOB_URL")
    if not url:
        print("ZFROG_JOB_URL is required (set by the operator)", file=sys.stderr)
        return 2
    mode = _env("ZFROG_JOB_MODE", "mirror") or "mirror"
    depth_raw = _env("ZFROG_JOB_MAX_DEPTH", "1") or "1"
    try:
        max_depth = int(depth_raw)
    except ValueError:
        print(f"ZFROG_JOB_MAX_DEPTH={depth_raw!r} is not an int", file=sys.stderr)
        return 2

    # Lazy imports so `python -m zfrog.k8s.job_runner --help` style checks
    # do not pay the heavy import cost when the module is only probed.
    from zfrog.models import JobCreate

    from zfrog.orchestrator import create_and_run_job_sync

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("k8s job runner: url=%s mode=%s max_depth=%s", url, mode, max_depth)

    try:
        job = JobCreate(url=url, mode=mode, max_depth=max_depth)  # type: ignore[arg-type]
    except Exception as exc:
        print(f"invalid JobCreate: {exc}", file=sys.stderr)
        return 2

    try:
        result = create_and_run_job_sync(job)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1
    except Exception as exc:
        logger.exception("job failed: %s", exc)
        return 1

    logger.info("job completed: status=%s output=%s", getattr(result, "status", "?"), getattr(result, "output_path", "?"))
    # Success even if the crawl partially failed — the Job's exit code
    # signals infra failure, not content failure. The CR status carries details.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
