"""Text translation with AI, chunked so long pages are fully translated.

The whole text is split on paragraph boundaries into pieces that fit one model
call (:func:`split_for_translation`) and every piece is translated, so a page
longer than the model's context is translated in full instead of truncated.
"""

from __future__ import annotations

import logging
import re

from zfrog.ai.client import complete, complete_structured, is_available
from zfrog.ai.schemas import TranslationResult
from zfrog.config import settings

logger = logging.getLogger(__name__)

# Characters per AI call — keeps small local models (e.g. qwen2.5) in context.
MAX_CHARS = 6000

# A paragraph break: a blank line (with optional spaces/tabs on it).
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")

SYSTEM_PROMPT = (
    "Traduza o texto recebido para o idioma de destino indicado. "
    "Retorne o texto traduzido, o idioma detectado no original (source_language) "
    "e o idioma de destino (target_language), usando códigos ISO como 'pt' ou 'en'. "
    "Preserve a formatação, os parágrafos e os nomes próprios. "
    "Não resuma, não comente e não acrescente nada ao texto."
)


def _collapse(text: str) -> str:
    """Collapse every whitespace run into a single space."""
    return " ".join(str(text or "").split())


def _split_words(paragraph: str, limit: int) -> list[str]:
    """Break one paragraph into pieces of at most ``limit`` chars, on word edges.

    A single word longer than ``limit`` (a URL, a hash) cannot fit in one piece;
    it is sliced so no character is lost.
    """
    if len(paragraph) <= limit:
        return [paragraph]

    pieces: list[str] = []
    current = ""
    for word in paragraph.split(" "):
        if not word:
            continue
        if len(word) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(word[i : i + limit] for i in range(0, len(word), limit))
            continue
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= limit:
            current = f"{current} {word}"
        else:
            pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces


def split_for_translation(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Split ``text`` into pieces of at most ``max_chars`` characters.

    Splits on paragraph boundaries first, then on word boundaries inside a
    paragraph that is too long. Nothing is dropped: joining the pieces with a
    blank line reproduces the input up to whitespace.

    Args:
        text: Text to translate.
        max_chars: Maximum length of each piece.

    Returns:
        The pieces, in order; ``[]`` for blank input.
    """
    if not text or not text.strip():
        return []

    limit = max(1, int(max_chars))
    chunks: list[str] = []
    current = ""
    for raw_paragraph in _PARAGRAPH_BREAK.split(text):
        paragraph = _collapse(raw_paragraph)
        if not paragraph:
            continue
        for piece in _split_words(paragraph, limit):
            if not current:
                current = piece
            elif len(current) + 2 + len(piece) <= limit:
                current = f"{current}\n\n{piece}"
            else:
                chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def _field(result: object, name: str, default: str = "") -> str:
    """Read a string field from a pydantic model or a plain dict."""
    if isinstance(result, dict):
        value = result.get(name)
    else:
        value = getattr(result, name, None)
    if value is None:
        return default
    return str(value).strip()


def _render_prompt(text: str, target: str, source: str) -> str:
    """Render one chunk as the user message."""
    lines = [f"Idioma de destino: {target}"]
    if source:
        lines.append(f"Idioma de origem: {source}")
    lines += ["", "Texto:", "", text]
    return "\n".join(lines)


async def _translate_chunk(text: str, target: str, source: str) -> dict:
    """Translate one chunk, falling back to a plain completion.

    Returns:
        ``{"text", "source_language", "target_language", "error"}`` where
        ``error`` is ``None`` on success.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _render_prompt(text, target, source)},
    ]

    try:
        result = await complete_structured(
            messages=messages,
            response_model=TranslationResult,
            temperature=0.0,
        )
        translated = _field(result, "text")
        return {
            "text": translated,
            "source_language": _field(result, "source_language") or source,
            "target_language": _field(result, "target_language") or target,
            "error": None,
        }
    except Exception as exc:
        logger.warning("structured translation failed (%s); falling back", exc)

    try:
        raw = await complete(messages=messages, temperature=0.0)
        return {
            "text": (raw or "").strip(),
            "source_language": source,
            "target_language": target,
            "error": None,
        }
    except Exception as exc:
        logger.warning("translation failed: %s", exc)
        # Keep the original chunk so a failed call never loses content.
        return {
            "text": text,
            "source_language": source,
            "target_language": target,
            "error": f"Falha na tradução: {exc}",
        }


async def translate_text(
    text: str,
    target: str = "",
    source: str = "",
    max_chars: int = MAX_CHARS,
) -> dict:
    """Translate a block of text into ``target``.

    Long input is split into chunks (:func:`split_for_translation`), each chunk
    is translated, and the results are joined with a blank line.

    Args:
        text: Content to translate.
        target: Target language code; defaults to ``settings.translation_target``.
        source: Known source language code (optional, the model detects it otherwise).
        max_chars: Characters per AI call.

    Returns:
        ``{"text", "source_language", "target_language"}``; adds ``"error"`` when
        the AI module is unavailable or a call failed. Never raises.
    """
    target_language = (target or "").strip() or settings.translation_target
    source_language = (source or "").strip()

    if not text or not text.strip():
        return {
            "text": "",
            "source_language": source_language,
            "target_language": target_language,
        }

    if not is_available():
        return {
            "text": "",
            "source_language": source_language,
            "target_language": target_language,
            "error": "AI indisponível",
        }

    chunks = split_for_translation(text, max_chars=max_chars)
    if not chunks:
        return {
            "text": "",
            "source_language": source_language,
            "target_language": target_language,
        }

    translated_parts: list[str] = []
    errors: list[str] = []
    detected_source = source_language
    result_target = target_language

    for chunk in chunks:
        chunk_result = await _translate_chunk(chunk, target_language, detected_source)
        if chunk_result["text"]:
            translated_parts.append(chunk_result["text"])
        if chunk_result["error"]:
            errors.append(chunk_result["error"])
        elif not detected_source:
            detected_source = chunk_result["source_language"]
        if chunk_result["target_language"]:
            result_target = chunk_result["target_language"]

    result: dict = {
        "text": "\n\n".join(translated_parts),
        "source_language": detected_source,
        "target_language": result_target,
    }
    if errors:
        result["error"] = errors[0]
    return result
