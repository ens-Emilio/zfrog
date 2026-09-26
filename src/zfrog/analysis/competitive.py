"""Competitive analysis — several cloned sites, side by side.

One clone directory per competitor goes in; what each clone *is* (pages, words,
detected prices, entities, titles) and what actually differs comes out: the
ground they share, what only one of them has, the price spread per product line
and the gaps that are documented rather than guessed.

Prices come from :mod:`zfrog.pricing`, imported lazily so this module works
whether or not that module is present — without it a site simply has no prices,
and everything else (pages, words, entities, titles) still works. Entities come
from the AI layer and are only ever the ones the model returned: when the AI is
unavailable the list stays empty instead of being filled with invented names.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Coroutine, TypeVar

from bs4 import BeautifulSoup

from zfrog.ai.client import is_available
from zfrog.ai.entities import extract_entities
from zfrog.config import settings
from zfrog.utils.text import extract_text

logger = logging.getLogger(__name__)

#: Page files a clone is made of (a directory called ``foo.html`` is not a page).
HTML_EXTENSIONS = frozenset({".html", ".htm"})

#: Text budget for the single entity-extraction call made per site.
ENTITY_TEXT_BUDGET = 8000

#: A site must be at least this much smaller than the leanest other site before
#: its page or word count is reported as a gap.
GAP_RATIO = 0.5

#: Label used for amounts that reached the comparison without a product name.
UNLABELLED = ""

_T = TypeVar("_T")


@dataclass
class SiteSnapshot:
    """What one cloned site looks like on its own.

    ``prices`` holds every amount found, in page order. ``price_labels`` keeps
    the same amounts keyed by the label :mod:`zfrog.pricing` read next to them,
    which is what lets the same product line up across sites in a comparison;
    it is empty when no price carried a label (or when there is no price at all).
    """

    site: str
    url: str
    pages: int
    words: int
    prices: list[float]
    entities: list[dict]
    titles: list[str]
    price_labels: dict[str, float] = field(default_factory=dict)


@dataclass
class Comparison:
    """Several sites measured against each other."""

    sites: list[SiteSnapshot]
    price_spread: dict
    shared_entities: list[str]
    unique_entities: dict[str, list[str]]
    content_gaps: list[str]
    summary: str


# ── Reading a clone ──

def _page_files(dir_path: Path) -> list[Path]:
    """Every page file of a clone, in a stable order."""
    root = Path(dir_path)
    if not root.is_dir():
        return []
    try:
        candidates = sorted(root.rglob("*"))
    except OSError as exc:
        logger.warning("não foi possível percorrer %s: %s", root, exc)
        return []
    return [
        path
        for path in candidates
        if path.is_file() and path.suffix.lower() in HTML_EXTENSIONS
    ]


def _read_html(path: Path) -> str:
    """Read one page, tolerating undecodable bytes."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("não foi possível ler %s: %s", path, exc)
        return ""


def _page_title(html: str) -> str:
    """The document title of a page, or ``""`` when it has none."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        logger.warning("não foi possível ler o título da página: %s", exc)
        return ""
    if soup.title is None:
        return ""
    return soup.title.get_text(strip=True)


def _word_count(text: str) -> int:
    """Words in an already-extracted text."""
    return len(text.split())


def _fold(value: str) -> str:
    """Fold text for comparison: no case, no accents, single spaces."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_accents.casefold().split())


def _ai_available() -> bool:
    """Whether the AI layer can be used at all (never raises)."""
    try:
        return bool(is_available())
    except Exception as exc:
        logger.warning("verificação de disponibilidade da IA falhou: %s", exc)
        return False


def _extract_prices(html: str) -> list[Any]:
    """Prices of one page, via :mod:`zfrog.pricing` when it is importable."""
    try:
        from zfrog.pricing import extract_from_html
    except ImportError:
        logger.warning("zfrog.pricing indisponível: preços não serão extraídos")
        return []
    try:
        return list(extract_from_html(html, settings.price_currency_hint))
    except Exception as exc:
        logger.warning("falha ao extrair preços: %s", exc)
        return []


def _entity_text(texts: list[str], budget: int = ENTITY_TEXT_BUDGET) -> str:
    """Join page texts up to the entity-extraction budget."""
    parts: list[str] = []
    used = 0
    for text in texts:
        if used >= budget:
            break
        chunk = text[: budget - used]
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)


async def _site_entities(text: str) -> list[dict]:
    """Entities of a site, or ``[]`` when the AI cannot be used.

    Only what the model returned is kept — no placeholder names, ever.
    """
    if not text.strip() or not _ai_available():
        return []
    try:
        result = await extract_entities(text)
    except Exception as exc:
        logger.warning("extração de entidades falhou: %s", exc)
        return []
    found = result.get("entities") if isinstance(result, dict) else None
    return [entity for entity in (found or []) if isinstance(entity, dict)]


def _run_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run a coroutine to completion from synchronous code.

    ``asyncio.run`` refuses to start inside a running loop (a synchronous helper
    called from an async request handler), so that case is handed to a worker
    thread with a loop of its own.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _summarize(site: str, dir_path: Path, url: str) -> SiteSnapshot:
    """Measure one clone (the body of :func:`summarize_site`)."""
    pages = 0
    words = 0
    prices: list[float] = []
    price_labels: dict[str, float] = {}
    titles: list[str] = []
    texts: list[str] = []

    for path in _page_files(dir_path):
        html = _read_html(path)
        text = extract_text(html)
        texts.append(text)
        pages += 1
        words += _word_count(text)
        title = _page_title(html)
        if title:
            titles.append(title)
        for price in _extract_prices(html):
            value = float(price.value)
            prices.append(value)
            label = str(getattr(price, "label", "") or "").strip()
            price_labels.setdefault(label, value)

    return SiteSnapshot(
        site=site,
        url=url,
        pages=pages,
        words=words,
        prices=prices,
        entities=await _site_entities(_entity_text(texts)),
        titles=titles,
        price_labels=price_labels,
    )


def summarize_site(site: str, dir_path: Path, url: str = "") -> SiteSnapshot:
    """Measure one cloned site.

    Args:
        site: Label of the site in the comparison.
        dir_path: Clone directory; a missing directory measures as an empty site.
        url: Origin URL of the clone, when known.

    Returns:
        The snapshot: page count, total words, every detected price, the labels
        those prices carried, the page titles and the entities the AI found.
    """
    return _run_sync(_summarize(site, Path(dir_path), url))


# ── Comparing snapshots ──

def _prices_by_label(snapshot: SiteSnapshot) -> dict[str, float]:
    """The site's label -> value map.

    Sites measured by :func:`summarize_site` carry their labels; a snapshot built
    by hand from bare amounts keeps them under :data:`UNLABELLED`, using the
    site's average amount as its level so the spread stays meaningful.
    """
    if snapshot.price_labels:
        return {str(label): float(value) for label, value in snapshot.price_labels.items()}
    if snapshot.prices:
        values = [float(value) for value in snapshot.prices]
        return {UNLABELLED: sum(values) / len(values)}
    return {}


def _price_spread(sites: list[SiteSnapshot]) -> dict:
    """Per shared label: min/max/mean and the cheapest site.

    Labels are matched accent- and case-insensitively, and the first spelling
    seen is the one reported. A label only one site has is not a shared line, so
    it stays out of the spread.
    """
    groups: dict[str, dict[str, float]] = {}
    spelling: dict[str, str] = {}
    for snapshot in sites:
        for label, value in _prices_by_label(snapshot).items():
            key = _fold(label)
            groups.setdefault(key, {}).setdefault(snapshot.site, float(value))
            spelling.setdefault(key, label)

    spread: dict[str, dict] = {}
    for key, per_site in groups.items():
        if len(per_site) < 2:
            continue
        values = list(per_site.values())
        cheapest = min(per_site, key=lambda name: per_site[name])
        spread[spelling.get(key) or key] = {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
            "cheapest": cheapest,
            "values": dict(per_site),
        }
    return spread


def _entity_names(snapshot: SiteSnapshot) -> dict[str, str]:
    """Folded entity name -> the spelling this site used."""
    names: dict[str, str] = {}
    for entity in snapshot.entities:
        name = str(entity.get("name") or "").strip()
        if name:
            names.setdefault(_fold(name), name)
    return names


def _entity_sets(sites: list[SiteSnapshot]) -> tuple[list[str], dict[str, list[str]]]:
    """The entities every site has, and per site the ones only it has."""
    per_site = [_entity_names(snapshot) for snapshot in sites]
    everywhere = set(per_site[0]) if per_site else set()
    for names in per_site[1:]:
        everywhere &= set(names)

    shared: list[str] = []
    seen: set[str] = set()
    for names in per_site:
        for key, spelling in names.items():
            if key in everywhere and key not in seen:
                seen.add(key)
                shared.append(spelling)

    unique: dict[str, list[str]] = {}
    for index, snapshot in enumerate(sites):
        others: set[str] = set()
        for position, names in enumerate(per_site):
            if position != index:
                others |= set(names)
        unique[snapshot.site] = [
            spelling for key, spelling in per_site[index].items() if key not in others
        ]
    return shared, unique


def _other_sites(sites: list[SiteSnapshot], index: int) -> list[SiteSnapshot]:
    """Every snapshot but the one at ``index``."""
    return [other for position, other in enumerate(sites) if position != index]


def _content_gaps(sites: list[SiteSnapshot]) -> list[str]:
    """What each site is missing relative to the others, when that is real.

    Only documented differences are reported: a clone with far fewer pages, far
    less text, or no price at all while the others have prices. Comparable sites
    produce no gaps.
    """
    gaps: list[str] = []
    for index, snapshot in enumerate(sites):
        others = _other_sites(sites, index)
        if not others:
            continue

        leanest_pages = min(other.pages for other in others)
        if leanest_pages > 0 and snapshot.pages < leanest_pages * GAP_RATIO:
            gaps.append(
                f"{snapshot.site} tem {snapshot.pages} páginas e os outros têm "
                f"{leanest_pages} ou mais."
            )
        else:
            # Only worth saying when the page count did not already cover it.
            leanest_words = min(other.words for other in others)
            if leanest_words > 0 and snapshot.words < leanest_words * GAP_RATIO:
                gaps.append(
                    f"{snapshot.site} tem {snapshot.words} palavras e os outros têm "
                    f"{leanest_words} ou mais."
                )

        if not snapshot.prices and any(other.prices for other in others):
            gaps.append(f"{snapshot.site} não tem nenhum preço detectado.")
    return gaps


def _widest_spread(price_spread: dict) -> tuple[str, dict] | None:
    """The shared label whose price varies the most between the sites."""
    widest: tuple[str, dict] | None = None
    widest_ratio = 0.0
    for label, stats in price_spread.items():
        low = float(stats["min"])
        high = float(stats["max"])
        if high <= low:
            continue
        ratio = (high - low) / abs(low) if low else float("inf")
        if ratio > widest_ratio:
            widest_ratio = ratio
            widest = (label, stats)
    return widest


def _summary(sites: list[SiteSnapshot], gaps: list[str], price_spread: dict) -> str:
    """One sentence naming the sites and the most notable difference."""
    if len(sites) < 2:
        return ""

    labels = ", ".join(snapshot.site for snapshot in sites)
    if gaps:
        return f"Comparação de {labels}: {gaps[0]}"

    widest = _widest_spread(price_spread)
    if widest is not None:
        label, stats = widest
        low = float(stats["min"])
        high = float(stats["max"])
        change = (high - low) / abs(low) * 100.0 if low else 0.0
        return (
            f"Comparação de {labels}: {label or 'os preços'} varia {change:.1f}% "
            f"entre os sites, e {stats['cheapest']} tem o menor preço."
        )

    return f"Comparação de {labels}: nenhuma diferença relevante encontrada."


def compare(sites: list[SiteSnapshot]) -> Comparison:
    """Compare site snapshots.

    Args:
        sites: One snapshot per site.

    Returns:
        The comparison: price spread per shared label, common and exclusive
        entities, the documented content gaps and a one-sentence summary. Fewer
        than two sites cannot be compared, so the analysis comes back empty.
    """
    snapshots = list(sites)
    if len(snapshots) < 2:
        return Comparison(
            sites=snapshots,
            price_spread={},
            shared_entities=[],
            unique_entities={},
            content_gaps=[],
            summary="",
        )

    price_spread = _price_spread(snapshots)
    shared, unique = _entity_sets(snapshots)
    gaps = _content_gaps(snapshots)
    return Comparison(
        sites=snapshots,
        price_spread=price_spread,
        shared_entities=shared,
        unique_entities=unique,
        content_gaps=gaps,
        summary=_summary(snapshots, gaps, price_spread),
    )


# ── Rendering ──

def _amount(value: float) -> str:
    """Render an amount without thousands separators, so it stays parseable."""
    return f"{float(value):.2f}"


def _bullets(lines: list[str], entries: list[str], empty: str) -> list[str]:
    """A bullet list, or the sentence used when there is nothing to list."""
    if not entries:
        return [*lines, empty]
    return [*lines, *(f"- {entry}" for entry in entries)]


def to_markdown(comparison: Comparison) -> str:
    """Render a comparison as a readable Markdown report."""
    lines = ["# Comparação de sites", ""]
    if not comparison.sites:
        lines.append("Nenhum site para comparar.")
        return "\n".join(lines) + "\n"

    for snapshot in comparison.sites:
        lines += [
            f"## {snapshot.site}",
            "",
            f"- URL: {snapshot.url or 'não informada'}",
            f"- Páginas: {snapshot.pages}",
            f"- Palavras: {snapshot.words}",
            f"- Preços detectados: {len(snapshot.prices)}",
            f"- Entidades: {len(snapshot.entities)}",
            f"- Títulos: {', '.join(snapshot.titles) if snapshot.titles else 'nenhum'}",
        ]
        exclusives = comparison.unique_entities.get(snapshot.site) or []
        lines.append(f"- Exclusivas: {', '.join(exclusives) if exclusives else 'nenhuma'}")
        lines.append("")

    lines += ["## Preços", ""]
    if comparison.price_spread:
        lines += [
            "| Produto | Mínimo | Máximo | Média | Mais barato |",
            "| --- | --- | --- | --- | --- |",
        ]
        for label, stats in comparison.price_spread.items():
            lines.append(
                f"| {label or '(sem rótulo)'} | {_amount(stats['min'])} | {_amount(stats['max'])} "
                f"| {_amount(stats['mean'])} | {stats['cheapest']} |"
            )
    else:
        lines.append("Nenhum preço em comum entre os sites.")
    lines.append("")

    lines += ["## Entidades comuns", ""]
    lines = _bullets(lines, comparison.shared_entities, "- Nenhuma entidade em comum.")
    lines.append("")

    lines += ["## Lacunas", ""]
    lines = _bullets(lines, comparison.content_gaps, "- Nenhuma diferença relevante.")
    lines.append("")

    lines += ["## Resumo", "", comparison.summary or "Sem resumo para menos de dois sites.", ""]
    return "\n".join(lines)


def to_json(comparison: Comparison) -> dict:
    """The comparison as plain JSON-ready data."""
    return asdict(comparison)


async def compare_directories(sites: dict[str, Path]) -> Comparison:
    """Summarise each clone directory and compare them.

    The sites are summarised one at a time: the AI call per site is the slow
    part, and running them together only piles requests onto the model.

    Args:
        sites: ``{label: clone directory}``.

    Returns:
        The comparison of every measured site.
    """
    snapshots = [
        await _summarize(label, Path(dir_path), "")
        for label, dir_path in sites.items()
    ]
    return compare(snapshots)
