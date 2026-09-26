"""Safety scan for cloned content.

A clone is opened by a human, usually offline, often with no browser sandbox
between them and a hostile page. This module looks for the markers that mean
"do not open this": hidden iframes, credential forms posting off-site, miner
scripts, obfuscated loaders, dangerous URL schemes and downloads.

Everything here is static and local — no network, no execution — so scanning a
clone is as safe as reading it. The output is a :class:`SafetyReport` whose
``risk`` is the worst thing found, which the CLI/API can turn into a warning.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Severities, worst first: used to rank findings and to pick the report risk.
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_SEVERITY_RANK = ("high", "medium", "low")

# Miner markers, matched case-insensitively against the raw markup.
_MINER_MARKERS = (
    "coinhive",
    "cryptonight",
    "CoinHive.Anonymous",
    "webminepool",
    "minero.cc",
)

# TLDs with a well-earned reputation for abuse.
_BAD_TLDS = ("tk", "ml", "ga", "cf", "gq", "top", "xyz")

# Extensions that mean "this link downloads something executable".
_DOWNLOAD_EXTENSIONS = (".exe", ".scr", ".js", ".vbs", ".bat", ".cmd", ".jar")

# Public suffixes that make a domain three labels long (foo.com.br).
_SECOND_LEVEL = ("com", "co", "net", "org", "gov", "edu")

# Schemes that address something other than a host.
_NON_NETWORK_SCHEMES = (
    "mailto",
    "javascript",
    "data",
    "tel",
    "sms",
    "callto",
    "about",
    "blob",
    "file",
    "intent",
    "market",
)

_OBFUSCATED_CALL = re.compile(r"\b(?:eval|Function)\s*\(", re.IGNORECASE)
_ESCAPED_HEX = re.compile(r"(?:\\x[0-9a-fA-F]{2}){8,}")
_ESCAPED_UNICODE = re.compile(r"(?:\\u[0-9a-fA-F]{4}){8,}")
_HEX_LITERAL = re.compile(r"0x[0-9a-fA-F]{16,}")
_FROM_CHAR_CODE = re.compile(r"String\.fromCharCode\s*\(([^()]*)\)", re.IGNORECASE)
_ATOB_EVAL = re.compile(r"eval\s*\(\s*(?:atob|unescape)\s*\(", re.IGNORECASE)
_JS_SCHEME = re.compile(r"javascript:|data:text/html", re.IGNORECASE)
_DANGEROUS_SCHEME = re.compile(r"^\s*(?:javascript:|data:text/html)", re.IGNORECASE)
_REFRESH_URL = re.compile(r"url\s*=\s*['\"]?([^'\"\s>]+)", re.IGNORECASE)
_NEGATIVE_OFFSET = re.compile(r"(?:left|top|margin-left|margin-top):-(\d{3,})")
_ZERO_DIMENSION = re.compile(r"(?:^|;)(?:width|height):0(?:px|em|rem|%)?(?:;|$)")

_MIN_FROM_CHAR_CODE_ARGS = 8


@dataclass
class Finding:
    """One suspicious thing found in one file."""

    kind: str
    severity: str
    file: str
    detail: str
    evidence: str


@dataclass
class SafetyReport:
    """Result of scanning a directory."""

    files_scanned: int
    findings: list[Finding] = field(default_factory=list)
    risk: str = "clean"
    summary: str = ""


# --------------------------------------------------------------------------- #
# Domains
# --------------------------------------------------------------------------- #

def domain_of(url: str) -> str:
    """Reduce a URL to its registrable-ish domain.

    Lowercases the host, drops a leading ``www.`` and keeps the last two labels
    — or three when the second-to-last is a public suffix such as ``com``
    (``foo.com.br``). Ports, userinfo and paths are ignored; relative URLs have
    no domain and return ``""``.

    Args:
        url: Absolute or relative URL.

    Returns:
        The domain, or ``""`` when the URL is relative/unparseable.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.hostname and parsed.scheme.lower() not in _NON_NETWORK_SCHEMES:
        # Scheme-less absolute URL ("example.com/x", "example.com:8080/x") —
        # retry as a network path. A mailto:/javascript: URL is not a network
        # location and has no domain.
        parsed = urlparse("//" + raw)
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)
    if labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _crosses_domain(target: str, page_domain: str, *, unknown_is_external: bool) -> bool:
    """Whether ``target`` leaves the page's own domain.

    A relative target never crosses. When the page domain is unknown we cannot
    prove the target is same-site; ``unknown_is_external`` says how to read
    that, per detector (see the callers for why forms and refreshes differ).
    """
    target_domain = domain_of(target)
    if not target_domain:
        return False
    if not page_domain:
        return unknown_is_external
    return target_domain != page_domain


def _page_domain(soup: BeautifulSoup, page_url: str = "") -> str:
    """Best-effort domain of the page itself.

    Prefers the caller-supplied URL (``scan_directory`` knows where the clone
    came from), then the document's own ``<base>``, canonical link and
    ``og:url``.
    """
    candidates = [page_url]
    base = soup.find("base", href=True)
    if base:
        candidates.append(str(base.get("href") or ""))
    for link in soup.find_all("link", href=True):
        rel = link.get("rel") or []
        rels = [str(item).lower() for item in (rel if isinstance(rel, list) else [rel])]
        if "canonical" in rels:
            candidates.append(str(link.get("href") or ""))
    for meta in soup.find_all("meta", content=True):
        prop = str(meta.get("property") or meta.get("name") or "").lower()
        if prop in ("og:url", "twitter:url"):
            candidates.append(str(meta.get("content") or ""))
    for candidate in candidates:
        found = domain_of(candidate)
        if found:
            return found
    return ""


# --------------------------------------------------------------------------- #
# Detectors
# --------------------------------------------------------------------------- #

def _finding(kind: str, severity: str, file: str, detail: str, evidence: str) -> Finding:
    return Finding(kind=kind, severity=severity, file=file, detail=detail, evidence=evidence)


def _scan_markers(text: str, file: str) -> list[Finding]:
    """Known miner markers anywhere in the markup (attributes included)."""
    lowered = text.lower()
    found = []
    for marker in _MINER_MARKERS:
        if marker.lower() in lowered:
            found.append(
                _finding(
                    "crypto_miner",
                    "high",
                    file,
                    f"Marcador de minerador de criptomoedas: {marker}",
                    marker,
                )
            )
    return found


def _scan_obfuscation(code: str, file: str) -> list[Finding]:
    """``eval``/``Function`` over long escapes, or big fromCharCode chains."""
    found: list[Finding] = []
    call = _OBFUSCATED_CALL.search(code)
    if call:
        escaped = (
            _ESCAPED_HEX.search(code)
            or _ESCAPED_UNICODE.search(code)
            or _HEX_LITERAL.search(code)
        )
        if escaped:
            found.append(
                _finding(
                    "obfuscated_js",
                    "medium",
                    file,
                    "Chamada dinâmica com string codificada (código ofuscado)",
                    f"{call.group().strip()} {escaped.group()[:60]}",
                )
            )
    for chain in _FROM_CHAR_CODE.finditer(code):
        arguments = [part for part in chain.group(1).split(",") if part.strip()]
        if len(arguments) >= _MIN_FROM_CHAR_CODE_ARGS:
            found.append(
                _finding(
                    "obfuscated_js",
                    "medium",
                    file,
                    "Cadeia String.fromCharCode montando texto em tempo de execução",
                    f"String.fromCharCode({len(arguments)} argumentos)",
                )
            )
            break
    return found


def _scan_atob_eval(code: str, file: str) -> list[Finding]:
    """``eval(atob(...))`` / ``eval(unescape(...))`` — the classic loader."""
    match = _ATOB_EVAL.search(code)
    if not match:
        return []
    return [
        _finding(
            "atob_eval",
            "high",
            file,
            "Código decodificado em base64 e executado dinamicamente",
            match.group().strip(),
        )
    ]


def _scan_js_schemes(code: str, file: str) -> list[Finding]:
    """``javascript:`` / ``data:text/html`` URLs inside a script."""
    match = _JS_SCHEME.search(code)
    if not match:
        return []
    return [
        _finding(
            "data_uri_script",
            "high",
            file,
            "URL com esquema perigoso embutido no script",
            match.group(),
        )
    ]


def scan_javascript(js: str, file: str = "") -> list[Finding]:
    """Scan a JavaScript source (file or inline ``<script>``).

    Args:
        js: JavaScript source.
        file: Path recorded in the findings.

    Returns:
        Deduplicated findings, worst severity first.
    """
    if not js or not js.strip():
        return []
    found: list[Finding] = []
    found += _scan_obfuscation(js, file)
    found += _scan_markers(js, file)
    found += _scan_js_schemes(js, file)
    found += _scan_atob_eval(js, file)
    return _finalize(found)


def _scan_iframes(soup: BeautifulSoup, file: str) -> list[Finding]:
    """Invisible iframes: zero size, hidden style, or a big negative offset."""
    found: list[Finding] = []
    for iframe in soup.find_all("iframe"):
        width = str(iframe.get("width") or "").strip()
        height = str(iframe.get("height") or "").strip()
        style = str(iframe.get("style") or "").lower().replace(" ", "")
        reasons: list[str] = []
        if width in ("0", "1") or height in ("0", "1"):
            reasons.append(f"dimensões {width or '?'}x{height or '?'}")
        if _ZERO_DIMENSION.search(style):
            reasons.append("dimensões zeradas no estilo")
        if "display:none" in style or "visibility:hidden" in style:
            reasons.append("estilo oculto")
        offset = _NEGATIVE_OFFSET.search(style)
        if offset:
            reasons.append(f"deslocamento negativo (-{offset.group(1)}px)")
        if reasons:
            found.append(
                _finding(
                    "iframe_hidden",
                    "medium",
                    file,
                    "Iframe invisível: " + ", ".join(reasons),
                    str(iframe)[:160],
                )
            )
    return found


def _scan_forms(soup: BeautifulSoup, file: str, page_domain: str) -> list[Finding]:
    """Forms that ship credentials off-site or over plain http."""
    found: list[Finding] = []
    for form in soup.find_all("form"):
        action = str(form.get("action") or "").strip()
        target_domain = domain_of(action)
        has_password = any(
            str(field.get("type") or "").strip().lower() == "password"
            for field in form.find_all("input")
        )
        reasons: list[str] = []
        if has_password and target_domain and action.lower().startswith("http://"):
            reasons.append("campo de senha enviado por http:// sem criptografia")
        # Only flag a cross-domain post when we know the page's own domain:
        # without it, a legitimate https login would look external.
        if _crosses_domain(action, page_domain, unknown_is_external=False):
            reasons.append(f"envio para outro domínio ({target_domain})")
        if reasons:
            found.append(
                _finding(
                    "form_exfil",
                    "high",
                    file,
                    "Formulário suspeito: " + "; ".join(reasons),
                    str(form)[:160],
                )
            )
    return found


def _scan_meta_refresh(soup: BeautifulSoup, file: str, page_domain: str) -> list[Finding]:
    """``<meta http-equiv="refresh">`` bouncing the visitor to another domain."""
    found: list[Finding] = []
    for meta in soup.find_all("meta"):
        if str(meta.get("http-equiv") or "").strip().lower() != "refresh":
            continue
        content = str(meta.get("content") or "")
        match = _REFRESH_URL.search(content)
        if not match:
            continue
        target = match.group(1)
        # A bare snippet has no page domain to compare against; an absolute
        # refresh target is then all the evidence there is, so it counts as
        # external.
        if _crosses_domain(target, page_domain, unknown_is_external=True):
            found.append(
                _finding(
                    "meta_refresh_external",
                    "medium",
                    file,
                    f"Redirecionamento automático para {target}",
                    str(meta)[:160],
                )
            )
    return found


def _scan_urls(soup: BeautifulSoup, file: str) -> list[Finding]:
    """Dangerous URL schemes, bad-TLD links and executable downloads."""
    found: list[Finding] = []
    for element in soup.find_all(href=True):
        href = str(element.get("href") or "").strip()
        if not href:
            continue
        if _DANGEROUS_SCHEME.match(href):
            found.append(
                _finding(
                    "data_uri_script",
                    "high",
                    file,
                    "URL com esquema perigoso em href",
                    href[:160],
                )
            )
            continue
        domain = domain_of(href)
        if domain and domain.rsplit(".", 1)[-1] in _BAD_TLDS:
            found.append(
                _finding(
                    "known_bad_tld",
                    "low",
                    file,
                    f"Link para domínio {domain} com TLD de alto risco",
                    href[:160],
                )
            )
        if _download_name(href).endswith(_DOWNLOAD_EXTENSIONS):
            found.append(
                _finding(
                    "suspicious_download",
                    "medium",
                    file,
                    "Link para download de arquivo executável",
                    href[:160],
                )
            )
    for element in soup.find_all(src=True):
        src = str(element.get("src") or "").strip()
        if src and _DANGEROUS_SCHEME.match(src):
            found.append(
                _finding(
                    "data_uri_script",
                    "high",
                    file,
                    "URL com esquema perigoso em src",
                    src[:160],
                )
            )
    return found


def _download_name(url: str) -> str:
    """Lowercased path of a URL, without query string or fragment."""
    return (urlparse(url).path or "").lower()


def scan_html(html: str, file: str = "", page_url: str = "") -> list[Finding]:
    """Scan one HTML document.

    Args:
        html: Markup to scan.
        file: Path recorded in the findings.
        page_url: URL the page was cloned from, used to tell "same site" from
            "elsewhere" for form actions and meta refreshes.

    Returns:
        Deduplicated findings, worst severity first.
    """
    if not html or not html.strip():
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        logger.warning("safety scan could not parse %s: %s", file or "<html>", exc)
        return []

    page_domain = _page_domain(soup, page_url)
    found: list[Finding] = []
    found += _scan_markers(html, file)
    for script in soup.find_all("script"):
        if script.get("src"):
            continue
        found += scan_javascript(script.string or script.get_text() or "", file)
    found += _scan_iframes(soup, file)
    found += _scan_forms(soup, file, page_domain)
    found += _scan_meta_refresh(soup, file, page_domain)
    found += _scan_urls(soup, file)
    return _finalize(found)


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

def _finalize(findings: list[Finding]) -> list[Finding]:
    """Deduplicate by ``(kind, file, evidence)`` and sort by severity."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[Finding] = []
    for item in findings:
        key = (item.kind, item.file, item.evidence)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return sorted(unique, key=lambda item: _SEVERITY_ORDER.get(item.severity, len(_SEVERITY_ORDER)))


def _risk_of(findings: list[Finding]) -> str:
    """Worst severity found, or ``clean`` when there is none."""
    if not findings:
        return "clean"
    for severity in _SEVERITY_RANK:
        if any(item.severity == severity for item in findings):
            return severity
    return "clean"


def _summary(risk: str, findings: int, files: int) -> str:
    return (
        f"Risco {risk}: {findings} indicador(es) de segurança em "
        f"{files} arquivo(s) inspecionado(s)."
    )


def scan_directory(dir_path: Path, url: str = "") -> SafetyReport:
    """Scan every ``*.html``/``*.js`` file of a cloned site.

    Args:
        dir_path: Root of the clone.
        url: URL the clone came from, used to compare form actions and meta
            refreshes against the site's own domain.

    Returns:
        A report whose ``risk`` is the worst severity found.
    """
    findings: list[Finding] = []
    files_scanned = 0
    for path in sorted(dir_path.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in (".html", ".js"):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("skipping %s: %s", path, exc)
            continue
        relative = path.relative_to(dir_path).as_posix()
        if suffix == ".html":
            findings += scan_html(content, relative, page_url=url)
        else:
            findings += scan_javascript(content, relative)
        files_scanned += 1

    findings = _finalize(findings)
    risk = _risk_of(findings)
    return SafetyReport(
        files_scanned=files_scanned,
        findings=findings,
        risk=risk,
        summary=_summary(risk, len(findings), files_scanned),
    )
