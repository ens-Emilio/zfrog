"""HLS (m3u8) and DASH (MPD) manifest parsing.

Pure text parsing — this module never touches the network, so it is trivially
unit-testable with literal manifests and reusable by any caller that already
holds the bytes (the video engine, a future live-recorder, ...).

Supported:

* HLS master playlists — one :class:`Variant` per ``#EXT-X-STREAM-INF`` tag,
  carrying ``BANDWIDTH``, ``RESOLUTION`` and ``CODECS``.
* HLS media playlists — one :class:`Segment` per media URI, honouring
  ``#EXTINF`` for the duration and ``#EXT-X-BYTERANGE`` for partial resources.
  The implicit offset of ``length@offset`` accumulates across consecutive
  ranges that address the same URI, exactly as RFC 8216 requires.
* DASH MPDs — one :class:`Variant` per ``<Representation>``, carrying
  ``bandwidth``, ``width``/``height`` and ``codecs``.

``#EXT-X-KEY`` (or a DASH ``ContentProtection``) only sets ``encrypted``: the
content is reported, never decrypted.

DASH segment templates (``<SegmentTemplate>``/``<SegmentList>``) are out of
scope, so ``segments`` is always empty for an MPD — only the variant list and
the protection flag are reported.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin
from xml.etree import ElementTree

logger = logging.getLogger(__name__)


@dataclass
class Variant:
    """One selectable rendition of a stream."""

    uri: str
    bandwidth: int = 0
    resolution: str = ""
    codecs: str = ""


@dataclass
class Segment:
    """One media segment.

    ``byte_range`` is a half-open ``(start, end)`` pair, so the end of one
    range is the start offset of the next one.
    """

    uri: str
    duration: float = 0.0
    byte_range: tuple[int, int] | None = None


_ATTR_RE = re.compile(r'([A-Za-z0-9-]+)=("[^"]*"|[^,]*)')
_EXTINF_RE = re.compile(r"#EXTINF:\s*([0-9.]+)")
_BYTERANGE_RE = re.compile(r"#EXT-X-BYTERANGE:\s*(\d+)(?:@(\d+))?")
_TARGETDURATION_RE = re.compile(r"#EXT-X-TARGETDURATION:\s*([0-9.]+)")
_MPD_RE = re.compile(r"<MPD[\s>]", re.IGNORECASE)
_ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)

MASTER_TAG = "#EXT-X-STREAM-INF:"


def is_master_playlist(text: str) -> bool:
    """True when ``text`` carries an ``#EXT-X-STREAM-INF`` tag."""
    return "#EXT-X-STREAM-INF" in (text or "")


def is_dash(text: str) -> bool:
    """True when ``text`` looks like a DASH MPD payload."""
    return bool(_MPD_RE.search(text or ""))


def _parse_attributes(raw: str) -> dict[str, str]:
    """Parse an HLS attribute list (``A=1,B="x,y"``) into a dict."""
    attributes: dict[str, str] = {}
    for match in _ATTR_RE.finditer(raw or ""):
        key = match.group(1).upper()
        value = match.group(2)
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        attributes[key] = value.strip()
    return attributes


def _as_int(value: str | None) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _empty_result(kind: str) -> dict:
    return {
        "kind": kind,
        "variants": [],
        "segments": [],
        "target_duration": 0.0,
        "encrypted": False,
    }


def parse_m3u8(text: str, base_url: str) -> dict:
    """Parse an HLS manifest into variants (master) or segments (media).

    Relative URIs are resolved against ``base_url``. ``kind`` is ``"master"``
    when the payload holds ``#EXT-X-STREAM-INF`` tags, ``"media"`` otherwise.
    """
    kind = "master" if is_master_playlist(text) else "media"
    result = _empty_result(kind)
    variants: list[Variant] = []
    segments: list[Segment] = []
    range_ends: dict[str, int] = {}

    pending_attrs: dict[str, str] | None = None
    pending_duration = 0.0
    pending_range: tuple[int, int | None] | None = None

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line == "#EXT-X-ENDLIST":
            continue

        if line.startswith("#"):
            if line.startswith(MASTER_TAG):
                pending_attrs = _parse_attributes(line[len(MASTER_TAG):])
            elif line.startswith("#EXTINF:"):
                match = _EXTINF_RE.match(line)
                if match:
                    pending_duration = float(match.group(1))
            elif line.startswith("#EXT-X-BYTERANGE:"):
                match = _BYTERANGE_RE.match(line)
                if match:
                    offset = int(match.group(2)) if match.group(2) is not None else None
                    pending_range = (int(match.group(1)), offset)
            elif line.startswith("#EXT-X-TARGETDURATION:"):
                match = _TARGETDURATION_RE.match(line)
                if match:
                    result["target_duration"] = float(match.group(1))
            elif line.startswith("#EXT-X-KEY:"):
                attributes = _parse_attributes(line[len("#EXT-X-KEY:"):])
                if attributes.get("METHOD", "NONE").upper() != "NONE":
                    result["encrypted"] = True
            # Any other tag (EXT-X-MEDIA, EXT-X-MAP, ...) is not needed here.
            continue

        uri = urljoin(base_url, line)

        if kind == "master":
            if pending_attrs is None:
                # A bare URI in a master playlist has no rendition metadata.
                continue
            variants.append(
                Variant(
                    uri=uri,
                    bandwidth=_as_int(pending_attrs.get("BANDWIDTH")),
                    resolution=pending_attrs.get("RESOLUTION", ""),
                    codecs=pending_attrs.get("CODECS", ""),
                )
            )
            pending_attrs = None
            continue

        byte_range: tuple[int, int] | None = None
        if pending_range is not None:
            length, offset = pending_range
            if offset is None:
                offset = range_ends.get(uri, 0)
            byte_range = (offset, offset + length)
            range_ends[uri] = offset + length
        segments.append(Segment(uri=uri, duration=pending_duration, byte_range=byte_range))
        pending_duration = 0.0
        pending_range = None

    result["variants"] = variants
    result["segments"] = segments
    return result


def _local_name(tag: str) -> str:
    """Strip the ``{namespace}`` prefix from an ElementTree tag."""
    return tag.rsplit("}", 1)[-1]


def _child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    for child in element:
        if _local_name(child.tag) == name:
            return child
    return None


def _effective_base(
    element: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
    base_url: str,
) -> str:
    """Resolve the ``<BaseURL>`` chain from the MPD root down to ``element``."""
    chain: list[ElementTree.Element] = []
    node: ElementTree.Element | None = element
    while node is not None:
        chain.append(node)
        node = parents.get(node)

    current = base_url
    for ancestor in reversed(chain):
        base = _child(ancestor, "BaseURL")
        text = (base.text or "").strip() if base is not None else ""
        if text:
            current = urljoin(current, text)
    return current


def _parse_iso_duration(value: str) -> float:
    """Seconds from an ISO-8601 duration such as ``PT4.5S`` (0.0 when invalid)."""
    match = _ISO_DURATION_RE.match(value.strip()) if value else None
    if not match:
        return 0.0
    parts = {key: float(raw) for key, raw in match.groupdict().items() if raw}
    return (
        parts.get("days", 0.0) * 86400
        + parts.get("hours", 0.0) * 3600
        + parts.get("minutes", 0.0) * 60
        + parts.get("seconds", 0.0)
    )


def parse_mpd(text: str, base_url: str) -> dict:
    """Parse a DASH MPD into variants.

    Each ``<Representation>`` becomes a :class:`Variant` whose URI is its own
    ``<BaseURL>`` (or the closest ancestor's, or the MPD path itself).
    ``segments`` stays empty: segment templates are out of scope.
    """
    result = _empty_result("dash")
    payload = (text or "").lstrip("\ufeff \t\r\n")
    if not payload:
        return result

    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        logger.warning("invalid MPD: %s", exc)
        return result
    if _local_name(root.tag) != "MPD":
        return result

    parents = {child: parent for parent in root.iter() for child in parent}
    variants: list[Variant] = []
    for element in root.iter():
        if _local_name(element.tag) != "Representation":
            continue
        width = _as_int(element.get("width"))
        height = _as_int(element.get("height"))
        variants.append(
            Variant(
                uri=_effective_base(element, parents, base_url),
                bandwidth=_as_int(element.get("bandwidth")),
                resolution=f"{width}x{height}" if width and height else "",
                codecs=element.get("codecs") or "",
            )
        )

    result["variants"] = variants
    result["target_duration"] = _parse_iso_duration(root.get("maxSegmentDuration") or "")
    result["encrypted"] = any(
        _local_name(element.tag) == "ContentProtection" for element in root.iter()
    )
    return result


def _height_of(resolution: str) -> int:
    """Height in pixels from a ``1920x1080`` string (0 when unknown)."""
    if not resolution or "x" not in resolution:
        return 0
    _, _, raw = resolution.rpartition("x")
    try:
        return int(raw)
    except ValueError:
        return 0


def select_variant(variants: list[Variant], max_height: int = 0) -> Variant | None:
    """Pick a rendition: highest bandwidth, optionally capped by height.

    With ``max_height`` set, only renditions whose resolution does not exceed
    it are considered (an unparsed resolution counts as compatible); ``None``
    is returned when none fits.
    """
    if not variants:
        return None
    if max_height > 0:
        eligible = [variant for variant in variants if _height_of(variant.resolution) <= max_height]
        if not eligible:
            return None
        return max(eligible, key=lambda variant: (variant.bandwidth, _height_of(variant.resolution)))
    return max(variants, key=lambda variant: (variant.bandwidth, _height_of(variant.resolution)))
