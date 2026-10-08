"""Append-only audit trail: who did what, when.

Every mutating action (job created, session removed, config changed, ...) can be
recorded as one JSON object per line in ``settings.audit_log`` (``audit.log`` by
default). The trail is append-only: entries are never rewritten, so a crash can
only ever lose the last line, never corrupt earlier ones.

Design notes:

* The file is created with mode ``0o600`` and re-tightened on every write, because
  entries may contain URLs, job identifiers and client addresses.
* :meth:`AuditLog.write` never raises — auditing must not break the request that
  triggered it. A failed write logs a warning and still returns the entry.
* :meth:`AuditLog.read` skips corrupt lines with a warning; one bad byte cannot make
  the whole trail unreadable.
* :func:`audited` is the helper the API and the CLI wrap around mutating calls: it
  writes an ``ok`` entry when the block succeeds and an ``error`` entry when it
  raises, then re-raises.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from zfrog.config import settings

logger = logging.getLogger(__name__)

#: Longest ``User-Agent`` kept when no address header is available.
USER_AGENT_MAX = 80

#: Mode the trail file is created with (owner read/write only).
LOG_FILE_MODE = 0o600

#: Actor used when the request carries nothing identifying.
FALLBACK_ACTOR = "local"


def _header(headers: Mapping[str, str] | None, name: str) -> str:
    """Case-insensitive header lookup returning a stripped value."""
    if not headers:
        return ""
    for key, value in headers.items():
        if str(key).lower() == name:
            return str(value or "").strip()
    return ""


def client_identity(headers: Mapping[str, str] | None = None, fallback: str = "local") -> str:
    """Best-effort actor for a request, never an empty string.

    Preference order: the first hop of ``X-Forwarded-For``, then ``X-Real-IP``,
    then the ``User-Agent`` truncated to :data:`USER_AGENT_MAX` characters, then
    ``fallback`` (which itself falls back to ``"local"``).
    """
    forwarded = _header(headers, "x-forwarded-for")
    if forwarded:
        hop = forwarded.split(",")[0].strip()
        if hop:
            return hop

    real_ip = _header(headers, "x-real-ip")
    if real_ip:
        return real_ip

    agent = _header(headers, "user-agent")
    if agent:
        return agent[:USER_AGENT_MAX]

    return fallback.strip() or FALLBACK_ACTOR


@dataclass
class AuditEntry:
    """One recorded action."""

    timestamp: str
    action: str
    actor: str
    target: str
    outcome: str
    detail: str
    metadata: dict = field(default_factory=dict)


class AuditLog:
    """JSONL audit trail stored at ``path`` (``settings.audit_log`` by default)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else Path(settings.audit_log)

    # ── writing ──

    def write(
        self,
        action: str,
        actor: str = "local",
        target: str = "",
        outcome: str = "ok",
        detail: str = "",
        metadata: dict | None = None,
    ) -> AuditEntry:
        """Append one entry and return it. Never raises."""
        try:
            extra = dict(metadata) if metadata else {}
        except (TypeError, ValueError):
            logger.warning("Invalid metadata in audit entry for %s: %r", action, metadata)
            extra = {}

        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action=str(action),
            actor=str(actor or FALLBACK_ACTOR),
            target=str(target or ""),
            outcome=str(outcome or "ok"),
            detail=str(detail or ""),
            metadata=extra,
        )
        try:
            self._append(json.dumps(asdict(entry), ensure_ascii=False))
        except Exception as exc:  # auditing must never break the caller
            logger.warning("Could not write audit entry to %s: %s", self.path, exc)
        return entry

    def _append(self, line: str) -> None:
        """Append a single line, atomically, with owner-only permissions."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, LOG_FILE_MODE)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
        try:
            os.chmod(self.path, LOG_FILE_MODE)
        except OSError as exc:
            logger.debug("Could not restrict permissions of %s: %s", self.path, exc)

    # ── reading ──

    def _iter_entries(self) -> Iterator[AuditEntry]:
        """Yield the stored entries oldest first, skipping corrupt lines."""
        try:
            with open(self.path, encoding="utf-8") as handle:
                lines = handle.readlines()
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning("Could not read audit log at %s: %s", self.path, exc)
            return

        for number, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("entry is not a JSON object")
            except (ValueError, TypeError) as exc:
                logger.warning("Skipping line %d of %s: %s", number, self.path, exc)
                continue
            metadata = raw.get("metadata")
            yield AuditEntry(
                timestamp=str(raw.get("timestamp", "")),
                action=str(raw.get("action", "")),
                actor=str(raw.get("actor", "")),
                target=str(raw.get("target", "")),
                outcome=str(raw.get("outcome", "ok")),
                detail=str(raw.get("detail", "")),
                metadata=dict(metadata) if isinstance(metadata, dict) else {},
            )

    def read(
        self,
        limit: int = 100,
        action: str | None = None,
        actor: str | None = None,
    ) -> list[AuditEntry]:
        """The newest ``limit`` entries, most recent first, optionally filtered."""
        if limit <= 0:
            return []
        entries = [
            entry
            for entry in self._iter_entries()
            if (action is None or entry.action == action) and (actor is None or entry.actor == actor)
        ]
        entries.reverse()
        return entries[:limit]

    def count(self) -> int:
        """Number of readable entries in the trail."""
        return sum(1 for _ in self._iter_entries())


@contextmanager
def audited(
    action: str,
    actor: str = "local",
    target: str = "",
    metadata: dict | None = None,
    log: AuditLog | None = None,
) -> Iterator[None]:
    """Audit a mutating block: ``ok`` on success, ``error`` when it raises.

    The exception is always re-raised after being recorded, so wrapping a call
    changes nothing but the trail.
    """
    audit = log if log is not None else AuditLog()
    try:
        yield
    except Exception as exc:
        audit.write(
            action,
            actor=actor,
            target=target,
            outcome="error",
            detail=str(exc),
            metadata=metadata,
        )
        raise
    else:
        audit.write(action, actor=actor, target=target, outcome="ok", metadata=metadata)
