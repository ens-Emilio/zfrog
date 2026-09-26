"""Privacy cleaner for removing tracking scripts."""

import re
from pathlib import Path

from bs4 import BeautifulSoup


# Known tracker domains
TRACKER_DOMAINS = [
    "google-analytics.com",
    "googletagmanager.com",
    "googletagservices.com",
    "doubleclick.net",
    "facebook.net",
    "facebook.com/tr",
    "hotjar.com",
    "clarity.ms",
    "segment.com",
    "segment.io",
    "amplitude.com",
    "mixpanel.com",
    "plausible.io",
    "umami.is",
    "matomo.org",
    "piwik.org",
    "heap.io",
    "fullstory.com",
    "mouseflow.com",
    "crazyegg.com",
    "optimizely.com",
]

# Inline script patterns that indicate trackers
TRACKER_INLINE_PATTERNS = [
    r"gtag\(",
    r"ga\(",
    r"_gaq\.push",
    r"fbq\(",
    r"_fbq",
    r"hotjar\(",
    r"hj\(",
    r"analytics\.track",
    r"mixpanel\.",
    r"mp\.track",
    r"plausible\(",
    r"_paq\.push",
]


async def clean_privacy(base_dir: Path) -> int:
    """Remove tracking scripts and analytics from files.
    
    Args:
        base_dir: Directory containing files to clean.
        
    Returns:
        Number of elements removed.
    """
    count = 0
    
    # Process HTML files
    for html_file in base_dir.rglob("*.html"):
        count += await _clean_html(html_file)
    
    # Process JS files (basic cleanup)
    for js_file in base_dir.rglob("*.js"):
        count += await _clean_js(js_file)
    
    return count


async def _clean_html(html_file: Path) -> int:
    """Remove tracker scripts from an HTML file."""
    content = html_file.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(content, "lxml")
    count = 0
    
    # Remove script tags with tracker src
    for script in soup.find_all("script", src=True):
        src = script.get("src", "").lower()
        if any(domain in src for domain in TRACKER_DOMAINS):
            script.decompose()
            count += 1
    
    # Remove inline scripts with tracker patterns
    for script in soup.find_all("script"):
        if script.string:
            script_content = script.string.lower()
            if any(re.search(pattern, script_content, re.IGNORECASE) 
                   for pattern in TRACKER_INLINE_PATTERNS):
                script.decompose()
                count += 1
    
    # Remove noscript tags that contain tracker redirects
    for noscript in soup.find_all("noscript"):
        if noscript.string:
            noscript_content = noscript.string.lower()
            if any(domain in noscript_content for domain in TRACKER_DOMAINS):
                noscript.decompose()
                count += 1
    
    # Remove meta tags with tracking refresh
    for meta in soup.find_all("meta", attrs={"http-equiv": "refresh"}):
        content = meta.get("content", "").lower()
        if any(domain in content for domain in TRACKER_DOMAINS):
            meta.decompose()
            count += 1
    
    # Write back if changes were made
    if count > 0:
        html_file.write_text(str(soup), encoding="utf-8")
    
    return count


async def _clean_js(js_file: Path) -> int:
    """Basic cleanup of JavaScript files."""
    try:
        content = js_file.read_text(encoding="utf-8", errors="replace")
        original = content
        
        # Remove common tracker initialization code
        # This is a basic approach - more sophisticated cleaning would require AST parsing
        
        # Remove gtag initialization
        content = re.sub(
            r"window\.dataLayer\s*=\s*window\.dataLayer\s*\|\|\s*\[\];.*?gtag\([^)]*\);",
            "",
            content,
            flags=re.DOTALL
        )
        
        # Remove fbq initialization
        content = re.sub(
            r"var\s+_fbq\s*=.*?;",
            "",
            content,
            flags=re.DOTALL
        )
        
        if content != original:
            js_file.write_text(content, encoding="utf-8")
            return 1
    except Exception:
        pass
    
    return 0
