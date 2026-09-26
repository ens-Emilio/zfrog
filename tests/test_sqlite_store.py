"""The SQLite settings every store depends on, and the migration path.

Two operational bugs motivated this module, and each test here pins one of them:

* `database is locked` under concurrency, because SQLite's default is to fail
  immediately instead of waiting for the writer lock.
* Schema drift, because `CREATE TABLE IF NOT EXISTS` with no version never added a
  column to a database that already existed.
"""

from __future__ import annotations

import sqlite3

import pytest

from zfrog.storage.sqlite import (
    DEFAULT_BUSY_TIMEOUT_MS,
    migrate,
    open_connection,
    schema_version,
    transaction,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "nested" / "store.db"


# ── connection settings ──

def test_the_parent_directory_is_created(db_path):
    """A store pointed at a fresh volume must not fail on a missing directory."""
    with open_connection(db_path) as conn:
        conn.execute("CREATE TABLE t (a)")

    assert db_path.is_file()


def test_a_writer_waits_instead_of_failing_immediately(db_path):
    """The busy_timeout is what stops `database is locked` under two workers."""
    with open_connection(db_path) as conn:
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert int(timeout) == DEFAULT_BUSY_TIMEOUT_MS


def test_wal_is_enabled_so_readers_are_not_blocked_by_a_writer(db_path):
    with open_connection(db_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert str(mode).lower() == "wal"


def test_rows_come_back_by_column_name(db_path):
    """Every store reads `row["column"]`, so the factory is part of the contract."""
    with open_connection(db_path) as conn:
        conn.execute("CREATE TABLE t (a, b)")
        conn.execute("INSERT INTO t VALUES (1, 2)")
        row = conn.execute("SELECT a, b FROM t").fetchone()

    assert row["a"] == 1
    assert row["b"] == 2


def test_a_read_only_connection_cannot_write(db_path):
    """Reporting must never mutate the database it reads."""
    with open_connection(db_path) as conn:
        conn.execute("CREATE TABLE t (a)")

    with pytest.raises(sqlite3.OperationalError):
        with open_connection(db_path, read_only=True) as conn:
            conn.execute("INSERT INTO t VALUES (1)")


def test_a_read_only_connection_does_not_create_the_file(tmp_path):
    """A missing file stays missing: a report must not conjure a schema."""
    missing = tmp_path / "ausente.db"

    with pytest.raises(sqlite3.OperationalError):
        with open_connection(missing, read_only=True) as conn:
            conn.execute("SELECT 1")

    assert not missing.exists()


def test_a_second_writer_waits_for_the_lock_instead_of_failing(tmp_path):
    """The regression: concurrent writers used to raise `database is locked`.

    One connection holds the write lock while a thread inserts through a second
    connection. Without `busy_timeout` the second raises `OperationalError`
    immediately; with it, it waits and then succeeds.
    """
    import threading
    import time

    path = tmp_path / "shared.db"
    with open_connection(path) as setup:
        setup.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, engine TEXT)")

    holder = open_connection(path)
    outcome: dict[str, object] = {}

    def insert_from_the_other_connection():
        try:
            with open_connection(path) as other:
                other.execute("INSERT INTO runs (engine) VALUES ('playwright')")
            outcome["ok"] = True
        except Exception as exc:  # the failure this test exists to catch
            outcome["error"] = exc

    try:
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO runs (engine) VALUES ('wget')")

        worker = threading.Thread(target=insert_from_the_other_connection)
        worker.start()

        # Let the worker reach the lock, then release it: a writer with no timeout
        # would already have failed by now.
        time.sleep(0.3)
        holder.commit()
        worker.join(timeout=10)

        assert "error" not in outcome, f"o segundo escritor falhou: {outcome.get('error')}"
        assert outcome.get("ok") is True
    finally:
        holder.close()

    with open_connection(path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert total == 2


# ── migrations ──

def test_a_fresh_database_reaches_the_newest_version(db_path):
    with open_connection(db_path) as conn:
        reached = migrate(conn, ((1, "CREATE TABLE a (x)"), (2, "CREATE TABLE b (y)")))

    assert reached == 2
    with open_connection(db_path) as conn:
        assert schema_version(conn) == 2


def test_a_database_created_before_versioning_upgrades_by_a_no_op(db_path):
    """The whole reason the first migration is written `IF NOT EXISTS`.

    A store that existed before `user_version` did sits at 0 with its tables
    already present; running migration 1 must not fail, and must stamp the
    version so a later migration can apply.
    """
    with open_connection(db_path) as conn:
        conn.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, engine TEXT)")
        assert schema_version(conn) == 0

    with open_connection(db_path) as conn:
        reached = migrate(
            conn,
            (
                (1, "CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, engine TEXT)"),
                (2, "ALTER TABLE runs ADD COLUMN mode TEXT"),
            ),
        )

    assert reached == 2
    with open_connection(db_path) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
    assert "mode" in columns


def test_an_already_current_database_is_left_alone(db_path):
    with open_connection(db_path) as conn:
        migrate(conn, ((1, "CREATE TABLE a (x)"),))

    with open_connection(db_path) as conn:
        reached = migrate(conn, ((1, "CREATE TABLE a (x)"),))

    assert reached == 1


def test_migrations_apply_in_version_order_not_list_order(db_path):
    """Ordering by the declared version keeps a reordered list from corrupting."""
    with open_connection(db_path) as conn:
        migrate(
            conn,
            (
                (2, "INSERT INTO log (step) VALUES (2)"),
                (1, "CREATE TABLE log (step INTEGER)"),
            ),
        )

    with open_connection(db_path) as conn:
        steps = [row["step"] for row in conn.execute("SELECT step FROM log")]
    assert steps == [2]


def test_a_failing_migration_raises_and_does_not_stamp_the_version(db_path):
    """A half-applied upgrade must not look like a finished one."""
    with open_connection(db_path) as conn:
        with pytest.raises(sqlite3.Error):
            migrate(conn, ((1, "THIS IS NOT SQL"),))

    with open_connection(db_path) as conn:
        assert schema_version(conn) == 0


# ── transaction ──

def test_transaction_commits_and_closes(db_path):
    with transaction(db_path) as conn:
        conn.execute("CREATE TABLE t (a)")
        conn.execute("INSERT INTO t VALUES (1)")

    # A separate connection sees the committed row, which proves the commit landed.
    with open_connection(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1


def test_transaction_closes_the_connection_even_when_the_body_raises(db_path):
    with pytest.raises(ValueError):
        with transaction(db_path) as conn:
            conn.execute("CREATE TABLE t (a)")
            raise ValueError("boom")

    # A second writer can take the lock, which it could not if the first stayed open.
    with transaction(db_path) as conn:
        conn.execute("INSERT INTO t VALUES (1)")
