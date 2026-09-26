"""Compare engine — compares two pages or two jobs.

Modes:
1. compare_url: Compare original URL vs its clone (same job, different engines)
2. compare_jobs: Compare outputs of two different jobs
3. compare_engines: Run same URL through multiple engines, report best
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.pipeline.fidelity import compute_fidelity, FidelityResult


@dataclass
class CompareResult:
    url: str
    fidelity: FidelityResult = field(default_factory=FidelityResult)
    summary: str = ""
    details: dict = field(default_factory=dict)


class CompareEngine(EngineAdapter):
    """Engine that compares original vs clone or across engines."""

    name = "compare"

    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        logs = []
        url = str(job.url)

        if on_progress:
            on_progress("Preparando comparação...")

        # Get original HTML from URL
        import httpx
        from zfrog.utils.http import create_client

        original_html = ""
        clone_html = ""
        original_files: list[Path] = []
        clone_files: list[Path] = []

        # Fetch original
        if on_progress:
            on_progress("Buscando página original...")
        try:
            async with create_client() as client:
                resp = await client.get(url)
                original_html = resp.text
                logs.append(f"Original: {len(original_html)} bytes")
        except Exception as e:
            logs.append(f"Falha ao buscar original: {e}")

        # For clone HTML, check if there's a previous mirror/singlepage job output
        # in the same output directory parent (user may have cloned before comparing)
        parent_dir = output_dir.parent
        for sibling in parent_dir.iterdir():
            if sibling.is_dir() and sibling != output_dir:
                # Look for HTML files (a directory named "*.html" is not a page)
                html_files = [f for f in sibling.rglob("*.html") if f.is_file()]
                if html_files:
                    clone_html = html_files[0].read_text(encoding="utf-8", errors="replace")
                    clone_files = [f for f in sibling.rglob("*") if f.is_file()]
                    logs.append(f"Clone encontrado: {html_files[0].name} ({len(clone_html)} bytes)")
                    break

        if not clone_html:
            # If no clone found, compare original vs itself (baseline)
            clone_html = original_html
            clone_files = []
            logs.append("Nenhum clone encontrado — comparando original consigo mesmo (baseline)")

        # Compute fidelity
        if on_progress:
            on_progress("Calculando Fidelity Score...")
        fidelity = compute_fidelity(
            original_html=original_html,
            clone_html=clone_html,
            original_files=original_files or [],
            clone_files=clone_files,
        )

        # Build result
        from datetime import datetime
        result = CompareResult(
            url=url,
            fidelity=fidelity,
            summary=f"Fidelity Score: {fidelity.composite}/100",
            details={
                "original_size": len(original_html),
                "clone_size": len(clone_html),
                "original_files": len(original_files),
                "clone_files": len(clone_files),
            },
        )

        # Save report
        report_path = output_dir / "comparison.json"
        report_path.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False, default=str), encoding="utf-8")

        # Save markdown
        md_path = output_dir / "comparison.md"
        md_path.write_text(self._to_markdown(result), encoding="utf-8")

        if on_progress:
            on_progress(f"Fidelity Score: {fidelity.composite}/100")

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

    def _to_markdown(self, result: CompareResult) -> str:
        f = result.fidelity
        lines = [
            f"# Comparação — {result.url}",
            "",
            f"## Fidelity Score: {f.composite}/100",
            "",
            "### Sub-scores",
            f"| Métrica | Score | Peso |",
            f"|---|---|---|",
            f"| Visual (similaridade de estrutura) | {f.visual}/100 | 25% |",
            f"| Estrutural (tags HTML) | {f.structural}/100 | 30% |",
            f"| Texto (conteúdo visível) | {f.text}/100 | 30% |",
            f"| Assets (cobertura de arquivos) | {f.assets}/100 | 15% |",
            "",
            "### Detalhes",
            f"- Tamanho original: {result.details.get('original_size', 0):,} bytes",
            f"- Tamanho clone: {result.details.get('clone_size', 0):,} bytes",
            f"- Arquivos originais: {result.details.get('original_files', 0)}",
            f"- Arquivos clone: {result.details.get('clone_files', 0)}",
            "",
            "### Interpretação",
        ]

        if f.composite >= 95:
            lines.append("🟢 **Excelente** — clone praticamente idêntico ao original.")
        elif f.composite >= 80:
            lines.append("🟡 **Bom** — clone fiel com pequenas diferenças.")
        elif f.composite >= 60:
            lines.append("🟠 **Razoável** — clone funcional mas com diferenças notáveis.")
        else:
            lines.append("🔴 **Baixo** — clone difere significativamente do original.")

        return "\n".join(lines)
