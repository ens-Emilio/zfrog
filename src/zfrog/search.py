"""Full-text and semantic search over cloned content, backed by SQLite.

The index lives in a single SQLite file (`settings.search_db` by default) and holds:

* ``pages``      — one row per indexed page (path, url, title, text, site, sha256)
* ``pages_fts``  — FTS5 virtual table over ``(title, text)``, kept in sync by triggers
* ``embeddings`` — float32 vectors, one row per ~1200 character chunk

``fulltext`` mode uses FTS5 ``MATCH`` ranked by ``bm25()`` and falls back to a ``LIKE``
scan when the query is not valid FTS5 syntax. ``semantic`` mode embeds the query and
ranks the stored chunk vectors by cosine similarity; it needs a configured embedding
model (``zfrog.ai.client.embed``), otherwise it returns no hits.
"""

from __future__ import annotations

import array
import asyncio
import hashlib
import html
import inspect
import logging
import math
import re
import sqlite3
import threading
from collections.abc import Awaitable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from zfrog.ai.client import embed, is_available
from zfrog.config import settings
from zfrog.storage.sqlite import migrate, open_connection
from zfrog.utils.text import extract_text

logger = logging.getLogger(__name__)

#: File types that are worth indexing (a directory named ``foo.html`` is not).
CONTENT_EXTENSIONS = frozenset({".html", ".htm", ".txt", ".md"})

HTML_EXTENSIONS = frozenset({".html", ".htm"})

#: Target size of a semantic chunk, in characters.
CHUNK_SIZE = 1200

#: Hard cap for the plain-text excerpt returned in ``SearchHit.snippet``.
SNIPPET_MAX = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    path TEXT PRIMARY KEY,
    url TEXT,
    title TEXT,
    text TEXT,
    site TEXT,
    sha256 TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    title,
    text,
    content='pages'
);

CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, title, text) VALUES (new.rowid, new.title, new.text);
END;

CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, text)
    VALUES ('delete', old.rowid, old.title, old.text);
END;

CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, text)
    VALUES ('delete', old.rowid, old.title, old.text);
    INSERT INTO pages_fts(rowid, title, text) VALUES (new.rowid, new.title, new.text);
END;

CREATE TABLE IF NOT EXISTS embeddings (
    path TEXT,
    chunk_index INTEGER,
    vector BLOB
);

CREATE INDEX IF NOT EXISTS embeddings_path ON embeddings(path);
"""

#: Schema version this module expects. See `zfrog.storage.sqlite`.
SCHEMA_VERSION = 1

#: Ordered ``(version, sql)``. Never edit an entry that has shipped: append.
_MIGRATIONS: tuple[tuple[int, str], ...] = ((1, _SCHEMA),)

_FTS_SQL = """
SELECT p.path AS path,
       p.url AS url,
       p.title AS title,
       snippet(pages_fts, -1, '', '', '…', 24) AS snippet,
       -bm25(pages_fts) AS score
FROM pages_fts
JOIN pages p ON p.rowid = pages_fts.rowid
WHERE pages_fts MATCH ?
ORDER BY score DESC
LIMIT ?
"""


@dataclass
class SearchHit:
    """A single search result."""

    path: str
    url: str
    title: str
    snippet: str
    score: float


class SearchIndex:
    """SQLite-backed full-text and semantic index of cloned pages."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else Path(settings.search_db)

    # ── storage plumbing ──

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open the index, migrate it, commit on success and always close.

        Pragmas and the schema version come from `zfrog.storage.sqlite`, so an
        index shared by the API and a worker does not hit `database is locked`.
        """
        conn = open_connection(self.db_path)
        try:
            migrate(conn, _MIGRATIONS)
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── indexing ──

    def index_directory(self, dir_path: Path, url: str = "", site: str = "") -> int:
        """Index every content file below ``dir_path``.

        Pages are keyed by their path as walked from ``dir_path``, so two different trees
        never collide in the same database. Returns the number of pages indexed;
        re-indexing an unchanged directory returns the same count and leaves the index
        untouched (only pages whose content changed are rewritten).
        """
        root = Path(dir_path)
        if not root.is_dir():
            return 0

        site_name = site or _site_from_url(url) or root.name
        count = 0
        for file in sorted(root.rglob("*")):
            if not file.is_file() or file.suffix.lower() not in CONTENT_EXTENSIONS:
                continue
            rel = file.relative_to(root).as_posix()
            page_url = f"{url.rstrip('/')}/{rel}" if url else ""
            try:
                self._index_file(file, file.as_posix(), page_url, site_name)
            except OSError as exc:
                logger.warning("Could not index %s: %s", file, exc)
                continue
            count += 1
        return count

    def index_file(self, file_path: Path, url: str = "", site: str = "") -> bool:
        """Index a single file. Returns ``True`` when its content was (re)written.

        The page is keyed by the path as given, exactly like :meth:`index_directory`.
        """
        path = Path(file_path)
        if not path.is_file() or path.suffix.lower() not in CONTENT_EXTENSIONS:
            return False
        site_name = site or _site_from_url(url) or path.parent.name
        return self._index_file(path, path.as_posix(), url, site_name)

    def _index_file(self, file_path: Path, key: str, url: str, site: str) -> bool:
        """Upsert one page, its FTS row (via trigger) and its embeddings."""
        raw = file_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT sha256 FROM pages WHERE path = ?", (key,)
            ).fetchone()
            if existing is not None and existing["sha256"] == digest:
                # Content is unchanged: only fill in embeddings that are still missing.
                if is_available() and not _has_embeddings(conn, key):
                    self._embed_page(conn, key)
                return False

            content = raw.decode("utf-8", errors="replace")
            if file_path.suffix.lower() in HTML_EXTENSIONS:
                title = _extract_title(content)
                text = extract_text(content)
            else:
                title = ""
                text = content

            conn.execute(
                """
                INSERT INTO pages (path, url, title, text, site, sha256)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    url = excluded.url,
                    title = excluded.title,
                    text = excluded.text,
                    site = excluded.site,
                    sha256 = excluded.sha256
                """,
                (key, url, title, text, site, digest),
            )
            self._embed_page(conn, key)
            return True

    def _embed_page(self, conn: sqlite3.Connection, key: str) -> int:
        """Rebuild the chunk vectors of one page. Returns the number of chunks stored."""
        row = conn.execute("SELECT text FROM pages WHERE path = ?", (key,)).fetchone()
        conn.execute("DELETE FROM embeddings WHERE path = ?", (key,))
        if row is None or not is_available():
            return 0

        chunks = _chunk_text(row["text"] or "")
        if not chunks:
            return 0

        try:
            vectors = _embed_sync(chunks)
        except Exception as exc:  # embedding backend unreachable, quota, bad model, ...
            logger.warning("Failed to generate embeddings for %s: %s", key, exc)
            return 0
        rows = [
            (key, index, _vector_to_blob(vector))
            for index, vector in enumerate(vectors[: len(chunks)])
        ]
        conn.executemany(
            "INSERT INTO embeddings (path, chunk_index, vector) VALUES (?, ?, ?)", rows
        )
        return len(rows)

    # ── searching ──

    def search(self, query: str, mode: str = "fulltext", limit: int = 20) -> list[SearchHit]:
        """Search the index. ``mode`` is ``"fulltext"`` or ``"semantic"``."""
        text = (query or "").strip()
        if not text:
            return []
        if mode == "semantic":
            return self._search_semantic(text, _row_limit(limit))
        if mode != "fulltext":
            raise ValueError(f"Invalid search mode: {mode!r} (use 'fulltext' or 'semantic')")
        return self._search_fulltext(text, _row_limit(limit))
    def _search_fulltext(self, query: str, limit: int) -> list[SearchHit]:
        """FTS5 ``MATCH`` ranked by bm25, with a ``LIKE`` scan as fallback."""
        with self._connect() as conn:
            try:
                rows = conn.execute(_FTS_SQL, (query, limit)).fetchall()
            except sqlite3.OperationalError as exc:
                logger.debug("Invalid FTS query (%r): %s — falling back to LIKE", query, exc)
                return _search_like(conn, query, limit)
        return [
            SearchHit(
                path=row["path"],
                url=row["url"] or "",
                title=row["title"] or "",
                snippet=_clean_snippet(row["snippet"]),
                score=float(row["score"] or 0.0),
            )
            for row in rows
        ]

    def _search_semantic(self, query: str, limit: int) -> list[SearchHit]:
        """Rank stored chunk vectors by cosine similarity to the query embedding."""
        if not is_available():
            return []

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT path, chunk_index, vector FROM embeddings"
            ).fetchall()
            if not rows:
                return []

            try:
                query_vector = _embed_sync([query])[0]
            except Exception as exc:  # embedding backend unreachable, quota, bad model, ...
                logger.warning("Failed to generate query embedding: %s", exc)
                return []
            best: dict[str, tuple[float, int]] = {}
            for row in rows:
                score = _cosine(query_vector, _blob_to_vector(row["vector"]))
                current = best.get(row["path"])
                if current is None or score > current[0]:
                    best[row["path"]] = (score, int(row["chunk_index"]))

            ranked = sorted(best.items(), key=lambda item: item[1][0], reverse=True)
            if limit > 0:
                ranked = ranked[:limit]
            hits = []
            for path, (score, chunk_index) in ranked:
                page = conn.execute(
                    "SELECT url, title, text FROM pages WHERE path = ?", (path,)
                ).fetchone()
                text = (page["text"] if page is not None else "") or ""
                chunks = _chunk_text(text)
                chunk = chunks[chunk_index] if chunk_index < len(chunks) else text
                hits.append(
                    SearchHit(
                        path=path,
                        url=(page["url"] if page is not None else "") or "",
                        title=(page["title"] if page is not None else "") or "",
                        snippet=_clean_snippet(chunk),
                        score=score,
                    )
                )
        return hits

    # ── introspection ──

    def sites(self) -> list[str]:
        """Every site present in the index, sorted."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT site FROM pages WHERE site <> '' ORDER BY site"
            ).fetchall()
        return [row["site"] for row in rows]

    def drop_site(self, site: str) -> int:
        """Remove every page (and vector) of ``site``. Returns the number of pages removed."""
        with self._connect() as conn:
            paths = [
                row["path"]
                for row in conn.execute("SELECT path FROM pages WHERE site = ?", (site,))
            ]
            if not paths:
                return 0
            conn.executemany("DELETE FROM embeddings WHERE path = ?", [(path,) for path in paths])
            conn.execute("DELETE FROM pages WHERE site = ?", (site,))
        return len(paths)

    def stats(self) -> dict:
        """Index counters: pages, sites, embedded chunks and the database location."""
        with self._connect() as conn:
            pages = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            embeddings = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            sites = conn.execute(
                "SELECT COUNT(DISTINCT site) FROM pages WHERE site <> ''"
            ).fetchone()[0]
        return {
            "pages": int(pages),
            "sites": int(sites),
            "embeddings": int(embeddings),
            "db": str(self.db_path),
        }


# ── helpers ──


def _row_limit(limit: int) -> int:
    """Translate a user limit into an SQLite ``LIMIT`` (-1 means no limit)."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return 20
    return value if value > 0 else -1


def _site_from_url(url: str) -> str:
    """Best-effort site label for a url (its host)."""
    if not url:
        return ""
    return urlparse(url).netloc or url.strip().rstrip("/")


def _extract_title(html: str) -> str:
    """Read the page title, falling back to the first heading."""
    soup = BeautifulSoup(html, "lxml")
    if soup.title is not None:
        title = " ".join(soup.title.get_text(" ", strip=True).split())
        if title:
            return title
    heading = soup.find(["h1", "h2"])
    if heading is not None:
        return " ".join(heading.get_text(" ", strip=True).split())
    return ""


def _chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Split text into word-aligned chunks of about ``size`` characters, no overlap."""
    chunks: list[str] = []
    current = ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > size:
            chunks.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        chunks.append(current)
    return chunks


def _clip(text: str, width: int) -> str:
    """Truncate to ``width`` characters, ending with an ellipsis when clipped."""
    if len(text) <= width:
        return text
    return text[: width - 1].rstrip() + "…"


def _clean_snippet(text: str | None, width: int = SNIPPET_MAX) -> str:
    """Collapse whitespace, HTML-escape, and cap at ``width`` characters."""
    collapsed = " ".join((text or "").split())
    escaped = html.escape(collapsed, quote=False)
    return _clip(escaped, width)


def _excerpt(text: str, needle: str, width: int = SNIPPET_MAX) -> str:
    """Plain-text window around ``needle``, capped at ``width`` characters."""
    flat = " ".join(text.split())
    if not flat:
        return ""
    index = flat.lower().find(needle.lower()) if needle else -1
    if index < 0:
        clipped = _clip(flat, width)
        return html.escape(clipped, quote=False)
    start = max(0, index - width // 3)
    window = flat[start : start + width]
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + width < len(flat) else ""
    clipped = _clip(f"{prefix}{window}{suffix}", width)
    return html.escape(clipped, quote=False)


def _search_like(conn: sqlite3.Connection, query: str, limit: int) -> list[SearchHit]:
    """Fallback scan for queries FTS5 cannot parse (e.g. an unbalanced quote)."""
    terms = [term for term in re.split(r"\W+", query, flags=re.UNICODE) if term]
    if not terms:
        return []

    where = " OR ".join(["text LIKE ?", "title LIKE ?"] * len(terms))
    params: list[Any] = []
    for term in terms:
        like = f"%{term}%"
        params.extend([like, like])
    rows = conn.execute(
        f"SELECT path, url, title, text FROM pages WHERE {where} LIMIT ?",  # noqa: S608
        (*params, limit),
    ).fetchall()

    hits = []
    for row in rows:
        body = row["text"] or ""
        title = row["title"] or ""
        matches = sum(body.lower().count(term.lower()) for term in terms)
        hits.append(
            SearchHit(
                path=row["path"],
                url=row["url"] or "",
                title=title,
                snippet=_excerpt(body or title, terms[0]),
                score=float(matches),
            )
        )
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits


def _has_embeddings(conn: sqlite3.Connection, path: str) -> bool:
    """True when the page already has at least one stored vector."""
    row = conn.execute(
        "SELECT 1 FROM embeddings WHERE path = ? LIMIT 1", (path,)
    ).fetchone()
    return row is not None


def _vector_to_blob(vector: Sequence[float]) -> bytes:
    """Pack a vector as float32 bytes."""
    return array.array("f", [float(value) for value in vector]).tobytes()


def _blob_to_vector(blob: bytes) -> array.array:
    """Unpack float32 bytes back into a vector."""
    values = array.array("f")
    values.frombytes(blob)
    return values


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 for empty, mismatched or zero-length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _resolve(awaitable: Awaitable[Any]) -> Any:
    """Await an awaitable from a plain coroutine wrapper."""
    return await awaitable


def _embed_sync(texts: list[str]) -> list[list[float]]:
    """Run the embedding client from synchronous code.

    ``zfrog.ai.client.embed`` is async while the search API is synchronous, so the
    coroutine is driven here — in a worker thread when an event loop already runs
    (the FastAPI endpoint does exactly that).
    """
    result = embed(texts)
    if not inspect.isawaitable(result):
        return result

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_resolve(result))

    outcome: list[Any] = []
    failure: list[BaseException] = []

    def _worker() -> None:
        try:
            outcome.append(asyncio.run(_resolve(result)))
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller thread
            failure.append(exc)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return outcome[0]
