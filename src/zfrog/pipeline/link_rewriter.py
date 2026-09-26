"""Link rewriter for converting absolute URLs to relative paths."""

import re
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup


async def rewrite_links(base_dir: Path) -> int:
    """Rewrite absolute URLs to relative paths in HTML and CSS files.
    
    Args:
        base_dir: Directory containing files to process.
        
    Returns:
        Number of links rewritten.
    """
    count = 0
    
    # Process HTML files
    for html_file in base_dir.rglob("*.html"):
        count += await _rewrite_html(html_file, base_dir)
    
    # Process CSS files
    for css_file in base_dir.rglob("*.css"):
        count += await _rewrite_css(css_file, base_dir)
    
    return count


async def _rewrite_html(html_file: Path, base_dir: Path) -> int:
    """Rewrite links in an HTML file."""
    content = html_file.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(content, "lxml")
    count = 0
    
    # Process href attributes (links)
    for tag in soup.find_all(["a", "link"], href=True):
        new_href = _rewrite_url(tag["href"], html_file, base_dir)
        if new_href != tag["href"]:
            tag["href"] = new_href
            count += 1
    
    # Process src attributes (scripts, images)
    for tag in soup.find_all(["script", "img"], src=True):
        new_src = _rewrite_url(tag["src"], html_file, base_dir)
        if new_src != tag["src"]:
            tag["src"] = new_src
            count += 1
    
    # Process action attributes (forms)
    for tag in soup.find_all("form", action=True):
        new_action = _rewrite_url(tag["action"], html_file, base_dir)
        if new_action != tag["action"]:
            tag["action"] = new_action
            count += 1
    
    # Process srcset attributes (responsive images)
    for tag in soup.find_all("img", srcset=True):
        tag["srcset"] = _rewrite_srcset(tag["srcset"], html_file, base_dir)
    
    # Write back
    html_file.write_text(str(soup), encoding="utf-8")
    
    return count


async def _rewrite_css(css_file: Path, base_dir: Path) -> int:
    """Rewrite URLs in a CSS file."""
    content = css_file.read_text(encoding="utf-8", errors="replace")
    count = 0
    
    # Match url() references
    def replace_url(match):
        nonlocal count
        url = match.group(1)
        if url.startswith(("http://", "https://")):
            new_url = _rewrite_url(url, css_file, base_dir)
            if new_url != url:
                count += 1
                return f'url("{new_url}")'
        return match.group(0)
    
    content = re.sub(r'url\(["\']?([^"\')\s]+)["\']?\)', replace_url, content)
    
    css_file.write_text(content, encoding="utf-8")
    
    return count


def _rewrite_url(url: str, source_file: Path, base_dir: Path) -> str:
    """Rewrite a single URL to be relative.
    
    Args:
        url: Original URL.
        source_file: File containing the URL.
        base_dir: Base directory for resolving paths.
        
    Returns:
        Rewritten URL (relative if possible).
    """
    # Skip data URIs and anchors
    if url.startswith(("data:", "#", "javascript:", "mailto:")):
        return url
    
    # Handle absolute URLs
    if url.startswith(("http://", "https://")):
        parsed = urlparse(url)
        
        # Try to find the file locally
        local_path = base_dir / parsed.path.lstrip("/")
        if local_path.exists():
            return _get_relative_path(source_file, local_path)
    
    # Handle root-relative URLs
    if url.startswith("/"):
        local_path = base_dir / url.lstrip("/")
        if local_path.exists():
            return _get_relative_path(source_file, local_path)
    
    return url


def _rewrite_srcset(srcset: str, source_file: Path, base_dir: Path) -> str:
    """Rewrite URLs in srcset attribute."""
    parts = []
    for part in srcset.split(","):
        part = part.strip()
        if part:
            tokens = part.split()
            if tokens:
                tokens[0] = _rewrite_url(tokens[0], source_file, base_dir)
                parts.append(" ".join(tokens))
    return ", ".join(parts)


def _get_relative_path(source_file: Path, target_file: Path) -> str:
    """Get relative path from source to target."""
    try:
        source_dir = source_file.parent
        rel_path = target_file.relative_to(source_dir)
        return "./" + str(rel_path)
    except ValueError:
        # Files not in same tree, return original
        return str(target_file)
