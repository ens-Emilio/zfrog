"""PDF engine — renders a page to a print-quality PDF with Playwright.

Reuses the shared browser pool from the Playwright engine, so a PDF job never
starts a second browser.
"""

from __future__ import annotations

import re
from pathlib import Path

from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.engines.playwright import get_pool, session_state_for
from zfrog.models import JobCreate, ProbeResult

_UNSAFE_PDF_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_pdf_name(name: str) -> str:
    """Turn an arbitrary string into a safe PDF base name.

    Path separators, spaces and anything outside ``[A-Za-z0-9._-]`` become
    ``_``; leading/trailing dots are dropped so ``..`` can never survive.
    Falls back to ``"index"`` when nothing usable is left.
    """
    sanitized = _UNSAFE_PDF_CHARS.sub("_", name).strip(".")
    return sanitized or "index"


class PdfEngine(EngineAdapter):
    """Engine that saves the rendered page as a PDF file."""

    name = "pdf"

    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        logs: list[str] = []

        pdf_path = output_dir / f"{sanitize_pdf_name(job.pdf_filename or 'index')}.pdf"

        if on_progress:
            on_progress("Gerando PDF...")

        pool = await get_pool()
        session_state = session_state_for(str(job.url))
        context = await pool.get_context(storage_state=session_state)
        if session_state:
            logs.append(f"Sessão salva em uso: {session_state}")
            if on_progress:
                on_progress("Usando sessão salva")
        page = await context.new_page()
        try:
            try:
                await page.goto(str(job.url), wait_until="networkidle", timeout=30000)
            except Exception as e:
                logs.append(f"Navigation warning: {e}")
                await page.goto(str(job.url), wait_until="domcontentloaded", timeout=30000)

            await page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                scale=0.8,
            )
        finally:
            # The context belongs to the pool — never close it here
            await page.close()

        logs.append(f"Saved PDF: {pdf_path}")

        if on_progress:
            on_progress("PDF concluído")

        return EngineResult(
            output_dir=output_dir,
            files=[pdf_path],
            total_bytes=pdf_path.stat().st_size,
            logs=logs,
        )

    def can_handle(self, probe: ProbeResult) -> bool:
        """PDF requires a real renderer, so it follows the Playwright probe."""
        return probe.suggested_engine == "playwright"
