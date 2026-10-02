"""Pipeline step: visit every downloaded HTML page in a browser and capture it.

Two products come out of the same visit, which is why they live in one function:

* a **screenshot** of every page, and
* when asked, the **design tokens** of the entry page.

Opening the browser twice to get both would double the slowest part of a job, so the
token pass rides along on the page that is already loaded. What gets measured is the
*downloaded copy*, not the live site — that copy is what the reference actually is, and
by the time this step runs ``rewrite_links`` has already pointed the assets at the
local files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: Page size above which a file is skipped: a page this large is usually a data dump
#: rather than something with a layout worth rendering.
MAX_PAGE_BYTES = 5_000_000


@dataclass
class CaptureReport:
    """What the browser pass produced."""

    screenshots: list[Path] = field(default_factory=list)
    #: Tokens of the entry page, when ``design`` was requested and it could be read.
    tokens: object | None = None
    tokens_path: Path | None = None
    #: The page the tokens were read from, relative to the output directory.
    token_source: str = ""
    #: The screenshot of that same page, which is the image a reference card shows.
    entry_screenshot: Path | None = None


def _entry_page(html_files: list[Path], output_dir: Path) -> Path:
    """The page a capture is *about*: ``index.html`` if there is one, else the shallowest.

    A mirror of a site has one obvious entry point, and it is the page the reference
    should describe. Picking it by depth rather than alphabetically keeps
    ``about.html`` from becoming the face of a site whose entry is ``index.html``.
    """
    for candidate in html_files:
        if candidate.name.lower() in ("index.html", "index.htm"):
            return candidate
    return min(html_files, key=lambda path: (len(path.relative_to(output_dir).parts), str(path)))


async def take_screenshots(
    output_dir: Path,
    max_pages: int = 50,
    viewport_width: int = 1280,
    viewport_height: int = 800,
    design: bool = False,
) -> CaptureReport:
    """Screenshot every downloaded HTML page, optionally reading design tokens too.

    Returns a :class:`CaptureReport`. A page that fails to render is skipped rather
    than failing the job — this step runs after the capture succeeded, and losing a
    thumbnail must not discard work that is already on disk.
    """
    html_files = sorted(
        path
        for path in output_dir.rglob("*.html")
        if path.is_file() and path.stat().st_size < MAX_PAGE_BYTES
    )[:max_pages]

    report = CaptureReport()
    if not html_files:
        return report

    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)
    entry = _entry_page(html_files, output_dir) if design else None

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )

            context = await browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )

            page = await context.new_page()

            for html_file in html_files:
                try:
                    rel = html_file.relative_to(output_dir)
                    safe_name = str(rel).replace("/", "_").replace("\\", "_")
                    png_path = screenshots_dir / (safe_name.rsplit(".", 1)[0] + ".png")

                    await page.goto(
                        html_file.resolve().as_uri(), wait_until="networkidle", timeout=15000
                    )

                    # Scroll to the bottom so lazy images load before the shot.
                    await page.evaluate(
                        """
                        async () => {
                            await new Promise(r => {
                                let y = 0;
                                const step = 400;
                                const id = setInterval(() => {
                                    window.scrollBy(0, step);
                                    y += step;
                                    if (y >= document.body.scrollHeight) { clearInterval(id); r(); }
                                }, 50);
                                setTimeout(() => { clearInterval(id); r(); }, 5000);
                            });
                        }
                        """
                    )
                    await page.wait_for_timeout(500)
                    await page.evaluate("window.scrollTo(0, 0)")
                    await page.wait_for_timeout(200)

                    await page.screenshot(path=str(png_path), full_page=True)
                    report.screenshots.append(png_path)

                    # Same visit, second product: the tokens of the entry page.
                    if entry is not None and html_file == entry:
                        from zfrog.tokens import (
                            collect_snapshot,
                            extract_tokens,
                            tokens_to_json,
                            tokens_to_markdown,
                        )

                        tokens = extract_tokens(await collect_snapshot(page))
                        if not tokens.title:
                            tokens.title = await page.title()
                        report.tokens = tokens
                        report.token_source = str(rel)
                        report.entry_screenshot = png_path

                        (output_dir / "design-tokens.json").write_text(
                            tokens_to_json(tokens), encoding="utf-8"
                        )
                        (output_dir / "design-tokens.md").write_text(
                            tokens_to_markdown(tokens), encoding="utf-8"
                        )
                        report.tokens_path = output_dir / "design-tokens.json"

                except Exception:
                    # Skip problematic pages, continue with others
                    pass

            await context.close()
            await browser.close()

    except ImportError:
        # Playwright not installed — silently skip
        pass
    except Exception:
        # Browser launch failed — silently skip
        pass

    return report


__all__ = ["CaptureReport", "MAX_PAGE_BYTES", "take_screenshots"]
