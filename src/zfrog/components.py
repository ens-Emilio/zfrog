"""Component extraction: the HTML and the *computed* CSS of one element.

This is the ``tongue`` of the design: point at a selector, get back the component —
its markup, the styles the browser actually resolved for it, and its position in the
box model. Nothing here guesses at intent; if a value did not resolve, it is reported
as empty rather than filled in with a plausible default.

Like :mod:`zfrog.tokens`, the browser side only collects and the interpretation is
pure, so the interesting part (:func:`summarize`) is testable without a browser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from zfrog.selector import sanitize_fragment

#: Properties worth reporting: everything that decides how the component *looks*.
#: Deliberately excludes the hundreds of inherited/reset properties Chromium also
#: resolves, which would bury the answer in noise.
STYLE_PROPERTIES = (
    # box
    "display",
    "position",
    "width",
    "height",
    "minWidth",
    "maxWidth",
    "margin",
    "padding",
    "boxSizing",
    "overflow",
    "flexDirection",
    "justifyContent",
    "alignItems",
    "gap",
    "gridTemplateColumns",
    # paint
    "backgroundColor",
    "backgroundImage",
    "backgroundSize",
    "color",
    "border",
    "borderRadius",
    "boxShadow",
    "opacity",
    "filter",
    "backdropFilter",
    # type
    "fontFamily",
    "fontSize",
    "fontWeight",
    "fontStyle",
    "lineHeight",
    "letterSpacing",
    "textAlign",
    "textDecoration",
    "textTransform",
    "whiteSpace",
    # interaction
    "cursor",
    "transition",
    "transform",
    "zIndex",
)

#: Defaults that carry no design decision. Reporting them would be noise, so a
#: property equal to its initial value is kept out of the summary — but it stays in
#: :attr:`ComponentExtract.computed`, so the full answer is still available.
_UNINTERESTING = {
    "position": {"static"},
    "opacity": {"1"},
    "filter": {"none"},
    "backdropFilter": {"none"},
    "transform": {"none"},
    "boxShadow": {"none"},
    "backgroundImage": {"none"},
    # A transparent background is not a design decision; reporting it as the
    # component's colour would read as "this element is black".
    "backgroundColor": {
        "rgba(0, 0, 0, 0)",
        "transparent",
        "rgba(255, 255, 255, 0)",
    },
    "color": {"rgba(0, 0, 0, 0)", "transparent"},
    "textDecoration": {"none solid rgb(0, 0, 0)", "none"},
    "textTransform": {"none"},
    "fontStyle": {"normal"},
    "letterSpacing": {"normal"},
    "overflow": {"visible"},
    "zIndex": {"auto"},
    "transition": {"all 0s ease 0s", "all"},
    "backgroundSize": {"auto"},
}

#: Properties that describe the *box* rather than the look; used by the summary.
_LAYOUT_PROPERTIES = (
    "display",
    "position",
    "width",
    "height",
    "margin",
    "padding",
    "gap",
    "borderRadius",
)

#: Properties that carry the visual identity.
_PAINT_PROPERTIES = (
    "backgroundColor",
    "color",
    "border",
    "boxShadow",
    "backgroundImage",
    "opacity",
)

#: Properties that carry the typography.
_TYPE_PROPERTIES = (
    "fontFamily",
    "fontSize",
    "fontWeight",
    "lineHeight",
    "letterSpacing",
    "textAlign",
    "textTransform",
)

#: Cap on the markup kept in the report. A component big enough to exceed this is
#: truncated with a marker rather than silently cut.
_MAX_HTML_CHARS = 20_000


@dataclass
class ComponentExtract:
    """One extracted element: markup, resolved styles, geometry and children."""

    url: str = ""
    selector: str = ""
    tag: str = ""
    label: str = ""
    html: str = ""
    text: str = ""
    computed: dict[str, str] = field(default_factory=dict)
    box: dict[str, float] = field(default_factory=dict)
    children: list[dict[str, str]] = field(default_factory=list)
    match_count: int = 1
    truncated: bool = False

    def interesting(self, properties: tuple[str, ...] | None = None) -> dict[str, str]:
        """The computed styles worth showing: the requested set, minus the defaults."""
        wanted = properties if properties is not None else STYLE_PROPERTIES
        out: dict[str, str] = {}
        for prop in wanted:
            value = self.computed.get(prop)
            if value and value not in _UNINTERESTING.get(prop, set()):
                out[prop] = value
        return out

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "url": self.url,
            "selector": self.selector,
            "tag": self.tag,
            "label": self.label,
            "match_count": self.match_count,
            "truncated": self.truncated,
            "box": self.box,
            "styles": self.interesting(),
            "computed": self.computed,
            "html": self.html,
            "text": self.text,
            "children": self.children,
        }


# ── browser side ────────────────────────────────────────────────────────────────

_COLLECT_JS = """
(args) => {
  const { selector, maxChildren, properties } = args;
  const nodes = document.querySelectorAll(selector);
  if (!nodes.length) return { found: false, count: 0 };
  const el = nodes[0];

  const cs = getComputedStyle(el);
  const computed = {};
  for (const prop of properties) computed[prop] = cs[prop];

  const rect = el.getBoundingClientRect();
  const box = {
    x: Math.round(rect.x), y: Math.round(rect.y),
    width: Math.round(rect.width), height: Math.round(rect.height),
  };

  const children = [];
  for (const child of el.children) {
    if (children.length >= maxChildren) break;
    const ccs = getComputedStyle(child);
    const cr = child.getBoundingClientRect();
    children.push({
      tag: child.tagName.toLowerCase(),
      cls: (typeof child.className === "string" ? child.className : "").slice(0, 120),
      text: (child.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 80),
      display: ccs.display,
      width: String(Math.round(cr.width)),
      height: String(Math.round(cr.height)),
    });
  }

  return {
    found: true,
    count: nodes.length,
    html: el.outerHTML,
    text: (el.innerText || "").trim().slice(0, 4000),
    tag: el.tagName.toLowerCase(),
    id: el.id || "",
    cls: (typeof el.className === "string" ? el.className : ""),
    computed,
    box,
    children,
  };
}
"""


async def collect_component(page: Any, selector: str, *, max_children: int = 24) -> dict[str, Any]:
    """Run the extraction pass on a Playwright page and return its raw result."""
    return await page.evaluate(
        _COLLECT_JS,
        {"selector": selector, "maxChildren": max_children, "properties": list(STYLE_PROPERTIES)},
    )


# ── interpretation (pure) ───────────────────────────────────────────────────────


def _label(raw: dict[str, Any]) -> str:
    """A short human name for the element: ``div.hero`` or ``button#submit``."""
    tag = str(raw.get("tag") or "")
    identifier = str(raw.get("id") or "").strip()
    classes = [part for part in str(raw.get("cls") or "").split() if part][:2]
    if identifier:
        return f"{tag}#{identifier}"
    return f"{tag}.{'.'.join(classes)}" if classes else tag


def build_extract(
    raw: dict[str, Any],
    *,
    url: str = "",
    selector: str = "",
) -> ComponentExtract | None:
    """Turn a :func:`collect_component` result into a :class:`ComponentExtract`.

    Returns ``None`` when the selector matched nothing, so callers can distinguish
    "no match" from "matched, but empty" without inspecting a sentinel field.
    """
    if not raw or not raw.get("found"):
        return None

    html = str(raw.get("html") or "")
    truncated = len(html) > _MAX_HTML_CHARS
    if truncated:
        html = html[:_MAX_HTML_CHARS] + "\n<!-- truncado -->"

    return ComponentExtract(
        url=url,
        selector=selector,
        tag=str(raw.get("tag") or ""),
        label=_label(raw),
        html=sanitize_fragment(html),
        text=str(raw.get("text") or ""),
        computed={str(k): str(v) for k, v in (raw.get("computed") or {}).items()},
        box={str(k): float(v) for k, v in (raw.get("box") or {}).items()},
        children=[
            {str(k): str(v) for k, v in child.items()} for child in (raw.get("children") or [])
        ],
        match_count=int(raw.get("count") or 1),
        truncated=truncated,
    )


def summarize(component: ComponentExtract) -> dict[str, dict[str, str]]:
    """Group the interesting styles into ``layout`` / ``paint`` / ``typography``.

    A property can appear in more than one group on purpose — ``borderRadius`` is both
    a box measurement and part of the look — because the groups answer different
    questions ("how is it laid out?" vs "what does it look like?").
    """
    return {
        "layout": component.interesting(_LAYOUT_PROPERTIES),
        "paint": component.interesting(_PAINT_PROPERTIES),
        "typography": component.interesting(_TYPE_PROPERTIES),
    }


# ── rendering ───────────────────────────────────────────────────────────────────


def _pairs(styles: dict[str, str], limit: int = 20) -> str:
    return " · ".join(f"`{prop}: {value}`" for prop, value in list(styles.items())[:limit]) or "—"


def component_to_markdown(component: ComponentExtract) -> str:
    """The component as a report: geometry, styles by group, children, markup."""
    groups = summarize(component)
    box = component.box

    lines = [
        f"# Componente — {component.label}",
        "",
        f"Fonte: {component.url}",
        f"Seletor: `{component.selector}`"
        + (f" — {component.match_count} correspondência(s), extraída a primeira"
           if component.match_count > 1 else ""),
        "",
        "## Caixa",
        "",
        f"{int(box.get('width', 0))}×{int(box.get('height', 0))} px"
        f" em ({int(box.get('x', 0))}, {int(box.get('y', 0))})",
        "",
        "## Layout",
        "",
        _pairs(groups["layout"]),
        "",
        "## Cor e superfície",
        "",
        _pairs(groups["paint"]),
        "",
        "## Tipografia",
        "",
        _pairs(groups["typography"]),
    ]

    if component.children:
        lines += ["", "## Filhos diretos", ""]
        for child in component.children[:20]:
            cls = f".{child['cls'].split()[0]}" if child.get("cls") else ""
            text = f" — {child['text'][:50]}" if child.get("text") else ""
            lines.append(
                f"- `{child['tag']}{cls}` ({child.get('display', '?')}, "
                f"{child.get('width', '?')}×{child.get('height', '?')}){text}"
            )

    lines += ["", "## HTML", "", "```html", component.html.strip(), "```"]
    if component.truncated:
        lines += ["", f"> Markup truncado em {_MAX_HTML_CHARS} caracteres."]

    return "\n".join(lines) + "\n"


def component_to_json(component: ComponentExtract) -> str:
    """The JSON sidecar, written next to the markdown."""
    return json.dumps(component.to_dict(), ensure_ascii=False, indent=2) + "\n"


__all__ = [
    "STYLE_PROPERTIES",
    "ComponentExtract",
    "build_extract",
    "collect_component",
    "component_to_json",
    "component_to_markdown",
    "summarize",
]
