"""Delta engine: revalidate known pages, download only what changed."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import deque
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from zfrog.config import settings
from zfrog.delta import (
    local_rel_path,
    normalize_url,
    page_request_url,
    plan_delta,
    summarize_delta,
)
from zfrog.diff import page_url_from_path
from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.utils.http import create_client

logger = logging.getLogger(__name__)

# Content types worth storing and following links from.
_HTML_TYPES = ("text/html", "application/xhtml+xml")
# Extensions that are never HTML, skipped before spending a request on them.
_SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".zip", ".gz", ".tar", ".mp4", ".mp3", ".avi", ".css", ".js", ".json",
    ".xml", ".rss", ".woff", ".woff2", ".ttf", ".eot",
)


def _unique_rel_path(rel: Path, url: str, taken: dict[str, str]) -> Path:
    """Keep two distinct URLs that map to the same local path from clobbering.

    Query strings are not part of a page path, so ``/list?page=1`` and
    ``/list?page=2`` both resolve to ``<host>/list``; the second one gets a
    short digest of its URL appended.
    """
    owner = taken.get(str(rel))
    if owner is None or owner == url:
        taken[str(rel)] = url
        return rel

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    disambiguated = rel.with_name(f"{rel.stem}_{digest}{rel.suffix}")
    taken[str(disambiguated)] = url
    return disambiguated


def _same_site(url: str, root: str) -> bool:
    """True when a link stays on the crawled host."""
    parsed, parsed_root = urlparse(url), urlparse(root)
    if parsed.scheme not in ("http", "https"):
        return False
    return parsed.netloc == parsed_root.netloc


def _should_follow(url: str, root: str) -> bool:
    """Whether a discovered link is worth requesting."""
    if not _same_site(url, root):
        return False
    path = urlparse(url).path.lower()
    return not path.endswith(_SKIP_EXTENSIONS)


def _extract_links(html: str, base_url: str) -> list[str]:
    """Absolute links found in a page, in document order."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:  # noqa: BLE001 - malformed HTML must not fail the crawl
        logger.warning("failed to parse %s: %s", base_url, exc)
        return []

    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        links.append(urljoin(base_url, href))
    return links


def _is_html(content_type: str) -> bool:
    """Whether a response content type is HTML (an absent type is assumed HTML)."""
    media_type = content_type.split(";")[0].strip().lower()
    return not media_type or media_type.startswith(_HTML_TYPES)


def _conditional_headers(previous: dict) -> dict[str, str]:
    """Revalidation headers for a known page."""
    headers: dict[str, str] = {}
    etag = str(previous.get("etag") or "")
    last_modified = str(previous.get("last_modified") or "")
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers


def _record_meta(
    meta: dict[str, dict],
    response: httpx.Response,
    snapshot_key: str | None = None,
) -> None:
    """Store the cache validators a response carried, if any.

    Recorded under the requested URL and, when it differs, under the URL
    :func:`zfrog.diff.capture_snapshot` will derive from the local page path —
    that is the key the next snapshot reads, so the validators survive into the
    next delta run.
    """
    entry: dict[str, str] = {}
    etag = response.headers.get("etag")
    last_modified = response.headers.get("last-modified")
    if etag:
        entry["etag"] = etag
    if last_modified:
        entry["last_modified"] = last_modified
    if not entry:
        return

    url = str(response.url)
    meta[url] = entry
    if snapshot_key and snapshot_key != url:
        meta[snapshot_key] = entry


class DeltaEngine(EngineAdapter):
    """Engine that only downloads pages that changed since the last snapshot."""

    name = "delta"

    def can_handle(self, probe: ProbeResult) -> bool:
        """Delta crawling reuses whatever a normal crawl would have used."""
        return probe.suggested_engine in ("wget", "static_file", "playwright")

    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        """Crawl ``job.url`` revalidating known pages and writing only changes.

        Args:
            job: Job configuration (``max_depth`` and ``max_pages`` are honoured).
            output_dir: Directory to store output.
            on_progress: Optional progress callback.

        Returns:
            EngineResult with the pages that were (re)written.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        logs: list[str] = []

        def progress(message: str) -> None:
            logs.append(message)
            if on_progress:
                on_progress(message)

        plan = plan_delta(str(job.url))
        progress(f"Revalidando {len(plan.known)} páginas conhecidas...")

        root = str(job.url)
        max_pages = min(job.max_pages, settings.delta_max_pages)

        previous: dict[str, dict] = dict(plan.known)
        current: dict[str, dict] = {}
        meta: dict[str, dict] = {}
        written: list[Path] = []
        taken_paths: dict[str, str] = {}
        seen: set[str] = {normalize_url(root)}
        root_path = str(local_rel_path(root))
        queue: deque[tuple[str, int]] = deque([(root, 0)])
        total_bytes = 0
        unchanged_bytes = 0
        processed = 0

        # A 304 carries no body, so links cannot be rediscovered from a page we
        # did not download. Known pages are therefore revalidated on their own,
        # not only when the crawl happens to reach them through a changed page.
        if job.max_depth > 0:
            for page in plan.known.values():
                page_url = page_request_url(page, root)
                if not page_url or not _should_follow(page_url, root):
                    continue
                if normalize_url(page_url) in seen:
                    continue
                # The crawled URL may be the ``index.html`` spelling of the root.
                if str(local_rel_path(page_url)) == root_path:
                    continue
                seen.add(normalize_url(page_url))
                queue.append((page_url, 0))

        async with create_client() as client:
            while queue and processed < max_pages:
                url, depth = queue.popleft()
                processed += 1

                known = plan.previous_for(url)
                try:
                    response = await client.get(
                        url, headers=_conditional_headers(known) if known else None
                    )
                except httpx.HTTPError as exc:
                    logger.warning("delta request failed for %s: %s", url, exc)
                    logs.append(f"Falha ao buscar {url}: {exc}")
                    continue

                final_url = str(response.url)

                if response.status_code == 304:
                    if known is None:
                        # Nothing to fall back on: a 304 for a page we never
                        # validated would otherwise be stored as an empty file.
                        logs.append(f"304 sem versão conhecida para {url}; ignorado")
                        continue
                    # Revalidated: the copy we already have is still current.
                    page_url = str(known.get("url") or final_url)
                    size = int(known.get("size_bytes") or 0)
                    current[page_url] = {
                        "sha256": str(known.get("sha256") or ""),
                        "size_bytes": size,
                    }
                    unchanged_bytes += size
                    known_path = known.get("path")
                    _record_meta(
                        meta,
                        response,
                        page_url_from_path(str(known_path), root) if known_path else None,
                    )
                    continue

                if response.status_code >= 400:
                    logs.append(f"HTTP {response.status_code} para {url}")
                    continue

                if not _is_html(response.headers.get("content-type", "")):
                    logs.append(
                        f"Ignorando conteúdo não HTML "
                        f"({response.headers.get('content-type', '')}): {url}"
                    )
                    continue

                body = response.content
                rel = _unique_rel_path(local_rel_path(final_url), final_url, taken_paths)
                target = output_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)

                page_url = str(known.get("url") or final_url) if known else final_url
                current[page_url] = {
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "size_bytes": len(body),
                }
                written.append(target)
                total_bytes += len(body)
                _record_meta(meta, response, page_url_from_path(str(rel), root))

                if depth < job.max_depth:
                    html = body.decode("utf-8", errors="replace")
                    for link in _extract_links(html, final_url):
                        key = normalize_url(link)
                        if key in seen or not _should_follow(link, root):
                            continue
                        seen.add(key)
                        queue.append((link, depth + 1))

        (output_dir / ".http_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        result = summarize_delta(previous, current, unchanged_bytes)
        (output_dir / "delta_report.json").write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )

        progress(f"Delta concluído: {len(result.added)} novas, {len(result.changed)} alteradas")

        return EngineResult(
            output_dir=output_dir,
            files=written,
            total_bytes=total_bytes,
            logs=logs,
        )
