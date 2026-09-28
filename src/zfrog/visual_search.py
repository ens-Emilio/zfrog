"""Descriptive search over the reference catalog.

"moodboards escuros com cards arredondados" is answered by embedding a *text
description of the visual properties* of each capture and ranking by cosine
similarity against the query.

The honest limitation, stated up front: this does **not** embed the screenshot
pixels. It embeds a structured description built from the extracted tokens — dominant
colours with their roles and lightness, the corner radii, the shadow vocabulary, the
typography. That is enough to answer the plan's own examples ("layouts escuros",
"tipografia serifada", "cards arredondados") because those are properties the
extraction already measured. It would not find "the one with the big photo of a dog".

Embedding the image itself needs a vision embedding model. :func:`describe` is the only
place that would change: everything else — storage, cosine ranking, the fallback —
already works with any vector.
"""

from __future__ import annotations

import asyncio
import colorsys
import math
import os
from dataclasses import dataclass

from zfrog.catalog import Card, Catalog

#: Words used for the lightness band of a colour. Chosen because they are what a
#: person types when describing a design, not because they are precise.
_LIGHTNESS_WORDS = (
    (0.18, "muito escuro"),
    (0.35, "escuro"),
    (0.65, "claro"),
    (1.01, "muito claro"),
)

#: Saturation threshold above which a colour gets a hue name.
_VIVID_SATURATION = 0.25

#: Hue ranges (degrees) and the Portuguese name for them.
_HUE_WORDS: tuple[tuple[float, float, str], ...] = (
    (15, "vermelho"),
    (45, "laranja"),
    (70, "amarelo"),
    (165, "verde"),
    (200, "ciano"),
    (255, "azul"),
    (290, "violeta"),
    (345, "rosa"),
    (361, "vermelho"),
)

#: Shadow scale words, by the largest blur radius reported.
_SHADOW_WORDS = ((4, "sombras discretas"), (16, "sombras médias"), (10_000, "sombras amplas"))


@dataclass
class VisualHit:
    """A catalog card and how well it matched a description."""

    card: Card
    score: float


def _hue_name(hue_degrees: float) -> str:
    for limit, name in _HUE_WORDS:
        if hue_degrees < limit:
            return name
    return "vermelho"


def _lightness_name(lightness: float) -> str:
    for limit, name in _LIGHTNESS_WORDS:
        if lightness < limit:
            return name
    return "muito claro"


def _color_words(hex_color: str) -> list[str]:
    """Descriptive words for one colour: hue, vividness and lightness."""
    raw = (hex_color or "").lstrip("#")
    if len(raw) != 6:
        return []
    try:
        channels = [int(raw[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    except ValueError:
        return []

    hue, lightness, saturation = colorsys.rgb_to_hls(*channels)

    words = [_lightness_name(lightness)]
    if saturation >= _VIVID_SATURATION:
        words.append(_hue_name(hue * 360))
        words.append("vivo")
    else:
        words.append("neutro")
    return words


def _radius_words(card: Card) -> list[str]:
    """Rounding vocabulary, from the token the extraction actually measured."""
    radii = [value for value, _count in card.tokens.get("radii", [])]
    pixels = []
    for value in radii:
        if isinstance(value, str) and value.endswith("px"):
            try:
                pixels.append(float(value[:-2]))
            except ValueError:
                continue
    if not pixels:
        return []
    largest = max(pixels)
    if largest == 0:
        return ["cantos retos", "sem arredondamento"]
    if largest < 6:
        return ["cantos levemente arredondados"]
    if largest < 14:
        return ["cantos arredondados"]
    return ["cantos muito arredondados", "pílulas"]


def _shadow_words(card: Card) -> list[str]:
    """Shadow vocabulary, by the largest blur in the shadow tokens."""
    largest = 0.0
    for value, _count in card.tokens.get("shadows", []):
        for part in str(value).replace(",", " ").split():
            if part.endswith("px"):
                try:
                    largest = max(largest, float(part[:-2]))
                except ValueError:
                    continue
    if largest == 0:
        return ["sem sombras", "superfícies planas"]
    return [name for limit, name in _SHADOW_WORDS if largest <= limit][:1]


def describe(card: Card) -> str:
    """The searchable text description of a capture's visual properties.

    Deterministic: the same card always describes to the same string, so an embedding
    is stable and a re-index does not drift.
    """
    parts: list[str] = []

    if card.title:
        parts.append(card.title)
    if card.note:
        parts.append(card.note)
    if card.tags:
        parts.extend(card.tags)
    if card.site:
        parts.append(card.site)

    palette = card.tokens.get("palette", [])
    for entry in palette[:5]:
        words = _color_words(str(entry.get("hex", "")))
        if words:
            role = entry.get("role")
            prefix = f"cor {role}" if role else "cor"
            parts.append(f"{prefix} {' '.join(words)}")

    fonts = card.tokens.get("fonts", [])
    serif_hints = ("serif", "times", "georgia", "playfair")
    for font in fonts[:3]:
        family = str(font.get("family", ""))
        if not family:
            continue
        generic = (
            "serifada"
            if any(hint in family.lower() for hint in serif_hints)
            else "sem serifa"
        )
        parts.append(f"tipografia {generic} {family}")

    parts.extend(_radius_words(card))
    parts.extend(_shadow_words(card))
    return " ".join(part for part in parts if part).strip()


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0.0 when either vector has no magnitude or shapes differ."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _lexical_score(query: str, text: str) -> float:
    """Share of the query's words that appear in the description.

    The fallback when no embedding model is configured, so the feature degrades to
    something useful instead of to nothing.
    """
    terms = [term for term in query.lower().split() if len(term) > 2]
    if not terms:
        return 0.0
    haystack = text.lower()
    return sum(1 for term in terms if term in haystack) / len(terms)


def embeddings_configured() -> bool:
    """Whether the user actually configured an embedding model.

    ``ai.client.is_available()`` only reports that litellm is importable, so it is
    true on every install — including one with no model running. Attempting an
    embedding then prints litellm's provider list to stderr and fails, which reads as
    a broken command. Treating "no explicit model configured" as "no embeddings" keeps
    the fallback silent and honest: the search still answers, by words.
    """
    return bool(os.environ.get("ZFROG_AI_EMBEDDING") or os.environ.get("ZFROG_AI_MODEL"))


async def embed_catalog(catalog: Catalog, *, force: bool = False) -> int:
    """Embed every card in the catalog and store the vectors.

    Returns how many vectors were written. Cards already embedded are skipped unless
    ``force`` is set, so this is cheap to call again after a new capture.
    """
    from zfrog.ai.client import embed, get_embedding_model, is_available

    if not (is_available() and embeddings_configured()):
        return 0

    existing = catalog.embeddings()
    cards = catalog.list(limit=10_000)
    pending = [card for card in cards if force or card.id not in existing]
    if not pending:
        return 0

    vectors = await embed([describe(card) for card in pending])
    model = get_embedding_model()
    for card, vector in zip(pending, vectors):
        catalog.store_embedding(card.id, vector, model=model)
    return len(pending)


def search(
    catalog: Catalog,
    query: str,
    *,
    limit: int = 20,
    vectors: dict[str, tuple[list[float], str]] | None = None,
    query_vector: list[float] | None = None,
) -> list[VisualHit]:
    """Rank catalog cards against a description.

    Uses embeddings when both a stored vector and an embedded query are available;
    falls back to word overlap otherwise, so a deployment with no model still gets
    results instead of an empty list.
    """
    text = (query or "").strip()
    if not text:
        return []

    cards = catalog.list(limit=10_000)
    if not cards:
        return []

    stored = vectors if vectors is not None else catalog.embeddings()

    hits: list[VisualHit] = []
    for card in cards:
        entry = stored.get(card.id)
        if query_vector is not None and entry is not None:
            score = _cosine(query_vector, entry[0])
        else:
            score = _lexical_score(text, describe(card))
        if score > 0:
            hits.append(VisualHit(card=card, score=score))

    hits.sort(key=lambda hit: (-hit.score, hit.card.id))
    return hits[:limit]


async def search_descriptive(catalog: Catalog, query: str, *, limit: int = 20) -> list[VisualHit]:
    """Search with the query embedded, falling back to the lexical ranking."""
    from zfrog.ai.client import embed, is_available

    query_vector: list[float] | None = None
    if is_available() and embeddings_configured():
        try:
            vectors = await embed([query])
            query_vector = vectors[0] if vectors else None
        except Exception:
            # A model that is configured but unreachable must not turn a search into
            # an error; the lexical ranking below still answers.
            query_vector = None

    return search(catalog, query, limit=limit, query_vector=query_vector)


def embed_catalog_sync(catalog: Catalog, *, force: bool = False) -> int:
    """Blocking wrapper for callers that are not already in an event loop."""
    return asyncio.run(embed_catalog(catalog, force=force))


__all__ = [
    "VisualHit",
    "embeddings_configured",
    "describe",
    "embed_catalog",
    "embed_catalog_sync",
    "search",
    "search_descriptive",
]
