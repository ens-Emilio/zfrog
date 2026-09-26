"""Delta crawling helpers: what we already have, and what changed.

The delta engine re-crawls a site but only transfers what it does not already
have. This module holds the pure (network-free) half of that: the plan built
from the latest snapshot of a site — which pages are known, and which validators
(``etag`` / ``last_modified``) can be replayed in a conditional request — and the
summary that classifies the result of a re-crawl.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse

from zfrog.diff import latest_snapshot

logger = logging.getLogger(__name__)

_DEFAULT_PORTS = {"http": "80", "https": "443"}
_UNSAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]")


def normalize_url(url: str) -> str:
    """Normalize a URL for comparison: lower-case host, no fragment, no default port.

    Non-HTTP(S) values are returned stripped but otherwise untouched.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return url.strip()

    host = (parsed.hostname or "").lower()
    port = parsed.port
    if port is None or str(port) == _DEFAULT_PORTS.get(parsed.scheme):
        netloc = host
    else:
        netloc = f"{host}:{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path or "/", parsed.params, parsed.query, ""))


def url_spellings(url: str) -> list[str]:
    """Spellings a URL may have in a snapshot.

    A site root is stored as ``https://host/index.html`` (the URL is derived
    from the local page path) while a crawl asks for ``https://host/``, so both
    directions of the ``index.html`` ↔ directory rewrite are accepted.
    """
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    if parsed.scheme not in ("http", "https"):
        return [normalized]

    variants = {normalized}
    if parsed.path.endswith("/index.html"):
        variants.add(normalized[: -len("index.html")])
    elif parsed.path.endswith("/"):
        variants.add(normalized + "index.html")
    return sorted(variants)


def local_rel_path(url: str) -> Path:
    """Local page path used for a URL: ``<host>/<path>``.

    A path that is empty or ends in ``/`` becomes ``index.html``. Path segments
    are percent-decoded and stripped of characters that are unsafe in file
    names; ``.``/``..`` segments are dropped so a URL can never escape the
    output directory.
    """
    parsed = urlparse(url)
    host = _UNSAFE_SEGMENT.sub("_", parsed.netloc) or "site"

    segments = []
    for raw in unquote(parsed.path).split("/"):
        segment = _UNSAFE_SEGMENT.sub("_", raw)
        if segment and segment not in (".", ".."):
            segments.append(segment)
    if not segments or parsed.path.endswith("/"):
        segments.append("index.html")

    return Path(host, *segments)


def page_request_url(page: dict, site_url: str) -> str | None:
    """Real URL to request for a page recorded in a snapshot.

    Pages are stored locally under ``<host>/<path>``, and a snapshot taken from
    such an output records the URL derived from that path — with the host
    repeated (``https://host/host/page.html``). The local path is authoritative
    there; layouts that keep the URL as written (wget mirrors) are returned
    unchanged.
    """
    stored = str(page.get("url") or "").strip()
    rel = str(page.get("path") or "").strip()
    parsed_site = urlparse(site_url)
    netloc = parsed_site.netloc

    parts = Path(rel).parts if rel else ()
    if netloc and len(parts) > 1 and parts[0] in (netloc, _UNSAFE_SEGMENT.sub("_", netloc)):
        rest = "/".join(parts[1:])
        return f"{parsed_site.scheme or 'https'}://{netloc}/{rest}"

    return stored or None


@dataclass
class DeltaPlan:
    """What the previous snapshot says we already have for a site.

    Attributes:
        url: Site the plan was built for.
        known: Previous page dict, keyed by the page URL stored in the snapshot.
        etags: Non-empty ``etag`` values, keyed by page URL.
    """

    url: str
    known: dict[str, dict] = field(default_factory=dict)
    etags: dict[str, str] = field(default_factory=dict)

    def previous_for(self, url: str) -> dict | None:
        """Previous page entry for a URL a crawl is about to request.

        Matches on the URL first (tolerating the ``index.html``/directory
        spellings), then on the local page path, which is how snapshots taken
        from the delta engine's own output are addressable.
        """
        for candidate in url_spellings(url):
            page = self.known.get(candidate)
            if page is not None:
                return page

        rel = str(local_rel_path(url))
        for page in self.known.values():
            if page.get("path") == rel:
                return page
        return None


@dataclass
class DeltaResult:
    """Outcome of a delta crawl."""

    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    bytes_saved: int = 0
    pages_written: int = 0


def plan_delta(url: str) -> DeltaPlan:
    """Build the revalidation plan for a site from its latest snapshot.

    Returns an empty plan when the site has never been snapshotted. Pages
    without a URL are skipped: they cannot be requested conditionally.
    """
    plan = DeltaPlan(url=url)
    snapshot_path = latest_snapshot(url)
    if snapshot_path is None:
        return plan

    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - a broken snapshot must not fail the crawl
        logger.warning("ignoring unreadable snapshot %s: %s", snapshot_path, exc)
        return plan

    pages = snapshot.get("pages") if isinstance(snapshot, dict) else None
    if not isinstance(pages, list):
        logger.warning("snapshot %s has no page list", snapshot_path)
        return plan

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_url = str(page.get("url") or "").strip()
        if not page_url:
            continue
        plan.known[page_url] = page
        etag = str(page.get("etag") or "")
        if etag:
            plan.etags[page_url] = etag

    return plan


def summarize_delta(
    previous: dict[str, dict],
    current: dict[str, dict],
    unchanged_bytes: int,
) -> DeltaResult:
    """Classify a re-crawl against what was known before, comparing by URL.

    ``added``/``changed``/``unchanged`` follow the order of ``current``;
    ``removed`` follows the order of ``previous``. ``unchanged_bytes`` is the
    transfer the revalidation avoided and is reported as ``bytes_saved``.
    """
    added: list[str] = []
    changed: list[str] = []
    unchanged: list[str] = []

    for url, page in current.items():
        old = previous.get(url)
        if old is None:
            added.append(url)
        elif old.get("sha256") != page.get("sha256"):
            changed.append(url)
        else:
            unchanged.append(url)

    removed = [url for url in previous if url not in current]

    return DeltaResult(
        added=added,
        changed=changed,
        unchanged=unchanged,
        removed=removed,
        bytes_saved=unchanged_bytes,
        pages_written=len(added) + len(changed),
    )
