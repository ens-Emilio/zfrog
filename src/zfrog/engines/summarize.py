"""Summarize engine — AI summary of a single page.

Single pass: fetches only the root URL and summarizes its text (same shape as
the `ask` engine). For a whole site, run a mirror/scrape clone and then
`zfrog summarize-dir <output_dir>`.
"""

from __future__ import annotations

import json
from pathlib import Path

from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult

AI_UNAVAILABLE_MSG = "Módulo de IA indisponível. Instale litellm: pip install litellm"


class SummarizeEngine(EngineAdapter):
    """Engine that summarizes page content with AI."""

    name = "summarize"

    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        logs: list[str] = []
        url = str(job.url)

        if on_progress:
            on_progress("Resumindo com IA...")

        from zfrog.ai.summarize import summarize_text, to_markdown
        from zfrog.utils.http import create_client

        html = ""
        text = ""
        try:
            async with create_client() as client:
                resp = await client.get(url)
                html = resp.text
                logs.append(f"Fetched {len(html)} bytes from {url}")
        except Exception as e:
            logs.append(f"Falha ao buscar {url}: {e}")

        if html:
            from zfrog.utils.text import extract_text

            text = extract_text(html)
            logs.append(f"Extracted {len(text)} chars of text")

        summary = await summarize_text(text, url)
        if summary.get("error") == "AI indisponível":
            summary["error"] = AI_UNAVAILABLE_MSG

        json_path = output_dir / "summary.json"
        json_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        md_path = output_dir / "summary.md"
        md_path.write_text(to_markdown(url, summary), encoding="utf-8")

        if on_progress:
            on_progress("Resumo concluído")

        return EngineResult(
            output_dir=output_dir,
            files=[json_path, md_path],
            total_bytes=sum(f.stat().st_size for f in (json_path, md_path)),
            logs=logs,
        )

    def can_handle(self, probe: ProbeResult) -> bool:
        return True
