"""Change detection — versioned site snapshots and diffs between them.

Every `mirror`/`scrape` job records a snapshot under
``output/snapshots/<url_slug>/<timestamp>.json``. Snapshots are self-contained
(page text is stored inside them) because job output dirs are removed by
``JobCleanup`` after 24h; the ``snapshots/`` dir is a sibling of the job dirs and
therefore never cleaned up.

`diff` is not an engine/mode: it works on local snapshot files, needs no network
and never goes through `probe_url`.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from zfrog.config import settings
from zfrog.utils.text import extract_text
from zfrog.utils.webhooks import notify_webhooks

logger = logging.getLogger(__name__)

# Cap on pages per snapshot (same order of magnitude as the screenshot pipeline).
MAX_SNAPSHOT_PAGES = 100
# Cap on stored page text — keeps snapshots small while staying useful for diffs.
MAX_SNAPSHOT_TEXT = 50_000

_UNSAFE_SLUG_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def url_slug(url: str) -> str:
    """Build a filesystem-safe slug from a URL (netloc + path, query dropped).

    Dots in the path become ``_`` so a slug directory can never end in a
    content extension. A directory named ``...static_site.html`` is matched by
    ``rglob("*.html")`` and gets read as a page by every crawl in the codebase
    (see CompareEngine), so the name must not impersonate a file. Dots in the
    host are kept, since ``example.com`` cannot be mistaken for content.
    """
    parsed = urlparse(url)
    host = _UNSAFE_SLUG_CHARS.sub("_", parsed.netloc)
    path = _UNSAFE_SLUG_CHARS.sub("_", parsed.path.replace("/", "_").replace(".", "_"))
    return f"{host}{path}".strip("_") or "site"


def snapshots_dir() -> Path:
    """Return (and create) the snapshots root directory."""
    path = Path(settings.output_dir) / "snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_snapshot(path: Path) -> dict | None:
    """Read a snapshot JSON, returning None (and logging) when it is unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("skipping unreadable snapshot %s: %s", path, exc)
        return None
    if not isinstance(data, dict) or "pages" not in data:
        logger.warning("skipping malformed snapshot %s", path)
        return None
    return data


def list_snapshots(url: str | None = None) -> list[Path]:
    """List snapshot files, oldest first (file names are sortable timestamps).

    Args:
        url: Restrict to one site; omit to list every snapshot.
    """
    root = snapshots_dir()
    if url:
        search_root = root / url_slug(url)
        paths = sorted(search_root.glob("*.json")) if search_root.is_dir() else []
    else:
        paths = sorted(root.glob("*/*.json"))
    return [p for p in paths if _read_snapshot(p) is not None]


def latest_snapshot(url: str) -> Path | None:
    """Return the most recent snapshot for a URL, or None."""
    snapshots = list_snapshots(url)
    return snapshots[-1] if snapshots else None


def resolve_snapshot(ref: str | Path) -> Path | None:
    """Resolve a snapshot reference to an existing file.

    Accepts either a filesystem path (what the CLI passes) or a
    ``<slug>/<filename>`` reference relative to the snapshots directory — the
    latter lets browser clients address snapshots without knowing server paths.

    Returns:
        The resolved path, or None when it does not exist / is not addressable.
    """
    raw = str(ref)
    candidate = Path(raw)
    if candidate.is_file():
        return candidate

    parts = raw.split("/")
    if len(parts) != 2 or any(p in ("", ".", "..") or "\\" in p for p in parts):
        return None

    path = snapshots_dir() / parts[0] / parts[1]
    return path if path.is_file() else None


def page_url_from_path(rel_path: str, site_url: str) -> str:
    """Map a local page path back to its source URL, best effort.

    Handles the host-directory layouts engines produce, where ``:`` in the host
    is rewritten to a filesystem-safe character:
    - ``mirror/<host with ":" -> "+">/<path>``   (wget)
    - ``<host with ":" -> "_">/<path>``          (delta)
    - ``<path>`` relative to the site root       (everything else)

    A ``site_url`` that is not a URL at all (the CLI lets a user name an indexed
    site with a label like ``loja``) yields ``<label>/<path>`` instead of a
    broken ``http:///path``.
    """
    parsed = urlparse(site_url)
    netloc = parsed.netloc
    if not netloc:
        label = site_url.strip("/")
        return f"{label}/{rel_path}" if label else str(rel_path)

    scheme = parsed.scheme or "http"
    parts = list(Path(rel_path).parts)

    if parts and parts[0] == "mirror":
        parts = parts[1:]

    if parts:
        host_dirs = {netloc, netloc.replace(":", "+"), _host_dir(netloc)}
        if parts[0] in host_dirs:
            parts = parts[1:]

    rest = "/".join(parts)
    return f"{scheme}://{netloc}/{rest}" if rest else f"{scheme}://{netloc}/"


def _host_dir(netloc: str) -> str:
    """Host as a directory name: every character unsafe in a file name becomes ``_``."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", netloc)


def load_revalidated_pages(output_dir: Path, previous_path: Path | None) -> list[dict]:
    """Pages the engine revalidated without writing a file (HTTP 304).

    Delta crawling sends conditional requests; a 304 leaves no file behind, so a
    plain directory scan would drop those pages from the next snapshot and the
    run after that would have no validator left to revalidate them with. The
    delta report names them, and the previous snapshot holds their metadata.
    """
    if previous_path is None:
        return []
    report_path = Path(output_dir) / "delta_report.json"
    if not report_path.is_file():
        return []
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("ignoring unreadable %s: %s", report_path, exc)
        return []

    unchanged = set(report.get("unchanged") or [])
    if not unchanged:
        return []

    previous = _read_snapshot(Path(previous_path))
    if not previous:
        return []
    return [page for page in previous.get("pages", []) if page.get("url") in unchanged]


def load_http_meta(output_dir: Path) -> dict:
    """Read per-URL HTTP cache metadata written by engines (etag/last-modified).

    Returns a mapping of URL to ``{"etag": ..., "last_modified": ...}``; an
    absent or unreadable sidecar file yields an empty mapping.
    """
    meta_path = Path(output_dir) / ".http_meta.json"
    if not meta_path.is_file():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("ignoring unreadable %s: %s", meta_path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def capture_snapshot(output_dir: Path, url: str, engine: str) -> tuple[Path, Path | None]:
    """Record a snapshot of a finished job.

    Args:
        output_dir: Job output directory (may be missing/empty).
        url: Site URL the snapshot belongs to.
        engine: Engine that produced the output.

    Returns:
        ``(new_snapshot_path, previous_snapshot_path_or_None)``.
    """
    output_dir = Path(output_dir)
    html_files = (
        sorted(f for f in output_dir.rglob("*.html") if f.is_file())[:MAX_SNAPSHOT_PAGES]
        if output_dir.is_dir()
        else []
    )

    http_meta = load_http_meta(output_dir)

    pages: list[dict] = []
    for path in html_files:
        raw = path.read_bytes()
        html = raw.decode("utf-8", errors="replace")
        try:
            title = BeautifulSoup(html, "lxml").title
            title = title.string.strip() if title and title.string else ""
        except Exception:
            title = ""
        rel = str(path.relative_to(output_dir))
        page_url = page_url_from_path(rel, url)
        meta = http_meta.get(page_url) or {}
        pages.append(
            {
                "path": rel,
                "url": page_url,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "title": title,
                "text": extract_text(html)[:MAX_SNAPSHOT_TEXT],
                "etag": meta.get("etag") or "",
                "last_modified": meta.get("last_modified") or "",
            }
        )

    now = datetime.now(timezone.utc)
    snapshot = {
        "url": url,
        "captured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine": engine,
        "pages": pages,
    }

    previous = latest_snapshot(url)

    # Pages an engine revalidated without writing a file (HTTP 304) still belong
    # to this snapshot, otherwise the next run has no validator for them.
    scanned = {page["path"] for page in pages}
    for page in load_revalidated_pages(output_dir, previous):
        if page.get("path") and page["path"] not in scanned:
            pages.append(page)

    pages.sort(key=lambda page: page["path"])

    target_dir = snapshots_dir() / url_slug(url)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Microsecond precision keeps the names lexicographically sortable AND
    # unique: second resolution let two runs in the same second overwrite each
    # other, silently destroying the previous version's timeline entry.
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    new_path = target_dir / f"{stamp}.json"
    suffix = 1
    while new_path.exists():
        new_path = target_dir / f"{stamp}_{suffix}.json"
        suffix += 1

    new_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    return new_path, previous


def _captured_at(snapshot: dict) -> str:
    return str(snapshot.get("captured_at") or "")


def _parse_captured_at(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class DiffReport:
    """Difference between two snapshots."""

    url: str
    a: str
    b: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    change_ratio: float = 0.0
    details: list[dict] = field(default_factory=list)


def _load_snapshot(path: Path) -> dict:
    data = _read_snapshot(Path(path))
    if data is None:
        raise ValueError(f"invalid snapshot: {path}")
    return data


def diff_snapshots(a: Path, b: Path) -> DiffReport:
    """Compare two snapshots. `a` is the older one, `b` the newer one.

    Order is corrected automatically (with a warning) when the timestamps say
    the arguments were swapped.
    """
    data_a = _load_snapshot(a)
    data_b = _load_snapshot(b)

    ts_a, ts_b = _parse_captured_at(_captured_at(data_a)), _parse_captured_at(_captured_at(data_b))
    if ts_a and ts_b and ts_a > ts_b:
        logger.warning("snapshots out of order; swapping %s and %s", a, b)
        data_a, data_b = data_b, data_a

    pages_a = {str(p.get("path")): p for p in data_a.get("pages", [])}
    pages_b = {str(p.get("path")): p for p in data_b.get("pages", [])}

    added = sorted(set(pages_b) - set(pages_a))
    removed = sorted(set(pages_a) - set(pages_b))

    changed: list[str] = []
    unchanged: list[str] = []
    details: list[dict] = []

    for path in sorted(set(pages_a) & set(pages_b)):
        page_a, page_b = pages_a[path], pages_b[path]
        if page_a.get("sha256") == page_b.get("sha256"):
            unchanged.append(path)
            continue
        changed.append(path)
        diff_lines = difflib.unified_diff(
            str(page_a.get("text", "")).splitlines(),
            str(page_b.get("text", "")).splitlines(),
            lineterm="",
        )
        details.append(
            {
                "path": path,
                "title_a": page_a.get("title", ""),
                "title_b": page_b.get("title", ""),
                "text_diff_lines": sum(
                    1 for line in diff_lines if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
                ),
            }
        )

    total_b = len(pages_b)
    return DiffReport(
        url=str(data_b.get("url") or data_a.get("url") or ""),
        a=_captured_at(data_a),
        b=_captured_at(data_b),
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
        change_ratio=(len(changed) / total_b) if total_b else 0.0,
        details=details,
    )


def diff_to_markdown(report: DiffReport) -> str:
    """Render a DiffReport as Markdown."""
    lines = [
        f"# Changes at {report.url or '(unknown)'}",
        "",
        f"- Before: {report.a or '(no timestamp)'}",
        f"- After: {report.b or '(no timestamp)'}",
        f"- Change ratio: {report.change_ratio * 100:.1f}%",
        "",
    ]

    lines.append(f"## Added ({len(report.added)})")
    lines += [f"- {p}" for p in report.added] or ["- (none)"]
    lines.append("")

    lines.append(f"## Removed ({len(report.removed)})")
    lines += [f"- {p}" for p in report.removed] or ["- (none)"]
    lines.append("")

    lines.append(f"## Changed ({len(report.changed)})")
    if report.details:
        for detail in report.details:
            lines.append(f"- {detail['path']} ({detail['text_diff_lines']} diff lines)")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append(f"## Unchanged ({len(report.unchanged)})")
    lines.append("")

    return "\n".join(lines)


async def maybe_alert(url: str, new_path: Path, prev_path: Path | None) -> DiffReport | None:
    """Diff a fresh snapshot against the previous one and notify webhooks.

    Args:
        url: Site URL.
        new_path: Snapshot just captured.
        prev_path: Previous snapshot, or None when this is the first capture.

    Returns:
        The DiffReport, or None when there is nothing to compare against.
    """
    if prev_path is None:
        return None

    report = diff_snapshots(prev_path, new_path)

    if report.change_ratio >= settings.change_alert_threshold:
        await notify_webhooks(
            "site.changed",
            {
                "url": url,
                "change_ratio": report.change_ratio,
                "added": report.added,
                "removed": report.removed,
                "changed": report.changed,
                "snapshot": str(new_path),
            },
        )

    return report


def report_to_dict(report: DiffReport) -> dict:
    """Serialize a DiffReport for JSON output (CLI/API)."""
    return asdict(report)
