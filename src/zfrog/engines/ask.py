"""Ask engine — natural language queries over web content.

Two modes:
1. extract: Ask "quais são os preços?" → structured JSON
2. query: Ask anything about a previously cloned site → answer with sources

Uses AI module (LiteLLM) for generation and RAG for context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult


@dataclass
class AskResult:
    url: str
    query: str
    answer: str = ""
    sources: list[str] = field(default_factory=list)
    context: list[dict] = field(default_factory=list)
    extraction: dict | None = None


class AskEngine(EngineAdapter):
    """Engine for natural language queries over web content."""

    name = "ask"

    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        logs = []
        url = str(job.url)

        # The query comes from job.follow_links (repurposed as query field)
        # In a real implementation, this would be a dedicated field
        query = getattr(job, "query", "") or "Extraia as informações principais desta página"

        if on_progress:
            on_progress("Preparando consulta...")

        # Step 1: Fetch page content
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

        # Step 2: Extract clean text
        if html:
            from zfrog.utils.text import extract_text

            text = extract_text(html)
            logs.append(f"Extracted {len(text)} chars of text")

        # Step 3: Index the page and query it.
        # Uses the same semantic index as `chat` (embeddings when a model is
        # configured, BM25 otherwise) instead of the old word-overlap search.
        from zfrog.ai.client import complete_structured, is_available
        from zfrog.ai.multisite import MultiSiteIndex
        from zfrog.ai.schemas import ExtractionResult

        index = MultiSiteIndex(output_dir.parent / ".rag-multi")

        if text:
            chunks = index.add_text(site=url, text=text, path=url, url=url, replace=True)
            logs.append(f"Indexed {chunks} chunk(s) for the query")

        # Step 4: Query
        if on_progress:
            on_progress("Consultando IA...")

        if is_available() and text:
            rag_result = await index.query(question=query)
            answer = rag_result.get("answer", "")
            citations = rag_result.get("citations", [])
            sources = [citation.url or citation.site for citation in citations]
            context = [
                {"text": citation.snippet, "source": citation.url or citation.site}
                for citation in citations
            ]

            # Also try structured extraction
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Extraia informações do texto fornecido de acordo com a pergunta. "
                        "Retorne um JSON com os campos encontrados e seus valores. "
                        "Se não encontrar algo, retorne null para esse campo."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Texto:\n\n{text[:4000]}\n\n---\nPergunta: {query}",
                },
            ]

            try:
                extraction = await complete_structured(
                    messages=messages,
                    response_model=ExtractionResult,
                    temperature=0.0,
                )
                extraction_dict = extraction.model_dump() if hasattr(extraction, "model_dump") else {}
            except Exception:
                extraction_dict = None
        else:
            answer = "Módulo de IA indisponível. Instale litellm: pip install litellm"
            sources = []
            context = []
            extraction_dict = None

        # Build result
        result = AskResult(
            url=url,
            query=query,
            answer=answer,
            sources=sources,
            context=context,
            extraction=extraction_dict,
        )

        # Save
        report_path = output_dir / "ask_result.json"
        report_path.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False, default=str), encoding="utf-8")

        md_path = output_dir / "ask_result.md"
        md_path.write_text(self._to_markdown(result), encoding="utf-8")

        if on_progress:
            on_progress("Consulta concluída")

        files = [report_path, md_path]
        total_bytes = sum(f.stat().st_size for f in files)

        return EngineResult(
            output_dir=output_dir,
            files=files,
            total_bytes=total_bytes,
            logs=logs,
        )

    def can_handle(self, probe: ProbeResult) -> bool:
        return True

    def _to_markdown(self, result: AskResult) -> str:
        lines = [
            f"# Consulta — {result.url}",
            f"**Pergunta:** {result.query}",
            "",
            "## Resposta",
            result.answer or "(sem resposta)",
            "",
        ]

        if result.sources:
            lines.append("## Fontes")
            for s in result.sources:
                lines.append(f"- {s}")
            lines.append("")

        if result.extraction:
            lines.append("## Extração Estruturada")
            lines.append("```json")
            lines.append(json.dumps(result.extraction, indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")

        if result.context:
            lines.append("## Trechos Relevantes")
            for i, c in enumerate(result.context[:3], 1):
                lines.append(f"### Trecho {i} ({c.get('source', 'n/a')})")
                lines.append(c.get("text", "")[:300])
                lines.append("")

        return "\n".join(lines)
