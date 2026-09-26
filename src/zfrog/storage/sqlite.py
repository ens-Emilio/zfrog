"""One place where Zfrog opens a SQLite database.

Every store used to call ``sqlite3.connect`` directly, which meant three separate
copies of the same defaults and no answer to two operational problems:

* **``database is locked``.** With two API workers plus Celery, writers collide.
  SQLite's default is to fail immediately rather than wait, so a perfectly healthy
  deployment returns 500s under light concurrency. ``busy_timeout`` makes the
  writer wait its turn.
* **Schema drift.** The tables were created with ``CREATE TABLE IF NOT EXISTS`` and
  no version. A column added later never reached a database that already existed,
  and the failure surfaced as an unrelated ``no such column`` far from the cause.
  ``user_version`` plus an ordered migration list makes the upgrade explicit.

Both are set here rather than per store so they cannot diverge.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

#: How long a writer waits for the lock before giving up, in milliseconds.
#: Long enough to ride out a normal write burst; short enough that a wedged
#: process fails a request instead of hanging it.
DEFAULT_BUSY_TIMEOUT_MS = 5_000

#: WAL lets readers proceed while a writer is active, which is the whole reason
#: concurrent access works at all. It is a persistent property of the file, so
#: setting it once is enough — and a read-only connection cannot set it, which is
#: why :func:`open_connection` skips it there.
_JOURNAL_MODE = "WAL"


def open_connection(db_path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open ``db_path`` with the durability and concurrency settings applied.

    ``read_only`` opens with ``mode=ro`` so a reporting path can never create or
    modify the database as a side effect of being called.
    """
    if read_only:
        # The URI form is what makes read-only real: `sqlite3.connect(path)` would
        # happily create a missing file.
        target = f"{Path(db_path).resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(target, uri=True)
    else:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)

    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn, read_only=read_only)
    return conn


def _apply_pragmas(conn: sqlite3.Connection, *, read_only: bool) -> None:
    """Set the per-connection and per-file pragmas.

    Best effort on purpose: a pragma that cannot be set (an older SQLite, a
    filesystem that refuses WAL) must degrade to the previous behaviour rather
    than make the store unusable.
    """
    try:
        conn.execute(f"PRAGMA busy_timeout = {int(DEFAULT_BUSY_TIMEOUT_MS)}")
    except sqlite3.Error as exc:  # pragma: no cover - depends on the build
        logger.warning("Não foi possível definir busy_timeout: %s", exc)

    if read_only:
        return

    try:
        # Returns the resulting mode; WAL is skipped when the file is on a
        # filesystem that cannot support it (some network mounts).
        mode = conn.execute(f"PRAGMA journal_mode = {_JOURNAL_MODE}").fetchone()
        if mode and str(mode[0]).lower() != _JOURNAL_MODE.lower():
            logger.warning(
                "journal_mode ficou em %s (WAL indisponível neste sistema de arquivos)", mode[0]
            )
    except sqlite3.Error as exc:  # pragma: no cover - depends on the build
        logger.warning("Não foi possível ativar WAL: %s", exc)


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the database's ``user_version``, or 0 when it was never set."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def migrate(conn: sqlite3.Connection, migrations: Sequence[tuple[int, str]]) -> int:
    """Bring ``conn`` up to the newest migration and return the version reached.

    ``migrations`` is an ordered list of ``(version, sql)``. Each entry with a
    version above the database's current one is applied inside a transaction, so
    an interrupted upgrade leaves the previous version intact rather than a
    half-applied schema.

    The first migration of every store is the schema the store shipped with, and
    it is written with ``IF NOT EXISTS``. That is what makes an existing database
    — created before versioning existed, and therefore at ``user_version`` 0 —
    upgrade by a no-op instead of by failing.
    """
    current = schema_version(conn)
    target = 0

    for version, sql in sorted(migrations, key=lambda item: item[0]):
        if version <= current:
            target = max(target, version)
            continue

        try:
            with conn:
                conn.executescript(sql)
                # PRAGMA does not accept a bound parameter, and the value is an
                # int from our own list, never user input.
                conn.execute(f"PRAGMA user_version = {int(version)}")
        except sqlite3.Error as exc:
            logger.error("Migração %d falhou: %s", version, exc)
            raise
        logger.info("Banco migrado para a versão %d", version)
        target = version

    return max(current, target)


@contextmanager
def transaction(db_path: Path, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Open a configured connection, commit on success and always close it.

    The replacement for the per-store ``_connect`` context managers, so the
    pragmas and the cleanup exist once.
    """
    conn = open_connection(db_path, read_only=read_only)
    try:
        yield conn
        if not read_only:
            conn.commit()
    finally:
        conn.close()


__all__ = [
    "DEFAULT_BUSY_TIMEOUT_MS",
    "migrate",
    "open_connection",
    "schema_version",
    "transaction",
]
