"""URL probing and auto-detection module."""

from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from zfrog.config import settings
from zfrog.models import ProbeResult

# Framework detection patterns
SPA_PATTERNS = {
    "next": ["_next/static", "__next", "next/dist"],
    "nuxt": ["__nuxt", "_nuxt", "nuxt/dist"],
    "react": ["react", "react-dom", "webpack", "bundle.js", "main.js"],
    "vue": ["vue", "vuejs", "vue/dist", "chunk-vendors", "app.js"],
    "angular": ["ng-app", "angular", "ng-version"],
}

SCRIPT_PATTERNS = ["webpack", "bundle", "chunk", "vendor", "app.js", "main.js"]


async def probe_url(url: str, client: httpx.AsyncClient) -> ProbeResult:
    """Probe a URL to detect its type and suggest an engine.
    
    Args:
        url: Target URL to probe.
        client: HTTP client with realistic headers.
        
    Returns:
        ProbeResult with detection results.
    """
    result = ProbeResult(url=url)
    
    try:
        # Fetch the main page. Probing is a quick look, so it gets its own
        # budget instead of the client's general read timeout.
        response = await client.get(url, follow_redirects=True, timeout=settings.probe_timeout)
        response.raise_for_status()
        
        result.status_code = response.status_code
        result.final_url = str(response.url)
        
        # Check content type
        content_type = response.headers.get("content-type", "")
        result.content_type = content_type.split(";")[0].strip()
        
        # Only analyze HTML content
        if "text/html" not in content_type:
            return result
        
        html = response.text
        soup = BeautifulSoup(html, "lxml")
        
        # Check robots.txt
        result.robots_restricted = await _check_robots(client, url)
        
        # Detect SPA frameworks
        result.framework = _detect_framework(html, soup)
        result.is_spa = result.framework is not None
        
        # Check if JS rendering is required
        result.has_js_rendering = _needs_js_rendering(html, soup)
        
        # Suggest engine based on detection
        result.suggested_engine = _suggest_engine(result)
        
    except httpx.HTTPError as e:
        # On error, default to Playwright: a page the probe could not fetch may
        # still render in a browser.
        result.suggested_engine = "playwright"
    
    return result


async def _check_robots(client: httpx.AsyncClient, url: str) -> bool:
    """Check if robots.txt restricts crawling."""
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        response = await client.get(robots_url, follow_redirects=True)
        if response.status_code == 200:
            content = response.text.lower()
            # Simple heuristic: if Disallow: / exists, it's restricted
            if "disallow: /" in content:
                return True
            # Check if our specific path is disallowed
            parsed_url = urlparse(url)
            if f"disallow: {parsed_url.path}" in content:
                return True
    except Exception:
        pass
    
    return False


def _detect_framework(html: str, soup: BeautifulSoup | None = None) -> str | None:
    """Detect JavaScript framework from HTML content."""
    html_lower = html.lower()
    
    # Lazy parse if soup not provided
    if soup is None:
        soup = BeautifulSoup(html, "lxml")
    
    # Check meta generator tag
    generator = soup.find("meta", attrs={"name": "generator"})
    if generator and generator.get("content"):
        gen = generator["content"].lower()
        if "next" in gen:
            return "next"
        if "nuxt" in gen:
            return "nuxt"
        if "gatsby" in gen:
            return "react"  # Gatsby uses React
    
    # Check for framework patterns in HTML
    for framework, patterns in SPA_PATTERNS.items():
        for pattern in patterns:
            if pattern in html_lower:
                return framework
    
    return None


def _needs_js_rendering(html: str, soup: BeautifulSoup | None = None) -> bool:
    """Check if page content requires JavaScript rendering."""
    # Lazy parse if soup not provided
    if soup is None:
        soup = BeautifulSoup(html, "lxml")
    
    html_size = len(html.encode("utf-8"))
    
    # Count script tags
    scripts = soup.find_all("script")
    script_sources = [s.get("src", "") for s in scripts if s.get("src")]
    
    # Check for heavy script bundles
    heavy_scripts = any(
        any(pattern in src.lower() for pattern in SCRIPT_PATTERNS)
        for src in script_sources
    )
    
    # Small HTML with many scripts = likely SPA
    if html_size < settings.spa_content_threshold and len(scripts) > 3:
        return True
    
    # Heavy script bundles = likely needs JS rendering
    if heavy_scripts and len(scripts) > 2:
        return True
    
    # Check for empty body content
    body = soup.find("body")
    if body and len(body.get_text(strip=True)) < 100 and len(scripts) > 2:
        return True
    
    return False


def _suggest_engine(probe: ProbeResult) -> str:
    """Suggest engine based on probe results.

    The zfrog capture flow: JavaScript means Playwright (the visual capture
    motor), a plain page means StaticFile (the light motor). A page the probe
    could not fetch is assumed to need rendering — a missed render loses the
    design, a missed shortcut only costs speed.
    """
    # SPA or JS-heavy sites need Playwright
    if probe.is_spa or probe.has_js_rendering:
        return "playwright"

    # A page we could not read at all may still render in a browser.
    if probe.status_code is None:
        return "playwright"

    # Plain static page: the light motor is enough.
    return "static_file"
