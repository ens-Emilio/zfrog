"""Pluggable search backends: SQLite (default), Meilisearch and Elasticsearch.

:class:`zfrog.search.SearchIndex` (SQLite FTS5) stays the default and the fallback: it needs
no server, no network and no credentials. When a corpus outgrows a single SQLite file the
same operations can be served by an HTTP search engine instead. Every backend implements
:class:`SearchBackend`, so the API and the CLI pick one through :func:`backend_for` and never
care which one answers:

``sqlite``
    :class:`SqliteBackend` — wraps :class:`~zfrog.search.SearchIndex`.
``meilisearch``
    :class:`MeilisearchBackend` — Meilisearch's REST API.
``elasticsearch``
    :class:`ElasticsearchBackend` — Elasticsearch's REST API.

The HTTP backends use plain ``httpx`` (no new dependency). They degrade instead of raising: an
unreachable server, a timeout or a non-2xx answer becomes an empty result set (or zero indexed
documents) plus a logged warning, so a search outage never surfaces as a 500 in the API.

A *page dict* is ``{"path", "url", "title", "text", "site"}``; ``path`` is the page's stable
key inside the index and the only required field.
"""

from __future__ import annotations

import hashlib
import html as html_module
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx

from zfrog.ai.client import embed
from zfrog.config import settings
from zfrog.search import SNIPPET_MAX, SearchHit, SearchIndex

logger = logging.getLogger(__name__)

#: Backend names accepted by :func:`backend_for`, in fallback order.
BACKENDS: tuple[str, ...] = ("sqlite", "meilisearch", "elasticsearch")

#: Search modes every backend understands.
MODES: tuple[str, ...] = ("fulltext", "semantic")

#: Timeout for a single HTTP call to a search engine, in seconds.
REQUEST_TIMEOUT = 10.0

#: Index name used for Meilisearch (Elasticsearch has its own setting).
DEFAULT_INDEX = "zfrog"

#: Directory, next to the SQLite database, holding the files :class:`SqliteBackend` indexes.
MIRROR_DIRNAME = "search_backend_pages"

#: Suffix appended to every mirrored file (SearchIndex only indexes known file types).
MIRROR_SUFFIX = ".html"

#: Length of each component of a mirrored file name (far below the usual 255-byte limit).
MIRROR_CHUNK = 120


@dataclass
class BackendHit:
    """One search result, whatever the backend that produced it."""

    path: str
    url: str
    title: str
    snippet: str
    score: float


class SearchBackend(ABC):
    """Interface shared by every search backend.

    Implementations are cheap to build, so a caller can create one per request and
    :meth:`aclose` it afterwards.
    """

    #: Short backend identifier, also the value accepted by :func:`backend_for`.
    name: str = ""

    @abstractmethod
    async def index(self, pages: list[dict]) -> int:
        """Index ``pages`` (page dicts). Returns how many were written."""

    @abstractmethod
    async def search(
        self, query: str, mode: str = "fulltext", limit: int = 20
    ) -> list[BackendHit]:
        """Search the index. ``mode`` is ``"fulltext"`` or ``"semantic"``."""

    @abstractmethod
    async def drop_site(self, site: str) -> int:
        """Remove every document of ``site``. Returns how many were removed."""

    @abstractmethod
    async def healthy(self) -> bool:
        """True when the backend is reachable and usable."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release the resources this backend opened."""


# ── shared helpers ──


def page_id(path: str) -> str:
    """Stable document id for a page path (sha1 hex).

    Re-indexing the same page therefore replaces its document instead of duplicating it.
    """
    return hashlib.sha1(str(path).encode("utf-8")).hexdigest()


def _check_mode(mode: str) -> str:
    """Normalise a search mode, rejecting anything the backends cannot honour."""
    value = (mode or "fulltext").strip().lower()
    if value not in MODES:
        raise ValueError(f"Invalid search mode: {mode!r} (use 'fulltext' or 'semantic')")
    return value


def _snippet(text: Any, width: int = SNIPPET_MAX) -> str:
    """Collapse whitespace and cap a backend-provided snippet at ``width`` characters."""
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= width:
        return collapsed
    return collapsed[: width - 1].rstrip() + "…"


def _document(page: dict) -> dict | None:
    """Build the indexed document for a page dict, or ``None`` when it has no path."""
    path = str(page.get("path") or "").strip()
    if not path:
        logger.warning("Page without 'path' skipped during indexing")
        return None
    return {
        "id": page_id(path),
        "path": path,
        "url": str(page.get("url") or ""),
        "title": str(page.get("title") or ""),
        "text": str(page.get("text") or ""),
        "site": str(page.get("site") or ""),
    }


def _site_of(page: dict) -> str:
    """Site label for a page: its explicit ``site``, else the url host (as SearchIndex does)."""
    site = str(page.get("site") or "").strip()
    if site:
        return site
    return urlparse(str(page.get("url") or "")).netloc


class _HttpBackend(SearchBackend):
    """Shared ``httpx`` plumbing: lazy client, auth headers, never-raising requests."""

    def __init__(self, url: str, client: httpx.AsyncClient | None = None) -> None:
        self.url = str(url or "").rstrip("/")
        self._client = client
        self._owns_client = client is None

    # ── HTTP plumbing ──

    def _headers(self) -> dict[str, str]:
        """Headers every request of this backend carries."""
        return {"Content-Type": "application/json"}

    def _auth(self) -> httpx.Auth | None:
        """Authentication for every request, or ``None`` when the server needs none."""
        return None

    def client(self) -> httpx.AsyncClient:
        """The shared client, created on first use and reused afterwards."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.url, headers=self._headers(), timeout=REQUEST_TIMEOUT
            )
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response | None:
        """Send one request; a transport error or non-2xx yields ``None`` and a warning."""
        kwargs.setdefault("auth", self._auth())
        try:
            response = await self.client().request(method, path, **kwargs)
            response.raise_for_status()
        except Exception as exc:  # connect error, timeout, bad url, 4xx/5xx, ...
            logger.warning("%s %s at %s failed: %s", method, path, self.name, exc)
            return None
        return response

    @staticmethod
    def _payload(response: httpx.Response) -> dict:
        """Decode a JSON body, returning an empty dict when the server sent junk."""
        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("Invalid search backend response: %s", exc)
            return {}
        return data if isinstance(data, dict) else {}

    async def aclose(self) -> None:
        """Close the HTTP client, but only when this backend created it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


# ── sqlite ──


class SqliteBackend(SearchBackend):
    """The default backend: :class:`~zfrog.search.SearchIndex` over SQLite FTS5.

    ``SearchIndex`` indexes *files* (``index_file`` / ``index_directory``), not text blobs, and
    adding a text API to it is out of scope here. So every page dict is written to a mirrored
    file under ``<index directory>/search_backend_pages/`` and handed to ``index_file``.

    The mirrored name is a reversible encoding of the page path — percent-encoded, dots
    included, cut into fixed-size components and suffixed with ``.html`` — so a search hit is
    mapped back to the page that produced it without a side table, and re-indexing a page
    rewrites the same file instead of adding another. The file also carries the page title in
    a ``<title>`` tag, which is how ``SearchIndex`` learns it. A page that cannot be written is
    logged and skipped; the rest of the batch still gets indexed.
    """

    name = "sqlite"

    def __init__(self, index: SearchIndex | None = None) -> None:
        self.indexer = index if index is not None else SearchIndex()
        self.pages_dir = Path(self.indexer.db_path).parent / MIRROR_DIRNAME
        self._mirrored: dict[str, set[Path]] = {}

    # ── mirror files ──

    def _mirror_file(self, path: str) -> Path:
        """File that mirrors ``path`` under :attr:`pages_dir`.

        The whole path is percent-encoded (slashes and dots included) and cut into
        fixed-size components, so every path — nested, dotted, accented, even a url —
        maps to one reversible file name without hitting the filesystem's name limit.
        """
        encoded = _encode_path(str(path))
        chunks = [encoded[at : at + MIRROR_CHUNK] for at in range(0, len(encoded), MIRROR_CHUNK)]
        chunks[-1] += MIRROR_SUFFIX
        return self.pages_dir.joinpath(*chunks)

    def _origin_path(self, file_path: str) -> str | None:
        """Recover the page path from a mirrored file path, or ``None`` if it is not one."""
        try:
            relative = Path(file_path).relative_to(self.pages_dir).as_posix()
        except ValueError:
            return None
        if not relative.endswith(MIRROR_SUFFIX):
            return None
        # Chunks carry no separator of their own, so dropping them restores the encoding.
        encoded = relative[: -len(MIRROR_SUFFIX)].replace("/", "")
        return unquote(encoded) if encoded else None

    def _to_hit(self, hit: SearchHit) -> BackendHit:
        """Translate an index hit, restoring the page path of mirrored files."""
        return BackendHit(
            path=self._origin_path(hit.path) or hit.path,
            url=hit.url,
            title=hit.title,
            snippet=hit.snippet,
            score=hit.score,
        )

    # ── SearchBackend ──

    async def index(self, pages: list[dict]) -> int:
        """Write every page dict into the SQLite index. Returns how many were written."""
        count = 0
        for page in pages:
            document = _document(page)
            if document is None:
                continue
            try:
                target = self._mirror_file(document["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(_mirror_html(document), encoding="utf-8")
                self.indexer.index_file(target, document["url"], _site_of(document))
            except (OSError, ValueError) as exc:
                logger.warning("Could not index %s: %s", document["path"], exc)
                continue
            self._mirrored.setdefault(_site_of(document), set()).add(target)
            count += 1
        return count

    async def search(
        self, query: str, mode: str = "fulltext", limit: int = 20
    ) -> list[BackendHit]:
        """Search the SQLite index and translate the hits."""
        mode = _check_mode(mode)
        if not (query or "").strip():
            return []
        try:
            hits = self.indexer.search(query, mode=mode, limit=limit)
        except Exception as exc:  # corrupt database, invalid FTS query, ...
            logger.warning("Search on the SQLite index failed: %s", exc)
            return []
        return [self._to_hit(hit) for hit in hits]

    async def drop_site(self, site: str) -> int:
        """Drop a site from the index, and the mirrored files this backend wrote for it.

        Files left behind by an earlier process are harmless: they are inputs to the index,
        not the index itself, and re-indexing the site reuses them.
        """
        name = (site or "").strip()
        if not name:
            return 0
        removed = self.indexer.drop_site(name)
        for target in self._mirrored.pop(name, set()):
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Could not remove %s: %s", target, exc)
        return removed

    async def healthy(self) -> bool:
        """True when the index database can be opened and read."""
        try:
            self.indexer.stats()
        except Exception as exc:  # unreadable or locked database
            logger.warning("SQLite index unavailable: %s", exc)
            return False
        return True

    async def aclose(self) -> None:
        """Nothing to release: ``SearchIndex`` opens and closes its connection per call."""
        return None


def _encode_path(path: str) -> str:
    """Percent-encode a whole path reversibly (slashes and dots included)."""
    return quote(path, safe="").replace(".", "%2E")


def _mirror_html(document: dict) -> str:
    """HTML shell holding a page's title and text for ``SearchIndex`` to index."""
    title = html_module.escape(document["title"])
    text = html_module.escape(document["text"])
    return f"<html><head><title>{title}</title></head><body><p>{text}</p></body></html>"


# ── meilisearch ──


class MeilisearchBackend(_HttpBackend):
    """Meilisearch backend.

    Semantic search is Meilisearch's hybrid search: the request asks for a
    ``semanticRatio`` of 1.0, which only returns semantic results when an embedder is
    configured for the index (``embedders`` in the index settings). Without one Meilisearch
    falls back to full-text ranking, so the caller sees results either way.
    """

    name = "meilisearch"

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        index: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(settings.meilisearch_url if url is None else url, client=client)
        self.key = settings.meilisearch_key if key is None else key
        self.index_name = index or DEFAULT_INDEX

    def _headers(self) -> dict[str, str]:
        """JSON content type plus the API key, when one is configured."""
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    async def index(self, pages: list[dict]) -> int:
        """Add or replace the pages as documents (primary key ``id``)."""
        documents = [doc for doc in (_document(page) for page in pages) if doc is not None]
        if not documents:
            return 0
        response = await self._request(
            "POST",
            f"/indexes/{self.index_name}/documents",
            params={"primaryKey": "id"},
            json=documents,
        )
        if response is None:
            return 0
        logger.debug("Meilisearch accepted %d documents (%s)", len(documents), self.index_name)
        return len(documents)
    async def search(
        self, query: str, mode: str = "fulltext", limit: int = 20
    ) -> list[BackendHit]:
        """Search the index, mapping Meilisearch hits (and ``_formatted`` snippets) to hits."""
        mode = _check_mode(mode)
        text = (query or "").strip()
        if not text:
            return []
        body: dict[str, Any] = {"q": text, "limit": limit}
        if mode == "semantic":
            body["hybrid"] = {"semanticRatio": 1.0}
        response = await self._request("POST", f"/indexes/{self.index_name}/search", json=body)
        if response is None:
            return []
        payload = self._payload(response)
        hits = payload.get("hits")
        if not isinstance(hits, list):
            return []
        return [_meili_hit(hit, rank) for rank, hit in enumerate(hits) if isinstance(hit, dict)]

    async def drop_site(self, site: str) -> int:
        """Delete every document of ``site`` with a filter delete."""
        name = (site or "").strip()
        if not name:
            return 0
        response = await self._request(
            "POST",
            f"/indexes/{self.index_name}/documents/delete",
            json={"filter": f'site = "{name}"'},
        )
        if response is None:
            return 0
        details = self._payload(response).get("details")
        if not isinstance(details, dict):
            return 0
        # Meilisearch runs deletions asynchronously: only some versions report the number of
        # documents the task matched, so the acknowledged count is what is available here.
        for key in ("deletedDocuments", "matchedDocuments"):
            value = details.get(key)
            if isinstance(value, int):
                return value
        return 0

    async def healthy(self) -> bool:
        """True when ``GET /health`` answers with a 2xx."""
        return await self._request("GET", "/health") is not None


def _meili_hit(hit: dict, rank: int) -> BackendHit:
    """Translate one Meilisearch hit; ``rank`` feeds the score when none is reported."""
    formatted = hit.get("_formatted")
    formatted = formatted if isinstance(formatted, dict) else {}
    ranking_score = hit.get("_rankingScore")
    score = (
        float(ranking_score)
        if isinstance(ranking_score, (int, float))
        # The search call does not request ranking scores, so fall back to the result order.
        else 1.0 / (rank + 1)
    )
    return BackendHit(
        path=str(hit.get("path") or ""),
        url=str(hit.get("url") or ""),
        title=str(hit.get("title") or formatted.get("title") or ""),
        snippet=_snippet(formatted.get("text") or hit.get("text") or ""),
        score=score,
    )


# ── elasticsearch ──


class ElasticsearchBackend(_HttpBackend):
    """Elasticsearch backend.

    Semantic search runs a ``knn`` query over the ``embedding`` field, and the query text is
    embedded with :func:`zfrog.ai.client.embed`. That only works when the caller indexed a
    vector per document in that field and the index maps it as a ``dense_vector``; without
    vectors the query matches nothing. When embeddings are unavailable the semantic search
    degrades to an empty result set.
    """

    name = "elasticsearch"

    def __init__(
        self,
        url: str | None = None,
        index: str | None = None,
        user: str | None = None,
        password: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(settings.elasticsearch_url if url is None else url, client=client)
        self.index_name = index or settings.elasticsearch_index
        self.user = settings.elasticsearch_user if user is None else user
        self.password = settings.elasticsearch_password if password is None else password

    def _auth(self) -> httpx.Auth | None:
        """Basic auth when a user is configured (ES then needs the password too)."""
        if self.user:
            return httpx.BasicAuth(self.user, self.password or "")
        return None

    async def index(self, pages: list[dict]) -> int:
        """Bulk-index the pages as NDJSON, reporting the documents the server rejected."""
        documents = [doc for doc in (_document(page) for page in pages) if doc is not None]
        if not documents:
            return 0
        lines: list[str] = []
        for document in documents:
            source = {key: value for key, value in document.items() if key != "id"}
            action = {"index": {"_index": self.index_name, "_id": document["id"]}}
            lines.append(json.dumps(action, ensure_ascii=False))
            lines.append(json.dumps(source, ensure_ascii=False))
        body = ("\n".join(lines) + "\n").encode("utf-8")
        response = await self._request(
            "POST",
            "/_bulk",
            content=body,
            headers={"Content-Type": "application/x-ndjson"},
        )
        if response is None:
            return 0
        payload = self._payload(response)
        if not payload:
            return 0
        if payload.get("errors"):
            logger.warning("Elasticsearch rejected batch documents in %s", self.index_name)
        failed = 0
        items = payload.get("items")
        for item in items if isinstance(items, list) else []:
            result = item.get("index") if isinstance(item, dict) else None
            if not isinstance(result, dict):
                continue
            status = result.get("status")
            if result.get("error") or (isinstance(status, int) and status >= 400):
                failed += 1
                logger.warning(
                    "Elasticsearch rejected %s: %s", result.get("_id"), result.get("error")
                )
        return max(len(documents) - failed, 0)

    async def search(
        self, query: str, mode: str = "fulltext", limit: int = 20
    ) -> list[BackendHit]:
        """Search the index; semantic mode runs a ``knn`` query on the ``embedding`` field."""
        mode = _check_mode(mode)
        text = (query or "").strip()
        if not text:
            return []
        if mode == "semantic":
            vector = await _embed_query(text)
            if vector is None:
                return []
            body: dict[str, Any] = {
                "query": {"knn": {"field": "embedding", "query_vector": vector, "k": limit}}
            }
        else:
            body = {
                "query": {"multi_match": {"query": text, "fields": ["title^2", "text"]}},
                "size": limit,
            }
        response = await self._request("POST", f"/{self.index_name}/_search", json=body)
        if response is None:
            return []
        container = self._payload(response).get("hits")
        hits = container.get("hits") if isinstance(container, dict) else None
        if not isinstance(hits, list):
            return []
        return [_es_hit(hit) for hit in hits if isinstance(hit, dict)]

    async def drop_site(self, site: str) -> int:
        """Delete every document of ``site`` with a term query, returning ES's count."""
        name = (site or "").strip()
        if not name:
            return 0
        response = await self._request(
            "POST",
            f"/{self.index_name}/_delete_by_query",
            json={"query": {"term": {"site": name}}},
        )
        if response is None:
            return 0
        deleted = self._payload(response).get("deleted")
        return deleted if isinstance(deleted, int) else 0

    async def healthy(self) -> bool:
        """True when the index exists and answers (``GET /{index}``)."""
        return await self._request("GET", f"/{self.index_name}") is not None


def _es_hit(hit: dict) -> BackendHit:
    """Translate one Elasticsearch hit (``_source`` + ``_score``)."""
    source = hit.get("_source")
    source = source if isinstance(source, dict) else {}
    highlight = hit.get("highlight")
    highlight = highlight if isinstance(highlight, dict) else {}
    fragments = highlight.get("text") or highlight.get("title") or []
    snippet = fragments[0] if fragments else source.get("text")
    score = hit.get("_score")
    return BackendHit(
        path=str(source.get("path") or ""),
        url=str(source.get("url") or ""),
        title=str(source.get("title") or ""),
        snippet=_snippet(snippet),
        score=float(score) if isinstance(score, (int, float)) else 0.0,
    )


async def _embed_query(text: str) -> list[float] | None:
    """Embed a query for a ``knn`` search, or ``None`` when embeddings are unavailable."""
    try:
        vectors = await embed([text])
    except Exception as exc:  # embedding backend unreachable, quota, bad model, ...
        logger.warning("Failed to embed the query: %s", exc)
        return None
    if not vectors or not vectors[0]:
        logger.warning("Embeddings unavailable: semantic search skipped")
        return None
    return [float(value) for value in vectors[0]]


# ── factory and convenience ──


def backend_for(name: str | None = None) -> SearchBackend:
    """Build the backend called ``name`` (``settings.search_backend`` by default).

    Raises:
        ValueError: the name is not one of :data:`BACKENDS`.
    """
    chosen = (name or settings.search_backend or "sqlite").strip().lower()
    if chosen == "sqlite":
        return SqliteBackend()
    if chosen == "meilisearch":
        return MeilisearchBackend()
    if chosen == "elasticsearch":
        return ElasticsearchBackend()
    valid = ", ".join(repr(item) for item in BACKENDS)
    raise ValueError(f"Unknown search backend: {name!r} (use {valid})")


async def index_and_search(
    pages: list[dict],
    query: str,
    mode: str = "fulltext",
    backend: SearchBackend | None = None,
    limit: int = 20,
) -> list[BackendHit]:
    """Index ``pages`` and search them in one call, closing a backend it created itself."""
    target = backend if backend is not None else backend_for()
    try:
        await target.index(pages)
        return await target.search(query, mode=mode, limit=limit)
    finally:
        if backend is None:
            await target.aclose()
