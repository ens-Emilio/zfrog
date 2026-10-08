"""Entities engine — named-entity extraction (NER) of a single page.

Single pass: fetches only the root URL and lists the people, organizations,
locations, dates and products it mentions (same shape as the `ask` engine).
For a whole site, run a mirror/scrape clone and merge the per-page results with
`zfrog.ai.entities.merge_entities`.
"""

from __future__ import annotations

import json
from pathlib import Path

from zfrog.ai.entities import extract_entities
from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.utils.http import create_client
from zfrog.utils.text import extract_text


def _confidence_text(value: object) -> str:
    """Format a confidence for the Markdown table, tolerating missing values."""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


def to_markdown(url: str, result: dict) -> str:
    """Render an entity result as Markdown (table of entities plus counts)."""
    lines = [f"# Entities — {url}", ""]

    if result.get("error"):
        lines += [f"> {result['error']}", ""]

    entities = result.get("entities") or []
    if entities:
        lines += ["| Name | Type | Confidence |", "| --- | --- | --- |"]
        for entity in entities:
            name = str(entity.get("name") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {name} | {entity.get('type') or 'other'} | {_confidence_text(entity.get('confidence'))} |"
            )
        lines.append("")
    else:
        lines += ["No entities found.", ""]

    counts = result.get("counts") or {}
    if counts:
        lines.append("## Count by type")
        lines += [f"- {entity_type}: {count}" for entity_type, count in counts.items()]
        lines.append("")

    return "\n".join(lines)


class EntitiesEngine(EngineAdapter):
    """Engine that extracts the named entities of a page with AI."""

    name = "entities"

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
            on_progress("Extracting entities...")

        html = ""
        try:
            async with create_client() as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
                logs.append(f"Fetched {len(html)} bytes from {url}")
        except Exception as exc:
            logs.append(f"Failed to fetch {url}: {exc}")

        text = extract_text(html)
        if text:
            logs.append(f"Extracted {len(text)} chars of text")

        extracted = await extract_entities(text)
        result: dict = {
            "url": url,
            "entities": extracted.get("entities", []),
            "counts": extracted.get("counts", {}),
        }
        if extracted.get("error"):
            result["error"] = extracted["error"]
            logs.append(f"AI: {extracted['error']}")
        else:
            logs.append(f"Extracted {len(result['entities'])} entities")

        json_path = output_dir / "entities.json"
        json_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        md_path = output_dir / "entities.md"
        md_path.write_text(to_markdown(url, result), encoding="utf-8")

        if on_progress:
            on_progress("Entities complete")

        return EngineResult(
            output_dir=output_dir,
            files=[json_path, md_path],
            total_bytes=sum(f.stat().st_size for f in (json_path, md_path)),
            logs=logs,
        )

    def can_handle(self, probe: ProbeResult) -> bool:
        return True
