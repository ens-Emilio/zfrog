"""Content-aware change alerts.

A webhook that fires on the *proportion* of changed pages cannot tell a footer
date bump from a price change — both are "one page changed". This module looks
at what the text actually says instead:

1. `select_candidates` ranks the changed pages of a `DiffReport` by how much of
   their text really changed (whitespace-normalised similarity).
2. `judge_significance` asks the model whether those changes matter, and always
   returns a usable verdict: a heuristic when there is no model or the call
   fails, an empty verdict when there is nothing to judge.
3. `significant_change` is the entry point the orchestrator/CLI calls with two
   snapshot paths; it returns ``None`` when nothing changed.
"""

from __future__ import annotations

import difflib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from zfrog.ai.client import complete_structured, is_available
from zfrog.ai.schemas import SignificanceResult
from zfrog.config import settings
from zfrog.diff import DiffReport, diff_snapshots

logger = logging.getLogger(__name__)

# How many changed pages are worth judging, and how small a change may be and
# still count as a change at all (below this it is noise, e.g. a cached
# timestamp inside otherwise identical text).
MAX_CANDIDATES = 5
MIN_CHANGE = 0.02

# Characters kept per side of the prompt (head + tail of the text).
EXCERPT_CHARS = 1200

# Bounded error text: model errors can be multi-line essays and end up in a webhook.
MAX_ERROR_CHARS = 200

# Heuristic score: the biggest single change dominates, the average keeps a
# broad-but-shallow rewrite honest, and each extra changed page adds a little.
TOP_WEIGHT = 0.6
MEAN_WEIGHT = 0.4
BREADTH_BONUS = 0.05
MAX_BREADTH_BONUS = 0.2

SYSTEM_PROMPT = (
    "Você avalia mudanças em páginas de um site monitorado. "
    "Diga se as mudanças importam para quem acompanha o site: preço, estoque, "
    "disponibilidade, dados de contato, prazos ou conteúdo relevante são importantes; "
    "rodapé, aviso de cookies, ano de copyright, data de atualização automática, "
    "banners e rodízio de anúncios são ruído. "
    "Dê uma nota de 0 a 1 para a importância (0 irrelevante, 1 muito importante), "
    "resuma em uma frase o que mudou e liste os motivos, um por linha. "
    "Baseie-se apenas no texto fornecido; não invente."
)


@dataclass
class ChangeCandidate:
    """One changed page, with both versions of its text."""

    path: str
    title: str
    before: str
    after: str
    diff_lines: int


def _normalize(text: str) -> str:
    """Collapse every whitespace run into a single space."""
    return " ".join(str(text or "").split())


def text_similarity(a: str, b: str) -> float:
    """Similarity of two texts, 0.0 (unrelated) to 1.0 (identical).

    Whitespace is collapsed first, so re-indentation or re-wrapping is not a
    change. Two empty texts are identical (1.0); one empty text is 0.0.
    """
    left, right = _normalize(a), _normalize(b)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def change_ratio(before: str, after: str) -> float:
    """Share of the text that changed: ``1 - text_similarity``."""
    return 1.0 - text_similarity(before, after)


def _pages_by_path(snapshot: dict) -> dict[str, dict]:
    """Index a snapshot's pages by path, skipping malformed entries."""
    pages = snapshot.get("pages") if isinstance(snapshot, dict) else None
    if not isinstance(pages, list):
        return {}
    return {
        str(page["path"]): page
        for page in pages
        if isinstance(page, dict) and page.get("path")
    }


def _as_int(value: object) -> int:
    """Coerce a snapshot/detail field into an int, defaulting to 0."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def select_candidates(
    report: DiffReport,
    snapshot_a: dict,
    snapshot_b: dict,
    max_candidates: int = MAX_CANDIDATES,
    min_change: float = MIN_CHANGE,
) -> list[ChangeCandidate]:
    """Pick the most-changed pages of a diff, largest change first.

    Args:
        report: Diff between the two snapshots.
        snapshot_a: Older snapshot (page text of the "before" side).
        snapshot_b: Newer snapshot (page text of the "after" side).
        max_candidates: Cap on the returned list.
        min_change: Minimum change ratio for a page to be worth judging.

    Returns:
        Candidates with a change ratio of at least ``min_change``, most changed
        first. Pages missing from either snapshot are ignored.
    """
    if max_candidates <= 0:
        return []

    pages_a = _pages_by_path(snapshot_a)
    pages_b = _pages_by_path(snapshot_b)
    details = {
        str(detail.get("path")): detail
        for detail in (report.details or [])
        if isinstance(detail, dict) and detail.get("path")
    }

    ranked: list[tuple[float, ChangeCandidate]] = []
    for path in report.changed or []:
        page_a, page_b = pages_a.get(path), pages_b.get(path)
        if page_a is None or page_b is None:
            continue
        before = str(page_a.get("text") or "")
        after = str(page_b.get("text") or "")
        ratio = change_ratio(before, after)
        if ratio < min_change:
            continue
        detail = details.get(path) or {}
        ranked.append(
            (
                ratio,
                ChangeCandidate(
                    path=path,
                    title=str(page_b.get("title") or page_a.get("title") or ""),
                    before=before,
                    after=after,
                    diff_lines=_as_int(detail.get("text_diff_lines")),
                ),
            )
        )

    # Path breaks ties so the selection is stable across runs.
    ranked.sort(key=lambda item: (-item[0], item[1].path))
    return [candidate for _, candidate in ranked[:max_candidates]]


def _format_percent(ratio: float) -> str:
    return f"{max(0.0, ratio) * 100:.1f}%"


def _ai_failure(exc: Exception) -> str:
    """One-line, bounded error text explaining why the heuristic was used."""
    message = " ".join(str(exc).split())
    if len(message) > MAX_ERROR_CHARS:
        message = message[: MAX_ERROR_CHARS - 1] + "…"
    return f"Falha na avaliação de significância: {message}"


def heuristic_significance(candidates: list[ChangeCandidate], threshold: float | None = None) -> dict:
    """Judge the changes without any model.

    The score blends the largest change with the average one, plus a small
    bonus per extra changed page (capped so page count alone can never reach
    the default threshold). ``significant`` is ``score >= threshold``.

    Args:
        candidates: Changed pages to weigh.
        threshold: Cut-off for ``significant``; defaults to
            ``settings.significance_threshold``.

    Returns:
        ``{"significant", "score", "summary", "reasons"}``.
    """
    if not candidates:
        return {"significant": False, "score": 0.0, "summary": "", "reasons": []}

    limit = settings.significance_threshold if threshold is None else threshold

    ratios = [change_ratio(candidate.before, candidate.after) for candidate in candidates]
    # Stable sort: the first candidate wins a tie, keeping the input order.
    order = sorted(range(len(candidates)), key=lambda index: -ratios[index])
    top_ratio = ratios[order[0]]
    mean_ratio = sum(ratios) / len(ratios)
    breadth = min(MAX_BREADTH_BONUS, BREADTH_BONUS * (len(candidates) - 1))
    score = round(min(1.0, TOP_WEIGHT * top_ratio + MEAN_WEIGHT * mean_ratio + breadth), 3)

    top = candidates[order[0]]
    if len(candidates) == 1:
        summary = f"A página {top.path} mudou {_format_percent(top_ratio)} do texto."
    else:
        summary = (
            f"{len(candidates)} páginas mudaram; a maior mudança foi em "
            f"{top.path} ({_format_percent(top_ratio)} do texto)."
        )

    reasons = [
        f"{candidates[index].path}: {_format_percent(ratios[index])} do texto alterado"
        for index in order
    ]

    return {
        "significant": score >= limit,
        "score": score,
        "summary": summary,
        "reasons": reasons,
    }


def _field(result: object, name: str, default: object) -> object:
    """Read a field from a pydantic model or a plain dict."""
    if isinstance(result, dict):
        return result.get(name, default)
    return getattr(result, name, default)


def _to_score(value: object) -> float:
    """Coerce a model-provided score into a float clamped to 0-1."""
    try:
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, score))


def _from_model(result: object) -> dict:
    """Normalize a SignificanceResult (or dict) into the public result dict."""
    reasons = [str(reason) for reason in (_field(result, "reasons", []) or []) if str(reason).strip()]
    summary = str(_field(result, "summary", "") or "")
    return {
        "significant": bool(_field(result, "significant", False)),
        "score": _to_score(_field(result, "score", 0.0)),
        "summary": summary,
        "reasons": reasons,
    }


def _excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """Whitespace-collapsed text, bounded to ``limit`` chars (head and tail)."""
    collapsed = _normalize(text)
    if len(collapsed) <= limit:
        return collapsed
    half = max(1, limit // 2)
    return f"{collapsed[:half]} […] {collapsed[-half:]}"


def _render_prompt(candidates: list[ChangeCandidate], url: str = "") -> str:
    """Render the candidates as bounded before/after excerpts."""
    lines = [f"Site: {url or '(desconhecido)'}", ""]
    for index, candidate in enumerate(candidates, start=1):
        lines += [
            f"### Página {index}: {candidate.path} — {candidate.title or '(sem título)'}",
            f"Linhas de diff: {candidate.diff_lines}",
            "ANTES:",
            _excerpt(candidate.before),
            "DEPOIS:",
            _excerpt(candidate.after),
            "",
        ]
    lines.append("Avalie se alguma dessas mudanças é significativa para quem acompanha o site.")
    return "\n".join(lines)


async def judge_significance(candidates: list[ChangeCandidate], url: str = "") -> dict:
    """Judge whether the given changes matter.

    Args:
        candidates: Changed pages, as returned by `select_candidates`.
        url: Site the changes belong to (context for the model).

    Returns:
        ``{"significant", "score", "summary", "reasons"}``, plus ``"error"``
        when the AI was unavailable or failed (the verdict then comes from
        `heuristic_significance`). Never raises.
    """
    if not candidates:
        return {"significant": False, "score": 0.0, "summary": "", "reasons": []}

    if not is_available():
        result = heuristic_significance(candidates)
        result["error"] = "AI indisponível"
        return result

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _render_prompt(candidates, url)},
    ]

    try:
        judged = await complete_structured(
            messages=messages,
            response_model=SignificanceResult,
            temperature=0.0,
        )
    except Exception as exc:
        logger.warning("significance judgement failed (%s); using the heuristic", exc)
        result = heuristic_significance(candidates)
        result["error"] = _ai_failure(exc)
        return result

    return _from_model(judged)


def _load_snapshot(path: Path) -> dict | None:
    """Read a snapshot JSON, returning None (and logging) when it is unusable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("skipping unreadable snapshot %s: %s", path, exc)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        logger.warning("skipping malformed snapshot %s", path)
        return None
    return data


async def significant_change(url: str, prev_snapshot: Path, new_snapshot: Path) -> dict | None:
    """Judge the content change between two snapshots of a site.

    Args:
        url: Site URL (falls back to the URL recorded in the snapshots).
        prev_snapshot: Older snapshot file.
        new_snapshot: Newer snapshot file.

    Returns:
        The verdict from `judge_significance`, or ``None`` when the snapshots
        are unreadable, identical, or nothing changed enough to judge.
    """
    data_a, data_b = _load_snapshot(prev_snapshot), _load_snapshot(new_snapshot)
    if data_a is None or data_b is None:
        return None

    try:
        report = diff_snapshots(Path(prev_snapshot), Path(new_snapshot))
    except Exception as exc:
        logger.warning("cannot diff %s against %s: %s", prev_snapshot, new_snapshot, exc)
        return None

    candidates = select_candidates(report, data_a, data_b)
    if not candidates:
        logger.info("no significant content change between %s and %s", prev_snapshot, new_snapshot)
        return None

    return await judge_significance(candidates, url=url or report.url)
