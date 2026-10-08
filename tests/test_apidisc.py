"""Tests for API discovery: endpoint parsing and the api_discovery engine."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from zfrog.apidisc import Endpoint, extract_endpoints, group_by_kind, is_likely_api
from zfrog.config import settings
from zfrog.engines import api_discovery
from zfrog.engines.api_discovery import ApiDiscoveryEngine
from zfrog.models import JobCreate, ProbeResult

BASE = "https://site.test/"


@pytest.fixture(autouse=True)
def _isolated_output(tmp_path, monkeypatch):
    """Keep any settings-driven path inside the test's tmp dir."""
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")


def test_fetch_call_is_resolved_against_base_url():
    html = '<html><body><script>fetch("/api/products");</script></body></html>'

    endpoints = extract_endpoints(html, BASE)

    assert endpoints == [
        Endpoint(
            url="https://site.test/api/products",
            method="GET",
            kind="rest",
            source="fetch",
        )
    ]


def test_xhr_and_jquery_methods_are_captured():
    html = """<html><body><script>
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/cart");
    $.ajax({url: "/api/x", method: "PUT"});
    $.post("/api/orders");
    </script></body></html>"""

    found = {endpoint.url: endpoint for endpoint in extract_endpoints(html, BASE)}

    assert found["https://site.test/api/cart"].method == "POST"
    assert found["https://site.test/api/cart"].source == "xhr"
    assert found["https://site.test/api/x"].method == "PUT"
    assert found["https://site.test/api/orders"].method == "POST"


def test_fetch_and_axios_verbs_are_captured():
    html = """<script>
    fetch("/api/a", {method: "DELETE"});
    axios.post("/api/b");
    </script>"""

    found = {endpoint.url: endpoint.method for endpoint in extract_endpoints(html, BASE)}

    assert found["https://site.test/api/a"] == "DELETE"
    assert found["https://site.test/api/b"] == "POST"


def test_forms_use_their_method_and_default_to_get():
    html = (
        '<html><body><form action="/search" method="post"></form>'
        '<form action="/filtro"></form></body></html>'
    )

    endpoints = extract_endpoints(html, BASE)

    assert {(endpoint.url, endpoint.method) for endpoint in endpoints} == {
        ("https://site.test/search", "POST"),
        ("https://site.test/filtro", "GET"),
    }
    assert {endpoint.source for endpoint in endpoints} == {"form"}


def test_graphql_endpoint_is_typed_and_query_body_marks_nearby_url():
    html = """<script>
    fetch("/graphql", {method: "POST", body: "query { user { id } }"});
    fetch("/api/gateway", {body: 'mutation { save }'});
    </script>"""

    found = {endpoint.url: endpoint for endpoint in extract_endpoints(html, BASE)}

    assert found["https://site.test/graphql"].kind == "graphql"
    assert found["https://site.test/graphql"].method == "POST"
    assert found["https://site.test/api/gateway"].kind == "graphql"
    assert found["https://site.test/api/gateway"].source == "fetch"


def test_graphql_body_does_not_leak_to_other_calls():
    html = """<script>
    fetch("/api/gateway", {body: 'mutation { save }'});
    $.get("/api/tags");
    var u = "https://third.test/v1/stream?query=live";
    </script>"""

    found = {endpoint.url: endpoint for endpoint in extract_endpoints(html, BASE)}

    assert found["https://site.test/api/gateway"].kind == "graphql"
    assert found["https://site.test/api/tags"].kind == "rest"
    assert found["https://third.test/v1/stream?query=live"].kind == "rest"


def test_duplicate_method_and_url_keeps_the_first_source():
    html = (
        '<script>fetch("/api/products"); fetch("/api/products");</script>'
        '<form action="/api/products"></form>'
    )

    endpoints = [e for e in extract_endpoints(html, BASE) if e.url.endswith("/api/products")]

    assert len(endpoints) == 1
    assert endpoints[0].source == "fetch"


def test_js_bodies_are_scanned():
    endpoints = extract_endpoints(
        "<html><body></body></html>", BASE, js_bodies=['axios.post("/api/log");']
    )

    assert endpoints == [
        Endpoint(url="https://site.test/api/log", method="POST", kind="rest", source="xhr")
    ]


def test_absolute_api_url_literal_in_script_is_reported():
    html = '<script>var u = "https://api.site.test/v1/items?query=x";</script>'

    endpoints = extract_endpoints(html, BASE)

    assert endpoints == [
        Endpoint(
            url="https://api.site.test/v1/items?query=x",
            method="GET",
            kind="rest",
            source="script",
        )
    ]


def test_api_link_tag_is_reported_and_assets_are_not():
    html = (
        '<html><head><link rel="stylesheet" href="/style.css">'
        '<link rel="preload" href="/api/feed.json"></head><body></body></html>'
    )

    endpoints = extract_endpoints(html, BASE)

    assert endpoints == [
        Endpoint(url="https://site.test/api/feed.json", method="GET", kind="rest", source="link")
    ]


def test_non_http_urls_are_dropped_and_results_are_sorted():
    html = """<script>
    fetch("mailto:ops@site.test");
    fetch("/api/z");
    fetch("/api/a");
    </script>"""

    urls = [endpoint.url for endpoint in extract_endpoints(html, BASE)]

    assert urls == ["https://site.test/api/a", "https://site.test/api/z"]


@pytest.mark.parametrize(
    "url",
    [
        "https://site.test/api/users",
        "https://site.test/graphql",
        "https://site.test/rest/items",
        "https://site.test/v1/items",
        "https://site.test/v2/items",
        "https://site.test/v3/items",
        "https://site.test/feed.json",
        "https://site.test/schema.graphql",
    ],
)
def test_is_likely_api_accepts_api_looking_urls(url):
    assert is_likely_api(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://site.test/",
        "https://site.test/blog/post",
        "https://site.test/sobre.html",
        "https://site.test/assets/app.js",
    ],
)
def test_is_likely_api_rejects_pages_and_assets(url):
    assert is_likely_api(url) is False


def test_group_by_kind_groups_and_keeps_order():
    endpoints = [
        Endpoint(url="https://x.test/api/a", source="fetch"),
        Endpoint(url="https://x.test/graphql", method="POST", kind="graphql", source="fetch"),
        Endpoint(url="https://x.test/api/b", source="form"),
    ]

    grouped = group_by_kind(endpoints)

    assert list(grouped) == ["graphql", "rest"]
    assert [endpoint.url for endpoint in grouped["rest"]] == [
        "https://x.test/api/a",
        "https://x.test/api/b",
    ]
    assert grouped["graphql"][0].method == "POST"


def test_can_handle_accepts_any_page():
    engine = ApiDiscoveryEngine()

    assert engine.name == "api_discovery"
    assert engine.can_handle(ProbeResult(url="https://x.test/")) is True
    assert engine.can_handle(ProbeResult(url="https://x.test/", is_spa=True)) is True


def _response(text: str, content_type: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": content_type}, text=text)


async def test_engine_fetches_scripts_and_writes_reports(tmp_path):
    page_url = "https://site.test/"
    script_url = "https://site.test/static/app.js"
    page = '<html><body><script src="/static/app.js"></script></body></html>'
    script = 'fetch("/api/items");'
    output_dir = tmp_path / "out"
    messages: list[str] = []

    with respx.mock(assert_all_called=False) as mock:
        mock.get(page_url).mock(
            side_effect=lambda request: _response(page, "text/html; charset=utf-8")
        )
        mock.get(script_url).mock(
            side_effect=lambda request: _response(script, "application/javascript")
        )
        result = await ApiDiscoveryEngine().execute(
            JobCreate(url=page_url, mode="api_discovery"),
            output_dir,
            on_progress=messages.append,
        )

    payload = json.loads((output_dir / "api_endpoints.json").read_text(encoding="utf-8"))
    expected = {
        "url": "https://site.test/api/items",
        "method": "GET",
        "kind": "rest",
        "source": "fetch",
    }
    assert payload["url"] == page_url
    assert payload["endpoints"] == [expected]
    assert payload["by_kind"] == {"rest": [expected]}

    markdown = (output_dir / "api_endpoints.md").read_text(encoding="utf-8")
    assert "https://site.test/api/items" in markdown
    assert "| GET | rest |" in markdown

    assert result.files == [output_dir / "api_endpoints.json", output_dir / "api_endpoints.md"]
    assert result.total_bytes > 0
    assert messages == ["Scanning for APIs...", "APIs found: 1"]
    assert any(script_url in log for log in result.logs)


async def test_engine_without_apis_writes_empty_reports(tmp_path):
    page_url = "https://empty.test/"
    page = "<html><body><h1>Ola</h1><p>sem scripts</p></body></html>"
    output_dir = tmp_path / "out"

    with respx.mock(assert_all_called=False) as mock:
        mock.get(page_url).mock(side_effect=lambda request: _response(page, "text/html"))
        result = await ApiDiscoveryEngine().execute(
            JobCreate(url=page_url, mode="api_discovery"), output_dir
        )

    payload = json.loads((output_dir / "api_endpoints.json").read_text(encoding="utf-8"))
    assert payload == {"url": page_url, "endpoints": [], "by_kind": {}}

    markdown = (output_dir / "api_endpoints.md").read_text(encoding="utf-8")
    assert "No endpoints found." in markdown
    assert result.files == [output_dir / "api_endpoints.json", output_dir / "api_endpoints.md"]


async def test_engine_survives_a_failing_script(tmp_path):
    page_url = "https://fail.test/"
    page = (
        '<html><body><script src="/broken.js"></script>'
        '<script src="/ok.js"></script></body></html>'
    )
    output_dir = tmp_path / "out"

    with respx.mock(assert_all_called=False) as mock:
        mock.get(page_url).mock(side_effect=lambda request: _response(page, "text/html"))
        mock.get("https://fail.test/broken.js").mock(
            side_effect=lambda request: httpx.Response(500, text="boom")
        )
        mock.get("https://fail.test/ok.js").mock(
            side_effect=lambda request: _response('fetch("/api/ok");', "application/javascript")
        )
        result = await ApiDiscoveryEngine().execute(
            JobCreate(url=page_url, mode="api_discovery"), output_dir
        )

    payload = json.loads((output_dir / "api_endpoints.json").read_text(encoding="utf-8"))
    assert [endpoint["url"] for endpoint in payload["endpoints"]] == ["https://fail.test/api/ok"]
    assert any("500" in log for log in result.logs)


async def test_engine_caps_the_number_of_scripts(tmp_path):
    page_url = "https://cap.test/"
    page = (
        "<html><body>"
        + "".join(f'<script src="/s{i}.js"></script>' for i in range(12))
        + "</body></html>"
    )
    output_dir = tmp_path / "out"
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) == page_url:
            return _response(page, "text/html")
        return _response('fetch("/api/deep");', "application/javascript")

    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://cap\.test/.*").mock(side_effect=handler)
        result = await ApiDiscoveryEngine().execute(
            JobCreate(url=page_url, mode="api_discovery"), output_dir
        )

    assert [url for url in requested if url != page_url] == [
        f"https://cap.test/s{i}.js" for i in range(10)
    ]
    assert any("Script limit of 10 reached" in log for log in result.logs)

    payload = json.loads((output_dir / "api_endpoints.json").read_text(encoding="utf-8"))
    assert payload["endpoints"] == [
        {
            "url": "https://cap.test/api/deep",
            "method": "GET",
            "kind": "rest",
            "source": "fetch",
        }
    ]


async def test_engine_truncates_oversized_scripts(tmp_path, monkeypatch):
    monkeypatch.setattr(api_discovery, "MAX_SCRIPT_BYTES", 40)
    page_url = "https://big.test/"
    page = '<html><body><script src="/big.js"></script></body></html>'
    script = "/*" + "x" * 500 + "*/ fetch('/api/hidden');"
    output_dir = tmp_path / "out"

    with respx.mock(assert_all_called=False) as mock:
        mock.get(page_url).mock(side_effect=lambda request: _response(page, "text/html"))
        mock.get("https://big.test/big.js").mock(
            side_effect=lambda request: _response(script, "application/javascript")
        )
        result = await ApiDiscoveryEngine().execute(
            JobCreate(url=page_url, mode="api_discovery"), output_dir
        )

    payload = json.loads((output_dir / "api_endpoints.json").read_text(encoding="utf-8"))
    assert payload["endpoints"] == []
    assert any("truncated" in log for log in result.logs)


async def test_engine_reports_an_unreachable_page(tmp_path):
    page_url = "https://down.test/"
    output_dir = tmp_path / "out"

    with respx.mock(assert_all_called=False) as mock:
        mock.get(page_url).mock(side_effect=httpx.ConnectError("recusado"))
        result = await ApiDiscoveryEngine().execute(
            JobCreate(url=page_url, mode="api_discovery"), output_dir
        )

    payload = json.loads((output_dir / "api_endpoints.json").read_text(encoding="utf-8"))
    assert payload == {"url": page_url, "endpoints": [], "by_kind": {}}
    assert any("Failed to fetch" in log for log in result.logs)
