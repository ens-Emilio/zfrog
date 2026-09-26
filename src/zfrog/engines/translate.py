"""Translate engine — translates the text of a single page.

Single pass: fetches only the root URL, extracts its text and translates it into
the target language (`--target`, defaulting to `settings.translation_target`).
Writes `translation.json` and `translation.md` even when the page or the model
is unreachable, so the job always leaves a readable result behind.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from zfrog.ai.translate import translate_text
from zfrog.config import settings
from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.utils.http import create_client
from zfrog.utils.text import extract_text

logger = logging.getLogger(__name__)


def resolve_target(job: JobCreate) -> str:
    """Target language for a job: its own `translate_target`, else the setting."""
    requested = getattr(job, "translate_target", "") or ""
    return str(requested).strip() or settings.translation_target


def to_markdown(url: str, result: dict) -> str:
    """Render a translation result as Markdown (heading, notice, text)."""
    lines = [f"# {url}", ""]

    if result.get("error"):
        lines += [f"> {result['error']}", ""]

    text = str(result.get("text") or "").strip()
    if text:
        lines += [text, ""]
    else:
        lines += ["Nenhum texto traduzido.", ""]

    return "\n".join(lines)


class TranslateEngine(EngineAdapter):
    """Engine that translates the text of a page with AI."""

    name = "translate"

    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        logs: list[str] = []
        url = str(job.url)
        target = resolve_target(job)

        if on_progress:
            on_progress("Traduzindo...")

        html = ""
        try:
            async with create_client() as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
                logs.append(f"Fetched {len(html)} bytes from {url}")
        except Exception as exc:
            logger.warning("Falha ao buscar %s: %s", url, exc)
            logs.append(f"Falha ao buscar {url}: {exc}")

        text = extract_text(html)
        if text:
            logs.append(f"Extracted {len(text)} chars of text")

        translated = await translate_text(text, target=target)

        result: dict = {
            "url": url,
            "target": target,
            "source_language": translated.get("source_language", ""),
            "text": translated.get("text", ""),
        }
        if translated.get("error"):
            result["error"] = translated["error"]
            logger.warning("Tradução de %s: %s", url, translated["error"])
            logs.append(f"AI: {translated['error']}")
        else:
            logs.append(f"Translated {len(result['text'])} chars")

        json_path = output_dir / "translation.json"
        json_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        md_path = output_dir / "translation.md"
        md_path.write_text(to_markdown(url, result), encoding="utf-8")

        if on_progress:
            on_progress("Tradução concluída")

        return EngineResult(
            output_dir=output_dir,
            files=[json_path, md_path],
            total_bytes=sum(f.stat().st_size for f in (json_path, md_path)),
            logs=logs,
        )

    def can_handle(self, probe: ProbeResult) -> bool:
        return True
