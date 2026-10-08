"""Point-and-click extractor backend: fetch, sanitise and preview CSS selectors.

The dashboard renders a fetched page inside an iframe and lets the user click
elements to build a CSS selector. The HTML handed to the browser must therefore
be inert: scripts, inline event handlers, ``javascript:`` URLs and meta refreshes
are stripped before the markup leaves the API process, and a ``<base>`` tag is
injected so that relative assets still resolve against the crawled page.

Everything here is pure except :func:`fetch_page`, which performs one HTTP GET.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass

from bs4 import BeautifulSoup, Tag
from soupsieve import SelectorSyntaxError
from soupsieve import compile as compile_selector

from zfrog.utils.http import create_client

logger = logging.getLogger(__name__)

# Preview payloads feed a click-to-build UI, so snippets stay small.
TEXT_LIMIT = 300
HTML_LIMIT = 500

_REMOVED_TAGS = ("script", "noscript")
_URL_ATTRS = ("href", "src", "action", "formaction")
_EVENT_ATTR = re.compile(r"^on", re.IGNORECASE)
_JAVASCRIPT_URL = re.compile(r"^javascript:", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


@dataclass
class SelectorMatch:
    """A single element matched by a preview selector."""

    index: int
    tag: str
    text: str
    html: str


async def fetch_page(url: str) -> dict:
    """Fetch ``url`` and return ``{"url", "title", "html"}``.

    ``html`` is sanitised for safe rendering inside an iframe (see
    :func:`_sanitize`), and ``title`` is the document title, empty when the page
    has none.
    """
    async with create_client() as client:
        response = await client.get(url)
        response.raise_for_status()

    page_url = str(response.url)
    html, title = _sanitize(response.text, page_url)
    logger.debug("Fetched %s (%d bytes)", page_url, len(response.content))
    return {"url": page_url, "title": title, "html": html}


def validate_selector(selector: str) -> None:
    """Raise ``ValueError`` when ``selector`` is blank or not valid CSS."""
    if selector is None or not str(selector).strip():
        raise ValueError("The CSS selector cannot be empty")
    try:
        compile_selector(selector)
    except (SelectorSyntaxError, NotImplementedError) as exc:
        raise ValueError(f"Invalid CSS selector: {selector!r} ({exc})") from exc


def preview_selector(html: str, selector: str, limit: int = 50) -> list[SelectorMatch]:
    """Match ``selector`` against ``html``, returning at most ``limit`` matches.

    The injected ``<base>`` tag is never reported, and invalid selectors raise
    ``ValueError``.
    """
    validate_selector(selector)
    elements = _select(BeautifulSoup(html or "", "lxml"), selector)
    return _matches(elements, limit)


def build_selector_preview(html: str, selector: str, limit: int = 50) -> dict:
    """Return ``{"count", "elements"}`` for ``selector`` over ``html``.

    ``count`` is the total number of matches, while ``elements`` is capped at
    ``limit``; the injected ``<base>`` tag counts as neither.
    """
    validate_selector(selector)
    elements = _select(BeautifulSoup(html or "", "lxml"), selector)
    return {
        "count": len(_matches(elements, None)),
        "elements": [asdict(match) for match in _matches(elements, limit)],
    }


def sanitize_fragment(html: str) -> str:
    """Strip anything executable from an HTML fragment and return it.

    The same rules as :func:`_sanitize` apply — scripts, inline event handlers,
    ``javascript:`` URLs, meta refresh — but without the document scaffolding, so the
    result is safe to paste into a report or render as a preview of one component.
    Extracted components come from a live DOM, where inline handlers are common.

    A fragment (no ``<html>``/``<!doctype>``) keeps its shape: the parser would
    otherwise wrap it in ``<html><body>``, and reporting that wrapper as part of a
    component would be wrong.
    """
    stripped = (html or "").lstrip()
    is_document = stripped[:5].lower() == "<!doc" or "<html" in stripped[:200].lower()

    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup.find_all(_REMOVED_TAGS):
        tag.decompose()
    for meta in soup.find_all("meta"):
        if str(meta.get("http-equiv", "")).strip().lower() == "refresh":
            meta.decompose()
    for element in soup.find_all(True):
        _strip_unsafe_attributes(element)

    if is_document or soup.body is None:
        return str(soup)
    return soup.body.decode_contents().strip()


def _sanitize(html: str, page_url: str) -> tuple[str, str]:
    """Return ``(sanitised_html, title)`` for a fetched page."""
    soup = BeautifulSoup(html or "", "lxml")
    title = soup.title.get_text(strip=True) if soup.title is not None else ""

    for tag in soup.find_all(_REMOVED_TAGS):
        tag.decompose()
    for meta in soup.find_all("meta"):
        if str(meta.get("http-equiv", "")).strip().lower() == "refresh":
            meta.decompose()
    for element in soup.find_all(True):
        _strip_unsafe_attributes(element)

    head = _ensure_head(soup)
    head.insert(0, soup.new_tag("base", href=page_url))
    return str(soup), title


def _strip_unsafe_attributes(element: Tag) -> None:
    """Drop inline event handlers and ``javascript:`` URLs from one element."""
    for attribute in list(element.attrs):
        if _EVENT_ATTR.match(attribute):
            del element[attribute]
        elif attribute.lower() in _URL_ATTRS and _is_javascript_url(str(element[attribute])):
            del element[attribute]


def _is_javascript_url(value: str) -> bool:
    """True when ``value`` is a ``javascript:`` URL, ignoring obfuscation.

    Browsers ignore whitespace and control characters inside the scheme, so
    ``java\\nscript:alert(1)`` must be caught too.
    """
    return bool(_JAVASCRIPT_URL.match("".join(ch for ch in value if ch > " ")))


def _ensure_head(soup: BeautifulSoup) -> Tag:
    """Return the document ``<head>``, creating it when the page has none."""
    if soup.head is not None:
        return soup.head
    head = soup.new_tag("head")
    root = soup.html if soup.html is not None else soup
    root.insert(0, head)
    return head


def _select(soup: BeautifulSoup, selector: str) -> list[Tag]:
    """Run ``selector`` over ``soup``, re-raising syntax errors as ``ValueError``."""
    try:
        return soup.select(selector)
    except (SelectorSyntaxError, NotImplementedError) as exc:
        raise ValueError(f"Invalid CSS selector: {selector!r} ({exc})") from exc


def _matches(elements: list[Tag], limit: int | None) -> list[SelectorMatch]:
    """Build match payloads, skipping the injected ``<base>`` tag."""
    matches: list[SelectorMatch] = []
    for index, element in enumerate(elements):
        if element.name == "base":
            continue
        if limit is not None and len(matches) >= limit:
            break
        matches.append(
            SelectorMatch(
                index=index,
                tag=element.name,
                text=_collapse_text(element.get_text(" ")),
                html=str(element)[:HTML_LIMIT],
            )
        )
    return matches


def _collapse_text(text: str) -> str:
    """Collapse runs of whitespace and truncate to :data:`TEXT_LIMIT` chars."""
    return _WHITESPACE.sub(" ", text).strip()[:TEXT_LIMIT]
