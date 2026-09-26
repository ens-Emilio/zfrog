"""Tests for the robots.txt / Terms-of-Service signal checker."""

from __future__ import annotations

import httpx
import respx

from zfrog.ai.tos import check_site, check_text, find_terms_url, robots_signals, terms_signals

BASE = "https://example.com/"
ROBOTS_URL = "https://example.com/robots.txt"
HOME_HTML = "<html><body><p>Bem-vindo ao site.</p></body></html>"

BLOCK_ALL = "User-agent: *\nDisallow: /\n"


def _severities(findings) -> list[str]:
    return [finding.severity for finding in findings]


def test_wildcard_disallow_of_everything_is_blocking():
    findings = robots_signals("https://example.com", BLOCK_ALL)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind == "robots_block_all"
    assert finding.severity == "blocking"
    assert finding.evidence == "Disallow: /"  # the rule line, verbatim
    assert finding.source == ROBOTS_URL


def test_path_specific_disallow_blocks_only_that_path():
    robots = "User-agent: *\nDisallow: /private\n"

    root = robots_signals("https://example.com", robots, "/")
    private = robots_signals("https://example.com", robots, "/private")

    assert not any(f.severity == "blocking" for f in root)
    assert root == []
    assert _severities(private) == ["blocking"]
    assert private[0].kind == "robots_disallow_path"
    assert private[0].evidence == "Disallow: /private"


def test_crawl_delay_is_info_and_ai_crawler_disallow_is_warning():
    robots = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nCrawl-delay: 10\n"

    findings = robots_signals("https://example.com", robots, "/")

    assert _severities(findings) == ["warning", "info"]
    crawler, delay = findings
    assert crawler.kind == "ai_crawler_disallow"
    assert "gptbot" in crawler.detail
    assert crawler.evidence == "Disallow: /"
    assert delay.kind == "crawl_delay"
    assert delay.evidence == "Crawl-delay: 10"


def test_robots_without_rules_yields_nothing():
    assert robots_signals("https://example.com", "") == []
    assert robots_signals("https://example.com", "# só comentários\n") == []
    assert robots_signals("https://example.com", "Sitemap: https://example.com/sitemap.xml\n") == []
    assert robots_signals("https://example.com", "User-agent: *\nDisallow:\n") == []


def test_terms_signals_quote_the_restricting_sentences():
    html = (
        "<html><body>"
        "<p>É proibido o uso de robôs para coletar dados deste site.</p>"
        "<p>No scraping of this website is allowed without permission.</p>"
        "<p>Bem-vindo.</p>"
        "</body></html>"
    )

    findings = terms_signals(html, "https://example.com/termos")

    restrictions = [f for f in findings if f.kind == "automated_collection_prohibited"]
    assert len(restrictions) == 2
    assert all(f.severity == "blocking" for f in restrictions)
    assert all(f.source == "https://example.com/termos" for f in restrictions)
    quotes = [f.evidence for f in restrictions]
    assert any("proibido o uso de robôs" in quote for quote in quotes)
    assert any("No scraping" in quote for quote in quotes)
    assert not any("Bem-vindo" in quote for quote in quotes)


def test_clean_legal_page_only_carries_the_notice():
    html = "<html><body><h1>Termos de Uso</h1><p>Este site publica notícias. Leia com atenção.</p></body></html>"

    findings = terms_signals(html, "https://example.com/termos")

    assert [f.kind for f in findings] == ["legal_notice"]
    assert findings[0].severity == "info"
    assert "não substitui orientação jurídica" in findings[0].detail


def test_terms_signals_cover_the_warning_phrases():
    alone = terms_signals("<p>© 2026 Example. All rights reserved.</p>", "https://example.com/termos")
    assert [f.kind for f in alone] == ["legal_notice"]  # a footer alone restricts nothing

    combined = terms_signals(
        "<p>All rights reserved and any reproduction requires written consent.</p>",
        "https://example.com/termos",
    )
    assert [f.kind for f in combined] == ["copyright_reproduction", "legal_notice"]
    assert combined[0].severity == "warning"

    limits = terms_signals(
        "<p>We apply a rate limit of 5 requests per minute.</p>"
        "<p>A conta será encerrada em caso de coleta automatizada.</p>",
        "https://example.com/termos",
    )
    kinds = {f.kind for f in limits}
    assert {"rate_limit", "account_termination", "legal_notice"} <= kinds
    assert all(f.severity == "warning" for f in limits if f.kind != "legal_notice")


def test_find_terms_url_resolves_and_returns_none_when_absent():
    html = (
        '<nav><a href="/blog">Blog</a><a href="/contato">Contato</a></nav>'
        '<footer><a href="/termos">Termos de Uso</a></footer>'
    )

    assert find_terms_url(html, "https://example.com/sobre") == "https://example.com/termos"
    assert (
        find_terms_url('<a href="/condicoes">Saiba mais</a>', "https://example.com")
        == "https://example.com/condicoes"
    )
    assert (
        find_terms_url('<a href="https://example.com/legal/privacidade">Privacidade</a>', BASE)
        == "https://example.com/legal/privacidade"
    )
    assert find_terms_url('<nav><a href="/blog">Blog</a></nav>', BASE) is None
    assert find_terms_url("", BASE) is None


def test_check_text_risk_transitions():
    blocked = check_text(HOME_HTML, robots_txt=BLOCK_ALL, url=BASE)
    caution = check_text(HOME_HTML, robots_txt="User-agent: GPTBot\nDisallow: /\n", url=BASE)
    clean = check_text(HOME_HTML, url=BASE)

    assert blocked.risk == "restricted"
    assert caution.risk == "caution"
    assert clean.risk == "clear"
    assert [f.kind for f in clean.findings] == ["legal_notice"]
    assert all("não constitui orientação jurídica" in report.summary for report in (blocked, caution, clean))
    assert blocked.error is None


def test_findings_are_deduplicated_and_sorted_by_severity():
    html = (
        "<p>É proibido o uso de robôs.</p>"
        "<p>É proibido o uso de robôs.</p>"  # repeated: same (kind, evidence)
        "<p>Reprodução não autorizada é proibida.</p>"
    )
    robots = "User-agent: *\nDisallow: /\nCrawl-delay: 5\n"

    report = check_text(html, robots_txt=robots, url=BASE)

    assert len(report.findings) == 5  # duplicate sentence collapsed into one
    keys = [(f.kind, f.evidence) for f in report.findings]
    assert len(keys) == len(set(keys))
    assert _severities(report.findings) == ["blocking", "blocking", "warning", "info", "info"]
    assert report.risk == "restricted"


async def test_check_site_without_robots_and_without_terms_link():
    with respx.mock(assert_all_called=True) as mock:
        mock.get(ROBOTS_URL).mock(return_value=httpx.Response(404))
        mock.get(BASE).mock(return_value=httpx.Response(200, text=HOME_HTML))
        report = await check_site(BASE)

    assert report.error is None  # a missing robots.txt is normal, not an error
    assert report.risk == "clear"
    assert [f.kind for f in report.findings] == ["legal_notice"]
    assert report.url == BASE


async def test_check_site_follows_the_terms_link():
    home = (
        "<html><body><p>Bem-vindo.</p>"
        '<footer><a href="/termos">Termos de Uso</a></footer></body></html>'
    )
    terms = "<html><body><p>No scraping is allowed on this website.</p></body></html>"
    robots = "User-agent: *\nDisallow: /admin\nCrawl-delay: 3\n"

    with respx.mock(assert_all_called=True) as mock:
        mock.get(ROBOTS_URL).mock(return_value=httpx.Response(200, text=robots))
        mock.get(BASE).mock(return_value=httpx.Response(200, text=home))
        mock.get("https://example.com/termos").mock(return_value=httpx.Response(200, text=terms))
        report = await check_site(BASE)

    assert report.error is None
    assert report.risk == "restricted"
    kinds = [f.kind for f in report.findings]
    assert "crawl_delay" in kinds  # the /admin rule does not block the checked path
    assert "robots_disallow_path" not in kinds
    restriction = next(f for f in report.findings if f.kind == "automated_collection_prohibited")
    assert restriction.source == "https://example.com/termos"
    assert "No scraping" in restriction.evidence


async def test_check_site_skips_terms_when_disabled():
    with respx.mock(assert_all_called=True) as mock:
        mock.get(ROBOTS_URL).mock(return_value=httpx.Response(200, text=BLOCK_ALL))
        report = await check_site(BASE, fetch_terms=False)

    assert report.error is None
    assert report.risk == "restricted"
    assert [f.kind for f in report.findings] == ["robots_block_all"]


async def test_check_site_falls_back_to_homepage_when_terms_page_fails():
    home = (
        '<html><body><a href="/termos">Termos</a><p>No scraping is allowed.</p></body></html>'
    )

    with respx.mock(assert_all_called=True) as mock:
        mock.get(ROBOTS_URL).mock(return_value=httpx.Response(404))
        mock.get(BASE).mock(return_value=httpx.Response(200, text=home))
        mock.get("https://example.com/termos").mock(return_value=httpx.Response(500))
        report = await check_site(BASE)

    assert report.error is not None and "termos" in report.error
    restriction = next(f for f in report.findings if f.kind == "automated_collection_prohibited")
    assert restriction.source == BASE  # scanned the homepage it actually read


async def test_check_site_reports_connection_errors_instead_of_raising():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ROBOTS_URL).mock(side_effect=httpx.ConnectError("sem rede"))
        mock.get(BASE).mock(side_effect=httpx.ConnectError("sem rede"))
        report = await check_site(BASE)

    assert report.error is not None
    assert "sem rede" in report.error
    assert report.findings == []
    assert report.risk == "clear"
