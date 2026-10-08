"""The ``tongue`` engine: extract one component from a rendered page.

Point at a CSS selector and get back the component — its markup, the styles the
browser resolved for it, and its position in the box model. The interpretation lives
in :mod:`zfrog.components`; this file owns only the browser lifecycle.

Split from ``jump`` because they answer different questions ("capture this page as a
reference" vs "show me this one element"), and a file named after one motor that also
holds another is a navigation problem rather than a saving.
"""

from __future__ import annotations

import logging
from pathlib import Path

from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult

logger = logging.getLogger(__name__)


class TongueEngine(EngineAdapter):
    """Extract one component: its HTML and the CSS the browser resolved for it."""

    name = "tongue"

    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        """Render ``job.url`` and extract the element ``job.selector`` matches."""
        output_dir.mkdir(parents=True, exist_ok=True)
        logs: list[str] = []

        def note(message: str) -> None:
            logs.append(message)
            if on_progress:
                on_progress(message)

        selector = getattr(job, "selector", None)
        if not selector:
            raise ValueError("tongue mode requires a CSS selector (use --selector)")

        from zfrog.components import (
            build_extract,
            collect_component,
            component_to_json,
            component_to_markdown,
        )
        from zfrog.engines.playwright import get_pool, session_state_for

        note(f"Opening {job.url}")
        pool = await get_pool()
        context = await pool.get_context(storage_state=session_state_for(str(job.url)))
        page = await context.new_page()

        try:
            await page.goto(str(job.url), wait_until="load", timeout=30_000)
            await page.wait_for_timeout(400)

            note(f"Extracting `{selector}`")
            raw = await collect_component(page, selector)
        finally:
            try:
                await page.close()
            except Exception:  # pragma: no cover
                pass

        component = build_extract(raw, url=str(job.url), selector=selector)
        if component is None:
            raise ValueError(f"The selector `{selector}` found no element at {job.url}")

        if component.match_count > 1:
            note(f"{component.match_count} elements matched; extracted the first")

        (output_dir / "component.html").write_text(component.html, encoding="utf-8")
        (output_dir / "component.json").write_text(component_to_json(component), encoding="utf-8")
        (output_dir / "component.md").write_text(
            component_to_markdown(component), encoding="utf-8"
        )
        box = component.box
        note(
            f"{component.label} — "
            f"{int(box.get('width', 0))}×{int(box.get('height', 0))} px"
        )

        files = [path for path in output_dir.rglob("*") if path.is_file()]
        return EngineResult(
            output_dir=output_dir,
            files=files,
            total_bytes=sum(path.stat().st_size for path in files),
            logs=logs,
        )

    def can_handle(self, probe: ProbeResult) -> bool:
        """``tongue`` is opt-in by mode; it never wins the auto-detection."""
        return probe.suggested_engine == "tongue"
