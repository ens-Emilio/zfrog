"""Return on investment: what the automation saved versus what it cost.

The model, stated up front because an invented number is worse than no number:

.. code-block:: text

    value  = pages × minutes_per_page ÷ 60 × hourly_rate   (manual work avoided)
    cost   = compute + transfer + storage                  (zfrog.analytics cost model)
    net    = value − cost
    ratio  = value ÷ cost                                  (None when either side is 0)

``minutes_per_page`` and ``hourly_rate`` are the *user's assumptions*, not measured
facts: nobody clocked the human this job replaced. Every :class:`RoiResult` therefore
carries the assumptions back, and :func:`to_markdown` prints them under a heading that
says so. The ratio is ``None`` rather than a number whenever there is nothing to
compare: a zero cost is not an infinite return, and a zero value (no rate, or no
minutes per page) is not a return of zero per unit spent — it is an unanswered
question, exactly as in :func:`break_even_pages`.

The cost side is not re-implemented here: :func:`roi_from_metrics` prices the recorded
runs through :func:`zfrog.analytics.rates_from_settings` and
:meth:`~zfrog.analytics.MetricsStore.cost_by_engine`, so ROI and the cost report can
never disagree.

Page counts are the weak spot and are documented rather than hidden: the metrics store
records the number of *files* a run produced, never a page count, so the ROI uses that
column as a proxy and says so in the note (``páginas estimadas pelos arquivos
gerados``).
"""

from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from zfrog.analytics import MetricsStore, format_cost, rates_from_settings
from zfrog.config import settings
from zfrog.storage.sqlite import open_connection

logger = logging.getLogger(__name__)

#: Totals of every recorded run. The ``files`` column is the page proxy (see module docstring).
_TOTALS_SQL = """
SELECT COUNT(*)                          AS runs,
       COALESCE(SUM(total_bytes), 0)     AS bytes,
       COALESCE(SUM(duration_s), 0)      AS duration_s,
       COALESCE(SUM(files), 0)           AS files
FROM runs
"""

#: Per-engine file counts: the page proxy, split the same way ``cost_by_engine`` splits cost.
_ENGINE_FILES_SQL = """
SELECT engine                     AS engine,
       COALESCE(SUM(files), 0)    AS files
FROM runs
GROUP BY engine
"""

#: The dash shown wherever a number cannot be computed (a zero-cost ratio).
NOT_AVAILABLE = "—"

#: Totals of a store that has not recorded anything yet.
_EMPTY_TOTALS: dict[str, Any] = {"runs": 0, "bytes": 0, "duration_s": 0.0, "files": 0}

#: Minutes in an hour: the unit bridge between minutes-per-page and an hourly rate.
_MINUTES_PER_HOUR = 60.0

@dataclass
class RoiInputs:
    """The assumptions the value side rests on.

    ``hourly_rate`` is money per hour and ``minutes_per_page`` is the manual time one
    page would have taken; both are supplied by the operator, not measured.
    """

    hourly_rate: float
    minutes_per_page: float
    currency: str

@dataclass
class RoiResult:
    """Value saved, cost paid, and the assumptions that produced them."""

    runs: int
    pages: int
    bytes: int
    duration_s: float
    value: float
    cost: float
    net: float
    ratio: float | None
    currency: str
    inputs: RoiInputs
    per_engine: list[dict]
    note: str

def _clamp(value: Any) -> float:
    """Best-effort non-negative float: ``None``, text, ``nan``, ``inf`` and negatives all read 0."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(number, 0.0)

def _clamp_int(value: Any) -> int:
    """``_clamp`` for counts: an unknown count is 0, never a negative or fractional one."""
    return int(_clamp(value))

def _number(value: Any) -> str:
    """Compact number for prose and tables: ``2`` for 2.0, ``2.5`` for 2.5."""
    return f"{_clamp(value):g}"

def _ratio_text(ratio: float | None) -> str:
    """``"2.50×"``, or ``"—"`` when there is no ratio (a zero cost has none)."""
    return NOT_AVAILABLE if ratio is None else f"{ratio:.2f}×"

def _clean_inputs(inputs: RoiInputs) -> RoiInputs:
    """Clamp an assumption set: a negative rate or duration of work saves nothing."""
    return RoiInputs(
        hourly_rate=_clamp(inputs.hourly_rate),
        minutes_per_page=_clamp(inputs.minutes_per_page),
        currency=str(inputs.currency or "").strip(),
    )

def inputs_from_settings() -> RoiInputs:
    """The assumptions configured in ``settings`` (``roi_*`` and ``cost_currency``).

    A non-numeric or negative setting is read as ``0.0`` rather than raising: a bad
    configuration must not break a report.
    """
    return _clean_inputs(
        RoiInputs(
            hourly_rate=settings.roi_hourly_rate,
            minutes_per_page=settings.roi_manual_minutes_per_page,
            currency=settings.cost_currency,
        )
    )

def _value_per_page(inputs: RoiInputs) -> float:
    """Money saved by one avoided page: the per-page factor of the value formula."""
    return inputs.minutes_per_page / _MINUTES_PER_HOUR * inputs.hourly_rate

def _assumptions_note(inputs: RoiInputs) -> str:
    """The Portuguese sentence naming both assumptions and the currency."""
    currency = inputs.currency or "moeda não configurada"
    return (
        f"Valor = páginas × {_number(inputs.minutes_per_page)} min por página ÷ "
        f"{_MINUTES_PER_HOUR:g} × {format_cost(inputs.hourly_rate, inputs.currency)} por hora, "
        f"em {currency} — minutos por página e valor da hora são premissas do usuário, "
        "não medições."
    )

def _metrics_note(inputs: RoiInputs) -> str:
    """``_assumptions_note`` plus the page-proxy caveat of :func:`roi_from_metrics`."""
    return (
        f"{_assumptions_note(inputs)} As páginas estimadas pelos arquivos gerados em cada "
        "execução são um proxy, não uma contagem página a página."
    )

def compute_roi(
    pages: int,
    cost: float,
    inputs: RoiInputs | None = None,
    runs: int = 0,
    bytes_: int = 0,
    duration_s: float = 0.0,
) -> RoiResult:
    """Apply the model to a page count and a cost.

    Every input is clamped to ``>= 0`` (a negative page count or rate would otherwise
    turn the manual work avoided into a loss), and ``inputs=None`` reads
    :func:`inputs_from_settings`. The returned ``inputs`` are the *effective* ones —
    clamped — so the report always shows the numbers the value was built from.
    ``ratio`` is ``None`` when either the cost or the value is zero (see the module
    docstring).
    """
    effective = _clean_inputs(inputs if inputs is not None else inputs_from_settings())
    page_count = _clamp_int(pages)
    money = _clamp(cost)
    value = page_count * _value_per_page(effective)
    return RoiResult(
        runs=_clamp_int(runs),
        pages=page_count,
        bytes=_clamp_int(bytes_),
        duration_s=_clamp(duration_s),
        value=value,
        cost=money,
        net=value - money,
        ratio=(value / money) if (money > 0 and value > 0) else None,
        currency=effective.currency,
        inputs=effective,
        per_engine=[],
        note=_assumptions_note(effective),
    )

def _db_missing(store: Any) -> bool:
    """True when the store names a database file that does not exist yet.

    Reporting is a read: it must not conjure a database (and a schema) out of nothing,
    so a store pointing at an absent file is treated as "no runs recorded".
    """
    path = getattr(store, "db_path", None)
    return path is not None and not Path(path).exists()

def _runs_totals(store: Any) -> dict[str, Any]:
    """Sum runs, bytes, duration and files straight from the metrics database.

    Read-only on purpose: reporting must never create or migrate the database, so a
    missing file, a missing directory or a database without the ``runs`` table all
    degrade to zeros with a warning instead of an exception.
    """
    empty: dict[str, Any] = dict(_EMPTY_TOTALS)
    raw_path = getattr(store, "db_path", None) or settings.metrics_db
    path = Path(raw_path)
    if not path.exists():
        return empty
    try:
        conn = open_connection(path, read_only=True)
    except sqlite3.Error as exc:
        logger.warning("Não foi possível ler as métricas em %s: %s", path, exc)
        return empty
    try:
        row = conn.execute(_TOTALS_SQL).fetchone()
    except sqlite3.Error as exc:
        logger.warning("Métricas em %s não puderam ser somadas: %s", path, exc)
        return empty
    finally:
        conn.close()
    if row is None:
        return empty
    return {
        "runs": int(row[0] or 0),
        "bytes": int(row[1] or 0),
        "duration_s": float(row[2] or 0.0),
        "files": int(row[3] or 0),
    }

def _engine_files(store: Any) -> dict[str, int]:
    """Files (the page proxy) per engine, read-only; empty on any missing database or table."""
    raw_path = getattr(store, "db_path", None) or settings.metrics_db
    path = Path(raw_path)
    if not path.exists():
        return {}
    try:
        conn = open_connection(path, read_only=True)
    except sqlite3.Error as exc:
        logger.warning("Não foi possível ler as métricas em %s: %s", path, exc)
        return {}
    try:
        rows = conn.execute(_ENGINE_FILES_SQL).fetchall()
    except sqlite3.Error as exc:
        logger.warning("Métricas em %s não puderam ser somadas por engine: %s", path, exc)
        return {}
    finally:
        conn.close()
    return {str(row[0] or ""): int(row[1] or 0) for row in rows}

def _per_engine(store: Any, rates: Any, inputs: RoiInputs) -> list[dict]:
    """``cost_by_engine`` rows extended with the value side, so the value can be shown per engine.

    The cost keys (``engine``, ``runs``, ``bytes``, ``duration_s``, ``cost``,
    ``cost_per_run``) are kept verbatim; ``pages`` (the files proxy for that engine),
    ``value`` and ``net`` are appended. The per-engine pages sum to the report's page
    count, because both come from the same ``files`` column.
    """
    per_page = _value_per_page(inputs)
    files = _engine_files(store)
    rows: list[dict] = []
    for row in store.cost_by_engine(rates):
        engine = str(row.get("engine", ""))
        pages = files.get(engine, 0)
        cost = _clamp(row.get("cost"))
        value = pages * per_page
        rows.append({**row, "pages": pages, "value": value, "net": value - cost})
    return rows

def roi_from_metrics(inputs: RoiInputs | None = None, store: Any = None) -> RoiResult:
    """ROI over every run recorded in the metrics store.

    ``store=None`` opens a :class:`~zfrog.analytics.MetricsStore` on
    ``settings.metrics_db``. Cost comes from the existing cost model
    (:meth:`~zfrog.analytics.MetricsStore.cost_by_engine` at
    :func:`~zfrog.analytics.rates_from_settings`), never from a second implementation.
    Reporting only reads: a store whose database file does not exist yet is reported as
    empty instead of being created.

    Approximation, documented in the result's note: the page count is the sum of the
    runs' ``files`` column — files produced, not pages fetched — so it is a proxy that
    undercounts a run that produced nothing and overcounts a run that produced assets.
    Each ``per_engine`` row carries that engine's cost-model fields plus ``pages`` (its
    share of the same proxy), ``value`` and ``net``.
    """
    effective = _clean_inputs(inputs if inputs is not None else inputs_from_settings())
    metrics = store if store is not None else MetricsStore()
    rates = rates_from_settings()
    if _db_missing(metrics):
        per_engine: list[dict] = []
        totals = dict(_EMPTY_TOTALS)
    else:
        per_engine = _per_engine(metrics, rates, effective)
        totals = _runs_totals(metrics)
    cost = round(sum(_clamp(row.get("cost")) for row in per_engine), 6)
    result = compute_roi(
        totals["files"],
        cost,
        effective,
        runs=totals["runs"],
        bytes_=totals["bytes"],
        duration_s=totals["duration_s"],
    )
    return replace(
        result,
        currency=effective.currency or rates.currency,
        per_engine=per_engine,
        note=_metrics_note(effective),
    )

def break_even_pages(cost: float, inputs: RoiInputs | None = None) -> int | None:
    """How many pages must be avoided for the value to cover ``cost``.

    Returns the ceiling of the exact quotient (a fraction of a page still means the cost
    is not covered yet), ``0`` for a non-positive cost, and ``None`` when the rate or the
    minutes per page are zero — the question has no answer then, and a wrong number would
    be worse than none.
    """
    effective = _clean_inputs(inputs if inputs is not None else inputs_from_settings())
    value_per_page = effective.minutes_per_page / _MINUTES_PER_HOUR * effective.hourly_rate
    if value_per_page <= 0:
        return None
    exact = _clamp(cost) / value_per_page
    return int(math.ceil(round(exact, 9)))

def to_json(result: RoiResult) -> dict:
    """The result as a plain dict, assumptions nested under ``inputs`` (JSON-safe)."""
    return asdict(result)

def to_markdown(result: RoiResult) -> str:
    """Render the ROI as a Markdown report: value, cost, net, ratio, assumptions, engines."""
    currency = result.currency
    lines = [
        "# Retorno do investimento (ROI)",
        "",
        "## Resumo",
        "",
        "| Item | Valor |",
        "| --- | --- |",
        f"| Execuções | {result.runs} |",
        f"| Páginas (proxy dos arquivos gerados) | {result.pages} |",
        f"| Bytes | {result.bytes} |",
        f"| Duração (s) | {_number(result.duration_s)} |",
        f"| Valor do trabalho manual evitado | {format_cost(result.value, currency)} |",
        f"| Custo estimado | {format_cost(result.cost, currency)} |",
        f"| Saldo (valor − custo) | {format_cost(result.net, currency)} |",
        f"| Retorno (valor ÷ custo) | {_ratio_text(result.ratio)} |",
        "",
        "## Premissas (não são medições)",
        "",
        f"- Minutos por página: {_number(result.inputs.minutes_per_page)}",
        f"- Valor da hora: {format_cost(result.inputs.hourly_rate, result.inputs.currency)}",
        f"- Moeda: {currency or 'não configurada'}",
        f"- {result.note}",
        "",
        "## Por engine",
        "",
    ]
    if result.per_engine:
        lines += [
            "| Engine | Execuções | Páginas (proxy) | Bytes | Duração (s) | Valor | Custo | Saldo |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in result.per_engine:
            lines.append(
                f"| {row.get('engine', '')} | {row.get('runs', 0)} | {row.get('pages', 0)} | "
                f"{row.get('bytes', 0)} | {_number(row.get('duration_s', 0.0))} | "
                f"{format_cost(row.get('value', 0.0), currency)} | "
                f"{format_cost(row.get('cost', 0.0), currency)} | "
                f"{format_cost(row.get('net', 0.0), currency)} |"
            )
    else:
        lines.append("_Nenhuma execução registrada._")
    lines.append("")
    return "\n".join(lines)
