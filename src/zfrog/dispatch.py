"""Hand a job to a worker: POST it to the worker's API and hold its slot.

:mod:`zfrog.workers` knows which workers exist, where they run and who should
take the next job; :mod:`zfrog.regions` decides the region. This module closes
the loop: it turns an :class:`~zfrog.workers.Assignment` into an HTTP call,
accounts the job on the worker while it runs and releases the slot when the
caller says the job is done.

Nothing here raises for the ordinary unhappy paths (no worker, unreachable
host, a worker answering nonsense): every outcome is a
:class:`DispatchResult` the caller can print or count.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import Any, Final

import httpx

from zfrog.config import settings
from zfrog.workers import Worker, WorkerRegistry

logger = logging.getLogger(__name__)

#: Path the worker API accepts a job on.
JOBS_PATH: Final[str] = "/jobs"

#: Mode used when the caller does not pick one.
DEFAULT_MODE: Final[str] = "mirror"

#: Crawl depth used when the caller does not pick one.
DEFAULT_MAX_DEPTH: Final[int] = 3

#: Host used when a worker record somehow carries no id.
DEFAULT_HOST: Final[str] = "localhost"

#: Fallback scheme when neither the caller nor the settings name one.
DEFAULT_SCHEME: Final[str] = "http"


@dataclass
class DispatchResult:
    """What happened to one job: who took it, and whether they took it at all."""

    job_id: str
    worker: str
    region: str
    accepted: bool
    detail: str


def _is_ipv6(host: str) -> bool:
    """Whether ``host`` is a bare IPv6 address (which must be bracketed in a URL)."""
    try:
        return isinstance(ipaddress.ip_address(host.strip("[]")), ipaddress.IPv6Address)
    except ValueError:
        return False


def _authority(host: str, port: int) -> str:
    """``host[:port]`` for a URL, keeping a port the id already carries."""
    if _is_ipv6(host):
        return f"[{host.strip('[]')}]:{port}"
    if ":" in host:
        # The id already carries its own port (``10.0.0.7:9000``): it wins.
        return host
    return f"{host}:{port}"


def worker_base_url(worker: Worker, scheme: str = "", port: int = 0) -> str:
    """The API base URL of ``worker``, without a trailing slash.

    The worker id doubles as the address: a deployment either sets
    ``ZFROG_WORKER_ID`` to something resolvable (``worker-a.sa-east.internal``)
    or puts the address itself in the id (``10.0.0.7``, ``10.0.0.7:9000``).
    An id that carries its own port keeps it. ``scheme`` and ``port`` default
    to ``settings.worker_api_scheme`` / ``settings.worker_api_port``.
    """
    host = str(worker.id or "").strip() or DEFAULT_HOST
    if not str(worker.id or "").strip():
        logger.warning("worker sem id; usando %s como host", DEFAULT_HOST)

    resolved_scheme = (scheme or settings.worker_api_scheme or DEFAULT_SCHEME).strip()
    resolved_scheme = resolved_scheme.rstrip(":/") or DEFAULT_SCHEME
    resolved_port = int(port or settings.worker_api_port)

    return f"{resolved_scheme}://{_authority(host, resolved_port)}"


def _as_depth(value: object) -> int:
    """Crawl depth from a job dict; anything unreadable falls back to the default."""
    if isinstance(value, bool):
        return DEFAULT_MAX_DEPTH
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_MAX_DEPTH


def _job_url(job: dict) -> str:
    """The URL a job dict targets (empty when the job is malformed)."""
    return str(job.get("url") or "").strip()


def _region_of(job: dict, fallback: str | None) -> str | None:
    """Region hint of one job, falling back to the batch-level preference."""
    hinted = str(job.get("preferred_region") or "").strip()
    if hinted:
        return hinted
    text = str(fallback or "").strip()
    return text or None


class Dispatcher:
    """Sends jobs to the workers the registry picks, over HTTP.

    The registry decides; this class only talks to the winner. A transport
    error, a non-2xx answer or a response without a ``job_id`` leaves the
    worker's slot untouched, so the registry keeps its capacity honest.
    """

    def __init__(
        self,
        registry: WorkerRegistry | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: int | None = None,
    ) -> None:
        self.registry = registry if registry is not None else WorkerRegistry()
        self._client = client
        self._owns_client = client is None
        self.timeout_s = int(settings.dispatch_timeout_s if timeout_s is None else timeout_s)

    # ── HTTP plumbing ────────────────────────────────────────────────────────

    def _ensure_client(self) -> httpx.AsyncClient:
        """Return the injected client, or build and cache one we own."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True)
            self._owns_client = True
        return self._client

    @property
    def client(self) -> httpx.AsyncClient:
        """The HTTP client, created on first use and reused afterwards."""
        return self._ensure_client()

    async def aclose(self) -> None:
        """Close the client, but only when this dispatcher created it."""
        if self._client is None or not self._owns_client:
            return
        client, self._client, self._owns_client = self._client, None, False
        await client.aclose()

    # ── sending ──────────────────────────────────────────────────────────────

    async def send(
        self,
        url: str,
        mode: str = DEFAULT_MODE,
        max_depth: int = DEFAULT_MAX_DEPTH,
        preferred_region: str | None = None,
        extra: dict | None = None,
    ) -> DispatchResult:
        """Send one job for ``url`` to the worker the registry picks.

        Never raises for an unavailable worker: an empty registry, a refused
        connection, an error status or a body without a ``job_id`` all come
        back as ``accepted=False`` with the reason in ``detail``. On
        acceptance the worker is marked busy with
        :meth:`~zfrog.workers.WorkerRegistry.start`, so the caller must call
        :meth:`complete` once the job is over.
        """
        assignment = self.registry.assign(url, preferred_region)
        worker = assignment.worker
        if worker is None:
            logger.info("no worker for %s: %s", url, assignment.reason)
            return DispatchResult("", "", assignment.region, False, assignment.reason)

        payload: dict[str, Any] = {"url": url, "mode": mode, "max_depth": max_depth}
        if extra:
            payload.update(extra)

        endpoint = f"{worker_base_url(worker)}{JOBS_PATH}"
        try:
            response = await self._ensure_client().post(endpoint, json=payload)
        except httpx.HTTPError as exc:
            logger.warning("failed to send to %s: %s", worker.id, exc)
            detail = f"failed to contact worker {worker.id}: {exc}"
            return DispatchResult("", worker.id, worker.region, False, detail)

        if not 200 <= response.status_code < 300:
            return DispatchResult(
                "",
                worker.id,
                worker.region,
                False,
                f"worker {worker.id} returned HTTP {response.status_code}",
            )

        job_id = self._job_id(response)
        if not job_id:
            return DispatchResult(
                "",
                worker.id,
                worker.region,
                False,
                f"worker {worker.id} accepted the request but returned no job_id",
            )

        try:
            self.registry.start(worker.id)
        except ValueError as exc:
            detail = f"worker unavailable: {exc}"
            return DispatchResult("", worker.id, worker.region, False, detail)

        return DispatchResult(
            job_id,
            worker.id,
            worker.region,
            True,
            f"job {job_id} accepted by {worker.id} in region {worker.region}",
        )

    @staticmethod
    def _job_id(response: httpx.Response) -> str:
        """The ``job_id`` of a worker's answer; empty when it did not send one."""
        try:
            body = response.json()
        except ValueError:
            return ""
        if not isinstance(body, dict):
            return ""
        return str(body.get("job_id") or "").strip()

    async def send_many(
        self, jobs: list[dict], preferred_region: str | None = None
    ) -> list[DispatchResult]:
        """Send every job, one result per job and in order.

        A job that fails does not stop the ones after it: an unreachable
        worker, an error status or a malformed job dict only shows up in that
        job's own result. Each job may carry ``url``, ``mode``, ``max_depth``,
        ``extra`` and its own ``preferred_region``.
        """
        results: list[DispatchResult] = []
        for job in jobs:
            try:
                results.append(await self._send_job(job, preferred_region))
            except Exception as exc:  # one broken job must not sink the batch
                logger.warning("job discarded in batch send: %s", exc)
                results.append(DispatchResult("", "", "", False, f"invalid job: {exc}"))
        return results

    async def _send_job(self, job: dict, preferred_region: str | None) -> DispatchResult:
        """Send one entry of a batch, reading its per-job options."""
        if not isinstance(job, dict):
            return DispatchResult("", "", "", False, "invalid job: expected a dict")
        url = _job_url(job)
        if not url:
            return DispatchResult("", "", "", False, "job without url")

        extra = job.get("extra")
        return await self.send(
            url,
            mode=str(job.get("mode") or DEFAULT_MODE),
            max_depth=_as_depth(job.get("max_depth")),
            preferred_region=_region_of(job, preferred_region),
            extra=extra if isinstance(extra, dict) else None,
        )

    async def complete(self, worker_id: str) -> None:
        """Release the slot ``worker_id`` was holding for a finished job.

        A worker that left the registry in the meantime is only logged: the
        caller is releasing a slot, not asserting that it still exists.
        """
        try:
            self.registry.finish(str(worker_id))
        except ValueError:
            logger.warning("worker %s is no longer in the registry; nothing to release", worker_id)


def plan_dispatch(jobs: list[dict], registry: WorkerRegistry | None = None) -> list[dict]:
    """Dry run: where each job *would* go, and why, with no network call.

    Backs a ``--dry-run`` flag: the registry is consulted exactly as
    :meth:`Dispatcher.send` would, but nothing is sent and no slot is taken.
    """
    store = registry if registry is not None else WorkerRegistry()
    plans: list[dict] = []
    for job in jobs:
        entry = job if isinstance(job, dict) else {}
        url = _job_url(entry)
        assignment = store.assign(url, _region_of(entry, None))
        worker = assignment.worker
        plans.append(
            {
                "url": url,
                "worker": worker.id if worker is not None else "",
                "region": worker.region if worker is not None else assignment.region,
                "target": worker_base_url(worker) if worker is not None else "",
                "accepted": worker is not None,
                "reason": assignment.reason,
            }
        )
    return plans


def dispatch_summary(results: list[DispatchResult]) -> str:
    """One sentence: how many were accepted, where, how many failed."""
    if not results:
        return "No jobs to send."

    accepted = [result for result in results if result.accepted]
    failed = len(results) - len(accepted)

    by_region: dict[str, int] = {}
    for result in accepted:
        by_region[result.region or "?"] = by_region.get(result.region or "?", 0) + 1

    if not accepted:
        head = (
            "No jobs were accepted"
            if len(results) == 1
            else f"None of the {len(results)} jobs were accepted"
        )
    else:
        regions = ", ".join(f"{region}: {count}" for region, count in sorted(by_region.items()))
        head = f"{len(accepted)} of {len(results)} jobs accepted ({regions})"

    if not failed:
        tail = ""
    elif failed == 1:
        tail = "; 1 failed"
    else:
        tail = f"; {failed} failed"

    return f"{head}{tail}."
