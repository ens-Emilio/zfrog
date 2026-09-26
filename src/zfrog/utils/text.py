"""HTML text extraction shared by engines, search, snapshots and AI.

Two extractors with different trade-offs, because "the text of a page" means
different things to different callers:

``extract_text`` (default)
    Every piece of visible text in the document body. Lossless. Used where
    dropping content would be a silent bug: the search index, snapshot diffs and
    the text stored for change detection.

``extract_main_text``
    Article-style extraction via trafilatura, which strips navigation, footers
    and sidebars. Higher precision, but it also discards short lists and other
    blocks it judges non-essential — trafilatura dropped a page's entire ``<ul>``
    in testing, so this is opt-in only.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

# Elements whose text is not content the user reads.
_NON_CONTENT_TAGS = ("script", "style", "noscript", "template", "svg", "iframe")


def extract_text(html: str) -> str:
    """Extract every visible text block from an HTML document.

    Lossless by design: list items, table cells and headings are all kept, so a
    search for text that is on the page always finds it.

    Args:
        html: Raw HTML.

    Returns:
        Whitespace-collapsed text, or ``""`` for empty/markup-free input.
    """
    if not html or not html.strip():
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return ""
    for tag in soup(_NON_CONTENT_TAGS):
        tag.decompose()
    body = soup.body or soup
    return body.get_text(separator=" ", strip=True)


def extract_main_text(html: str) -> str:
    """Extract the main article text, discarding boilerplate.

    Prefer :func:`extract_text` unless navigation and footers genuinely hurt —
    trafilatura prunes short lists and similar blocks, so content can be lost.
    Falls back to :func:`extract_text` when trafilatura is unavailable or finds
    nothing.

    Args:
        html: Raw HTML.

    Returns:
        Extracted main text, or ``""`` for empty input.
    """
    if not html or not html.strip():
        return ""
    try:
        import trafilatura

        return trafilatura.extract(html, include_comments=False) or extract_text(html)
    except ImportError:
        return extract_text(html)
