"""Per-engine execution metrics for Zfrog.

``/stats`` only counts jobs, which says nothing about *which* engine actually works.
This module keeps a small SQLite table of every engine run (``settings.metrics_db``,
``metrics.db`` by default) so the API, the CLI and the dashboard can show success
rates, average duration, average payload size and throughput per engine.

It also turns those resources into money: :func:`estimate_cost` prices one run with
the operator-configured ``cost_*`` rates (all zero by default, so no cost is invented
for users who never configured a tariff).

Design notes:

* The schema is created lazily and idempotently on every connection, so the API and
  the worker can point at the same file without any coordination.
* Every aggregation happens in SQL (``COUNT``/``SUM``/``AVG``) — no Python loop ever
  walks the rows to compute a mean. The cost aggregates are the one exception: a run
  is charged exactly as :func:`estimate_cost` prices it (rounded per run), so the
  per-run inputs are summed through that same function instead of re-deriving the
  formula in SQL.
* Metrics are observational: :meth:`MetricsStore.record` never raises, because a
  broken metrics database must never break the job that was just recorded. A run
  counts as successful when its status is ``"completed"``; every other status
  (``failed``, ``cancelled``, ...) counts as a failure.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zfrog.config import settings
from zfrog.storage.sqlite import migrate, open_connection

logger = logging.getLogger(__name__)

#: Status that counts as a successful run in the aggregates.
SUCCESS_STATUS = "completed"

#: Schema version this module expects. Bump it and append to ``_MIGRATIONS`` when
#: the shape changes — see `zfrog.storage.sqlite` for why the first entry is the
#: original schema written idempotently.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    engine TEXT,
    mode TEXT,
    url TEXT,
    status TEXT,
    duration_s REAL,
    total_bytes INTEGER,
    files INTEGER,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS runs_engine ON runs(engine);
"""

#: Ordered ``(version, sql)``. Never edit an entry that has shipped: append.
_MIGRATIONS: tuple[tuple[int, str], ...] = ((1, _SCHEMA),)

_STATS_SQL = """
SELECT engine                                                AS engine,
       COUNT(*)                                              AS runs,
       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS succeeded,
       SUM(CASE WHEN status = 'completed' THEN 0 ELSE 1 END) AS failed,
       AVG(duration_s)                                       AS avg_duration_s,
       AVG(total_bytes)                                      AS avg_bytes,
       SUM(total_bytes)                                      AS total_bytes,
       AVG(files)                                            AS avg_files
FROM runs
{where}
GROUP BY engine
ORDER BY runs DESC, engine ASC
"""

_TOTALS_SQL = """
SELECT COUNT(*)                                              AS runs,
       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS succeeded,
       SUM(CASE WHEN status = 'completed' THEN 0 ELSE 1 END) AS failed,
       SUM(total_bytes)                                      AS bytes,
       AVG(duration_s)                                       AS avg_duration_s
FROM runs
"""

_RECENT_SQL = """
SELECT id, engine, mode, url, status, duration_s, total_bytes, files, created_at
FROM runs
ORDER BY id DESC
LIMIT ?
"""

#: Per-run cost inputs, grouped in Python by :func:`estimate_cost` (see design notes).
_RUN_COSTS_SQL = """
SELECT engine, duration_s, total_bytes
FROM runs
{where}
"""

#: Resource sums per engine, used by :meth:`MetricsStore.cost_by_engine`.
_ENGINE_RESOURCES_SQL = """
SELECT engine                    AS engine,
       COUNT(*)                  AS runs,
       COALESCE(SUM(total_bytes), 0) AS bytes,
       COALESCE(SUM(duration_s), 0)  AS duration_s
FROM runs
GROUP BY engine
"""


def _now() -> str:
    """ISO-8601 UTC timestamp for a freshly recorded run."""
    return datetime.now(timezone.utc).isoformat()


def _success_rate(succeeded: int, runs: int) -> float:
    """Success ratio rounded to three decimals; ``0.0`` when nothing ran."""
    if runs <= 0:
        return 0.0
    return round(succeeded / runs, 3)

def _as_float(value: Any) -> float:
    """Best-effort float for a metrics value.

    Missing values (``None``/``""``) and unusable ones (non-numeric, ``NaN``,
    ``inf``) become ``0.0``, because a broken setting must never break the job that
    is being recorded; only the unusable case is worth a log line.
    """
    if value is None or value == "":
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        logger.warning("Invalid numeric value in cost metrics: %r", value)
        return 0.0
    if not math.isfinite(number):
        logger.warning("Non-finite value in cost metrics: %r", value)
        return 0.0
    return number

def _non_negative(value: Any) -> float:
    """``_as_float`` clamped at zero: a negative duration, size or rate means nothing."""
    return max(_as_float(value), 0.0)

#: Currency symbols :func:`format_cost` knows; any other code prints itself.
_CURRENCY_SYMBOLS = {"BRL": "R$", "USD": "$"}

#: Below this amount :func:`format_cost` keeps four decimals instead of two.
_CENTS_THRESHOLD = 0.01

@dataclass(frozen=True)
class CostRates:
    """Money charged per unit of resource.

    All rates default to ``0.0``: an operator who configures nothing gets resources
    only, never invented money.
    """

    per_gb_transfer: float = 0.0
    per_cpu_hour: float = 0.0
    per_gb_month: float = 0.0
    currency: str = ""

@dataclass(frozen=True)
class CostBreakdown:
    """Estimated cost of one run, split into its three components."""

    transfer: float
    compute: float
    storage: float
    total: float
    currency: str

def rates_from_settings() -> CostRates:
    """Build :class:`CostRates` from the ``cost_*`` settings.

    Reads are strict about *where* the values come from and forgiving about what they
    contain: a non-numeric or negative setting is treated as ``0.0`` so a bad
    configuration cannot break a job.
    """
    return CostRates(
        per_gb_transfer=_non_negative(settings.cost_per_gb_transfer),
        per_cpu_hour=_non_negative(settings.cost_per_cpu_hour),
        per_gb_month=_non_negative(settings.cost_per_gb_month),
        currency=str(settings.cost_currency or "").strip(),
    )

def estimate_cost(
    duration_s: float,
    total_bytes: int,
    rates: CostRates | None = None,
) -> CostBreakdown:
    """Estimate what one run cost, in the currency of ``rates``.

    ``rates=None`` reads :func:`rates_from_settings`. Each component is charged on the
    whole run — nothing is prorated:

    * ``transfer = total_bytes / 1e9 * per_gb_transfer`` — the payload crossed the
      network once, so the bytes are billed as egress.
    * ``compute = duration_s / 3600 * per_cpu_hour`` — the wall-clock time a run held
      one worker slot.
    * ``storage = total_bytes / 1e9 * per_gb_month`` — a deliberate simplification: the
      output is charged one full month of storage, not the slice of the month it
      actually exists for.

    Negative durations, byte counts and rates are clamped to zero; ``total`` is the sum
    of the three components rounded to six decimals.
    """
    active = rates if rates is not None else rates_from_settings()
    gigabytes = _non_negative(total_bytes) / 1e9
    transfer = gigabytes * _non_negative(active.per_gb_transfer)
    compute = _non_negative(duration_s) / 3600.0 * _non_negative(active.per_cpu_hour)
    storage = gigabytes * _non_negative(active.per_gb_month)
    return CostBreakdown(
        transfer=transfer,
        compute=compute,
        storage=storage,
        total=round(transfer + compute + storage, 6),
        currency=str(active.currency or ""),
    )

def format_cost(value: float, currency: str = "") -> str:
    """Render an amount as money, e.g. ``"R$ 0.0042"`` or ``"$ 1.20"``.

    Known codes use their symbol (``BRL`` -> ``R$``, ``USD`` -> ``$``, case-insensitive);
    an unknown code is printed as-is before the amount (``"XYZ 1.20"``), and an empty
    code prints the bare number. Amounts below ``0.01`` keep four decimals so small runs
    stay readable, larger ones use two.
    """
    amount = _as_float(value)
    digits = 4 if abs(amount) < _CENTS_THRESHOLD else 2
    number = f"{amount:.{digits}f}"
    code = str(currency or "").strip()
    if not code:
        return number
    symbol = _CURRENCY_SYMBOLS.get(code.upper())
    return f"{symbol} {number}" if symbol else f"{code} {number}"


@dataclass
class EngineStats:
    """Aggregated performance of a single engine.

    ``total_cost``/``avg_cost`` are expressed in the currency of the rates that were
    active when the stats were read (:func:`rates_from_settings`), and stay ``0.0``
    when no tariff is configured.
    """

    engine: str
    runs: int
    succeeded: int
    failed: int
    success_rate: float
    avg_duration_s: float
    avg_bytes: float
    total_bytes: int
    avg_files: float
    total_cost: float = 0.0
    avg_cost: float = 0.0


class MetricsStore:
    """SQLite-backed store of engine runs."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else Path(settings.metrics_db)

    # ── storage plumbing ──

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open the database, migrate it, commit on success and always close.

        The pragmas (busy_timeout, WAL) and the schema version come from
        `zfrog.storage.sqlite`, so two workers writing this same file wait for
        each other instead of raising `database is locked`.
        """
        conn = open_connection(self.db_path)
        try:
            migrate(conn, _MIGRATIONS)
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── writing ──

    def record(
        self,
        engine: str,
        status: str,
        duration_s: float,
        total_bytes: int = 0,
        files: int = 0,
        url: str = "",
        mode: str = "",
    ) -> None:
        """Append one run. Never raises: a broken database only logs a warning."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO runs "
                    "(engine, mode, url, status, duration_s, total_bytes, files, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(engine),
                        str(mode),
                        str(url),
                        str(status),
                        float(duration_s),
                        int(total_bytes),
                        int(files),
                        _now(),
                    ),
                )
        except Exception as exc:  # metrics must never break the job that produced them
            logger.warning("Could not record metrics at %s: %s", self.db_path, exc)

    def record_from_result(self, engine: str, result: Any, status: str = "completed") -> None:
        """Record a finished job straight from its result object.

        Accepts a :class:`~zfrog.models.JobResult` (``engine_used``,
        ``duration_seconds``, ``total_size_bytes``, ``files_count``) as well as an
        engine :class:`~zfrog.engines.base.EngineResult` (``total_bytes``, ``files``
        list, no duration), so callers do not have to normalise anything.
        """
        duration = float(getattr(result, "duration_seconds", 0.0) or 0.0)
        size = getattr(result, "total_size_bytes", None)
        if size is None:
            size = getattr(result, "total_bytes", 0)
        files = getattr(result, "files_count", None)
        if files is None:
            files = len(getattr(result, "files", None) or [])
        self.record(
            engine,
            status,
            duration,
            int(size or 0),
            int(files or 0),
            str(getattr(result, "url", "") or ""),
            str(getattr(result, "mode", "") or ""),
        )

    # ── reading ──

    def engine_stats(self, engine: str | None = None) -> list[EngineStats]:
        """Aggregate runs per engine, busiest engine first."""
        where = "WHERE engine = ?" if engine is not None else ""
        params: tuple[Any, ...] = (engine,) if engine is not None else ()
        with self._connect() as conn:
            rows = conn.execute(_STATS_SQL.format(where=where), params).fetchall()
        costs = self._engine_costs(rates_from_settings(), engine)
        stats: list[EngineStats] = []
        for row in rows:
            runs = int(row["runs"] or 0)
            succeeded = int(row["succeeded"] or 0)
            name = str(row["engine"] or "")
            total_cost = costs.get(name, 0.0)
            stats.append(
                EngineStats(
                    engine=name,
                    runs=runs,
                    succeeded=succeeded,
                    failed=int(row["failed"] or 0),
                    success_rate=_success_rate(succeeded, runs),
                    avg_duration_s=float(row["avg_duration_s"] or 0.0),
                    avg_bytes=float(row["avg_bytes"] or 0.0),
                    total_bytes=int(row["total_bytes"] or 0),
                    avg_files=float(row["avg_files"] or 0.0),
                    total_cost=total_cost,
                    avg_cost=total_cost / runs if runs else 0.0,
                )
            )
        return stats

    # ── cost ──

    def _engine_costs(self, rates: CostRates, engine: str | None = None) -> dict[str, float]:
        """Sum each engine's runs through :func:`estimate_cost`, keyed by engine.

        A run is priced exactly as the public helper prices it — including its
        per-run rounding — so the aggregates never drift from a hand-computed
        :func:`estimate_cost` for the same runs.
        """
        where = "WHERE engine = ?" if engine is not None else ""
        params: tuple[Any, ...] = (engine,) if engine is not None else ()
        with self._connect() as conn:
            rows = conn.execute(_RUN_COSTS_SQL.format(where=where), params).fetchall()
        costs: dict[str, float] = {}
        for row in rows:
            name = str(row["engine"] or "")
            run_cost = estimate_cost(row["duration_s"], row["total_bytes"], rates).total
            costs[name] = costs.get(name, 0.0) + run_cost
        return {name: round(cost, 6) for name, cost in costs.items()}

    def cost_by_engine(self, rates: CostRates | None = None) -> list[dict]:
        """Estimated cost per engine, most expensive first.

        ``rates=None`` reads :func:`rates_from_settings`. Each row carries the engine's
        ``runs``, ``bytes``, ``duration_s``, ``cost`` and ``cost_per_run``; engines with
        no recorded run never appear, and ``cost_per_run`` is ``0.0`` (never an error)
        when the configured rates are all zero.
        """
        active = rates if rates is not None else rates_from_settings()
        with self._connect() as conn:
            rows = conn.execute(_ENGINE_RESOURCES_SQL).fetchall()
        costs = self._engine_costs(active)
        by_engine: list[dict] = []
        for row in rows:
            name = str(row["engine"] or "")
            runs = int(row["runs"] or 0)
            cost = costs.get(name, 0.0)
            by_engine.append(
                {
                    "engine": name,
                    "runs": runs,
                    "bytes": int(row["bytes"] or 0),
                    "duration_s": float(row["duration_s"] or 0.0),
                    "cost": cost,
                    "cost_per_run": cost / runs if runs else 0.0,
                }
            )
        by_engine.sort(key=lambda row: (-row["cost"], row["engine"]))
        return by_engine

    def recent(self, limit: int = 20) -> list[dict]:
        """The most recent runs, newest first."""
        if limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(_RECENT_SQL, (int(limit),)).fetchall()
        return [dict(row) for row in rows]

    def totals(self) -> dict:
        """Overall figures across every engine.

        ``cost`` sums the per-engine costs at the rates configured right now, and
        ``currency`` names the currency those costs are in.
        """
        with self._connect() as conn:
            row = conn.execute(_TOTALS_SQL).fetchone()
        runs = int(row["runs"] or 0) if row is not None else 0
        succeeded = int(row["succeeded"] or 0) if row is not None else 0
        failed = int(row["failed"] or 0) if row is not None else 0
        rates = rates_from_settings()
        return {
            "runs": runs,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": _success_rate(succeeded, runs),
            "bytes": int(row["bytes"] or 0) if row is not None else 0,
            "avg_duration_s": float(row["avg_duration_s"] or 0.0) if row is not None else 0.0,
            "cost": round(sum(self._engine_costs(rates).values()), 6),
            "currency": rates.currency,
        }

    def reset(self) -> None:
        """Drop every recorded run."""
        with self._connect() as conn:
            conn.execute("DELETE FROM runs")


def format_engine_table(stats: list[EngineStats]) -> list[dict]:
    """Render stats as plain dicts for a rich table or a JSON response.

    Keys mirror :class:`EngineStats`; ``success_rate`` is a percentage string
    (``"66.7%"``) because every consumer prints it directly.
    """
    table: list[dict] = []
    for stat in stats:
        row = asdict(stat)
        row["success_rate"] = f"{stat.success_rate * 100:.1f}%"
        table.append(row)
    return table
