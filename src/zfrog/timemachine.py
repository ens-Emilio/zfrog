"""Time machine — browse a site as it was on a past date.

A clone is already archived twice over: :class:`~zfrog.versioning.VersionStore`
keeps every file of every commit as a content-addressed blob, and
:mod:`zfrog.diff` keeps one snapshot JSON per run with the extracted text of
each page. This module joins the two so a past state of a site can be listed,
navigated and rendered:

- :meth:`TimeMachine.timeline` — the versions, oldest first (a date picker).
- :meth:`TimeMachine.at` / :meth:`TimeMachine.page` — the pages of one version,
  with title and text read from that version's snapshot, so browsing keeps
  working after the job output directory was deleted.
- :meth:`TimeMachine.content` — the raw archived bytes (the original HTML), for
  a viewer.
- :meth:`TimeMachine.restore` — write a whole version back to disk.
- :func:`resolve_date` — "show me the site as it was on 2026-09-01".
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path

from zfrog.config import settings
from zfrog.diff import DiffReport, page_url_from_path, snapshots_dir, url_slug
from zfrog.versioning import Version, VersionStore

logger = logging.getLogger(__name__)

# Formats accepted by `parse_when`, in the order the error message lists them.
WHEN_FORMATS = ("YYYY-MM-DD", "YYYY-MM-DDTHH:MM", "YYYY-MM-DD HH:MM")
WHEN_HELP = ", ".join(f"'{pattern}'" for pattern in WHEN_FORMATS)


@dataclass
class TimelineEntry:
    """One version of a site, as a timeline row."""

    ref: str
    captured_at: str
    message: str
    branch: str
    pages: int
    size_bytes: int


@dataclass
class ArchivedPage:
    """One page of one version."""

    path: str
    url: str
    title: str
    text: str
    sha256: str
    size_bytes: int


def parse_when(when: str) -> datetime:
    """Parse a user-supplied date or datetime into an aware UTC ``datetime``.

    Accepted: ``"2026-09-01"``, ``"2026-09-01T12:00"``, ``"2026-09-01 12:00"``
    (seconds and a trailing ``Z``/offset are tolerated too). A date without a
    time means the *end* of that day, so "as it was on 2026-09-01" includes
    that day's captures.

    Raises:
        ValueError: The text is empty or is not one of the accepted formats.
    """
    text = str(when or "").strip()
    if not text:
        raise ValueError(f"empty date; accepted formats: {WHEN_HELP}")

    date_only = "T" not in text and " " not in text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"invalid date: '{text}'; accepted formats: {WHEN_HELP}") from None

    if date_only:
        parsed = datetime.combine(parsed.date(), time(23, 59, 59))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_captured_at(value: str) -> datetime | None:
    """Parse a snapshot timestamp; ``None`` when it is missing or malformed."""
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _as_int(value: object) -> int:
    """Best-effort int for values coming out of a snapshot JSON."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _is_safe_relative(rel: str) -> bool:
    """Reject absolute paths and ``..`` before writing into a restore directory."""
    parts = Path(rel).parts
    return bool(parts) and not Path(rel).is_absolute() and ".." not in parts


def resolve_date(url: str, when: str, root: Path | None = None) -> str | None:
    """Return the ref of the version captured on or before ``when``.

    Args:
        url: Site URL that was versioned.
        when: Date or datetime string accepted by :func:`parse_when`.
        root: Version store root; defaults to ``settings.versions_dir``.

    Returns:
        The ref of the last version captured at or before that moment, or
        ``None`` when the site has no version that old.

    Raises:
        ValueError: ``when`` is not a date/datetime this module understands.
    """
    moment = parse_when(when)
    found: str | None = None
    for entry in TimeMachine(url, root=root).timeline():
        captured = _parse_captured_at(entry.captured_at)
        if captured is None:
            continue
        if captured > moment:
            break
        found = entry.ref
    return found


def timeline_summary(entries: list[TimelineEntry]) -> str:
    """One Portuguese sentence describing a timeline: how many, from when to when."""
    total = len(entries)
    if total == 0:
        return "No versions saved for this site."
    first = entries[0].captured_at or "unknown date"
    if total == 1:
        return f"1 saved version, captured at {first}."
    last = entries[-1].captured_at or "unknown date"
    return f"{total} saved versions, from {first} to {last}."


class TimeMachine:
    """Navigate the archived versions of one site."""

    def __init__(self, url: str, root: Path | None = None) -> None:
        self.url = url
        self.root = Path(root) if root is not None else Path(settings.versions_dir)
        self.store = VersionStore(self.root)

    # ----------------------------------------------------------------- versions

    def timeline(self, branch: str | None = None) -> list[TimelineEntry]:
        """Every version of the site, oldest first.

        ``pages`` and ``size_bytes`` are read from each version's snapshot; a
        version whose snapshot is no longer available reports 0 for both.
        """
        entries: list[TimelineEntry] = []
        for version in reversed(self.store.log(self.url, branch)):
            pages, size_bytes = self._snapshot_size(version)
            entries.append(
                TimelineEntry(
                    ref=version.id,
                    captured_at=version.captured_at,
                    message=version.message,
                    branch=version.branch,
                    pages=pages,
                    size_bytes=size_bytes,
                )
            )
        return entries

    def dates(self) -> list[str]:
        """The ``captured_at`` values, oldest first — what a date picker needs."""
        return [entry.captured_at for entry in self.timeline()]

    def resolve_date(self, when: str) -> str | None:
        """The ref of the version captured on or before ``when`` (see :func:`resolve_date`)."""
        return resolve_date(self.url, when, root=self.root)

    def between(self, ref_a: str, ref_b: str) -> DiffReport:
        """Diff two versions (snapshot order is corrected by timestamp)."""
        return self.store.diff_versions(self.url, ref_a, ref_b)

    # -------------------------------------------------------------------- pages

    def at(self, ref: str) -> list[ArchivedPage]:
        """The pages of one version, ordered by path.

        Metadata comes from the version's snapshot, so this keeps working after
        the job output was cleaned up. If that snapshot is gone, the version's
        archived files are listed instead (path, url, sha256 and size from the
        blob store; no title/text was recorded for them).

        Raises:
            ValueError: ``ref`` is not a version of this site.
        """
        version = self._require(ref)
        snapshot = self._read_snapshot(version)
        raw_pages = snapshot.get("pages") if snapshot is not None else None
        if isinstance(raw_pages, list):
            pages = [self._archived_page(raw) for raw in raw_pages if isinstance(raw, dict)]
        else:
            logger.warning("snapshot of version %s unavailable; listing the archived files", version.id)
            pages = self._pages_from_files(version)
        return sorted((page for page in pages if page.path), key=lambda page: page.path)

    def page(self, ref: str, path: str) -> ArchivedPage | None:
        """One page of one version; ``None`` when it is not in that version."""
        wanted = str(path or "").strip()
        if not wanted:
            return None
        version = self._resolve_or_none(ref)
        if version is None:
            return None
        for page in self.at(version.id):
            if page.path == wanted:
                return page
        return None

    def content(self, ref: str, path: str) -> str | None:
        """The raw archived bytes of one file, decoded as UTF-8 with replacement.

        This is the original HTML (not the extracted text), which is what a
        browser viewer needs. A file that is not in the version, or whose blob
        was deleted from the store, yields ``None``.
        """
        version = self._resolve_or_none(ref)
        if version is None:
            return None
        rel = str(path or "").strip()
        digest = version.files.get(rel)
        if digest is None:
            logger.warning("'%s' does not belong to version %s of %s", rel, version.id, self.url)
            return None
        blob = self.store.store.get(digest)
        if blob is None:
            logger.warning("blob %s missing for '%s' at version %s", digest, rel, version.id)
            return None
        return blob.read_bytes().decode("utf-8", errors="replace")

    # ------------------------------------------------------------------ restore

    def restore(self, ref: str, dest: Path | None = None) -> Path:
        """Write every file of a version into ``dest``, preserving relative paths.

        Args:
            ref: Version reference (id, id prefix, branch or ``HEAD``).
            dest: Target directory; defaults to ``<root>/<slug>/restore-<id>``.

        Returns:
            The directory the version was written to.
        """
        version = self._require(ref)
        destination = (
            Path(dest) if dest is not None else self.root / url_slug(self.url) / f"restore-{version.id}"
        )
        destination.mkdir(parents=True, exist_ok=True)

        restored = 0
        for rel, digest in sorted(version.files.items()):
            if not _is_safe_relative(rel):
                logger.warning("invalid path at version %s: %s", version.id, rel)
                continue
            blob = self.store.store.get(digest)
            if blob is None:
                logger.warning("blob %s missing; %s not restored", digest, rel)
                continue
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(blob, target)
            restored += 1

        logger.info("version %s restored at %s (%d file(s))", version.id, destination, restored)
        return destination

    # ------------------------------------------------------------------ helpers

    def _require(self, ref: str) -> Version:
        """Resolve ``ref``, raising ``ValueError`` when it is not a version of this site."""
        version = self.store.resolve(self.url, ref)
        if version is None:
            raise ValueError(f"unknown version: '{ref}' at {self.url}")
        return version

    def _resolve_or_none(self, ref: str) -> Version | None:
        """Like :meth:`_require`, but a bad ref is a logged ``None`` (viewer-friendly)."""
        try:
            return self._require(ref)
        except ValueError as exc:
            logger.warning("invalid reference '%s' at %s: %s", ref, self.url, exc)
            return None

    def _snapshot_path(self, version: Version) -> Path:
        return snapshots_dir() / url_slug(self.url) / version.snapshot

    def _read_snapshot(self, version: Version) -> dict | None:
        """Read the version's snapshot JSON; missing/unreadable becomes ``None``."""
        path = self._snapshot_path(version)
        if not path.is_file():
            logger.warning("snapshot '%s' of version %s not found", version.snapshot, version.id)
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("unreadable snapshot %s: %s", path, exc)
            return None
        return data if isinstance(data, dict) else None

    def _snapshot_size(self, version: Version) -> tuple[int, int]:
        """``(pages, size_bytes)`` from the version's snapshot; ``(0, 0)`` when unavailable."""
        snapshot = self._read_snapshot(version)
        pages = snapshot.get("pages") if snapshot is not None else None
        if not isinstance(pages, list):
            return 0, 0
        return len(pages), sum(_as_int(page.get("size_bytes")) for page in pages if isinstance(page, dict))

    def _archived_page(self, raw: dict) -> ArchivedPage:
        """Build an :class:`ArchivedPage` from one snapshot page entry."""
        path = str(raw.get("path") or "")
        url = str(raw.get("url") or "") or (page_url_from_path(path, self.url) if path else "")
        return ArchivedPage(
            path=path,
            url=url,
            title=str(raw.get("title") or ""),
            text=str(raw.get("text") or ""),
            sha256=str(raw.get("sha256") or ""),
            size_bytes=_as_int(raw.get("size_bytes")),
        )

    def _pages_from_files(self, version: Version) -> list[ArchivedPage]:
        """List a version's archived files when its snapshot is unavailable."""
        pages: list[ArchivedPage] = []
        for rel, digest in sorted(version.files.items()):
            blob = self.store.store.get(digest)
            if blob is None:
                logger.warning("blob %s missing for '%s' at version %s", digest, rel, version.id)
            pages.append(
                ArchivedPage(
                    path=rel,
                    url=page_url_from_path(rel, self.url),
                    title="",
                    text="",
                    sha256=digest,
                    size_bytes=blob.stat().st_size if blob is not None else 0,
                )
            )
        return pages
