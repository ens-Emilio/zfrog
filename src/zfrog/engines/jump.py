"""The ``jump`` engine: capture a page and turn it into a reference card.

This is the motor the plan describes as the heart of zfrog — the main engine. It renders
the page, takes a full-page screenshot, extracts the design tokens, and
writes a card into the catalog so the capture is findable later.

It complements the other motors rather than replacing them: Playwright/wget/Scrapy
still do the *downloading*, and this reads what they produced. That is why the token
extraction lives here and not inside :mod:`zfrog.engines.playwright` — a capture made
by ``mirror`` or ``extract`` can be turned into a card afterwards with no re-download.
"""

from __future__ import annotations

import logging
from pathlib import Path

from zfrog.catalog import Catalog
from zfrog.config import settings
from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.pipeline.reference import register_reference
from zfrog.tokens import (
    collect_snapshot,
    extract_tokens,
    tokens_to_json,
    tokens_to_markdown,
)

logger = logging.getLogger(__name__)

#: Screenshot widths the plan asks for, in the order it lists them. A capture can be
#: repeated per breakpoint so a layout can be compared across contexts.
BREAKPOINTS: dict[str, tuple[int, int]] = {
    "desktop": (1440, 900),
    "tablet": (834, 1112),
    "mobile": (390, 844),
}

#: Default when the job did not name one.
DEFAULT_BREAKPOINT = "desktop"


def _screenshot_name(url: str, name: str) -> str:
    """A stable file name for one captured page."""
    return name or "index"


class JumpEngine(EngineAdapter):
    """Capture a page as a design reference: screenshot + tokens + catalog card."""

    name = "jump"

    def __init__(self) -> None:
        self.catalog = Catalog(Path(settings.catalog_db))

    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        """Render ``job.url``, extract its tokens and register the card."""
        output_dir.mkdir(parents=True, exist_ok=True)
        logs: list[str] = []

        def note(message: str) -> None:
            logs.append(message)
            if on_progress:
                on_progress(message)

        token = getattr(job, "token_breakpoint", None) or DEFAULT_BREAKPOINT
        width, height = BREAKPOINTS.get(token, BREAKPOINTS[DEFAULT_BREAKPOINT])

        note(f"Opening {job.url} in {token} ({width}×{height})")

        # Imported here so the module stays importable without Playwright installed.
        from zfrog.engines.playwright import get_pool, session_state_for

        pool = await get_pool()
        session_state = session_state_for(str(job.url))
        context = await pool.get_context(storage_state=session_state)
        page = await context.new_page()

        shots_dir = output_dir / "screenshots"
        shots_dir.mkdir(exist_ok=True)

        # PNG is lossless and is the default; WebP is roughly a third of the size for
        # a screenshot, which matters once a catalog has hundreds of them.
        image_format = (job.screenshot_format or "png").lower()
        if image_format not in ("png", "webp"):
            raise ValueError(f"Unsupported image format: {image_format} (use png or webp)")

        full_page = job.screenshot_full_page
        screenshot_path = shots_dir / f"{token}.{image_format}"
        tokens = None
        try:
            await page.set_viewport_size({"width": width, "height": height})
            await page.goto(str(job.url), wait_until="load", timeout=30_000)

            # Give late layout a moment; a screenshot taken mid-shift is worse than
            # a second of waiting.
            await page.wait_for_timeout(600)

            note(
                "Capturing full-page screenshot"
                if full_page
                else "Capturing viewport screenshot"
            )
            await page.screenshot(path=str(screenshot_path), full_page=full_page)

            note("Reading design tokens")
            snapshot = await collect_snapshot(page)
            tokens = extract_tokens(snapshot)
            if not tokens.title:
                tokens.title = (await page.title()) or ""
            tokens.url = str(job.url)

            (output_dir / "design-tokens.json").write_text(
                tokens_to_json(tokens), encoding="utf-8"
            )
            (output_dir / "design-tokens.md").write_text(
                tokens_to_markdown(tokens), encoding="utf-8"
            )
            note(
                f"{len(tokens.palette)} colors, {len(tokens.fonts)} font families, "
                f"{len(tokens.assets)} assets"
            )
        finally:
            try:
                await page.close()
            except Exception:  # pragma: no cover - closing a dead page is not an error
                pass

        # Register the card through the shared step, so the card a `jump` writes and
        # the card a regular clone writes are built by the same code.
        if tokens is not None:
            card = register_reference(
                url=str(job.url),
                mode=job.mode,
                engine=self.name,
                tokens=tokens,
                screenshot=screenshot_path,
                job_id=getattr(job, "job_id", "") or "",
                tags=job.card_tags,
                catalog=self.catalog,
            )
            note(
                f"Reference registered in the catalog: {card.id}"
                if card is not None
                else "Catalog unavailable; the capture remains on disk"
            )

        files = [path for path in output_dir.rglob("*") if path.is_file()]
        return EngineResult(
            output_dir=output_dir,
            files=files,
            total_bytes=sum(path.stat().st_size for path in files),
            logs=logs,
        )

    def can_handle(self, probe: ProbeResult) -> bool:
        """``jump`` is opt-in by mode; it never wins the auto-detection."""
        return probe.suggested_engine == "jump"

