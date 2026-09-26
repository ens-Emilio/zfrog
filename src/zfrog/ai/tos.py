"""Robots.txt and Terms-of-Service signal checker.

Answers one question before or after a crawl: does this site *look* like it
restricts automated collection, and what is the evidence? Every finding quotes
the rule line or the sentence it came from, so the user can read the source and
judge for themselves.

**This is an automated aid, not legal advice.** It reads public documents
(``robots.txt`` and the Terms/Privacy page linked from the homepage) and reports
what they say; interpretation, jurisdiction and authorisation are the user's
call. Both this docstring and every returned summary say so.

Risk rule — the only thing ``risk`` means here:

* any ``blocking`` finding -> ``restricted``
* otherwise any ``warning`` finding -> ``caution``
* otherwise -> ``clear``

An ``info`` finding (a ``Crawl-delay``, the legal notice itself) never raises
the risk: absence of rules is not a restriction.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from zfrog.utils.text import extract_text

logger = logging.getLogger(__name__)

# Where robots.txt lives on any host, and how long we are willing to wait.
ROBOTS_PATH = "/robots.txt"
HTTP_TIMEOUT = 20.0

# Bounded quotes: a legal page has sentences that would swamp a terminal table,
# and a failed fetch has an exception text that does not belong in a webhook.
MAX_EVIDENCE_CHARS = 240
MAX_ERROR_CHARS = 200

# Worst first: this is the sort order of the findings.
SEVERITY_ORDER = {"blocking": 0, "warning": 1, "info": 2}
RISK_LABELS = {
    "restricted": "Conteúdo restrito para coleta automatizada",
    "caution": "Coleta automatizada exige atenção",
    "clear": "Nenhuma restrição aparente para coleta automatizada",
}

# Crawlers that collect content for AI training/inference. A robots.txt that
# singles them out is a deliberate signal, hence a warning even when the
# wildcard group is permissive.
AI_CRAWLERS = ("gptbot", "ccbot", "google-extended", "anthropic-ai")

LEGAL_NOTICE = (
    "Esta é uma leitura automática dos termos e do robots.txt; "
    "não constitui orientação jurídica."
)


@dataclass
class TosFinding:
    """One signal, with the text it came from."""

    kind: str
    severity: str  # "info" | "warning" | "blocking"
    detail: str
    evidence: str  # the rule line or sentence that triggered this
    source: str = ""  # URL the evidence came from


@dataclass
class TosReport:
    """Everything the checker could tell about one site."""

    url: str
    findings: list[TosFinding] = field(default_factory=list)
    risk: str = "clear"  # "clear" | "caution" | "restricted"
    summary: str = ""
    error: str | None = None

def _fold(text: str) -> str:
    """Lowercase, accent-stripped, whitespace-collapsed form used for matching."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.lower().split())


def _trim(text: str, limit: int = MAX_EVIDENCE_CHARS) -> str:
    """Whitespace-collapsed text, bounded to ``limit`` chars (head and tail)."""
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    half = limit // 2
    return f"{collapsed[:half]} […] {collapsed[-half:]}"


def _order(findings: list[TosFinding]) -> list[TosFinding]:
    """Sort findings by severity, worst first (stable within a severity)."""
    return sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.severity, len(SEVERITY_ORDER)))


def _dedupe(findings: list[TosFinding]) -> list[TosFinding]:
    """Drop findings that repeat a ``(kind, evidence)`` pair already seen."""
    seen: set[tuple[str, str]] = set()
    unique: list[TosFinding] = []
    for finding in findings:
        key = (finding.kind, finding.evidence)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def _risk(findings: list[TosFinding]) -> str:
    """Worst severity wins: blocking -> restricted, warning -> caution, else clear."""
    if any(f.severity == "blocking" for f in findings):
        return "restricted"
    if any(f.severity == "warning" for f in findings):
        return "caution"
    return "clear"


def _summary(url: str, risk: str, findings: list[TosFinding]) -> str:
    """One user-facing paragraph: verdict, counts, and the legal-advice caveat."""
    counts = Counter(f.severity for f in findings)
    parts = [f"{RISK_LABELS.get(risk, risk)} — {url or 'documento informado'}: {len(findings)} sinal(is)."]
    if counts:
        detail = ", ".join(f"{counts[sev]} {sev}" for sev in ("blocking", "warning", "info") if counts[sev])
        parts.append(f"Gravidade: {detail}.")
    else:
        parts.append("Nenhum sinal de restrição encontrado nos documentos analisados.")
    parts.append(LEGAL_NOTICE)
    return " ".join(parts)


def _build(url: str, findings: list[TosFinding], error: str | None = None) -> TosReport:
    """Deduplicate, sort and score a set of findings into a report."""
    ordered = _dedupe(_order(findings))
    risk = _risk(ordered)
    return TosReport(url=url, findings=ordered, risk=risk, summary=_summary(url, risk, ordered), error=error)


def _path_of(url: str) -> str:
    """Path component of ``url``, defaulting to ``/`` when there is none."""
    try:
        return urlparse(url or "").path or "/"
    except ValueError:  # malformed URL (e.g. broken IPv6 literal)
        return "/"


def _error_text(errors: list[str]) -> str | None:
    """Join fetch failures into one bounded line, or ``None`` when there were none."""
    if not errors:
        return None
    return _trim("; ".join(errors), MAX_ERROR_CHARS)

@dataclass(frozen=True)
class _RobotsGroup:
    """One ``User-agent`` block: the agents it applies to and its directives."""

    agents: tuple[str, ...]
    rules: tuple[tuple[str, str, str], ...]  # (directive, value, raw line)


def _parse_robots(robots_txt: str) -> list[_RobotsGroup]:
    """Parse robots.txt into agent groups without fetching anything.

    Comments are stripped, directive names are lowercased, and a ``User-agent``
    line that follows rules starts a new group (the consecutive-agent form of
    the standard). Directives appearing before any ``User-agent`` are ignored.
    """
    groups: list[_RobotsGroup] = []
    agents: list[str] = []
    rules: list[tuple[str, str, str]] = []

    def flush() -> None:
        nonlocal agents, rules
        if agents:
            groups.append(_RobotsGroup(tuple(agents), tuple(rules)))
        agents, rules = [], []

    for raw in (robots_txt or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        name = name.strip().lower()
        if name == "user-agent":
            if rules:  # a new agent after rules begins a new group
                flush()
            agents.append(value.strip().lower())
            continue
        if agents:
            rules.append((name, value.strip(), line))
    flush()
    return groups


def _rule_matches(path: str, rule: str) -> bool:
    """Robots.txt prefix matching, with ``*`` wildcards and a trailing ``$``."""
    if not rule:
        return False  # an empty Disallow means "nothing is disallowed"
    anchored = rule.endswith("$")
    pattern = rule[:-1] if anchored else rule
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
    return re.match(regex + ("$" if anchored else ""), path) is not None


def _matching_rule(rules: tuple[tuple[str, str, str], ...], path: str) -> tuple[str, str, str] | None:
    """Most specific rule for ``path``; the longest rule wins and Allow breaks ties."""
    best: tuple[tuple[int, bool], tuple[str, str, str]] | None = None
    for directive, value, raw in rules:
        if directive not in ("allow", "disallow") or not _rule_matches(path, value):
            continue
        rank = (len(value.rstrip("$")), directive == "allow")
        if best is None or rank > best[0]:
            best = (rank, (directive, value, raw))
    return best[1] if best else None


def _robots_source(base_url: str) -> str:
    """Absolute URL of the robots.txt the signals would have come from."""
    return urljoin(base_url or "", ROBOTS_PATH)


def robots_signals(base_url: str, robots_txt: str, path: str = "/") -> list[TosFinding]:
    """Find restriction signals in an already-fetched robots.txt.

    Args:
        base_url: Site URL, used to fill ``TosFinding.source``.
        robots_txt: Raw robots.txt content (empty is valid and yields nothing).
        path: Path being checked, e.g. ``/`` or ``/private``.

    Returns:
        Findings sorted by severity: a wildcard block on the whole site or on
        ``path`` (``blocking``), a ``Disallow`` aimed at a known AI crawler
        (``warning``) and any ``Crawl-delay`` (``info``).
    """
    findings: list[TosFinding] = []
    groups = _parse_robots(robots_txt)
    if not groups:
        return findings

    source = _robots_source(base_url)
    target = path or "/"
    if not target.startswith("/"):
        target = f"/{target}"

    for group in groups:
        if "*" in group.agents:
            matched = _matching_rule(group.rules, target)
            if matched and matched[0] == "disallow":
                value, raw = matched[1], matched[2]
                if value == "/":
                    kind = "robots_block_all"
                    detail = "robots.txt proíbe o acesso de qualquer crawler a todo o site."
                else:
                    kind = "robots_disallow_path"
                    detail = f"robots.txt proíbe o acesso de qualquer crawler a {value}."
                findings.append(TosFinding(kind, "blocking", detail, raw, source))
        bots = [bot for bot in AI_CRAWLERS if bot in group.agents]
        if bots:
            matched = _matching_rule(group.rules, target)
            if matched and matched[0] == "disallow":
                detail = f"robots.txt bloqueia crawlers de IA: {', '.join(bots)}."
                findings.append(TosFinding("ai_crawler_disallow", "warning", detail, matched[2], source))
        for directive, value, raw in group.rules:
            if directive == "crawl-delay" and value:
                detail = f"robots.txt pede um intervalo de {value} entre requisições."
                findings.append(TosFinding("crawl_delay", "info", detail, raw, source))

    return _dedupe(_order(findings))

@dataclass(frozen=True)
class _Phrase:
    """A Terms-of-Service phrase to look for.

    ``terms`` are folded (lowercase, no accents) because matching runs on folded
    sentences, which makes the search accent-insensitive. Every string in
    ``requires`` must appear in the *same sentence* — used for phrases that only
    mean something together, e.g. "all rights reserved" alone is in every footer
    but "all rights reserved" + "reproduction" is a restriction.
    """

    kind: str
    severity: str
    detail: str
    terms: tuple[str, ...]
    requires: tuple[str, ...] = ()


# Portuguese and English wording that restricts automated collection.
_PHRASES = (
    _Phrase(
        kind="automated_collection_prohibited",
        severity="blocking",
        detail="Os termos proíbem coleta automatizada (robôs, scraping ou mineração de dados).",
        terms=(
            "proibido o uso de robos",
            "proibido o uso de bots",
            "proibido scraping",
            "no scraping",
            "automated means",
            "meios automatizados",
            "data mining",
            "mineracao de dados",
        ),
    ),
    _Phrase(
        kind="unauthorized_reproduction",
        severity="warning",
        detail="Os termos restringem a reprodução do conteúdo sem autorização.",
        terms=("reproducao nao autorizada", "reproducao proibida"),
    ),
    _Phrase(
        kind="copyright_reproduction",
        severity="warning",
        detail="Os termos reservam os direitos de reprodução do conteúdo.",
        terms=("reproduction",),
        requires=("all rights reserved",),
    ),
    _Phrase(
        kind="rate_limit",
        severity="warning",
        detail="Os termos impõem limite de requisições.",
        terms=("rate limit", "limite de requisicoes", "limites de requisicoes"),
    ),
    _Phrase(
        kind="account_termination",
        severity="warning",
        detail="Os termos preveem encerramento da conta por uso automatizado.",
        terms=("conta sera encerrada", "conta podera ser encerrada", "terminate your account"),
    ),
)

# Sentences end on punctuation or a line break; extract_text collapses runs of
# whitespace, so in practice only punctuation separates them.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")


def _sentences(text: str) -> list[str]:
    """Split text into trimmed, non-empty sentences."""
    return [part.strip() for part in _SENTENCE_SPLIT.split(text or "") if part.strip()]


def terms_signals(html: str, url: str) -> list[TosFinding]:
    """Find restriction signals in the text of a Terms/legal page.

    Args:
        html: Raw HTML of the legal page (or of the homepage as a fallback).
        url: URL that HTML came from, stored as each finding's ``source``.

    Returns:
        One finding per matching sentence (severity by phrase), plus the
        ``legal_notice`` info finding that states this is not legal advice.
    """
    findings: list[TosFinding] = []
    for sentence in _sentences(extract_text(html)):
        folded = _fold(sentence)
        if not folded:
            continue
        for phrase in _PHRASES:
            if not any(term in folded for term in phrase.terms):
                continue
            if any(required not in folded for required in phrase.requires):
                continue
            findings.append(
                TosFinding(phrase.kind, phrase.severity, phrase.detail, _trim(sentence), url)
            )
    findings.append(
        TosFinding(
            kind="legal_notice",
            severity="info",
            detail="Verificação automática dos documentos; não substitui orientação jurídica.",
            evidence=LEGAL_NOTICE,
            source=url,
        )
    )
    return _dedupe(_order(findings))

# Link keywords that mark a Terms/Privacy page. Folded, so "condições" matches
# "condicoes" and "Privacidade" matches "privacidade".
_TERMS_KEYWORDS = ("termos", "terms", "legal", "condicoes", "privacidade", "privacy")

# Non-navigational hrefs never point at a legal page.
_DEAD_HREFS = ("#", "javascript:", "mailto:", "tel:")


def find_terms_url(html: str, base_url: str) -> str | None:
    """Locate the Terms/Privacy link of a page and resolve it against the base.

    Args:
        html: Raw HTML of the page (usually the homepage).
        base_url: URL the HTML came from, used to resolve relative hrefs.

    Returns:
        Absolute URL of the first matching link, or ``None`` when there is none.
    """
    if not html or not html.strip():
        return None
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        logger.debug("HTML ilegível ao procurar o link de termos")
        return None
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.lower().startswith(_DEAD_HREFS):
            continue
        label = _fold(anchor.get_text(" ", strip=True))
        target = _fold(href)
        if any(keyword in label or keyword in target for keyword in _TERMS_KEYWORDS):
            return urljoin(base_url or "", href)
    return None


def check_text(html: str, robots_txt: str = "", url: str = "") -> TosReport:
    """Check documents that were already fetched — no network access.

    Args:
        html: HTML of the legal page (or homepage).
        robots_txt: Raw robots.txt; empty means "no robots signals to report".
        url: URL the documents came from; its path is the one checked in robots.

    Returns:
        A report whose findings are deduplicated and sorted by severity.
    """
    findings: list[TosFinding] = []
    if robots_txt and robots_txt.strip():
        findings.extend(robots_signals(url, robots_txt, _path_of(url)))
    findings.extend(terms_signals(html, url))
    return _build(url, findings)

async def _get_text(
    client: httpx.AsyncClient,
    url: str,
    label: str,
    errors: list[str],
    tolerate_missing: bool = False,
) -> str:
    """Fetch ``url`` and return its text, recording failures in ``errors``.

    With ``tolerate_missing`` a non-200 response is normal and silent (used for
    robots.txt, where a 404 just means the site has no rules); without it the
    status is reported. Network errors are always reported and never raised.
    """
    try:
        response = await client.get(url)
    except Exception as exc:  # DNS, TLS, timeout, malformed URL: all just signals
        logger.debug("Falha ao buscar %s: %s", url, exc)
        errors.append(f"{label}: {exc}")
        return ""
    if response.status_code == 200:
        return response.text
    if tolerate_missing:
        logger.debug("Sem conteúdo em %s (HTTP %s)", url, response.status_code)
    else:
        errors.append(f"{label}: HTTP {response.status_code}")
    return ""


async def check_site(url: str, fetch_terms: bool = True) -> TosReport:
    """Check a live site's robots.txt and (optionally) its Terms page.

    Best effort by design: robots.txt is fetched first and a missing one is
    normal, then the homepage is fetched to locate the Terms/Privacy link. When
    no such link exists — or it cannot be fetched — the homepage text itself is
    scanned instead, because footers often carry the wording.

    Args:
        url: Site URL to check.
        fetch_terms: Whether to fetch and scan the legal page at all.

    Returns:
        A report with everything that was found; ``error`` holds a bounded
        description of the fetches that failed. This function never raises.
    """
    findings: list[TosFinding] = []
    errors: list[str] = []
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=HTTP_TIMEOUT) as client:
            robots_txt = await _get_text(
                client, _robots_source(url), "robots.txt", errors, tolerate_missing=True
            )
            if robots_txt.strip():
                findings.extend(robots_signals(url, robots_txt, _path_of(url)))

            if fetch_terms:
                home = await _get_text(client, url, "página inicial", errors)
                if home:
                    terms_url = find_terms_url(home, url)
                    terms_html = ""
                    if terms_url:
                        terms_html = await _get_text(client, terms_url, "termos de uso", errors)
                    if terms_html:
                        findings.extend(terms_signals(terms_html, terms_url))
                    else:
                        findings.extend(terms_signals(home, url))
    except Exception as exc:  # nothing below may escape: callers show this to users
        logger.warning("Falha ao verificar %s: %s", url, exc)
        errors.append(f"verificação: {exc}")
    return _build(url, findings, _error_text(errors))
