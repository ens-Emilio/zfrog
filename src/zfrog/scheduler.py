"""Recurring schedules: a JSON-backed store plus the loop that fires jobs.

A schedule pairs a cron expression with the URL/mode of the job it should start.
`daemon` polls the store every `settings.scheduler_interval_s` seconds and hands
every due schedule to `zfrog.orchestrator.run_job` as a fire-and-forget task.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from zfrog.config import settings
from zfrog.cron import parse_cron
from zfrog.models import JobCreate
from zfrog.orchestrator import run_job

logger = logging.getLogger(__name__)

_ID_LENGTH = 8


@dataclass
class Schedule:
    """A recurring job definition."""

    id: str
    cron: str
    url: str
    mode: str
    max_depth: int
    enabled: bool = True
    last_run: str | None = None
    next_run: str | None = None


def _as_utc(value: datetime | None) -> datetime | None:
    """Return `value` in UTC, assuming UTC when it carries no timezone."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def next_run_for(schedule: Schedule, now: datetime | None = None) -> str | None:
    """Return the next firing time of `schedule` as an ISO-8601 UTC string.

    Returns None when the cron expression is invalid or can never fire.
    """
    reference = _as_utc(now) or datetime.now(timezone.utc)
    try:
        cron = parse_cron(schedule.cron)
    except ValueError as exc:
        logger.warning("Schedule %s has invalid cron (%r): %s", schedule.id, schedule.cron, exc)
        return None

    upcoming = cron.next_after(reference)
    if upcoming is None:
        logger.warning("Schedule %s will never run: %r", schedule.id, schedule.cron)
        return None
    return _as_utc(upcoming).isoformat()


def _is_due(schedule: Schedule, now: datetime) -> bool:
    """Return True when `schedule` is enabled and its next run is not in the future."""
    if not schedule.enabled or not schedule.next_run:
        return False
    try:
        upcoming = datetime.fromisoformat(schedule.next_run)
    except ValueError:
        logger.warning("Schedule %s has invalid next_run: %r", schedule.id, schedule.next_run)
        return False
    return _as_utc(upcoming) <= now


class ScheduleStore:
    """JSON-file store of schedules, written atomically on every mutation."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else settings.schedules_file

    def list(self) -> list[Schedule]:
        """Return every stored schedule, in insertion order."""
        if not self.path.exists():
            return []

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid schedules file ({self.path}): {exc}") from exc

        if not isinstance(raw, list):
            raise ValueError(f"invalid schedules file ({self.path}): expected a list")

        return [self._from_dict(item) for item in raw]

    def get(self, id: str) -> Schedule | None:
        """Return the schedule with this id, or None."""
        for schedule in self.list():
            if schedule.id == id:
                return schedule
        return None

    def add(self, cron: str, url: str, mode: str = "auto", max_depth: int = 3) -> Schedule:
        """Create and persist a schedule.

        Raises:
            ValueError: when `cron` is not a valid five-field cron expression.
        """
        parse_cron(cron)

        schedule = Schedule(
            id=uuid.uuid4().hex[:_ID_LENGTH],
            cron=cron,
            url=url,
            mode=mode,
            max_depth=max_depth,
        )
        schedule.next_run = next_run_for(schedule)

        schedules = self.list()
        schedules.append(schedule)
        self._save(schedules)
        return schedule

    def update(self, schedule: Schedule) -> bool:
        """Replace the stored schedule with the same id, persisting the change."""
        schedules = self.list()
        for index, existing in enumerate(schedules):
            if existing.id == schedule.id:
                schedules[index] = schedule
                self._save(schedules)
                return True
        return False

    def remove(self, id: str) -> bool:
        """Delete a schedule; return False when the id is unknown."""
        schedules = self.list()
        remaining = [schedule for schedule in schedules if schedule.id != id]
        if len(remaining) == len(schedules):
            return False
        self._save(remaining)
        return True

    def set_enabled(self, id: str, enabled: bool) -> bool:
        """Enable or disable a schedule; return False when the id is unknown.

        Re-enabling recomputes `next_run` from now, so a schedule paused for a long
        time does not fire immediately for every slot it missed.
        """
        schedules = self.list()
        for schedule in schedules:
            if schedule.id == id:
                schedule.enabled = enabled
                if enabled:
                    schedule.next_run = next_run_for(schedule)
                self._save(schedules)
                return True
        return False

    def _from_dict(self, item: object) -> Schedule:
        """Build a Schedule from one JSON record."""
        if not isinstance(item, dict):
            raise ValueError(f"invalid schedules file ({self.path}): record is not an object")

        missing = [key for key in ("id", "cron", "url") if not item.get(key)]
        if missing:
            raise ValueError(
                f"invalid schedules file ({self.path}): missing fields {', '.join(missing)}"
            )

        return Schedule(
            id=str(item["id"]),
            cron=str(item["cron"]),
            url=str(item["url"]),
            mode=str(item.get("mode", "auto")),
            max_depth=int(item.get("max_depth", 3)),
            enabled=bool(item.get("enabled", True)),
            last_run=item.get("last_run"),
            next_run=item.get("next_run"),
        )

    def _save(self, schedules: list[Schedule]) -> None:
        """Write the whole list atomically (temp file + os.replace)."""
        payload = json.dumps([asdict(schedule) for schedule in schedules], indent=2, ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        handle_fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise


def due_schedules(now: datetime | None = None) -> list[Schedule]:
    """Return the enabled schedules whose next run has already arrived."""
    reference = _as_utc(now) or datetime.now(timezone.utc)
    return [schedule for schedule in ScheduleStore().list() if _is_due(schedule, reference)]


def _log_job_result(schedule_id: str, job_id: str, task: asyncio.Task) -> None:
    """Report the outcome of a scheduled job; never raises into the event loop."""
    if task.cancelled():
        logger.warning("Job %s of schedule %s was cancelled", job_id, schedule_id)
        return

    error = task.exception()
    if error is not None:
        logger.error("Job %s of schedule %s failed: %s", job_id, schedule_id, error)
        return

    result = task.result()
    logger.info(
        "Job %s of schedule %s completed (job %s): %s file(s)",
        job_id,
        schedule_id,
        getattr(result, "job_id", "-"),
        getattr(result, "files_count", "-"),
    )


async def run_due(now: datetime | None = None) -> list[str]:
    """Start a job for every due schedule and return the scheduler's job ids.

    Each job runs as its own task: a failure is logged and never propagates, so one
    broken schedule cannot stop the others. `last_run` is stamped and `next_run` is
    recomputed from `now` before the job starts, which keeps the loop from firing the
    same slot twice.
    """
    reference = _as_utc(now) or datetime.now(timezone.utc)
    store = ScheduleStore()
    job_ids: list[str] = []

    for schedule in due_schedules(reference):
        try:
            job = JobCreate(url=schedule.url, mode=schedule.mode, max_depth=schedule.max_depth)
        except Exception as exc:
            logger.error("Schedule %s has invalid destination (%s): %s", schedule.id, schedule.url, exc)
            continue

        job_id = str(uuid.uuid4())
        schedule.last_run = reference.isoformat()
        schedule.next_run = next_run_for(schedule, reference)
        store.update(schedule)

        task = asyncio.create_task(run_job(job))
        task.add_done_callback(partial(_log_job_result, schedule.id, job_id))
        job_ids.append(job_id)
        logger.info("Schedule %s triggered job %s (%s)", schedule.id, job_id, schedule.url)

    return job_ids


async def daemon(interval_s: int | None = None, stop_event: asyncio.Event | None = None) -> None:
    """Poll the schedule store forever, firing due jobs every `interval_s` seconds.

    Exits as soon as `stop_event` is set. Errors from a single poll are logged and
    the loop keeps going.
    """
    interval = settings.scheduler_interval_s if interval_s is None else interval_s
    timeout = interval if interval and interval > 0 else 0.001
    stop = stop_event if stop_event is not None else asyncio.Event()

    logger.info("Scheduler started — checking every %ss", interval)
    while not stop.is_set():
        try:
            await run_due()
        except Exception:
            logger.exception("Failed to check schedules")

        try:
            await asyncio.wait_for(stop.wait(), timeout=timeout)
        except TimeoutError:
            continue
        break

    logger.info("Scheduler stopped")
