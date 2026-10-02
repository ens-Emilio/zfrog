"""Pipeline step: turn a finished capture into a reference card.

One place owns the question "how does a capture become a card", so the ``jump`` engine
and the regular clone pipeline cannot drift apart in what they record. Both call
:func:`register_reference`.

A catalog failure never fails the job. The capture is already on disk; losing the index
entry is a smaller loss than throwing away the work, so it is logged and the job
succeeds without the card.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from pathlib import Path

from zfrog.catalog import Card, Catalog, site_of
from zfrog.config import settings
from zfrog.tokens import DesignTokens

logger = logging.getLogger(__name__)

#: Modes whose capture is a page whose *design* is worth reading. The analysis engines
#: (analyze, compare, ask, summarize…) read text, not layout, and a palette from them
#: would be noise. `jump` is absent on purpose: it extracts its own tokens and
#: registers its own card, so routing it here would do both twice.
DESIGN_MODES: frozenset[str] = frozenset({"auto", "mirror", "scrape", "singlepage", "delta"})


def parse_tags(raw: str | Sequence[str] | None) -> list[str]:
    """Normalise tags from a comma-separated string or a list into the card's form."""
    if raw is None:
        return []
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    return [clean for item in items if (clean := (item or "").strip().lstrip("#").lower())]


def screenshot_reference(screenshot: Path | None, media_root: Path) -> str:
    """The screenshot path to store on the card.

    Relative to the media root when the capture is under it, because that is what the
    API resolves the image against; absolute otherwise, so the endpoint's containment
    check — not this function — decides whether it may be served.
    """
    if screenshot is None or not screenshot.exists():
        return ""
    try:
        return str(screenshot.resolve().relative_to(media_root.resolve()))
    except ValueError:
        return str(screenshot)


def register_reference(
    *,
    url: str,
    mode: str,
    engine: str,
    tokens: DesignTokens,
    screenshot: Path | None = None,
    job_id: str = "",
    tags: str | Sequence[str] | None = None,
    catalog: Catalog | None = None,
) -> Card | None:
    """Write the card for a capture. Returns it, or ``None`` when it could not be written."""
    store = catalog if catalog is not None else Catalog(Path(settings.catalog_db))
    screenshot_ref = screenshot_reference(screenshot, Path(settings.catalog_media_dir))

    try:
        card = store.save(
            Card(
                id=uuid.uuid4().hex,
                url=url,
                site=site_of(url),
                title=tokens.title,
                mode=mode,
                engine=engine,
                job_id=job_id,
                screenshot=screenshot_ref,
                tokens=tokens.to_dict(),
                tags=parse_tags(tags),
                bytes=screenshot.stat().st_size if screenshot and screenshot.exists() else 0,
            )
        )
    except Exception as exc:
        logger.warning("não foi possível registrar a referência de %s: %s", url, exc)
        return None

    return card


__all__ = ["DESIGN_MODES", "parse_tags", "register_reference", "screenshot_reference"]
