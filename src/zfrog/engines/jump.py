"""The ``jump`` engine: capture a page and turn it into a reference card.

This is the motor the plan describes as the heart of zfrog — "sempre. É o motor
principal". It renders the page, takes a full-page screenshot, extracts the design
tokens, and writes a card into the catalog so the capture is findable later.

It complements the other motors rather than replacing them: Playwright/wget/Scrapy
still do the *downloading*, and this reads what they produced. That is why the token
extraction lives here and not inside :mod:`zfrog.engines.playwright` — a capture made
by ``mirror`` or ``extract`` can be turned into a card afterwards with no re-download.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from zfrog.catalog import Card, Catalog, site_of
from zfrog.config import settings
from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
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

        note(f"Abrindo {job.url} em {token} ({width}×{height})")

        # Imported here so the module stays importable without Playwright installed.
        from zfrog.engines.playwright import get_pool, session_state_for

        pool = await get_pool()
        session_state = session_state_for(str(job.url))
        context = await pool.get_context(storage_state=session_state)
        page = await context.new_page()

        shots_dir = output_dir / "screenshots"
        shots_dir.mkdir(exist_ok=True)

        screenshot_path = shots_dir / f"{token}.png"
        tokens = None
        try:
            await page.set_viewport_size({"width": width, "height": height})
            await page.goto(str(job.url), wait_until="load", timeout=30_000)

            # Give late layout a moment; a screenshot taken mid-shift is worse than
            # a second of waiting.
            await page.wait_for_timeout(600)

            note("Capturando screenshot de página inteira")
            await page.screenshot(path=str(screenshot_path), full_page=True)

            note("Lendo os tokens de design")
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
                f"{len(tokens.palette)} cores, {len(tokens.fonts)} famílias, "
                f"{len(tokens.assets)} assets"
            )
        finally:
            try:
                await page.close()
            except Exception:  # pragma: no cover - closing a dead page is not an error
                pass

        # Register the card. A catalog failure must not lose the capture that is
        # already on disk, so it is reported and skipped.
        #
        # The stored path is relative to the *media root*, not to this job's
        # directory: the API resolves it against the root to serve the image, and a
        # job-relative path would point at a file that does not exist there.
        card_id = uuid.uuid4().hex
        media_root = Path(settings.catalog_media_dir)
        try:
            screenshot_ref = str(screenshot_path.resolve().relative_to(media_root.resolve()))
        except ValueError:
            # The capture landed outside the media root; store the absolute path and
            # let the endpoint's containment check decide whether it is servable.
            screenshot_ref = str(screenshot_path)

        try:
            card = self.catalog.save(
                Card(
                    id=card_id,
                    url=str(job.url),
                    site=site_of(str(job.url)),
                    title=tokens.title if tokens else "",
                    mode=job.mode,
                    engine=self.name,
                    job_id=getattr(job, "job_id", "") or "",
                    screenshot=screenshot_ref,
                    tokens=tokens.to_dict() if tokens else {},
                    tags=list(job.card_tags or []),
                    bytes=screenshot_path.stat().st_size if screenshot_path.exists() else 0,
                )
            )
            note(f"Referência registrada no catálogo: {card.id}")
        except Exception as exc:
            logger.warning("não foi possível registrar a referência: %s", exc)
            note(f"Catálogo indisponível ({exc}); a captura continua em disco")

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

