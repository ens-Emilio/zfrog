"""API discovery: find the REST/GraphQL endpoints a page talks to.

Pure analysis, no network: :func:`extract_endpoints` scans a page plus the
JavaScript bodies the caller already fetched and reports every endpoint it
recognises — ``fetch()``/axios/XHR/jQuery calls, ``<form>`` actions,
``<link href>`` pointing at an API and bare absolute API URLs quoted inside
scripts.

The ``source`` field records how an endpoint was found: ``"fetch"`` for
``fetch()``, ``"xhr"`` for axios / ``XMLHttpRequest`` / jQuery, ``"form"``,
``"link"``, ``"script"`` for a bare URL literal and ``"graphql"`` when that
literal is a GraphQL endpoint.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

__all__ = ["Endpoint", "extract_endpoints", "group_by_kind", "is_likely_api"]

# Path fragments that mark a URL as an API rather than a document.
API_PATH_MARKERS = ("/api/", "/graphql", "/rest/", "/v1/", "/v2/", "/v3/")
# File suffixes that are APIs even without one of the path markers.
API_FILE_SUFFIXES = (".json", ".graphql")
# Fragments that make an absolute URL literal inside a script worth reporting.
_SCRIPT_URL_MARKERS = ("/api/", "/graphql", "/v1/", "/v2/", "?query=")

# Statement separators used to scope GraphQL-body evidence to a single call.
_STATEMENT_BREAKS = ";\n{}"

_FETCH_CALL_RE = re.compile(r"\bfetch\s*\(")
_AXIOS_CALL_RE = re.compile(r"\baxios\s*\.\s*(?P<verb>[A-Za-z_$][\w$]*)\s*\(")
_XHR_OPEN_CALL_RE = re.compile(r"(?<!window)\.open\s*\(")
_JQ_AJAX_CALL_RE = re.compile(r"\$\s*\.\s*ajax\s*\(")
_JQ_SHORT_CALL_RE = re.compile(r"\$\s*\.\s*(?P<name>get|post)\s*\(")
_FIRST_STRING_RE = re.compile(r"""^\s*(?P<q>["'`])(?P<url>[^"'`\s]*)(?P=q)""")
_METHOD_PAIR_RE = re.compile(
    r"""^\s*(?P<q>["'])(?P<method>[A-Za-z]+)(?P=q)\s*,\s*(?P<q2>["'`])(?P<url>[^"'`\s]*)(?P=q2)"""
)
_METHOD_IN_OBJECT_RE = re.compile(r"""\b(?:method|type)\s*:\s*["'](?P<method>[A-Za-z]+)["']""")
_URL_IN_OBJECT_RE = re.compile(r"""\burl\s*:\s*["'](?P<url>[^"']+)["']""")
_STRING_URL_RE = re.compile(r"""(?P<q>["'`])(?P<url>https?://[^"'`\s<>]+)(?P=q)""")
_GRAPHQL_BODY_RE = re.compile(r"\b(?:query|mutation)\s*(?:[A-Za-z_]\w*\s*)?\{")

_AXIOS_VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


@dataclass
class Endpoint:
    """A single API endpoint discovered on a page."""

    url: str
    method: str = "GET"
    kind: str = "rest"
    source: str = ""


def is_likely_api(url: str) -> bool:
    """Whether a URL looks like an API rather than a page or an asset."""
    path = urlparse(url).path.lower()
    if any(marker in path for marker in API_PATH_MARKERS):
        return True
    return path.endswith(API_FILE_SUFFIXES)


def group_by_kind(endpoints: list[Endpoint]) -> dict[str, list[Endpoint]]:
    """Group endpoints by ``kind``, keeping their order inside each group."""
    grouped: dict[str, list[Endpoint]] = {}
    for endpoint in endpoints:
        grouped.setdefault(endpoint.kind, []).append(endpoint)
    return {kind: grouped[kind] for kind in sorted(grouped)}


def extract_endpoints(
    html: str,
    base_url: str,
    js_bodies: list[str] | None = None,
) -> list[Endpoint]:
    """Extract the API endpoints a page and its scripts talk to.

    Args:
        html: Page markup (inline scripts plus ``<form>``/``<link>`` tags).
        base_url: URL the page was served from; relative URLs resolve against it.
        js_bodies: Already-fetched external script bodies.

    Returns:
        Endpoints deduplicated by ``(method, url)`` and sorted by URL then method.
    """
    soup = _parse(html)
    scripts = _inline_scripts(soup)
    scripts.extend(body for body in (js_bodies or []) if body)

    found: list[Endpoint] = []
    for body in scripts:
        found.extend(_scan_js(body, base_url))
    if soup is not None:
        found.extend(_form_endpoints(soup, base_url))
        found.extend(_link_endpoints(soup, base_url))

    unique = _dedupe(found)
    unique.sort(key=lambda endpoint: (endpoint.url, endpoint.method))
    return unique


def _parse(html: str) -> BeautifulSoup | None:
    """Parse a page, tolerating malformed markup."""
    if not html:
        return None
    try:
        return BeautifulSoup(html, "lxml")
    except Exception as exc:  # noqa: BLE001 - broken HTML must not fail discovery
        logger.warning("failed to parse page: %s", exc)
        return None


def _inline_scripts(soup: BeautifulSoup | None) -> list[str]:
    """Bodies of the inline ``<script>`` blocks of a page, in document order."""
    if soup is None:
        return []
    bodies: list[str] = []
    for tag in soup.find_all("script"):
        if tag.get("src"):
            continue
        text = tag.get_text() or ""
        if text.strip():
            bodies.append(text)
    return bodies


def _resolve(raw: str, base_url: str) -> str | None:
    """Resolve a raw reference against the page URL, keeping only http(s)."""
    raw = raw.strip()
    if not raw or any(char.isspace() for char in raw):
        return None
    try:
        resolved = urljoin(base_url, raw)
    except ValueError:
        return None
    parsed = urlparse(resolved)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return resolved


def _clean_method(value: str) -> str:
    """Normalise an HTTP verb; anything unusable falls back to GET."""
    method = value.strip().upper()
    return method if method.isalpha() else "GET"


def _is_graphql_url(url: str) -> bool:
    """Whether a URL is a GraphQL endpoint."""
    return "graphql" in url.lower()


def _near_graphql(context: str) -> bool:
    """Whether a GraphQL query body appears in the same call/statement."""
    return _GRAPHQL_BODY_RE.search(context) is not None


def _statement(text: str, position: int) -> str:
    """The statement around a position, scoping GraphQL evidence to one call."""
    start = position
    while start > 0 and text[start - 1] not in _STATEMENT_BREAKS:
        start -= 1
    end = position
    while end < len(text) and text[end] not in _STATEMENT_BREAKS:
        end += 1
    return text[start:end]


def _dedupe(endpoints: list[Endpoint]) -> list[Endpoint]:
    """Keep the first occurrence of every ``(method, url)`` pair."""
    seen: set[tuple[str, str]] = set()
    unique: list[Endpoint] = []
    for endpoint in endpoints:
        key = (endpoint.method, endpoint.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(endpoint)
    return unique


def _balanced(text: str, open_index: int, opener: str, closer: str) -> str:
    """Text between a balanced ``opener``/``closer`` pair, quotes respected."""
    depth = 0
    quote = ""
    index = open_index
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[open_index + 1:index]
        index += 1
    return text[open_index + 1:]


def _call_args(js: str, open_index: int) -> str:
    """Arguments of a call whose ``(`` sits at ``open_index``."""
    return _balanced(js, open_index, "(", ")")


def _scan_js(body: str, base_url: str) -> list[Endpoint]:
    """Endpoints referenced by one JavaScript body."""
    found: list[Endpoint] = []

    def add(raw: str, method: str, source: str, context: str) -> None:
        url = _resolve(raw, base_url)
        if url is None:
            return
        kind = "graphql" if _is_graphql_url(url) or _near_graphql(context) else "rest"
        found.append(
            Endpoint(url=url, method=_clean_method(method), kind=kind, source=source)
        )

    for match in _FETCH_CALL_RE.finditer(body):
        args = _call_args(body, match.end() - 1)
        target = _FIRST_STRING_RE.match(args)
        if target is None:
            continue
        explicit = _METHOD_IN_OBJECT_RE.search(args)
        add(
            target.group("url"),
            explicit.group("method") if explicit else "GET",
            "fetch",
            args,
        )

    for match in _AXIOS_CALL_RE.finditer(body):
        args = _call_args(body, match.end() - 1)
        verb = match.group("verb").upper()
        target = _FIRST_STRING_RE.match(args)
        if verb in _AXIOS_VERBS and target is not None:
            add(target.group("url"), verb, "xhr", args)
            continue
        # axios({url: "...", method: "..."}) and axios.request({...})
        object_text = _object_literal(args)
        url_match = _URL_IN_OBJECT_RE.search(object_text)
        if url_match is None:
            continue
        method_match = _METHOD_IN_OBJECT_RE.search(object_text)
        add(
            url_match.group("url"),
            method_match.group("method") if method_match else "GET",
            "xhr",
            object_text,
        )

    for match in _XHR_OPEN_CALL_RE.finditer(body):
        args = _call_args(body, match.end() - 1)
        pair = _METHOD_PAIR_RE.match(args)
        if pair is None:
            continue
        add(pair.group("url"), pair.group("method"), "xhr", args)

    for match in _JQ_SHORT_CALL_RE.finditer(body):
        args = _call_args(body, match.end() - 1)
        target = _FIRST_STRING_RE.match(args)
        if target is None:
            continue
        add(target.group("url"), match.group("name"), "xhr", args)

    for match in _JQ_AJAX_CALL_RE.finditer(body):
        object_text = _object_literal(_call_args(body, match.end() - 1))
        url_match = _URL_IN_OBJECT_RE.search(object_text)
        if url_match is None:
            continue
        method_match = _METHOD_IN_OBJECT_RE.search(object_text)
        add(
            url_match.group("url"),
            method_match.group("method") if method_match else "GET",
            "xhr",
            object_text,
        )

    for match in _STRING_URL_RE.finditer(body):
        raw = match.group("url")
        if not any(marker in raw for marker in _SCRIPT_URL_MARKERS):
            continue
        url = _resolve(raw, base_url)
        if url is None:
            continue
        context = _statement(body, match.start())
        if _is_graphql_url(url) or _near_graphql(context):
            found.append(Endpoint(url=url, kind="graphql", source="graphql"))
        else:
            found.append(Endpoint(url=url, source="script"))

    return found


def _object_literal(args: str) -> str:
    """The ``{...}`` literal at the start of a call's arguments, if any."""
    start = args.find("{")
    if start < 0:
        return ""
    return _balanced(args, start, "{", "}")


def _form_endpoints(soup: BeautifulSoup, base_url: str) -> list[Endpoint]:
    """Endpoints submitted by the page's forms."""
    found: list[Endpoint] = []
    for form in soup.find_all("form"):
        action = str(form.get("action") or "").strip()
        if not action:
            continue
        url = _resolve(action, base_url)
        if url is None:
            continue
        method = _clean_method(str(form.get("method") or "GET"))
        kind = "graphql" if _is_graphql_url(url) else "rest"
        found.append(Endpoint(url=url, method=method, kind=kind, source="form"))
    return found


def _link_endpoints(soup: BeautifulSoup, base_url: str) -> list[Endpoint]:
    """API-looking ``<link href>`` targets (feeds, JSON manifests, preloads)."""
    found: list[Endpoint] = []
    for link in soup.find_all("link", href=True):
        url = _resolve(str(link.get("href") or ""), base_url)
        if url is None or not is_likely_api(url):
            continue
        kind = "graphql" if _is_graphql_url(url) else "rest"
        found.append(Endpoint(url=url, kind=kind, source="link"))
    return found
