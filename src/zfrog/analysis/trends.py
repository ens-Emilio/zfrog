"""Market trends — which way a term (or a price) is moving over a site's history.

The question this answers is "is this being mentioned more, and is it getting
more expensive?" using history the repo already keeps: the snapshots recorded by
:mod:`zfrog.diff` and the price points recorded by :mod:`zfrog.pricing`. Nothing
here re-crawls a site or re-implements storage — it replays what is on disk and
turns the first-to-last movement into a direction.

Two honest choices worth knowing about:

* A term that never appears in the window is *not* reported as a trend by
  :func:`trends` — there is no series to trend. Asking :func:`mention_counts`
  for it directly still returns zeros rather than raising.
* Fewer than two points cannot show a direction, so :func:`compute_trend`
  returns ``"unknown"`` instead of guessing ``"flat"``.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from zfrog.diff import list_snapshots

logger = logging.getLogger(__name__)

RISING = "rising"
FALLING = "falling"
FLAT = "flat"
UNKNOWN = "unknown"

# Snapshots are JSON documents whose "pages" hold the extracted page text.
_SNAPSHOT_TEXT_SEPARATOR = "\n"


@dataclass
class TrendPoint:
    """One observation of a term at a point in time."""

    captured_at: str
    value: float


@dataclass
class Trend:
    """How a term moved from its first observation to its last."""

    term: str
    points: list[TrendPoint]
    direction: str = UNKNOWN
    change_pct: float = 0.0
    first: float = 0.0
    last: float = 0.0
    samples: int = 0


def _fold(value: str) -> str:
    """Normalize text for comparison: lower case, no accents.

    ``NFKD`` splits ``ç`` into ``c`` + combining cedilla, so dropping the
    combining marks makes ``"Preço"`` and ``"preco"`` the same string.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _normalize_label(label: str) -> str:
    """Normalize a price label the way :mod:`zfrog.pricing` stores it."""
    return " ".join(_fold(label).split())


def _read_snapshot(path: Path) -> dict | None:
    """Read one snapshot document, or None (with a warning) when unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("unreadable snapshot %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("snapshot %s is not an object", path)
        return None
    return data


def _snapshot_texts(url: str, limit: int) -> list[tuple[str, str]]:
    """Return ``(captured_at, text)`` per snapshot, oldest first.

    Only the oldest ``limit`` snapshots are considered — the cap bounds the work
    a single call does, and the chronological order is what a trend needs.
    """
    if limit <= 0:
        return []

    series: list[tuple[str, str]] = []
    for path in list_snapshots(url)[:limit]:
        data = _read_snapshot(path)
        if data is None:
            continue
        pages = data.get("pages") or []
        text = _SNAPSHOT_TEXT_SEPARATOR.join(
            str(page.get("text") or "") for page in pages if isinstance(page, dict)
        )
        series.append((str(data.get("captured_at") or ""), text))
    return series


def mention_counts(url: str, term: str, limit: int = 50) -> list[TrendPoint]:
    """Count how often ``term`` appears in each stored snapshot of ``url``.

    The match ignores case and accents, so ``"preco"`` finds ``"Preço"``.

    Args:
        url: Site whose snapshots are replayed.
        term: Term to count.
        limit: Maximum number of snapshots to look at (oldest first).

    Returns:
        One point per snapshot, oldest first, holding that snapshot's total
        count. A term that appears nowhere yields zeros, never an error.
    """
    folded = _fold(term)
    if not folded:
        snapshots = _snapshot_texts(url, limit)
        return [TrendPoint(captured_at=captured_at, value=0.0) for captured_at, _ in snapshots]
    return [
        TrendPoint(captured_at=captured_at, value=float(_fold(text).count(folded)))
        for captured_at, text in _snapshot_texts(url, limit)
    ]


def _attribute(obj: object, name: str, default: object) -> object:
    """Read ``name`` from a dataclass or a plain mapping, with a default."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _match_series(history: dict, label: str) -> list:
    """Pick the series whose stored label folds to ``label``."""
    if not history or not label:
        return []
    wanted = _normalize_label(label)
    for key, series in history.items():
        if _normalize_label(str(key)) == wanted:
            return list(series or [])
    return []


def _select_series(tracker, url: str, label: str) -> list:
    """Read the recorded series for one label out of a tracker's history."""
    if not label:
        return []

    history = tracker.history(url, label) or {}
    if history:
        # The tracker matched the label on its own terms (case-insensitively, by
        # the key it stored); that single series is the one that was asked for.
        return list(next(iter(history.values())) or [])

    # No match: the tracker compares labels exactly, so "preco" never reaches a
    # stored "preço". Read everything and fold the labels here instead.
    return _match_series(tracker.history(url) or {}, label)


def _default_tracker():
    """Build the default price tracker.

    Imported lazily so this module works even before :mod:`zfrog.pricing` is
    installed — a caller that passes its own tracker never needs it.
    """
    from zfrog.pricing import PriceTracker

    return PriceTracker()


def price_series(url: str, label: str, tracker=None) -> list[TrendPoint]:
    """Read the recorded price history of ``label`` for ``url``.

    Delegates to :class:`zfrog.pricing.PriceTracker` — the storage lives there,
    this only converts its points into the common :class:`TrendPoint` shape.

    Args:
        url: Site the price belongs to.
        label: Price label, matched ignoring case and accents.
        tracker: Optional tracker instance; a default one is built when omitted.

    Returns:
        The recorded points, oldest first. An unknown or empty label yields
        ``[]`` — a series needs a label to name it.
    """
    if tracker is None:
        tracker = _default_tracker()

    return [
        TrendPoint(
            captured_at=str(_attribute(point, "captured_at", "")),
            value=float(_attribute(point, "value", 0.0)),
        )
        for point in _select_series(tracker, url, label)
    ]


def _change_pct(first: float, last: float) -> float:
    """Relative change from ``first`` to ``last``, in percent.

    A zero baseline has no percentage to compute. A rise out of an empty
    baseline is reported as ``+100.0`` — a full step up from nothing, and the
    only value that keeps ``first == 0, last > 0`` classified as rising instead
    of flat. Everything else on a zero baseline is ``0.0``.
    """
    if first == 0:
        return 100.0 if last > 0 else 0.0
    return (last - first) / abs(first) * 100.0


def compute_trend(term: str, points: list[TrendPoint], flat_band_pct: float = 5.0) -> Trend:
    """Classify the movement of ``term`` between the first and last point.

    Args:
        term: Term the series belongs to.
        points: Chronological series (oldest first).
        flat_band_pct: Movements within this percentage either way count as flat.

    Returns:
        A :class:`Trend`. Fewer than two points cannot show a direction, so the
        result is ``"unknown"`` with ``change_pct`` 0.0 rather than a guess.
    """
    samples = len(points)
    if samples == 0:
        return Trend(term=term, points=[], direction=UNKNOWN, change_pct=0.0, first=0.0, last=0.0)

    first = float(points[0].value)
    last = float(points[-1].value)
    if samples < 2:
        return Trend(
            term=term,
            points=list(points),
            direction=UNKNOWN,
            change_pct=0.0,
            first=first,
            last=last,
            samples=samples,
        )

    change_pct = _change_pct(first, last)
    if abs(change_pct) <= flat_band_pct:
        direction = FLAT
    else:
        direction = RISING if change_pct > 0 else FALLING
    return Trend(
        term=term,
        points=list(points),
        direction=direction,
        change_pct=change_pct,
        first=first,
        last=last,
        samples=samples,
    )


def trends(url: str, terms: list[str], limit: int = 50) -> list[Trend]:
    """Trend every term of ``terms`` over the snapshots of ``url``.

    Terms are returned in the order asked. Terms that never appear in the window
    are skipped: a series of zeros has no direction to report.

    Args:
        url: Site whose snapshots are replayed.
        terms: Terms to trend, in the order they should be returned.
        limit: Maximum number of snapshots to look at (oldest first).
    """
    texts = [(captured_at, _fold(text)) for captured_at, text in _snapshot_texts(url, limit)]
    if not texts:
        return []

    result: list[Trend] = []
    for term in terms:
        folded = _fold(term)
        points = [
            TrendPoint(captured_at=captured_at, value=float(text.count(folded) if folded else 0))
            for captured_at, text in texts
        ]
        if not any(point.value for point in points):
            continue
        result.append(compute_trend(term, points))
    return result


def _movers(series: list[Trend], direction: str, min_samples: int) -> list[Trend]:
    """Movers in one direction, strongest first, with enough samples behind them."""
    selected = [
        trend
        for trend in series
        if trend.direction == direction and trend.samples >= min_samples
    ]
    selected.sort(key=lambda trend: abs(trend.change_pct), reverse=True)
    return selected


def rising(trends: list[Trend], min_samples: int = 2) -> list[Trend]:
    """Trends that went up, strongest first."""
    return _movers(trends, RISING, min_samples)


def falling(trends: list[Trend], min_samples: int = 2) -> list[Trend]:
    """Trends that went down, strongest first."""
    return _movers(trends, FALLING, min_samples)


def _format_value(value: float) -> str:
    """Render a series value: whole numbers without a trailing ``.0``."""
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def _format_change(change_pct: float) -> str:
    return f"{change_pct:+.1f}%"


def to_markdown(url: str, trends: list[Trend]) -> str:
    """Render trends as a Markdown table, plus a note where history is too short."""
    lines = [f"# Tendências — {url}", ""]
    if not trends:
        lines.append("Nenhum termo com histórico suficiente.")
        return "\n".join(lines) + "\n"

    lines.append("| termo | primeiro | último | variação | direção |")
    lines.append("| --- | --- | --- | --- | --- |")
    for trend in trends:
        lines.append(
            f"| {trend.term} | {_format_value(trend.first)} | {_format_value(trend.last)} "
            f"| {_format_change(trend.change_pct)} | {trend.direction} |"
        )

    short = [trend for trend in trends if trend.samples < 2]
    if short:
        lines.append("")
        for trend in short:
            lines.append(
                f'- "{trend.term}": apenas {trend.samples} amostra(s) — '
                "histórico insuficiente para concluir uma tendência."
            )
    return "\n".join(lines) + "\n"


def summarize(trends: list[Trend]) -> str:
    """One sentence naming the strongest mover, or admitting there is too little history."""
    movers = [
        trend
        for trend in trends
        if trend.samples >= 2 and trend.direction in (RISING, FALLING)
    ]
    if not movers:
        return "Histórico insuficiente para apontar uma tendência."

    strongest = max(movers, key=lambda trend: abs(trend.change_pct))
    verb = "alta" if strongest.direction == RISING else "queda"
    return (
        f'O termo "{strongest.term}" é o que mais se move: {verb} de '
        f"{abs(strongest.change_pct):.1f}% "
        f"({_format_value(strongest.first)} → {_format_value(strongest.last)}, "
        f"{strongest.samples} amostras)."
    )
