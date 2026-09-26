"""Automatic summarization with AI.

Pure AI layer (no engine/browser concerns) so it is testable in isolation:
`summarize_text` summarizes a string, `summarize_directory` summarizes a cloned
site (per page + one global summary).

Never raises for missing/unavailable AI: the caller always gets a dict, with an
`"error"` key when the AI module could not be used.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from zfrog.ai.client import complete, complete_structured, is_available
from zfrog.ai.schemas import SummaryResult

logger = logging.getLogger(__name__)

# Truncation budget per AI call — keeps small local models (e.g. qwen2.5) in context.
MAX_CHARS = 6000
# Truncation budget for the global summary built from per-page summaries.
MAX_GLOBAL_CHARS = 8000

SYSTEM_PROMPT = (
    "Resuma o conteúdo em português. "
    "Retorne título, resumo (3-5 frases) e 3-7 pontos-chave."
)


def _empty(error: str | None = None) -> dict:
    result: dict = {"summary": "", "key_points": [], "title": ""}
    if error:
        result["error"] = error
    return result


def _extract_text(html: str) -> str:
    """Extract readable text from HTML, with a BeautifulSoup fallback."""
    from zfrog.utils.text import extract_text

    return extract_text(html)


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


async def summarize_text(text: str, url: str = "", max_chars: int = MAX_CHARS) -> dict:
    """Summarize a block of text.

    Args:
        text: Content to summarize.
        url: Source URL (used for the prompt only).
        max_chars: Truncation limit for the input text.

    Returns:
        ``{"title", "summary", "key_points"}``; adds ``"error"`` when the AI
        module is unavailable or the request failed beyond fallback.
    """
    if not text.strip():
        return _empty()

    if not is_available():
        return _empty("AI indisponível")

    excerpt = text[:max_chars]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"URL: {url}\n\nConteúdo:\n\n{excerpt}"},
    ]

    try:
        result = await complete_structured(
            messages=messages,
            response_model=SummaryResult,
            temperature=0.0,
        )
        return {
            "title": result.title,
            "summary": result.summary,
            "key_points": list(result.key_points),
        }
    except Exception as exc:
        logger.warning("structured summarization failed (%s); falling back", exc)

    try:
        raw = await complete(messages=messages, temperature=0.0)
        parsed = _parse_loose_json(raw)
        if parsed is not None:
            key_points = parsed.get("key_points") or []
            return {
                "title": str(parsed.get("title") or ""),
                "summary": str(parsed.get("summary") or ""),
                "key_points": [str(p) for p in key_points] if isinstance(key_points, list) else [],
            }
        return {"title": "", "summary": raw[:max_chars].strip(), "key_points": []}
    except Exception as exc:
        logger.warning("summarization failed: %s", exc)
        return _empty(f"Falha na sumarização: {exc}")


async def summarize_directory(dir_path: Path, url: str, max_pages: int = 30) -> dict:
    """Summarize every HTML page in a cloned directory plus a global summary.

    Args:
        dir_path: Directory produced by a mirror/scrape job.
        url: Original site URL (used for the global summary prompt).
        max_pages: Maximum number of pages to summarize.

    Returns:
        ``{"url", "pages": [...], "global_summary": {...}}``.
    """
    html_files = sorted(f for f in dir_path.rglob("*.html") if f.is_file())[:max_pages]
    pages: list[dict] = []
    first_error: str | None = None

    for path in html_files:
        html = path.read_text(encoding="utf-8", errors="replace")
        text = _extract_text(html)
        summary = await summarize_text(text, url)
        if summary.get("error") and first_error is None:
            first_error = summary["error"]
        try:
            rel = path.relative_to(dir_path)
        except ValueError:
            rel = path
        pages.append(
            {
                "path": str(rel),
                "title": summary.get("title", ""),
                "summary": summary.get("summary", ""),
                "key_points": summary.get("key_points", []),
            }
        )

    global_summary: dict = {}
    if pages:
        combined = "\n\n".join(
            f"{p['title'] or p['path']}: {p['summary']}" for p in pages if p["summary"]
        )
        if combined.strip():
            global_summary = await summarize_text(combined[:MAX_GLOBAL_CHARS], url)
        elif first_error:
            # No page produced a summary: surface why instead of an empty dict,
            # otherwise callers (CLI, API) report success with nothing to show.
            global_summary = _empty(first_error)

    return {"url": url, "pages": pages, "global_summary": global_summary}


def to_markdown(url: str, summary: dict, pages: list[dict] | None = None) -> str:
    """Render a summary (optionally with per-page entries) as Markdown."""
    lines = [f"# Resumo — {url}", ""]

    if summary.get("error"):
        lines += [f"> {summary['error']}", ""]

    if summary.get("title"):
        lines += [f"**{summary['title']}**", ""]

    lines += ["## Resumo", summary.get("summary") or "(sem resumo)", ""]

    if summary.get("key_points"):
        lines.append("## Pontos-chave")
        lines += [f"- {point}" for point in summary["key_points"]]
        lines.append("")

    if pages:
        lines.append("## Páginas")
        for page in pages:
            lines.append(f"### {page.get('title') or page.get('path', '')}")
            lines.append(page.get("summary") or "(sem resumo)")
            for point in page.get("key_points") or []:
                lines.append(f"- {point}")
            lines.append("")

    return "\n".join(lines)
