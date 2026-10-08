"""Named-entity extraction (NER) over page text.

Pure AI layer (no engine/browser concerns) so it is testable in isolation:
`extract_entities` analyses one block of text, `merge_entities` and
`entity_counts` combine the per-page results of a multi-page run.

Never raises for missing/unavailable AI: the caller always gets a dict, with an
`"error"` key when the AI module could not be used.
"""

from __future__ import annotations

import json
import logging

from zfrog.ai.client import complete, complete_structured, is_available
from zfrog.ai.schemas import EntityResult

logger = logging.getLogger(__name__)

# Truncation budget per AI call — keeps small local models (e.g. qwen2.5) in context.
MAX_CHARS = 8000

# Type vocabulary the model is asked to use (mirrors the Entity schema).
ENTITY_TYPES = ("person", "organization", "location", "date", "product", "other")

# Confidence assumed when the model omits it or sends something unusable.
DEFAULT_CONFIDENCE = 0.8

SYSTEM_PROMPT = (
    "Extract the named entities from the text. "
    "Look for people, organizations, locations, dates and products. "
    "Use exactly these types: 'person' for people, 'organization' for organizations, "
    "'location' for locations, 'date' for dates, 'product' for products and "
    "'other' when unsure. "
    "Give each entity a confidence between 0 and 1. "
    "Do not invent: return only names that appear in the text."
)


def _empty(error: str | None = None) -> dict:
    """Empty result, with an ``"error"`` key when there is a reason to report."""
    result: dict = {"entities": [], "counts": {}}
    if error:
        result["error"] = error
    return result


def _to_confidence(value: object) -> float:
    """Coerce a model-provided confidence into a float clamped to 0-1."""
    try:
        confidence = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE
    return min(1.0, max(0.0, confidence))


def _clean_item(item: object) -> dict | None:
    """Normalize one entity (pydantic model or dict) into a plain dict.

    Returns ``None`` for entries without a usable name.
    """
    if isinstance(item, dict):
        name = str(item.get("name") or "").strip()
        entity_type = str(item.get("type") or "").strip().lower()
        confidence = item.get("confidence")
    else:
        name = str(getattr(item, "name", "") or "").strip()
        entity_type = str(getattr(item, "type", "") or "").strip().lower()
        confidence = getattr(item, "confidence", None)

    if not name:
        return None
    return {
        "name": name,
        "type": entity_type or "other",
        "confidence": _to_confidence(confidence),
    }


def _normalize(items: object) -> list[dict]:
    """Normalize a list of entities, dropping the unusable ones."""
    if not isinstance(items, list):
        return []
    cleaned = (_clean_item(item) for item in items)
    return [item for item in cleaned if item is not None]


def _entities_of(result: object) -> object:
    """Pull the entity list out of an EntityResult, a dict or a bare list."""
    if isinstance(result, dict):
        return result.get("entities", [])
    if isinstance(result, list):
        return result
    return getattr(result, "entities", [])


def _parse_loose_json(raw: str) -> dict | None:
    """Parse a JSON object from a model reply, tolerating ```json fences."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].lstrip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def entity_counts(entities: list[dict]) -> dict[str, int]:
    """Count entities per type, sorted by type name."""
    counts: dict[str, int] = {}
    for item in entities:
        cleaned = _clean_item(item)
        if cleaned is None:
            continue
        counts[cleaned["type"]] = counts.get(cleaned["type"], 0) + 1
    return dict(sorted(counts.items()))


def merge_entities(entities: list[dict]) -> list[dict]:
    """Deduplicate entities from several pages into one ranked list.

    Entities whose names match case-insensitively are merged, keeping the
    spelling, type and confidence of the highest-confidence occurrence. The
    result is sorted by confidence, descending.
    """
    merged: dict[str, dict] = {}
    for item in entities:
        cleaned = _clean_item(item)
        if cleaned is None:
            continue
        key = cleaned["name"].casefold()
        current = merged.get(key)
        if current is None or cleaned["confidence"] > current["confidence"]:
            merged[key] = cleaned
    return sorted(merged.values(), key=lambda item: (-item["confidence"], item["name"].casefold()))


async def extract_entities(text: str, max_chars: int = MAX_CHARS) -> dict:
    """Extract named entities from a block of text.

    Args:
        text: Content to analyse.
        max_chars: Truncation limit for the input text.

    Returns:
        ``{"entities": [{"name", "type", "confidence"}], "counts": {type: n}}``;
        adds ``"error"`` when the AI module is unavailable or both attempts failed.
    """
    if not text.strip():
        return _empty()

    if not is_available():
        return _empty("AI unavailable")

    excerpt = text[:max_chars]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Text:\n\n{excerpt}"},
    ]

    try:
        result = await complete_structured(
            messages=messages,
            response_model=EntityResult,
            temperature=0.0,
        )
        entities = _normalize(_entities_of(result))
        return {"entities": entities, "counts": entity_counts(entities)}
    except Exception as exc:
        logger.warning("structured entity extraction failed (%s); falling back", exc)

    try:
        raw = await complete(messages=messages, temperature=0.0)
        parsed = _parse_loose_json(raw)
        if parsed is None:
            logger.warning("entity extraction reply had no JSON object")
            return _empty("AI reply had no valid JSON")
        entities = _normalize(parsed.get("entities"))
        return {"entities": entities, "counts": entity_counts(entities)}
    except Exception as exc:
        logger.warning("entity extraction failed: %s", exc)
        return _empty(f"Entity extraction failed: {exc}")
