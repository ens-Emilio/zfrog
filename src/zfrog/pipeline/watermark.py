"""Invisible provenance watermarks for cloned content.

Every file Zfrog produces can carry a short mark identifying the run that wrote
it, so a copy found elsewhere can be traced back to the source URL, the moment
of the run and the tool version. The carriers are standards-based and invisible
in a rendered page:

``<meta name="zfrog-provenance" content="TOKEN">``
    Primary carrier, inserted as the last child of ``<head>``.
``data-zfrog-provenance`` on ``<html>``
    Redundant attribute carrier.
``<!-- zfrog:TOKEN -->``
    Trailing comment at the end of the document, and of ``.txt``/``.md`` files.
    Text files additionally get a zero-width-character encoding of the token.

``TOKEN`` is the watermark payload as compact JSON, base64url encoded without
padding (:func:`encode_payload`), so it survives being copied into text or HTML.

What this does **not** do — stated plainly because the difference matters:

* It is **not DRM**. The payload is readable by anyone who looks at the file's
  bytes, and removable by anyone who deletes the carriers. One regex, one
  "save as" through a tool that drops unknown attributes, or one copy-paste
  through a plain-text field strips the mark.
* It is **not steganographic proof of ownership**. It records where a copy came
  from; it does not establish who owned the content first.
* It does not survive re-encoding through media that discard comments,
  attributes or zero-width characters (PDF pipelines, many editors, most chat
  clients).

The three HTML carriers are redundant on purpose: :func:`extract_html` recovers
the payload from whichever one survives.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import string
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import zfrog
from bs4 import BeautifulSoup, Comment, Tag

logger = logging.getLogger(__name__)

# ── Mark ────────────────────────────────────────────────────────────────────

MARK_PREFIX = "ZK-"
MARK_RE = re.compile(r"^ZK-\d{14}-[0-9a-f]{8}$")
_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
_TOOL_NAME = "zfrog"
_MARKABLE_SUFFIXES = (".html", ".txt", ".md")

_last_stamp = ""


@dataclass
class Watermark:
    """A provenance mark plus everything needed to reproduce its payload.

    Attributes:
        mark: Short, sortable identifier, e.g. ``ZK-20240102030405-1a2b3c4d``.
        created_at: ISO-8601 UTC creation time.
        source_url: URL the marked content was cloned from (``""`` if unknown).
        payload: The data embedded in the content; see :func:`make_mark`.
    """

    mark: str
    created_at: str
    source_url: str
    payload: dict


def _next_stamp() -> str:
    """Return a strictly increasing ``YYYYmmddHHMMSS`` UTC stamp.

    Strictly increasing rather than merely "now" so that two marks created
    within the same second stay distinct (and therefore hash differently).
    """
    global _last_stamp
    stamp = datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)
    if stamp <= _last_stamp:
        previous = datetime.strptime(_last_stamp, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
        stamp = (previous + timedelta(seconds=1)).strftime(_TIMESTAMP_FORMAT)
    _last_stamp = stamp
    return stamp


def make_mark(source_url: str, extra: dict | None = None) -> Watermark:
    """Create a watermark for content cloned from ``source_url``.

    The mark is ``"ZK-" + <14-char UTC timestamp> + "-" + <8 hex>``, where the
    hex digits are a hash of the URL and the timestamp: the shape is fixed and
    sortable, while the value is unique per call.

    Args:
        source_url: URL the content was cloned from.
        extra: Additional payload entries (engine, job id, ...). Entries whose
            keys collide with the reserved ones (``mark``, ``created_at``,
            ``source_url``, ``tool``, ``version``) are ignored.

    Returns:
        The watermark, with its payload already built.
    """
    stamp = _next_stamp()
    digest = hashlib.sha256(f"{source_url}|{stamp}".encode("utf-8")).hexdigest()[:8]
    mark = f"{MARK_PREFIX}{stamp}-{digest}"
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = dict(extra or {})
    payload.update(
        {
            "mark": mark,
            "created_at": created_at,
            "source_url": source_url,
            "tool": _TOOL_NAME,
            "version": getattr(zfrog, "__version__", "0"),
        }
    )
    return Watermark(mark=mark, created_at=created_at, source_url=source_url, payload=payload)


# ── Token encoding ──────────────────────────────────────────────────────────


def encode_payload(watermark: Watermark) -> str:
    """Encode a watermark's payload as unpadded base64url.

    Args:
        watermark: Watermark to encode.

    Returns:
        A token safe to embed in HTML attributes, comments and plain text.
    """
    raw = json.dumps(watermark.payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_payload(token: str) -> dict:
    """Decode a token produced by :func:`encode_payload`.

    Args:
        token: base64url token.

    Returns:
        The payload dictionary.

    Raises:
        ValueError: The token is empty, is not valid base64url, or does not
            decode to a JSON object.
    """
    if not isinstance(token, str) or not token:
        raise ValueError("empty provenance token")
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"corrupt provenance token: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("provenance token does not carry a JSON object")
    return data


# ── HTML carriers ───────────────────────────────────────────────────────────

META_NAME = "zfrog-provenance"
META_ATTR = "data-zfrog-provenance"
COMMENT_PREFIX = "zfrog:"
_COMMENT_RE = re.compile(rf"{re.escape(COMMENT_PREFIX)}([A-Za-z0-9_\-]+)")


def inject_html(html: str, watermark: Watermark) -> str:
    """Embed a watermark in an HTML document without changing what renders.

    Adds the meta tag as the last child of ``<head>`` (creating ``<head>``, and
    the whole document skeleton, when absent), the ``data-zfrog-provenance``
    attribute on ``<html>`` and a trailing ``<!-- zfrog:TOKEN -->`` comment after
    ``</html>``. Carriers from an earlier injection are replaced, so calling
    this twice leaves exactly one of each.

    Args:
        html: Document or fragment.
        watermark: Watermark to embed.

    Returns:
        The marked document.
    """
    token = encode_payload(watermark)
    soup = BeautifulSoup(html or "", "lxml")
    _strip_html_carriers(soup)
    soup, root = _ensure_document(soup)
    root[META_ATTR] = token
    head = root.find("head")
    if head is None:
        head = soup.new_tag("head")
        root.insert(0, head)
    head.append(soup.new_tag("meta", attrs={"name": META_NAME, "content": token}))
    soup.append(Comment(f" {COMMENT_PREFIX}{token} "))
    return str(soup)


def extract_html(html: str) -> dict | None:
    """Read a watermark payload back out of an HTML document.

    Carriers are tried in order of reliability — meta tag, ``<html>``
    attribute, trailing comment — and the first one that decodes wins, so a
    document whose meta tag was stripped but whose comment survived is still
    traced.

    Args:
        html: Document to inspect.

    Returns:
        The payload, or ``None`` when no carrier decodes.
    """
    if not html or not html.strip():
        return None
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:  # pragma: no cover - bs4 rarely raises on strings
        logger.warning("unparseable HTML document: %s", exc)
        return None
    for token in _html_tokens(soup):
        try:
            return decode_payload(token)
        except ValueError:
            continue
    return None


def verify_html(html: str, expected: Watermark) -> bool:
    """Check whether ``html`` carries exactly the expected watermark.

    Args:
        html: Document to inspect.
        expected: Watermark the document should carry.

    Returns:
        ``True`` only when both the mark and the source URL match.
    """
    payload = extract_html(html)
    if payload is None:
        return False
    return payload.get("mark") == expected.mark and payload.get("source_url") == expected.source_url


def _ensure_document(soup: BeautifulSoup) -> tuple[BeautifulSoup, Tag]:
    """Return the soup plus its ``<html>`` element, building a skeleton if needed."""
    root = soup.find("html")
    if root is not None:
        return soup, root
    document = BeautifulSoup("<html><head></head><body></body></html>", "lxml")
    new_root = document.find("html")
    body = new_root.find("body")
    for child in list(soup.contents):
        body.append(child.extract())
    return document, new_root


def _strip_html_carriers(soup: BeautifulSoup) -> None:
    """Remove every provenance carrier already present in ``soup``."""
    for meta in soup.find_all("meta", attrs={"name": META_NAME}):
        meta.decompose()
    for tag in soup.find_all(True):
        if META_ATTR in tag.attrs:
            del tag[META_ATTR]
    for node in soup.find_all(string=lambda s: isinstance(s, Comment) and COMMENT_PREFIX in s):
        node.extract()


def _html_tokens(soup: BeautifulSoup) -> Iterator[str]:
    """Yield candidate tokens from ``soup``, most reliable carrier first."""
    for meta in soup.find_all("meta", attrs={"name": META_NAME}):
        content = meta.get("content")
        if content:
            yield content
    root = soup.find("html")
    if root is not None:
        value = root.get(META_ATTR)
        if value:
            yield value
    for node in soup.find_all(string=lambda s: isinstance(s, Comment)):
        match = _COMMENT_RE.search(str(node))
        if match:
            yield match.group(1)


# ── Zero-width text carrier ─────────────────────────────────────────────────
#
# Alphabet: four zero-width characters carry two base-4 digits each, so one
# base64url character (64 values) is three zero-width characters. U+FEFF
# (zero-width no-break space) is reserved for framing and never appears in an
# encoded value, which is what makes the end of a carrier unambiguous.

_ZW_DIGITS = ("\u200b", "\u200c", "\u200d", "\u2060")  # ZWSP, ZWNJ, ZWJ, word joiner
_ZW_GUARD = "\ufeff"
_ZW_START = "\u200b\u200c\u200b\u200c"
_ZW_STOP = _ZW_GUARD * 3
_ZW_CARRIER_RE = re.compile(
    rf"\n?{re.escape(_ZW_START)}[^{re.escape(_ZW_GUARD)}]*{re.escape(_ZW_STOP)}\n?"
)
_ZW_COMMENT_RE = re.compile(rf"<!--\s*{re.escape(COMMENT_PREFIX)}[^\s>]*\s*-->\n?")
_B64_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "-_"


def inject_text(text: str, watermark: Watermark) -> str:
    """Embed a watermark in plain text (``.txt``/``.md``) without changing it.

    The input is kept byte-for-byte as a prefix; the carriers are appended after
    it, so no visible character is added, moved or removed. Carriers from an
    earlier injection are replaced, so calling this twice is idempotent.

    Args:
        text: Original file content.
        watermark: Watermark to embed.

    Returns:
        The marked content.
    """
    token = encode_payload(watermark)
    return (
        f"{strip_text_carriers(text or '')}\n"
        f"{_encode_zw(token)}\n"
        f"<!-- {COMMENT_PREFIX}{token} -->\n"
    )


def extract_text_mark(text: str) -> str | None:
    """Recover the token from the zero-width carrier in ``text``.

    Args:
        text: Content that may carry a zero-width encoded token.

    Returns:
        The token, or ``None`` when there is no readable carrier.
    """
    if not text:
        return None
    position = text.find(_ZW_START)
    while position != -1:
        token = _decode_zw_at(text, position)
        if token is not None:
            return token
        position = text.find(_ZW_START, position + 1)
    return None


def strip_text_carriers(text: str) -> str:
    """Remove any watermark carriers previously appended to ``text``.

    Args:
        text: Content that may end with carriers.

    Returns:
        The content as it was before injection.
    """
    return _ZW_COMMENT_RE.sub("", _ZW_CARRIER_RE.sub("", text))


def _encode_zw(token: str) -> str:
    """Encode a base64url token as zero-width characters."""
    digits = []
    for char in token:
        value = _B64_ALPHABET.find(char)
        if value < 0:
            raise ValueError(f"not a base64url character: {char!r}")
        digits.append(
            _ZW_DIGITS[value // 16] + _ZW_DIGITS[(value // 4) % 4] + _ZW_DIGITS[value % 4]
        )
    return _ZW_START + "".join(digits) + _ZW_STOP


def _decode_zw_at(text: str, position: int) -> str | None:
    """Decode the carrier starting at ``position``, or ``None`` if malformed."""
    start = position + len(_ZW_START)
    end = text.find(_ZW_GUARD, start)
    if end == -1:
        return None
    body = text[start:end]
    if not body or len(body) % 3:
        return None
    chars = []
    for offset in range(0, len(body), 3):
        group = body[offset : offset + 3]
        values = [_ZW_DIGITS.index(char) if char in _ZW_DIGITS else -1 for char in group]
        if -1 in values:
            return None
        chars.append(_B64_ALPHABET[values[0] * 16 + values[1] * 4 + values[2]])
    token = "".join(chars)
    try:
        decode_payload(token)
    except ValueError:
        return None
    return token


def _text_payload(text: str) -> dict | None:
    """Decode a payload from a text file, zero-width carrier first, comment second."""
    token = extract_text_mark(text)
    if token is None:
        match = _COMMENT_RE.search(text)
        token = match.group(1) if match else None
    if token is None:
        return None
    try:
        return decode_payload(token)
    except ValueError:
        return None


# ── Directory helpers ───────────────────────────────────────────────────────


def _markable_files(dir_path: Path) -> list[Path]:
    """Return the sorted markable files under ``dir_path``."""
    return sorted(
        path
        for path in Path(dir_path).rglob("*")
        if path.is_file() and path.suffix.lower() in _MARKABLE_SUFFIXES
    )


async def watermark_directory(
    dir_path: Path, watermark: Watermark | None = None, source_url: str = ""
) -> dict:
    """Mark every ``.html``/``.txt``/``.md`` file under ``dir_path``.

    Files that cannot be read or parsed are logged and skipped. Only files whose
    content actually changes are rewritten.

    Args:
        dir_path: Directory to walk.
        watermark: Watermark to embed; created from ``source_url`` when omitted.
        source_url: Source URL used when ``watermark`` is not given.

    Returns:
        ``{"files": <candidates found>, "marked": <files now carrying the mark>,
        "mark": <mark string used>}``.
    """
    active = watermark or make_mark(source_url)
    files = _markable_files(dir_path)
    marked = 0
    for path in files:
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("skipping unreadable file %s: %s", path, exc)
            continue
        try:
            updated = (
                inject_html(original, active)
                if path.suffix.lower() == ".html"
                else inject_text(original, active)
            )
        except Exception as exc:
            logger.warning("skipping unparseable file %s: %s", path, exc)
            continue
        if updated != original:
            path.write_text(updated, encoding="utf-8")
        marked += 1
    return {"files": len(files), "marked": marked, "mark": active.mark}


async def verify_directory(dir_path: Path) -> dict:
    """Report which files under ``dir_path`` carry a watermark.

    A text file counts as marked when either of its carriers survives; a
    corrupt token is treated as unmarked.

    Args:
        dir_path: Directory to walk.

    Returns:
        ``{"files": <candidates scanned>, "marked": <files carrying a mark>,
        "marks": [<distinct marks>], "sources": [<distinct source URLs>]}``.
    """
    files = _markable_files(dir_path)
    marks: set[str] = set()
    sources: set[str] = set()
    marked = 0
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("skipping unreadable file %s: %s", path, exc)
            continue
        payload = (
            extract_html(content)
            if path.suffix.lower() == ".html"
            else _text_payload(content)
        )
        if payload is None:
            continue
        marked += 1
        if payload.get("mark"):
            marks.add(payload["mark"])
        if payload.get("source_url"):
            sources.add(payload["source_url"])
    return {
        "files": len(files),
        "marked": marked,
        "marks": sorted(marks),
        "sources": sorted(sources),
    }
