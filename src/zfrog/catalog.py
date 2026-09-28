"""The reference catalog: one card per captured page, searchable.

A card is what the plan calls a *referência*: the screenshot, the design tokens that
came off the page, the source URL, when it was captured, and tags the user defined.
Cards live in one SQLite file so they can be filtered by tag, by dominant colour, by
site or by date without loading the screenshots.

Two design decisions worth stating:

* The screenshot embedding lives in its own table, keyed by card. That is what makes
  "moodboards escuros com cards arredondados" possible — the description is embedded
  and compared against the *image* vector, not against the page text.
* Colours are indexed by hex in a side table, because "find captures with this accent"
  is a query over `json_each(palette)`, and doing it on every search would scan every
  card. The side table is rebuilt whenever a card is written.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from zfrog.storage.sqlite import migrate, open_connection

#: Schema version this module expects. See `zfrog.storage.sqlite`.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    site TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '',
    engine TEXT NOT NULL DEFAULT '',
    job_id TEXT NOT NULL DEFAULT '',
    screenshot TEXT NOT NULL DEFAULT '',
    tokens_json TEXT NOT NULL DEFAULT '{}',
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    bytes INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS cards_site ON cards(site);
CREATE INDEX IF NOT EXISTS cards_created ON cards(created_at);

CREATE TABLE IF NOT EXISTS card_tags (
    card_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (card_id, tag)
);

CREATE INDEX IF NOT EXISTS card_tags_tag ON card_tags(tag);

-- One row per colour in a card's palette, so filtering by colour is an indexed
-- lookup instead of a json scan. `principal` marks the card's dominant colour.
CREATE TABLE IF NOT EXISTS card_colors (
    card_id TEXT NOT NULL,
    hex TEXT NOT NULL,
    role TEXT,
    count INTEGER NOT NULL DEFAULT 0,
    principal INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (card_id, hex)
);

CREATE INDEX IF NOT EXISTS card_colors_hex ON card_colors(hex);

CREATE TABLE IF NOT EXISTS card_embedding (
    card_id TEXT PRIMARY KEY,
    vector BLOB NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
"""

_MIGRATIONS: tuple[tuple[int, str], ...] = ((1, _SCHEMA),)


@dataclass
class Card:
    """One captured reference."""

    id: str
    url: str
    site: str
    title: str = ""
    mode: str = ""
    engine: str = ""
    job_id: str = ""
    screenshot: str = ""
    note: str = ""
    created_at: float = 0.0
    bytes: int = 0
    tags: list[str] = field(default_factory=list)
    tokens: dict[str, Any] = field(default_factory=dict)

    @property
    def palette(self) -> list[str]:
        """Hex colours of the card, most used first."""
        entries = self.tokens.get("palette", [])
        return [entry["hex"] for entry in entries if entry.get("hex")]

    @property
    def dominant(self) -> str:
        """The most used colour, or an empty string when the page had no readable one."""
        palette = self.palette
        return palette[0] if palette else ""

    @property
    def captured_at_label(self) -> str:
        """``dd/mm/aaaa · hh:mm`` of the capture."""
        if not self.created_at:
            return "—"
        return time.strftime("%d/%m/%Y · %H:%M", time.localtime(self.created_at))

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form, with the fields the dashboard reads already flattened."""
        return {
            "id": self.id,
            "url": self.url,
            "site": self.site,
            "title": self.title,
            "mode": self.mode,
            "engine": self.engine,
            "job_id": self.job_id,
            "screenshot": self.screenshot,
            "note": self.note,
            "created_at": self.created_at,
            "captured_at": self.captured_at_label,
            "bytes": self.bytes,
            "tags": self.tags,
            "palette": self.palette,
            "dominant": self.dominant,
            "tokens": self.tokens,
        }


def site_of(url: str) -> str:
    """The host of a URL, without ``www.``; the URL itself when it has no host."""
    host = urlparse(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def normalize_tag(tag: str) -> str:
    """Lowercase, trimmed, without the leading ``#`` — the canonical tag form."""
    return (tag or "").strip().lstrip("#").lower()


class Catalog:
    """SQLite-backed catalog of captured design references."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = open_connection(self.db_path)
        try:
            migrate(conn, _MIGRATIONS)
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── writing ─────────────────────────────────────────────────────────────────

    def save(self, card: Card) -> Card:
        """Insert or replace a card and rebuild its tag and colour indexes."""
        created = card.created_at or time.time()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cards (
                    id, url, site, title, mode, engine, job_id, screenshot,
                    tokens_json, note, created_at, bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    url=excluded.url, site=excluded.site, title=excluded.title,
                    mode=excluded.mode, engine=excluded.engine, job_id=excluded.job_id,
                    screenshot=excluded.screenshot, tokens_json=excluded.tokens_json,
                    note=excluded.note, bytes=excluded.bytes
                """,
                (
                    card.id,
                    card.url,
                    card.site or site_of(card.url),
                    card.title,
                    card.mode,
                    card.engine,
                    card.job_id,
                    card.screenshot,
                    json.dumps(card.tokens, ensure_ascii=False),
                    card.note,
                    created,
                    card.bytes,
                ),
            )

            conn.execute("DELETE FROM card_tags WHERE card_id = ?", (card.id,))
            for tag in sorted({normalize_tag(t) for t in card.tags if normalize_tag(t)}):
                conn.execute(
                    "INSERT OR IGNORE INTO card_tags (card_id, tag) VALUES (?, ?)", (card.id, tag)
                )

            conn.execute("DELETE FROM card_colors WHERE card_id = ?", (card.id,))
            for index, entry in enumerate(card.tokens.get("palette", [])):
                hex_color = entry.get("hex")
                if not hex_color:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO card_colors (card_id, hex, role, count, principal)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        card.id,
                        hex_color,
                        entry.get("role"),
                        entry.get("count", 0),
                        1 if index == 0 else 0,
                    ),
                )

        card.created_at = created
        card.site = card.site or site_of(card.url)
        card.tags = sorted({normalize_tag(t) for t in card.tags if normalize_tag(t)})
        return card

    def tag(self, card_id: str, tags: Sequence[str], *, replace: bool = False) -> list[str]:
        """Add tags to a card (or replace the whole list) and return the final set."""
        clean = sorted({normalize_tag(tag) for tag in tags if normalize_tag(tag)})

        with self._connect() as conn:
            if replace:
                conn.execute("DELETE FROM card_tags WHERE card_id = ?", (card_id,))
            for tag in clean:
                conn.execute(
                    "INSERT OR IGNORE INTO card_tags (card_id, tag) VALUES (?, ?)", (card_id, tag)
                )
            rows = conn.execute(
                "SELECT tag FROM card_tags WHERE card_id = ? ORDER BY tag", (card_id,)
            ).fetchall()

        return [row["tag"] for row in rows]

    def note(self, card_id: str, text: str) -> None:
        """Set the free-form note of a card."""
        with self._connect() as conn:
            conn.execute("UPDATE cards SET note = ? WHERE id = ?", (text, card_id))

    def delete(self, card_id: str) -> bool:
        """Remove a card and everything indexed for it. Returns whether it existed."""
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone()
            if exists is None:
                return False
            conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
            conn.execute("DELETE FROM card_tags WHERE card_id = ?", (card_id,))
            conn.execute("DELETE FROM card_colors WHERE card_id = ?", (card_id,))
            conn.execute("DELETE FROM card_embedding WHERE card_id = ?", (card_id,))
        return True

    def store_embedding(self, card_id: str, vector: Sequence[float], model: str = "") -> None:
        """Persist the screenshot embedding of a card."""
        import array

        blob = array.array("f", [float(value) for value in vector]).tobytes()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO card_embedding (card_id, vector, model, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                    vector=excluded.vector, model=excluded.model, updated_at=excluded.updated_at
                """,
                (card_id, blob, model, time.time()),
            )

    # ── reading ─────────────────────────────────────────────────────────────────

    def _hydrate(self, conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[Card]:
        """Attach tags and tokens to card rows. Two queries, not two per card."""
        if not rows:
            return []

        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)

        tags_by_card: dict[str, list[str]] = {card_id: [] for card_id in ids}
        for row in conn.execute(
            f"SELECT card_id, tag FROM card_tags WHERE card_id IN ({placeholders}) ORDER BY tag",
            ids,
        ):
            tags_by_card[row["card_id"]].append(row["tag"])

        cards: list[Card] = []
        for row in rows:
            try:
                tokens = json.loads(row["tokens_json"] or "{}")
            except json.JSONDecodeError:
                tokens = {}
            cards.append(
                Card(
                    id=row["id"],
                    url=row["url"],
                    site=row["site"],
                    title=row["title"],
                    mode=row["mode"],
                    engine=row["engine"],
                    job_id=row["job_id"],
                    screenshot=row["screenshot"],
                    note=row["note"],
                    created_at=row["created_at"],
                    bytes=row["bytes"],
                    tags=tags_by_card.get(row["id"], []),
                    tokens=tokens,
                )
            )
        return cards

    def get(self, card_id: str) -> Card | None:
        """One card by id, or ``None``."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
            if row is None:
                return None
            return self._hydrate(conn, [row])[0]

    def list(
        self,
        *,
        tag: str | None = None,
        color: str | None = None,
        site: str | None = None,
        since: float | None = None,
        until: float | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Card]:
        """Cards matching every filter given; newest first.

        All filters combine with AND, which is what "moodboard escuro do site X
        tagueado como dash" expects.
        """
        where: list[str] = []
        params: list[Any] = []

        if tag:
            where.append("id IN (SELECT card_id FROM card_tags WHERE tag = ?)")
            params.append(normalize_tag(tag))
        if site:
            where.append("site = ?")
            params.append(site)
        if since is not None:
            where.append("created_at >= ?")
            params.append(since)
        if until is not None:
            where.append("created_at <= ?")
            params.append(until)
        if color:
            where.append("id IN (SELECT card_id FROM card_colors WHERE hex = ?)")
            params.append(color.upper())
        if query:
            where.append("(url LIKE ? OR title LIKE ? OR note LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])

        sql = "SELECT * FROM cards"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return self._hydrate(conn, rows)

    def tags(self) -> list[tuple[str, int]]:
        """Every tag in use with its card count, most used first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tag, COUNT(*) AS total FROM card_tags
                GROUP BY tag ORDER BY total DESC, tag ASC
                """
            ).fetchall()
        return [(row["tag"], row["total"]) for row in rows]

    def colors(self, limit: int = 60) -> list[tuple[str, int]]:
        """Every colour in the catalog with its card count, most widespread first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT hex, COUNT(*) AS total FROM card_colors
                GROUP BY hex ORDER BY total DESC, hex ASC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [(row["hex"], row["total"]) for row in rows]

    def sites(self) -> list[tuple[str, int]]:
        """Every captured site with its card count, most captured first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT site, COUNT(*) AS total FROM cards
                GROUP BY site ORDER BY total DESC, site ASC
                """
            ).fetchall()
        return [(row["site"], row["total"]) for row in rows]

    def count(self) -> int:
        """How many cards the catalog holds."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM cards").fetchone()
        return int(row["total"]) if row else 0

    def embeddings(self) -> dict[str, tuple[list[float], str]]:
        """Every stored vector, keyed by card id. Used by the visual search."""
        import array

        with self._connect() as conn:
            rows = conn.execute("SELECT card_id, vector, model FROM card_embedding").fetchall()

        out: dict[str, tuple[list[float], str]] = {}
        for row in rows:
            vector = array.array("f")
            vector.frombytes(row["vector"])
            out[row["card_id"]] = (list(vector), row["model"])
        return out


__all__ = ["Card", "Catalog", "normalize_tag", "site_of"]
