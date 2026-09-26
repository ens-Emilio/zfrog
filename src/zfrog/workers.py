"""Worker registry: which workers exist, where they are, and who gets the next job.

``zfrog.regions`` decides *where* work should run; this module is the other half:
it keeps a live inventory of the worker processes themselves, learns about them
through heartbeats, and hands a job to one of them.

Design notes:

* The registry is one small JSON file (``settings.output_dir / "workers.json"``
  by default) written atomically through a temporary file plus :func:`os.replace`
  and created with mode ``0o600``.
* A corrupt registry file is never fatal: it is reported with a warning and
  treated as empty, because losing the worker inventory must not break a job.
* Liveness is derived from ``last_seen`` and ``settings.workers_heartbeat_ttl_s``;
  :meth:`WorkerRegistry.reap` removes the workers whose heartbeat expired.
* :func:`heartbeat_loop` is what a worker process runs in the background, and
  :func:`ready_workers_for` is the query an autoscaler can poll.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from zfrog.config import settings
from zfrog.regions import route

logger = logging.getLogger(__name__)

#: Mode the registry file is created with (owner read/write only).
REGISTRY_FILE_MODE = 0o600

#: Name of the registry file inside ``settings.output_dir``.
REGISTRY_FILE_NAME = "workers.json"

#: Default region for a worker whose process did not advertise one.
DEFAULT_REGION = "local"

#: Reason returned when there is nothing to assign the job to.
NO_WORKER_REASON = "nenhum worker disponível"


@dataclass
class Worker:
    """One worker process: where it runs and how much work it is carrying."""

    id: str
    region: str
    capacity: int
    running: int
    last_seen: str
    started_at: str
    version: str = ""
    tags: list[str] = field(default_factory=list)
    enabled: bool = True

    def free(self) -> int:
        """Capacity still available on this worker (never negative)."""
        return max(0, self.capacity - self.running)


@dataclass
class Assignment:
    """The outcome of an assignment: who takes the job, where, and why."""

    worker: Worker | None
    region: str
    reason: str


def _now() -> str:
    """Current instant as an ISO-8601 UTC string."""
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: object) -> datetime | None:
    """Parse a stored timestamp; ``None`` when it is missing or unreadable.

    Naive timestamps are assumed to be UTC, so a hand-edited file still works.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_int(value: object, default: int) -> int:
    """Best-effort integer coercion for hand-edited records."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _as_tags(value: object) -> list[str]:
    """Normalise the ``tags`` field to a list of non-empty strings."""
    if isinstance(value, str):
        value = [part for part in value.split(",")]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def current_worker_id() -> str:
    """Identity of this process as a worker.

    ``settings.worker_id`` wins when configured; otherwise a stable id is derived
    from the hostname and the pid, so a worker that forgets to configure one still
    gets a usable identity instead of an empty string.
    """
    configured = (settings.worker_id or "").strip()
    if configured:
        return configured
    return f"{socket.gethostname()}-{os.getpid()}"


def _default_path() -> Path:
    """Registry location: ``settings.output_dir / "workers.json"``."""
    return Path(settings.output_dir) / REGISTRY_FILE_NAME


class WorkerRegistry:
    """JSON-backed inventory of workers, with heartbeats and region-aware picking."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_path()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Worker]:
        """Read the registry; a missing or corrupt file yields an empty inventory."""
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Registro de workers ilegível em %s (%s); tratando como vazio", self.path, exc)
            return {}
        if not isinstance(raw, list):
            logger.warning("Registro de workers inválido em %s (esperado uma lista); tratando como vazio", self.path)
            return {}

        workers: dict[str, Worker] = {}
        for item in raw:
            worker = self._from_record(item)
            if worker is None:
                logger.warning("Registro de workers em %s tem um item inválido; item ignorado", self.path)
                continue
            workers[worker.id] = worker
        return workers

    def _from_record(self, item: object) -> Worker | None:
        """Build a :class:`Worker` from one JSON record; ``None`` when unusable."""
        if not isinstance(item, dict):
            return None
        worker_id = str(item.get("id") or "").strip()
        region = str(item.get("region") or "").strip()
        if not worker_id or not region:
            return None
        started_at = item.get("started_at")
        last_seen = item.get("last_seen")
        return Worker(
            id=worker_id,
            region=region,
            capacity=max(0, _as_int(item.get("capacity"), 1)),
            running=max(0, _as_int(item.get("running"), 0)),
            last_seen=str(last_seen) if isinstance(last_seen, str) else _now(),
            started_at=str(started_at) if isinstance(started_at, str) else _now(),
            version=str(item.get("version") or ""),
            tags=_as_tags(item.get("tags")),
            enabled=bool(item.get("enabled", True)),
        )

    def _save(self, workers: dict[str, Worker]) -> None:
        """Write the whole inventory atomically (temp file + ``os.replace``), mode 0600."""
        payload = json.dumps(
            [asdict(workers[worker_id]) for worker_id in sorted(workers)],
            indent=2,
            ensure_ascii=False,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)

        handle_fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, REGISTRY_FILE_MODE)
            os.replace(temp_name, self.path)
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise

    # ── membership ───────────────────────────────────────────────────────────

    def register(
        self,
        worker_id: str,
        region: str,
        capacity: int = 1,
        version: str = "",
        tags: list[str] | None = None,
    ) -> Worker:
        """Create a worker, or refresh the existing one, and return it.

        A refresh keeps ``started_at`` (the process has been around since then),
        the current ``running`` count and, when ``tags`` is not given, the tags
        already stored — the caller is announcing itself, not resetting its state.
        """
        worker_id = str(worker_id).strip()
        if not worker_id:
            raise ValueError("worker_id não pode ser vazio")
        region = str(region).strip() or DEFAULT_REGION
        capacity = max(0, _as_int(capacity, 1))
        now = _now()

        workers = self._load()
        existing = workers.get(worker_id)
        if existing is None:
            worker = Worker(
                id=worker_id,
                region=region,
                capacity=capacity,
                running=0,
                last_seen=now,
                started_at=now,
                version=str(version or ""),
                tags=_as_tags(tags),
            )
        else:
            worker = Worker(
                id=existing.id,
                region=region,
                capacity=capacity,
                running=existing.running,
                last_seen=now,
                started_at=existing.started_at,
                version=str(version or ""),
                tags=existing.tags if tags is None else _as_tags(tags),
                enabled=existing.enabled,
            )
        workers[worker_id] = worker
        self._save(workers)
        return worker

    def heartbeat(self, worker_id: str, running: int | None = None) -> Worker:
        """Refresh ``last_seen`` (and ``running`` when given); unknown worker -> ValueError."""
        workers = self._load()
        worker = workers.get(str(worker_id))
        if worker is None:
            raise ValueError(f"worker desconhecido: {worker_id}")

        worker.last_seen = _now()
        if running is not None:
            worker.running = max(0, _as_int(running, worker.running))
        self._save(workers)
        return worker

    def unregister(self, worker_id: str) -> bool:
        """Remove a worker; ``True`` when it existed."""
        workers = self._load()
        if workers.pop(str(worker_id), None) is None:
            return False
        self._save(workers)
        return True

    def get(self, worker_id: str) -> Worker | None:
        """One worker by id, or ``None``."""
        return self._load().get(str(worker_id))

    def list(self, region: str | None = None, alive_only: bool = True) -> list[Worker]:
        """Workers, optionally filtered by region and by liveness, sorted by id."""
        workers = self._load()
        selected = [
            worker
            for worker in workers.values()
            if (region is None or worker.region == region) and (not alive_only or self._is_alive(worker))
        ]
        return sorted(selected, key=lambda worker: worker.id)

    def alive(self, worker_id: str) -> bool:
        """Whether a known worker heartbeated within the configured TTL."""
        worker = self._load().get(str(worker_id))
        return worker is not None and self._is_alive(worker)

    def reap(self) -> list[str]:
        """Drop the workers whose heartbeat expired; returns the removed ids."""
        workers = self._load()
        expired = sorted(worker_id for worker_id, worker in workers.items() if not self._is_alive(worker))
        if not expired:
            return []
        for worker_id in expired:
            del workers[worker_id]
        self._save(workers)
        logger.info("Removidos %d workers sem heartbeat: %s", len(expired), ", ".join(expired))
        return expired

    # ── assignment ───────────────────────────────────────────────────────────

    def assign(self, url: str, preferred_region: str | None = None) -> Assignment:
        """Pick the worker that should take ``url``.

        The region comes from :func:`zfrog.regions.route` unless ``preferred_region``
        is given. Inside that region the alive, enabled worker with the most free
        capacity wins, ties broken by id so the answer is deterministic. When the
        region has no such worker the job falls back to any alive, enabled worker
        elsewhere and the reason says so; with no worker at all the assignment
        carries ``worker=None``.
        """
        region = str(preferred_region).strip() if preferred_region else ""
        if not region:
            region = route(url).region

        local = self._pick(self.list(region=region, alive_only=True))
        if local is not None:
            return Assignment(
                worker=local,
                region=region,
                reason=f"worker {local.id} na região {region} (livre: {local.free()}/{local.capacity})",
            )

        elsewhere = self._pick(
            [worker for worker in self.list(alive_only=True) if worker.region != region]
        )
        if elsewhere is not None:
            return Assignment(
                worker=elsewhere,
                region=elsewhere.region,
                reason=(
                    f"nenhum worker vivo em {region}; usando {elsewhere.id} na região "
                    f"{elsewhere.region} (livre: {elsewhere.free()}/{elsewhere.capacity})"
                ),
            )

        return Assignment(worker=None, region=region, reason=NO_WORKER_REASON)

    def _pick(self, candidates: list[Worker]) -> Worker | None:
        """Most free capacity among usable workers, ties broken by id."""
        usable = [worker for worker in candidates if worker.enabled]
        if not usable:
            return None
        return min(usable, key=lambda worker: (-worker.free(), worker.id))

    # ── job lifecycle ────────────────────────────────────────────────────────

    def start(self, worker_id: str) -> Worker:
        """Account one more running job on ``worker_id`` and refresh its heartbeat."""
        workers = self._load()
        worker = workers.get(str(worker_id))
        if worker is None:
            raise ValueError(f"worker desconhecido: {worker_id}")

        worker.running += 1
        worker.last_seen = _now()
        self._save(workers)
        return worker

    def finish(self, worker_id: str) -> Worker:
        """Account one finished job on ``worker_id``; ``running`` never goes below 0."""
        workers = self._load()
        worker = workers.get(str(worker_id))
        if worker is None:
            raise ValueError(f"worker desconhecido: {worker_id}")

        worker.running = max(0, worker.running - 1)
        worker.last_seen = _now()
        self._save(workers)
        return worker

    def stats(self) -> dict[str, object]:
        """Totals of the registry.

        ``workers`` counts everything registered; ``capacity``, ``running``,
        ``free`` and ``by_region`` describe the *alive* workers only, because
        capacity sitting on a worker that stopped heartbeating is not capacity
        this scheduler can use.
        """
        everyone = self.list(alive_only=False)
        alive = self.list(alive_only=True)

        by_region: dict[str, dict[str, int]] = {}
        for worker in alive:
            bucket = by_region.setdefault(
                worker.region, {"workers": 0, "capacity": 0, "running": 0, "free": 0}
            )
            bucket["workers"] += 1
            bucket["capacity"] += worker.capacity
            bucket["running"] += worker.running
            bucket["free"] += worker.free()

        return {
            "workers": len(everyone),
            "alive": len(alive),
            "capacity": sum(worker.capacity for worker in alive),
            "running": sum(worker.running for worker in alive),
            "free": sum(worker.free() for worker in alive),
            "by_region": by_region,
        }

    # ── liveness ─────────────────────────────────────────────────────────────

    def _is_alive(self, worker: Worker) -> bool:
        """Whether ``worker`` heartbeated within ``settings.workers_heartbeat_ttl_s``."""
        seen = _parse_time(worker.last_seen)
        if seen is None:
            logger.warning("Worker %s tem last_seen inválido (%r); considerado expirado", worker.id, worker.last_seen)
            return False
        ttl = max(0, int(settings.workers_heartbeat_ttl_s))
        return (datetime.now(timezone.utc) - seen).total_seconds() <= ttl


def ready_workers_for(region: str, registry: WorkerRegistry | None = None) -> list[Worker]:
    """Alive, enabled workers in ``region`` that still have free capacity.

    This is the query an operator (for instance the Kubernetes one) can poll to
    decide whether a region needs more workers, or has too many idle ones.
    """
    store = registry if registry is not None else WorkerRegistry()
    return [worker for worker in store.list(region=region, alive_only=True) if worker.enabled and worker.free() > 0]


async def heartbeat_loop(
    worker_id: str,
    interval_s: int = 20,
    stop_event: asyncio.Event | None = None,
    registry: WorkerRegistry | None = None,
) -> None:
    """Announce ``worker_id`` and keep its heartbeat fresh until stopped.

    The first iteration registers the worker if it is unknown (or was reaped) and
    then heartbeats it, so a worker process can simply run this in the background.
    Any registry error is logged and retried on the next tick — a registry hiccup
    must never take the worker down.
    """
    store = registry if registry is not None else WorkerRegistry()
    stop = stop_event if stop_event is not None else asyncio.Event()
    region = (settings.region or "").strip() or DEFAULT_REGION

    while not stop.is_set():
        try:
            if store.get(worker_id) is None:
                store.register(worker_id, region)
            store.heartbeat(worker_id)
        except Exception as exc:  # noqa: BLE001 - a heartbeat must never raise
            logger.warning("Falha ao registrar heartbeat do worker %s: %s", worker_id, exc)

        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.0, float(interval_s)))
        except TimeoutError:
            continue
        return
