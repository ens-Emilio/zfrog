"""Content enrichment with AI: sentiment analysis and topical auto-tagging.

Pure AI layer (no engine/browser concerns) so it is testable in isolation:
`analyze_sentiment` rates the tone of a block of text, `suggest_tags` proposes
short topical tags for it.

Never raises for missing/unavailable AI: the caller always gets a dict, with an
`"error"` key when the AI module could not be used.
"""

from __future__ import annotations

import json
import logging
import math

from zfrog.ai.client import complete, complete_structured, is_available
from zfrog.ai.schemas import SentimentResult, TagResult

logger = logging.getLogger(__name__)

# Truncation budget per AI call — keeps small local models (e.g. qwen2.5) in context.
MAX_CHARS = 6000

# How many tags a caller gets when it does not ask for a specific amount.
DEFAULT_MAX_TAGS = 8

# Canonical sentiment vocabulary (mirrors the SentimentResult schema).
SENTIMENTS = ("positive", "negative", "neutral")

# Models answer in Portuguese as often as in English; both map to the canonical set.
SENTIMENT_ALIASES = {
    "positive": "positive",
    "positivo": "positive",
    "positiva": "positive",
    "negative": "negative",
    "negativo": "negative",
    "negativa": "negative",
    "neutral": "neutral",
    "neutro": "neutral",
    "neutra": "neutral",
}

# Substring fallbacks, so "muito positivo" or "positive (pt-BR)" still resolve.
SENTIMENT_STEMS = (
    ("positiv", "positive"),
    ("negativ", "negative"),
    ("neutr", "neutral"),
)

SENTIMENT_PROMPT = (
    "Classifique o sentimento do texto em relação ao seu assunto principal. "
    "Responda com 'sentiment' valendo 'positive', 'negative' ou 'neutral', "
    "com 'score' entre -1 (muito negativo) e 1 (muito positivo) "
    "e com 'rationale' contendo uma justificativa curta."
)

TAGS_PROMPT = (
    "Sugira até {max_tags} assuntos (tags) curtos, em português, que descrevam o texto. "
    "Use termos simples em minúsculas, sem repetições e sem numeração."
)


def _empty_sentiment(error: str | None = None) -> dict:
    """Neutral sentiment result, with an ``"error"`` key when there is a reason."""
    result: dict = {"sentiment": "neutral", "score": 0.0, "rationale": ""}
    if error:
        result["error"] = error
    return result


def _empty_tags(error: str | None = None) -> dict:
    """Empty tag result, with an ``"error"`` key when there is a reason."""
    result: dict = {"tags": []}
    if error:
        result["error"] = error
    return result


def _field(result: object, name: str) -> object:
    """Read ``name`` from a pydantic model, a dict or any duck-typed object."""
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)


def _to_score(value: object) -> float:
    """Coerce a model-provided score into a float clamped to -1..1."""
    try:
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(score):
        return 0.0
    return max(-1.0, min(1.0, score))


def _normalize_sentiment(value: object) -> str:
    """Map a model-provided label onto positive, negative or neutral."""
    label = str(value or "").strip().lower()
    if label in SENTIMENT_ALIASES:
        return SENTIMENT_ALIASES[label]
    for stem, canonical in SENTIMENT_STEMS:
        if stem in label:
            return canonical
    return "neutral"


def _normalize_tags(tags: object, max_tags: int) -> list[str]:
    """Lower-case, trim, deduplicate (case-insensitively) and cap a tag list."""
    if max_tags <= 0 or not isinstance(tags, (list, tuple, set)):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in tags:
        if not isinstance(item, (str, int, float)):
            continue
        tag = str(item).strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        cleaned.append(tag)
        if len(cleaned) >= max_tags:
            break
    return cleaned


def _parse_loose_json(raw: str) -> object | None:
    """Parse the JSON payload of a model reply, tolerating ```json fences.

    Models answer with either an object or a bare array, so both are accepted.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].lstrip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start == -1 or end <= start:
            continue
        try:
            parsed = json.loads(text[start : end + 1])
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
    return None


def _sentiment_from(payload: object) -> dict:
    """Normalize a sentiment payload (pydantic model or dict) into the result dict."""
    return {
        "sentiment": _normalize_sentiment(_field(payload, "sentiment")),
        "score": _to_score(_field(payload, "score")),
        "rationale": str(_field(payload, "rationale") or "").strip(),
    }


def _tags_from(payload: object, max_tags: int) -> list[str]:
    """Normalize a tag payload (pydantic model, dict or bare list) into a tag list."""
    if isinstance(payload, list):
        return _normalize_tags(payload, max_tags)
    return _normalize_tags(_field(payload, "tags"), max_tags)


async def analyze_sentiment(text: str, max_chars: int = MAX_CHARS) -> dict:
    """Rate the emotional tone of a block of text.

    Args:
        text: Content to analyse.
        max_chars: Truncation limit for the input text.

    Returns:
        ``{"sentiment", "score", "rationale"}`` with the sentiment in
        ``positive|negative|neutral`` and the score in ``-1..1``; adds
        ``"error"`` when the AI module is unavailable or both attempts failed.
    """
    if not text.strip():
        return _empty_sentiment()

    if not is_available():
        return _empty_sentiment("AI indisponível")

    messages = [
        {"role": "system", "content": SENTIMENT_PROMPT},
        {"role": "user", "content": f"Texto:\n\n{text[:max_chars]}"},
    ]

    try:
        result = await complete_structured(
            messages=messages,
            response_model=SentimentResult,
            temperature=0.0,
        )
        return _sentiment_from(result)
    except Exception as exc:
        logger.warning("structured sentiment analysis failed (%s); falling back", exc)

    try:
        raw = await complete(messages=messages, temperature=0.0)
        parsed = _parse_loose_json(raw)
        if not isinstance(parsed, dict):
            logger.warning("sentiment reply had no JSON object")
            return _empty_sentiment("Resposta da IA sem JSON válido")
        return _sentiment_from(parsed)
    except Exception as exc:
        logger.warning("sentiment analysis failed: %s", exc)
        return _empty_sentiment(f"Falha na análise de sentimento: {exc}")


async def suggest_tags(
    text: str,
    max_tags: int = DEFAULT_MAX_TAGS,
    max_chars: int = MAX_CHARS,
) -> dict:
    """Propose short topical tags for a block of text.

    Args:
        text: Content to analyse.
        max_tags: Maximum number of tags to return.
        max_chars: Truncation limit for the input text.

    Returns:
        ``{"tags": [str]}`` (lower-cased, deduplicated, at most ``max_tags``);
        adds ``"error"`` when the AI module is unavailable or both attempts failed.
    """
    if not text.strip():
        return _empty_tags()

    if not is_available():
        return _empty_tags("AI indisponível")

    messages = [
        {"role": "system", "content": TAGS_PROMPT.format(max_tags=max_tags)},
        {"role": "user", "content": f"Texto:\n\n{text[:max_chars]}"},
    ]

    try:
        result = await complete_structured(
            messages=messages,
            response_model=TagResult,
            temperature=0.0,
        )
        return {"tags": _tags_from(result, max_tags)}
    except Exception as exc:
        logger.warning("structured tag suggestion failed (%s); falling back", exc)

    try:
        raw = await complete(messages=messages, temperature=0.0)
        parsed = _parse_loose_json(raw)
        if parsed is None:
            logger.warning("tag reply had no JSON payload")
            return _empty_tags("Resposta da IA sem JSON válido")
        return {"tags": _tags_from(parsed, max_tags)}
    except Exception as exc:
        logger.warning("tag suggestion failed: %s", exc)
        return _empty_tags(f"Falha na sugestão de assuntos: {exc}")
