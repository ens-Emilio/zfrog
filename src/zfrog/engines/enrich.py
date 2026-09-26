"""Enrich engine — sentiment analysis and topical tags for a single page.

Single pass: fetches only the root URL and writes `enrichment.json` plus
`enrichment.md` (same shape as the `ask` engine). For a whole site, run a
mirror/scrape clone and enrich the pages one by one.
"""

from __future__ import annotations

import json
from pathlib import Path

from zfrog.ai.enrich import analyze_sentiment, suggest_tags
from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.utils.http import create_client
from zfrog.utils.text import extract_text


def _score_text(value: object) -> str:
    """Format a sentiment score for the Markdown report, tolerating missing values."""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def to_markdown(url: str, result: dict) -> str:
    """Render an enrichment result as Markdown (sentiment, tags and errors)."""
    lines = [f"# Enriquecimento — {url}", ""]

    sentiment = result.get("sentiment") or {}
    lines += ["## Sentimento", ""]
    lines.append(f"- Sentimento: {sentiment.get('sentiment', 'neutral')}")
    lines.append(f"- Pontuação: {_score_text(sentiment.get('score'))}")
    rationale = str(sentiment.get("rationale") or "").strip()
    if rationale:
        lines.append(f"- Justificativa: {rationale}")
    lines.append("")

    lines += ["## Assuntos", ""]
    tags = result.get("tags") or []
    if tags:
        lines += [f"- {tag}" for tag in tags]
    else:
        lines.append("Nenhum assunto identificado.")
    lines.append("")

    errors = result.get("errors") or []
    if errors:
        lines.append("## Erros")
        lines += [f"- {error}" for error in errors]
        lines.append("")

    return "\n".join(lines)


class EnrichEngine(EngineAdapter):
    """Engine that analyses the sentiment and the subjects of a page with AI."""

    name = "enrich"

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
            on_progress("Analisando sentimento e assuntos...")

        html = ""
        try:
            async with create_client() as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
                logs.append(f"Fetched {len(html)} bytes from {url}")
        except Exception as exc:
            logs.append(f"Falha ao buscar {url}: {exc}")

        text = extract_text(html)
        if text:
            logs.append(f"Extracted {len(text)} chars of text")

        sentiment = await analyze_sentiment(text)
        tags_result = await suggest_tags(text)

        errors: list[str] = []
        for label, payload in (("sentimento", sentiment), ("assuntos", tags_result)):
            message = str(payload.get("error") or "").strip()
            if not message:
                continue
            logs.append(f"AI ({label}): {message}")
            if message not in errors:
                errors.append(message)

        result: dict = {
            "url": url,
            "sentiment": sentiment,
            "tags": tags_result.get("tags", []),
            "errors": errors,
        }

        json_path = output_dir / "enrichment.json"
        json_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        md_path = output_dir / "enrichment.md"
        md_path.write_text(to_markdown(url, result), encoding="utf-8")

        if on_progress:
            on_progress("Enriquecimento concluído")

        return EngineResult(
            output_dir=output_dir,
            files=[json_path, md_path],
            total_bytes=sum(f.stat().st_size for f in (json_path, md_path)),
            logs=logs,
        )

    def can_handle(self, probe: ProbeResult) -> bool:
        return True
