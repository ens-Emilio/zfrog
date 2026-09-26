"""Tests for the point-and-click selector backend."""

import re

import pytest
import respx
from bs4 import BeautifulSoup

from zfrog import selector as selector_mod

PAGE_URL = "https://preview.test/shop/index.html"

PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url=https://evil.test/">
  <title>Loja Teste</title>
  <link rel="stylesheet" href="/assets/site.css">
  <script>window.leak = "secret";</script>
  <noscript><img src="/pixel.gif" alt="no-js"></noscript>
</head>
<body onload="boot()">
  <h1 class="title" data-kind="hero">Produtos</h1>
  <ul id="list">
    <li class="item" data-sku="a1"><a href="javascript:alert(1)" onclick="track()">Primeiro</a></li>
    <li class="item" data-sku="a2"><a href="/a2.html" onmouseover="hi()">Segundo</a></li>
    <li class="item" data-sku="a3"><a href="/a3.html">Terceiro</a></li>
  </ul>
  <form action="javascript:steal()"><input name="q"></form>
</body>
</html>
"""


def _serve(mock, url: str, html: str) -> None:
    mock.get(url).respond(200, text=html, headers={"content-type": "text/html; charset=utf-8"})


async def test_fetch_page_returns_url_title_and_html():
    with respx.mock(assert_all_called=True) as mock:
        _serve(mock, PAGE_URL, PAGE_HTML)
        page = await selector_mod.fetch_page(PAGE_URL)

    assert page["url"] == PAGE_URL
    assert page["title"] == "Loja Teste"
    assert isinstance(page["html"], str) and page["html"]


async def test_fetch_page_sanitises_html():
    with respx.mock(assert_all_called=True) as mock:
        _serve(mock, PAGE_URL, PAGE_HTML)
        html = (await selector_mod.fetch_page(PAGE_URL))["html"]

    assert "<script" not in html
    assert "window.leak" not in html
    assert "noscript" not in html
    assert "pixel.gif" not in html
    assert "onload" not in html
    assert "onclick" not in html
    assert "onmouseover" not in html
    assert "javascript:" not in html.lower()

    soup = BeautifulSoup(html, "lxml")
    # Normal markup survives untouched.
    assert soup.h1.get_text() == "Produtos"
    assert soup.h1["data-kind"] == "hero"
    assert soup.find("link")["href"] == "/assets/site.css"
    assert soup.find("input")["name"] == "q"
    assert [li.get_text() for li in soup.select("li.item")] == ["Primeiro", "Segundo", "Terceiro"]
    assert soup.find("meta", attrs={"charset": "utf-8"}) is not None

    # javascript: URLs lose the attribute entirely; safe ones stay.
    links = soup.select("li.item a")
    assert links[0].get("href") is None
    assert links[1]["href"] == "/a2.html"
    assert links[2]["href"] == "/a3.html"
    assert soup.find("form").get("action") is None

    # Meta refresh is gone, <base> is injected first inside <head>.
    assert soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.IGNORECASE)}) is None
    assert soup.head.contents[0].name == "base"
    assert soup.head.find("base")["href"] == PAGE_URL
    assert len(soup.find_all("base")) == 1


async def test_fetch_page_without_title_returns_empty_string():
    with respx.mock(assert_all_called=True) as mock:
        _serve(mock, PAGE_URL, "<html><body><p>sem titulo</p></body></html>")
        page = await selector_mod.fetch_page(PAGE_URL)

    assert page["title"] == ""
    assert "sem titulo" in page["html"]


async def test_fetch_page_injects_base_when_page_has_no_head():
    with respx.mock(assert_all_called=True) as mock:
        _serve(mock, PAGE_URL, "<div id='fragment'>so um fragmento</div>")
        html = (await selector_mod.fetch_page(PAGE_URL))["html"]

    soup = BeautifulSoup(html, "lxml")
    assert soup.head.contents[0].name == "base"
    assert soup.head.find("base")["href"] == PAGE_URL
    assert soup.select_one("div#fragment").get_text() == "so um fragmento"


def test_preview_selector_matches_by_class():
    matches = selector_mod.preview_selector(PAGE_HTML, "li.item")

    assert [m.tag for m in matches] == ["li", "li", "li"]
    assert [m.text for m in matches] == ["Primeiro", "Segundo", "Terceiro"]
    assert [m.index for m in matches] == [0, 1, 2]
    assert matches[0].html.startswith("<li")


def test_preview_selector_matches_by_attribute():
    matches = selector_mod.preview_selector(PAGE_HTML, "li[data-sku='a2']")

    assert len(matches) == 1
    assert matches[0].text == "Segundo"
    assert matches[0].index == 0


def test_preview_selector_matches_by_nth_child():
    matches = selector_mod.preview_selector(PAGE_HTML, "ul#list > li:nth-child(2)")

    assert [m.text for m in matches] == ["Segundo"]


def test_preview_selector_without_matches_returns_empty_list():
    assert selector_mod.preview_selector(PAGE_HTML, "table.nope") == []
    assert selector_mod.build_selector_preview(PAGE_HTML, "table.nope") == {"count": 0, "elements": []}


def test_preview_selector_with_invalid_selector_raises_value_error():
    with pytest.raises(ValueError):
        selector_mod.preview_selector(PAGE_HTML, "div[[")

    with pytest.raises(ValueError):
        selector_mod.build_selector_preview(PAGE_HTML, "div[[")


@pytest.mark.parametrize("selector", ["", "   ", "\n\t"])
def test_validate_selector_rejects_blank(selector):
    with pytest.raises(ValueError):
        selector_mod.validate_selector(selector)

    with pytest.raises(ValueError):
        selector_mod.preview_selector(PAGE_HTML, selector)


def test_validate_selector_rejects_invalid_css():
    with pytest.raises(ValueError):
        selector_mod.validate_selector("div[[")


def test_validate_selector_accepts_valid_css():
    assert selector_mod.validate_selector("ul#list > li:nth-child(2)") is None


def test_preview_text_is_collapsed_and_truncated():
    long_text = "palavra " * 100
    html = f"<div class='a'>  alpha\n\t beta   gamma </div><div class='b'>{long_text}</div>"

    matches = selector_mod.preview_selector(html, "div")

    assert matches[0].text == "alpha beta gamma"
    assert len(matches[1].text) == 300
    assert matches[1].text == " ".join(long_text.split())[:300]
    assert matches[1].text == matches[1].text.strip()


def test_preview_html_is_truncated():
    html = "<div class='big'>" + "<span>x</span>" * 200 + "</div>"

    match = selector_mod.preview_selector(html, "div.big")[0]

    assert len(match.html) == 500
    assert match.html.startswith("<div class=\"big\">")


def test_build_selector_preview_counts_all_matches_but_limits_elements():
    html = "".join(f"<p class='row'>item {i}</p>" for i in range(12))

    result = selector_mod.build_selector_preview(html, "p.row", limit=5)

    assert result["count"] == 12
    assert len(result["elements"]) == 5
    assert [e["index"] for e in result["elements"]] == [0, 1, 2, 3, 4]
    assert result["elements"][0] == {
        "index": 0,
        "tag": "p",
        "text": "item 0",
        "html": "<p class=\"row\">item 0</p>",
    }


def test_build_selector_preview_limit_caps_one_hundred_matches():
    html = "<ul>" + "".join(f"<li class='row'>r{i}</li>" for i in range(100)) + "</ul>"

    result = selector_mod.build_selector_preview(html, "li.row", limit=10)

    assert result["count"] == 100
    assert len(result["elements"]) == 10
    assert result["elements"][-1]["text"] == "r9"


async def test_preview_on_sanitised_page_skips_injected_base():
    with respx.mock(assert_all_called=True) as mock:
        _serve(mock, PAGE_URL, PAGE_HTML)
        page = await selector_mod.fetch_page(PAGE_URL)

    assert selector_mod.preview_selector(page["html"], "base") == []
    assert selector_mod.build_selector_preview(page["html"], "base") == {"count": 0, "elements": []}

    matches = selector_mod.preview_selector(page["html"], "li.item")
    assert [m.text for m in matches] == ["Primeiro", "Segundo", "Terceiro"]
    assert [m.index for m in matches] == [0, 1, 2]
    assert "onclick" not in matches[0].html
