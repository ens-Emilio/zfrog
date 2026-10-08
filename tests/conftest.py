"""Shared fixtures for Zfrog tests."""

import asyncio
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

from zfrog.config import settings

@pytest.fixture(scope="session", autouse=True)
def _isolated_catalog(tmp_path_factory):
    """Keep the catalog of the machine running the tests out of the run.

    Every job now registers a reference card, so without this any test that runs one
    writes into the developer's real catalog — and the card points at a temp directory
    that is gone as soon as the run ends. Session-scoped because isolation from the
    real catalog is what matters here; a test that needs a clean catalog of its own
    builds one, as the catalog tests do.
    """
    root = tmp_path_factory.mktemp("catalog")
    original = (settings.catalog_db, settings.catalog_media_dir)
    settings.catalog_db = root / "catalog.db"
    settings.catalog_media_dir = root
    yield
    settings.catalog_db, settings.catalog_media_dir = original


# ── Fixture sites (static HTML served by local HTTP server) ──

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _ensure_fixtures(target: Path = FIXTURE_DIR):
    """Create fixture HTML files if they don't exist."""
    target.mkdir(parents=True, exist_ok=True)

    # 1. Static site (minimal)
    (target / "static_site.html").write_text("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Static Test Page</title>
    <meta name="description" content="A minimal test page for Zfrog">
    <link rel="canonical" href="http://localhost:PORT/static_site.html">
    <meta property="og:title" content="Static Test">
    <style>body { font-family: sans-serif; margin: 2rem; }</style>
</head>
<body>
    <h1>Welcome to the Static Test Site</h1>
    <p>This is a simple static page with known content for testing.</p>
    <p>Word count test: one two three four five six seven eight nine ten.</p>
    <ul>
        <li>Item one</li>
        <li>Item two</li>
        <li>Item three</li>
    </ul>
    <a href="page2.html">Page 2</a>
    <img src="logo.png" alt="Logo">
</body>
</html>""", encoding="utf-8")

    (target / "page2.html").write_text("""<!DOCTYPE html>
<html lang="en">
<head><title>Page 2</title></head>
<body>
    <h1>Second Page</h1>
    <p>Content on page two.</p>
    <a href="static_site.html">Back to home</a>
</body>
</html>""", encoding="utf-8")

    # 2. SPA-like page (simulates React/Vue output)
    (target / "spa_page.html").write_text("""<!DOCTYPE html>
<html lang="en">
<head>
    <title>SPA Test</title>
    <meta name="description" content="Simulated SPA page">
</head>
<body>
    <div id="app">
        <h1>SPA Content</h1>
        <p>This simulates a server-rendered SPA page.</p>
        <div data-reactroot>
            <span>React-like content</span>
        </div>
    </div>
    <script src="/static/js/bundle.js"></script>
    <script>window.__NEXT_DATA__ = {};</script>
</body>
</html>""", encoding="utf-8")

    # 3. Page with trackers (for privacy cleaner testing)
    (target / "tracked_page.html").write_text("""<!DOCTYPE html>
<html lang="en">
<head>
    <title>Tracked Page</title>
    <script src="https://www.google-analytics.com/analytics.js"></script>
    <script src="https://www.googletagmanager.com/gtm.js"></script>
</head>
<body>
    <h1>Page with Trackers</h1>
    <script>gtag('config', 'UA-12345-1');</script>
    <script>fbq('init', '123');</script>
    <p>Content here.</p>
</body>
</html>""", encoding="utf-8")

    # 4. Page with many links (for crawl budget testing)
    links_html = '<!DOCTYPE html><html><head><title>Link Farm</title></head><body>\n'
    links_html += '<h1>Links Page</h1>\n'
    for i in range(20):
        links_html += f'<a href="page{i}.html">Link {i}</a>\n'
    links_html += '</body></html>'
    (target / "link_farm.html").write_text(links_html, encoding="utf-8")

    for i in range(20):
        (target / f"page{i}.html").write_text(
            f"<html><head><title>Page {i}</title></head><body><p>Content {i}</p></body></html>",
            encoding="utf-8",
        )

    # 5. Minimal image placeholder (1x1 PNG)
    import base64
    # 1x1 transparent PNG
    png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    (target / "logo.png").write_bytes(base64.b64decode(png_b64))


@pytest.fixture(scope="session", autouse=True)
def _ensure_fixture_files(tmp_path_factory):
    """Populate fixture files in a temp dir so import has no side-effects."""
    tmp = tmp_path_factory.mktemp("zfrog-fixtures")
    _ensure_fixtures(tmp)
    global FIXTURE_DIR
    FIXTURE_DIR = tmp
    yield


class FixtureHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves from the fixture directory."""

    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=str(FIXTURE_DIR), **kwargs)

    def log_message(self, format, *args):
        pass  # Suppress request logs during tests


@pytest.fixture(scope="session")
def fixture_server():
    """Start a local HTTP server serving fixture files.

    Yields (host, port) tuple.
    """
    server = HTTPServer(("127.0.0.1", 0), FixtureHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "127.0.0.1", port
    server.shutdown()


@pytest.fixture
def fixture_url(fixture_server):
    """Return the base URL for the fixture server."""
    host, port = fixture_server
    return f"http://{host}:{port}"


@pytest.fixture
def static_page_url(fixture_server):
    """Return URL for the static test page."""
    host, port = fixture_server
    return f"http://{host}:{port}/static_site.html"


@pytest.fixture
def spa_page_url(fixture_server):
    """Return URL for the SPA test page."""
    host, port = fixture_server
    return f"http://{host}:{port}/spa_page.html"


@pytest.fixture
def tracked_page_url(fixture_server):
    """Return URL for the page with trackers."""
    host, port = fixture_server
    return f"http://{host}:{port}/tracked_page.html"
