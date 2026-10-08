"""Playwright engine: the visual capture motor of zfrog.

It is the default motor and the heart of the capture flow: it renders the page
the way a browser would and keeps what the browser actually loaded — the
rendered HTML plus the CSS, JS and image responses. The pipeline then shoots a
full-page screenshot of every captured page.
"""

import asyncio
import base64
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.config import settings
from zfrog.utils.stealth import locale, user_agent, viewport
from zfrog.session import SessionStore

logger = logging.getLogger(__name__)


def session_state_for(url: str) -> str | None:
    """Return the path of the saved login session for ``url``'s domain, if any."""
    path = SessionStore().state_path(url)
    return str(path) if path is not None else None


class BrowserPool:
    """Browser pool with context recycling.

    Contexts older than ``max_age_s`` or with more than ``max_pages`` pages are
    recycled. One stable browser identity (see :mod:`zfrog.utils.stealth`) is
    used for every context: this pool exists to reuse browsers, not to evade
    detection.
    """

    def __init__(
        self,
        pool_size: int | None = None,
        max_pages: int | None = None,
        max_age_s: int | None = None,
    ):
        self.pool_size = pool_size or settings.browser_pool_size
        self.max_pages = max_pages or settings.browser_context_max_pages
        self.max_age_s = max_age_s or settings.browser_context_max_age_s

        self._playwright = None
        self._browser: Browser | None = None
        # Each entry: {"context": BrowserContext, "created_at": float}
        self._contexts: list[dict] = []
        self._lock = asyncio.Lock()

    # ── lifecycle ───────────────────────────────────────────────────

    async def start(self):
        """Start the browser pool with a Chromium browser."""
        self._playwright = await async_playwright().start()
        self._browser = await self._chromium_launch()

    async def close(self):
        """Close all contexts and browsers."""
        async with self._lock:
            for entry in self._contexts:
                try:
                    await entry["context"].close()
                except Exception:
                    pass
            self._contexts.clear()

            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
            self._browser = None

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

    # ── context management ──────────────────────────────────────────

    async def get_context(self, storage_state: str | None = None) -> BrowserContext:
        """Return a context, optionally loaded with a saved login session.

        Without ``storage_state`` this is the usual pooled behaviour: reuse a
        healthy cached context, create one while there is room, otherwise
        recycle the oldest. With ``storage_state`` a cached context can never be
        reused — it was created without the saved cookies — so a fresh context
        is always built, evicting the oldest entry when the pool is full.
        """
        async with self._lock:
            # Evict expired entries
            await self._evict_stale()

            if storage_state is not None:
                if len(self._contexts) >= self.pool_size:
                    await self._drop_oldest()
                return await self._add_context(storage_state)

            # Prefer an existing context
            for entry in self._contexts:
                return entry["context"]

            # Create a new context if we have room
            if len(self._contexts) < self.pool_size:
                return await self._add_context()

            # Pool full – recycle the oldest entry
            await self._drop_oldest()
            return await self._add_context()

    # ── private helpers ─────────────────────────────────────────────

    async def _evict_stale(self):
        """Remove expired contexts (caller holds lock)."""
        now = asyncio.get_event_loop().time()
        surviving: list[dict] = []
        for entry in self._contexts:
            age = now - entry["created_at"]
            pages_ok = len(entry["context"].pages) < self.max_pages
            age_ok = age < self.max_age_s
            if pages_ok and age_ok:
                surviving.append(entry)
            else:
                logger.debug("Recycling context (age=%.0fs pages=%d)", age, len(entry["context"].pages))
                try:
                    await entry["context"].close()
                except Exception:
                    pass
        self._contexts = surviving

    async def _new_context(self, storage_state: str | None = None) -> BrowserContext:
        """Create a new context on the pooled browser.

        ``storage_state`` is forwarded to ``new_context`` only when set, so the
        default call signature stays exactly as it was.
        """
        kwargs: dict = {
            "viewport": viewport(),
            "user_agent": user_agent(),
            "java_script_enabled": True,
            "locale": locale(),
        }
        if storage_state is not None:
            kwargs["storage_state"] = storage_state
        return await self._browser.new_context(**kwargs)

    async def _add_context(self, storage_state: str | None = None) -> BrowserContext:
        """Create a context and register it in the pool (caller holds lock)."""
        context = await self._new_context(storage_state)
        self._contexts.append(
            {"context": context, "created_at": asyncio.get_event_loop().time()}
        )
        return context

    async def _drop_oldest(self):
        """Close and unregister the oldest pooled context (caller holds lock)."""
        if not self._contexts:
            return
        oldest = self._contexts.pop(0)
        try:
            await oldest["context"].close()
        except Exception:
            pass

    def _chromium_launch(self):
        """Launch a browser, preferring a system install (no download on first run).

        Tauri desktop hybrid strategy (PLANO-TAURI.md §4.1):
        1. Try ``channel="chrome"`` / ``channel="msedge"`` — uses the browser the
           user already has (Edge is always present on Windows).
        2. Fall back to the bundled Chromium from ``playwright install``.
        The channel is tried at ``launch`` time; if the channel is not installed
        Playwright raises, so we catch and retry without it.
        """
        return self._try_launch_with_channel()

    async def _try_launch_with_channel(self):  # type: ignore[no-untyped-def]
        # Import locally so the module still imports when playwright isn't installed
        # (e.g. in a minimal CI that only runs non-browser tests).
        for channel in ("chrome", "msedge", None):
            try:
                kwargs: dict = dict(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
                if channel:
                    kwargs["channel"] = channel
                browser = await self._playwright.chromium.launch(**kwargs)  # type: ignore[union-attr]
                if channel:
                    logger.info("Browser launched via channel=%s (system install)", channel)
                return browser
            except Exception as e:
                # "chromium" channel not installed — try the next one
                msg = str(e).lower()
                if channel and ("executable doesn't exist" in msg or "browser" in msg or "channel" in msg):
                    logger.debug("Channel %s not available, trying next: %s", channel, e)
                    continue
                if channel is None:
                    raise
                # Unexpected error with a channel — don't mask it
                raise

# Global pool (lazy initialized)
_pool: BrowserPool | None = None
_pool_lock = asyncio.Lock()


async def get_pool() -> BrowserPool:
    """Get or create the global browser pool."""
    global _pool
    async with _pool_lock:
        if _pool is None:
            _pool = BrowserPool()
            await _pool.start()
        return _pool


async def close_pool():
    """Close the global browser pool."""
    global _pool
    async with _pool_lock:
        if _pool:
            await _pool.close()
            _pool = None


class PlaywrightEngine(EngineAdapter):
    """Visual capture motor: renders the page and saves what it looks like.

    The browser pool renders JavaScript (including SPAs), intercepts the
    network to capture CSS/JS/image assets, and scrolls to trigger lazy
    loading. One stable identity, no evasion.
    """
    
    name = "playwright"
    
    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        """Execute Playwright to scrape a dynamic site.
        
        Args:
            job: Job configuration.
            output_dir: Directory to store output.
            on_progress: Optional progress callback.
            
        Returns:
            EngineResult with scraped files.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        logs = []
        captured_assets: dict[str, bytes] = {}
        
        # Get browser pool
        pool = await get_pool()
        session_state = session_state_for(str(job.url))
        context = await pool.get_context(storage_state=session_state)
        if session_state:
            logs.append(f"Saved session in use: {session_state}")
            if on_progress:
                on_progress("Using saved session")
        
        try:
            # Create page with network interception
            page = await context.new_page()

            # Set up network interception to capture assets
            async def handle_response(response):
                url = response.url
                status = response.status
                
                # Capture CSS, JS, and image resources
                if status == 200:
                    content_type = response.headers.get("content-type", "")
                    if any(t in content_type for t in ["text/css", "javascript", "image/"]):
                        try:
                            body = await response.body()
                            captured_assets[url] = body
                            logs.append(f"Captured: {url} ({len(body)} bytes)")
                        except Exception:
                            pass
            
            page.on("response", handle_response)
            
            # Navigate to the page
            if on_progress:
                on_progress("Loading page...")
            
            try:
                await page.goto(str(job.url), wait_until="networkidle", timeout=30000)
            except Exception as e:
                logs.append(f"Navigation warning: {e}")
                # Try with domcontentloaded instead
                try:
                    await page.goto(str(job.url), wait_until="domcontentloaded", timeout=30000)
                except Exception as e2:
                    logs.append(f"Navigation failed: {e2}")
                    raise
            
            # Wait for dynamic content
            await page.wait_for_timeout(2000)
            
            # Scroll to trigger lazy loading
            if on_progress:
                on_progress("Scrolling to load lazy content...")
            
            await page.evaluate("""
                async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        const distance = 300;
                        const timer = setInterval(() => {
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if (totalHeight >= document.body.scrollHeight) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, 100);
                        // Safety timeout
                        setTimeout(() => {
                            clearInterval(timer);
                            resolve();
                        }, 10000);
                    });
                }
            """)
            
            # Wait for any remaining dynamic content
            await page.wait_for_timeout(1000)
            
            # Get the rendered HTML
            if on_progress:
                on_progress("Extracting rendered content...")
            
            html = await page.content()
            
            # Save the main HTML file
            html_file = output_dir / "index.html"
            html_file.write_text(html, encoding="utf-8")
            logs.append(f"Saved HTML: {html_file}")
            
            # Save captured assets
            asset_dir = output_dir / "assets"
            asset_dir.mkdir(exist_ok=True)
            
            saved_count = 0
            for asset_url, asset_data in captured_assets.items():
                # Generate filename from URL
                parsed = urlparse(asset_url)
                asset_path = parsed.path.lstrip("/")
                if not asset_path:
                    continue
                
                # Handle query strings in filename
                if "?" in asset_path:
                    asset_path = asset_path.split("?")[0]
                
                local_path = asset_dir / asset_path
                local_path.parent.mkdir(parents=True, exist_ok=True)
                
                local_path.write_bytes(asset_data)
                saved_count += 1
            
            logs.append(f"Saved {saved_count} assets")
            
            # Collect all output files
            files = list(output_dir.rglob("*"))
            files = [f for f in files if f.is_file()]
            total_bytes = sum(f.stat().st_size for f in files)
            
            if on_progress:
                on_progress(f"Captured {len(files)} files ({total_bytes:,} bytes)")
            
            return EngineResult(
                output_dir=output_dir,
                files=files,
                total_bytes=total_bytes,
                logs=logs,
            )
            
        finally:
            # Don't close the context - it's shared in the pool
            pass
    
    def can_handle(self, probe: ProbeResult) -> bool:
        """Check if Playwright should handle this job."""
        return probe.suggested_engine == "playwright"
