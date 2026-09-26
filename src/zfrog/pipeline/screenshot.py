"""Pipeline step: screenshot every downloaded HTML page via Playwright."""

import asyncio
from pathlib import Path

from zfrog.config import settings


async def take_screenshots(
    output_dir: Path,
    max_pages: int = 50,
    viewport_width: int = 1280,
    viewport_height: int = 800,
) -> list[Path]:
    """Open every .html file in output_dir with Playwright and save full-page screenshots.

    Returns list of created screenshot paths.
    """
    html_files = sorted(
        f for f in output_dir.rglob("*.html")
        if f.is_file() and f.stat().st_size < 5_000_000  # skip files > 5 MB
    )[:max_pages]

    if not html_files:
        return []

    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    saved: list[Path] = []

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
                    # Build a unique filename from the relative path
                    rel = html_file.relative_to(output_dir)
                    safe_name = str(rel).replace("/", "_").replace("\\", "_")
                    # Strip extension, add .png
                    png_name = safe_name.rsplit(".", 1)[0] + ".png"
                    png_path = screenshots_dir / png_name

                    # Navigate to local file
                    file_url = html_file.resolve().as_uri()
                    await page.goto(file_url, wait_until="networkidle", timeout=15000)

                    # Scroll to bottom to trigger lazy images
                    await page.evaluate("""
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
                    """)
                    await page.wait_for_timeout(500)

                    # Back to top before screenshot
                    await page.evaluate("window.scrollTo(0, 0)")
                    await page.wait_for_timeout(200)

                    # Full-page screenshot
                    await page.screenshot(path=str(png_path), full_page=True)
                    saved.append(png_path)

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

    return saved
