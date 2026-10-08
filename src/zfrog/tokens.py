"""Design token extraction: palette, typography, spacing and assets of a page.

Only the browser knows a page's *computed* style, so the work is split in two:

* :func:`collect_snapshot` runs one counting pass inside the page and returns plain
  JSON — ``value -> how many elements used it``, per CSS property.
* :func:`extract_tokens` turns that snapshot into :class:`DesignTokens`. It is pure,
  so the interpretation (hex conversion, ranking, role heuristics) is testable
  without launching a browser.

The palette roles are a heuristic and are labelled as such: frequency plus
saturation, not a model. Everything reported is something the page actually used —
nothing is inferred or invented, and values the parser cannot read are counted in
:attr:`DesignTokens.unreadable_colors` instead of being silently dropped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

#: CSS properties whose computed value is a colour we care about.
_COLOR_PROPERTIES = ("color", "backgroundColor", "borderTopColor", "outlineColor")

#: Colour syntaxes Chromium evaluates that :func:`parse_color` understands. The sign
#: is optional so an out-of-range channel is clamped rather than rejected: Chromium
#: does not emit negatives today, but a caller feeding in CSS Color 4 syntax should
#: get a colour, not silence.
_RGB_RE = re.compile(
    r"rgba?\(\s*(-?[\d.]+)[,\s]+(-?[\d.]+)[,\s]+(-?[\d.]+)(?:\s*[,/]\s*(-?[\d.]+%?))?\s*\)"
)

#: Spacing properties, grouped by the box they belong to.
_SPACING_PROPERTIES = {
    "padding": ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft"),
    "margin": ("marginTop", "marginRight", "marginBottom", "marginLeft"),
}

#: How many entries of each ranking the JSON keeps. The markdown renderer shows fewer.
_MAX_ENTRIES = 40

#: Saturation below which a colour counts as neutral (grey) rather than a brand colour.
_NEUTRAL_SATURATION = 0.12

#: Element count above which the browser snapshot stops walking the DOM. A page this
#: large has more elements than a palette needs samples from, and the walk is the
#: expensive part of the extraction.
_MAX_ELEMENTS = 6000


@dataclass
class ColorUse:
    """One colour, how often it appeared, and where."""

    hex: str
    count: int
    properties: dict[str, int] = field(default_factory=dict)
    role: str | None = None

    @property
    def saturation(self) -> float:
        """HSL saturation of the colour, 0.0 (grey) to 1.0."""
        r, g, b = _channels(self.hex)
        high, low = max(r, g, b), min(r, g, b)
        if high == low:
            return 0.0
        lightness = (high + low) / 2
        delta = high - low
        return delta / (2 - high - low) if lightness > 0.5 else delta / (high + low)


@dataclass
class FontUse:
    """One font family and how the page uses it."""

    family: str
    count: int
    sizes: dict[str, int] = field(default_factory=dict)
    weights: dict[str, int] = field(default_factory=dict)
    headings: int = 0
    body: int = 0


@dataclass
class AssetRef:
    """A visual asset the page loaded."""

    url: str
    kind: str
    width: int = 0
    height: int = 0
    alt: str = ""


@dataclass
class DesignTokens:
    """Everything :func:`extract_tokens` read off one rendered page."""

    url: str = ""
    title: str = ""
    element_count: int = 0
    palette: list[ColorUse] = field(default_factory=list)
    fonts: list[FontUse] = field(default_factory=list)
    font_sizes: list[tuple[str, int]] = field(default_factory=list)
    font_weights: list[tuple[str, int]] = field(default_factory=list)
    padding: list[tuple[str, int]] = field(default_factory=list)
    margin: list[tuple[str, int]] = field(default_factory=list)
    radii: list[tuple[str, int]] = field(default_factory=list)
    shadows: list[tuple[str, int]] = field(default_factory=list)
    assets: list[AssetRef] = field(default_factory=list)
    unreadable_colors: int = 0

    @property
    def hex_palette(self) -> list[str]:
        """The palette as plain hex strings, most used first."""
        return [color.hex for color in self.palette]

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form; ``roles`` is filled in by :func:`assign_roles`."""
        return {
            "url": self.url,
            "title": self.title,
            "element_count": self.element_count,
            "palette": [
                {"hex": c.hex, "count": c.count, "role": c.role, "properties": c.properties}
                for c in self.palette
            ],
            "fonts": [
                {
                    "family": f.family,
                    "count": f.count,
                    "sizes": f.sizes,
                    "weights": f.weights,
                    "headings": f.headings,
                    "body": f.body,
                }
                for f in self.fonts
            ],
            "font_sizes": self.font_sizes,
            "font_weights": self.font_weights,
            "padding": self.padding,
            "margin": self.margin,
            "radii": self.radii,
            "shadows": self.shadows,
            "assets": [a.__dict__ for a in self.assets],
            "unreadable_colors": self.unreadable_colors,
        }


# ── browser side ────────────────────────────────────────────────────────────────

#: The counting pass. Deliberately mechanical: it aggregates in the page so the
#: payload stays small on a big document, and interprets nothing.
_COLLECT_JS = """
() => {
  const colors = {};
  const fonts = {};
  const sizes = {};
  const weights = {};
  const padding = {};
  const margin = {};
  const radii = {};
  const shadows = {};
  const images = [];
  const backgrounds = new Set();
  const COLOR_PROPS = ["color", "backgroundColor", "borderTopColor", "outlineColor"];
  const PADDING_PROPS = ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft"];
  const MARGIN_PROPS = ["marginTop", "marginRight", "marginBottom", "marginLeft"];
  const MAX = %MAX%;

  const bump = (bucket, key) => { if (key) bucket[key] = (bucket[key] || 0) + 1; };

  const all = document.querySelectorAll("*");
  let counted = 0;

  for (const el of all) {
    if (counted >= MAX) break;
    // Hidden elements would contribute the styles of things nobody sees.
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;
    counted++;

    const cs = getComputedStyle(el);

    for (const prop of COLOR_PROPS) {
      const value = cs[prop];
      if (!value || value === "transparent") continue;
      const entry = colors[value] || (colors[value] = { count: 0, props: {} });
      entry.count++;
      entry.props[prop] = (entry.props[prop] || 0) + 1;
    }

    const family = (cs.fontFamily || "").split(",")[0].replace(/["']/g, "").trim();
    if (family) {
      const entry = fonts[family] || (fonts[family] = {
        count: 0, sizes: {}, weights: {}, headings: 0, body: 0,
      });
      entry.count++;
      bump(entry.sizes, cs.fontSize);
      bump(entry.weights, String(cs.fontWeight));
      if (/^H[1-6]$/.test(el.tagName)) entry.headings++;
      if (el.tagName === "P" || el.tagName === "LI") entry.body++;
    }

    bump(sizes, cs.fontSize);
    bump(weights, String(cs.fontWeight));
    for (const prop of PADDING_PROPS) bump(padding, cs[prop]);
    for (const prop of MARGIN_PROPS) bump(margin, cs[prop]);
    bump(radii, cs.borderTopLeftRadius);
    if (cs.boxShadow && cs.boxShadow !== "none") bump(shadows, cs.boxShadow);

    if (el.tagName === "IMG" && el.currentSrc) {
      images.push({
        src: el.currentSrc,
        w: el.naturalWidth || 0,
        h: el.naturalHeight || 0,
        alt: el.alt || "",
      });
    }
    const bg = cs.backgroundImage;
    if (bg && bg !== "none" && bg.startsWith("url(")) {
      const match = bg.match(/url\\((['"]?)(.*?)\\1\\)/);
      if (match && match[2]) backgrounds.add(match[2]);
    }
  }

  return {
    url: location.href,
    title: document.title || "",
    elements: counted,
    colors,
    fonts,
    sizes,
    weights,
    padding,
    margin,
    radii,
    shadows,
    images: images.slice(0, 200),
    backgrounds: Array.from(backgrounds).slice(0, 200),
  };
}
""".replace("%MAX%", str(_MAX_ELEMENTS))


async def collect_snapshot(page: Any) -> dict[str, Any]:
    """Run the counting pass on a Playwright page and return its raw result."""
    return await page.evaluate(_COLLECT_JS)


# ── interpretation (pure) ───────────────────────────────────────────────────────


def parse_color(value: str) -> tuple[str, float] | None:
    """Convert a computed CSS colour to ``(hex, alpha)``, or ``None`` if unreadable.

    Chromium reports ``rgb(r, g, b)`` / ``rgba(r, g, b, a)`` for the values this
    module asks about. Anything else (``color(srgb …)``, gradients, ``currentColor``)
    returns ``None`` and is counted as unreadable rather than guessed at.
    """
    match = _RGB_RE.fullmatch((value or "").strip())
    if match is None:
        return None

    channels = tuple(
        max(0, min(255, int(round(float(match.group(index)))))) for index in (1, 2, 3)
    )
    alpha_raw = match.group(4)
    if alpha_raw is None:
        alpha = 1.0
    elif alpha_raw.endswith("%"):
        alpha = float(alpha_raw[:-1]) / 100
    else:
        alpha = float(alpha_raw)

    return "#%02X%02X%02X" % channels, alpha


def _channels(hex_color: str) -> tuple[float, float, float]:
    """RGB channels of a ``#RRGGBB`` colour, each 0.0–1.0."""
    raw = hex_color.lstrip("#")
    return tuple(int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _rank(
    counts: dict[str, int],
    *,
    drop_zero: bool = False,
    limit: int = _MAX_ENTRIES,
) -> list[tuple[str, int]]:
    """Sort a ``value -> count`` map by count, descending, with a stable tie-break.

    The tie-break is the value itself so two runs over the same page produce the same
    order; without it the ranking of equally-used values would vary between runs.
    """
    zero = ("0px", "0")
    items = [
        (value, count)
        for value, count in counts.items()
        if not (drop_zero and value in zero)
    ]
    items.sort(key=lambda item: (-item[1], item[0]))
    return items[:limit]


def _family_names(counts: dict[str, int]) -> list[FontUse]:
    """Build the font ranking, most used family first."""
    fonts = [
        FontUse(
            family=family,
            count=entry.get("count", 0),
            sizes=dict(sorted(entry.get("sizes", {}).items(), key=lambda kv: -kv[1])),
            weights=dict(sorted(entry.get("weights", {}).items(), key=lambda kv: -kv[1])),
            headings=entry.get("headings", 0),
            body=entry.get("body", 0),
        )
        for family, entry in counts.items()
    ]
    fonts.sort(key=lambda font: (-font.count, font.family))
    return fonts


def assign_roles(palette: list[ColorUse]) -> None:
    """Label the most-used colours ``primary`` / ``secondary`` / ``accent``, in place.

    The rule, stated so it can be argued with: the most used colour is the
    ``primary`` (on most pages that is the page or text colour); the most used
    *saturated* colour that is not the primary is the ``accent``; the next saturated
    one is the ``secondary``. Neutrals never take the accent role, which is what
    keeps a grey-heavy page from reporting grey as its brand colour.
    """
    if not palette:
        return

    palette[0].role = "primary"

    saturated = [color for color in palette[1:] if color.saturation >= _NEUTRAL_SATURATION]
    for role, color in zip(("accent", "secondary"), saturated):
        color.role = role


def extract_tokens(snapshot: dict[str, Any]) -> DesignTokens:
    """Turn a :func:`collect_snapshot` result into :class:`DesignTokens`."""
    palette: list[ColorUse] = []
    unreadable = 0

    for raw, entry in (snapshot.get("colors") or {}).items():
        parsed = parse_color(raw)
        if parsed is None:
            unreadable += entry.get("count", 0)
            continue
        hex_color, alpha = parsed
        if alpha <= 0.05:
            # Fully transparent: a placeholder, not a colour anyone sees.
            continue
        palette.append(
            ColorUse(
                hex=hex_color,
                count=entry.get("count", 0),
                properties=dict(entry.get("props", {})),
            )
        )

    # Two rgba() spellings of the same colour collapse to one hex; sum their counts.
    merged: dict[str, ColorUse] = {}
    for color in palette:
        seen = merged.get(color.hex)
        if seen is None:
            merged[color.hex] = color
            continue
        seen.count += color.count
        for prop, count in color.properties.items():
            seen.properties[prop] = seen.properties.get(prop, 0) + count

    palette = sorted(merged.values(), key=lambda color: (-color.count, color.hex))[:_MAX_ENTRIES]
    assign_roles(palette)

    assets = [
        AssetRef(
            url=str(item.get("src", "")),
            kind="img",
            width=int(item.get("w") or 0),
            height=int(item.get("h") or 0),
            alt=str(item.get("alt") or ""),
        )
        for item in snapshot.get("images") or []
        if item.get("src")
    ]
    assets += [
        AssetRef(url=str(url), kind="background")
        for url in snapshot.get("backgrounds") or []
        if url
    ]

    return DesignTokens(
        url=str(snapshot.get("url", "")),
        title=str(snapshot.get("title", "")),
        element_count=int(snapshot.get("elements") or 0),
        palette=palette,
        fonts=_family_names(snapshot.get("fonts") or {}),
        font_sizes=_rank(snapshot.get("sizes") or {}),
        font_weights=_rank(snapshot.get("weights") or {}),
        padding=_rank(snapshot.get("padding") or {}, drop_zero=True, limit=12),
        margin=_rank(snapshot.get("margin") or {}, drop_zero=True, limit=12),
        radii=_rank(snapshot.get("radii") or {}, limit=12),
        shadows=_rank(snapshot.get("shadows") or {}, limit=8),
        assets=assets[:_MAX_ENTRIES],
        unreadable_colors=unreadable,
    )


# ── rendering ───────────────────────────────────────────────────────────────────


def _table(rows: list[tuple[str, int]], limit: int) -> str:
    return " · ".join(f"`{value}` ×{count}" for value, count in rows[:limit]) or "—"


def tokens_to_markdown(tokens: DesignTokens) -> str:
    """A compact report — what a person reads instead of the JSON."""
    lines = [
        f"# Design tokens — {tokens.title or tokens.url}",
        "",
        f"Fonte: {tokens.url}",
        f"Elementos analisados: {tokens.element_count}",
        "",
        "## Paleta",
        "",
    ]

    for color in tokens.palette[:12]:
        role = f" · *{color.role}*" if color.role else ""
        where = ", ".join(sorted(color.properties, key=lambda p: -color.properties[p])[:2])
        lines.append(f"- `{color.hex}` ×{color.count}{role} — {where}")

    lines += ["", "## Typography", ""]
    for font in tokens.fonts[:6]:
        sizes = ", ".join(f"{size}×{count}" for size, count in list(font.sizes.items())[:4]) or "—"
        weights = ", ".join(font.weights.keys()) or "—"
        where = []
        if font.headings:
            where.append(f"{font.headings} heading(s)")
        if font.body:
            where.append(f"{font.body} body")
        suffix = f" ({', '.join(where)})" if where else ""
        lines.append(f"- **{font.family}**{suffix} — tamanhos: {sizes} · pesos: {weights}")

    lines += [
        "",
        "## Scale and measures",
        "",
        f"- Font sizes: {_table(tokens.font_sizes, 8)}",
        f"- Weights: {_table(tokens.font_weights, 6)}",
        f"- Padding: {_table(tokens.padding, 8)}",
        f"- Margin: {_table(tokens.margin, 8)}",
        f"- Radii: {_table(tokens.radii, 8)}",
        f"- Shadows: {_table(tokens.shadows, 4)}",
    ]

    if tokens.assets:
        lines += ["", "## Assets", ""]
        for asset in tokens.assets[:12]:
            size = f" ({asset.width}×{asset.height})" if asset.width else ""
            label = f" — {asset.alt}" if asset.alt else ""
            lines.append(f"- `{asset.url}`{size} [{asset.kind}]{label}")

    if tokens.unreadable_colors:
        lines += [
            "",
            f"> {tokens.unreadable_colors} color use(s) in unsupported syntax "
            "(e.g., `color(srgb …)`) were left out of the palette.",
        ]

    return "\n".join(lines) + "\n"


def tokens_to_json(tokens: DesignTokens) -> str:
    """The JSON sidecar, written next to the markdown."""
    return json.dumps(tokens.to_dict(), ensure_ascii=False, indent=2) + "\n"


__all__ = [
    "AssetRef",
    "ColorUse",
    "DesignTokens",
    "FontUse",
    "assign_roles",
    "collect_snapshot",
    "extract_tokens",
    "parse_color",
    "tokens_to_json",
    "tokens_to_markdown",
]
