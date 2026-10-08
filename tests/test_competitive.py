"""Tests for the competitive analysis of cloned sites.

Real clone trees under ``tmp_path``, real price extraction; only the AI layer is
monkeypatched (never a model call, never a fabricated entity).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zfrog.analysis import competitive as comp
from zfrog.config import settings


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Keep analysis output in the test tree and keep the AI out of the way."""
    monkeypatch.setattr(settings, "analysis_dir", tmp_path / "analysis")
    monkeypatch.setattr(comp, "is_available", lambda: False)


def _page(title: str, body: str) -> str:
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


def _site(root: Path, name: str, pages: dict[str, str]) -> Path:
    """A clone directory holding exactly the given pages."""
    directory = root / name
    directory.mkdir(parents=True)
    for filename, html in pages.items():
        (directory / filename).write_text(html, encoding="utf-8")
    return directory


def _snapshot(
    site: str,
    *,
    pages: int = 1,
    words: int = 10,
    prices: list[float] | None = None,
    price_labels: dict[str, float] | None = None,
    entities: list[dict] | None = None,
    titles: list[str] | None = None,
) -> comp.SiteSnapshot:
    return comp.SiteSnapshot(
        site=site,
        url="",
        pages=pages,
        words=words,
        prices=list(prices or []),
        entities=list(entities or []),
        titles=list(titles or []),
        price_labels=dict(price_labels or {}),
    )


def _entity(name: str, kind: str = "organization") -> dict:
    return {"name": name, "type": kind, "confidence": 0.9}


# ── summarize_site ────────────────────────────────────────────────────────

def test_summarize_site_counts_pages_words_and_titles(tmp_path):
    directory = _site(
        tmp_path,
        "lojaA",
        {
            "index.html": _page("Página inicial", "<p>Notebook bom de trabalho com garantia</p>"),
            "sobre.html": _page("Sobre nós", "<p>Somos uma loja de tecnologia</p>"),
        },
    )
    (directory / "dados.html").mkdir()  # a directory is not a page

    snapshot = comp.summarize_site("lojaA", directory, "https://a.example")

    assert snapshot.site == "lojaA"
    assert snapshot.url == "https://a.example"
    assert snapshot.pages == 2
    assert snapshot.words > 0
    assert snapshot.titles == ["Página inicial", "Sobre nós"]


def test_summarize_site_of_a_missing_directory_is_empty(tmp_path):
    snapshot = comp.summarize_site("lojaA", tmp_path / "nao-existe")

    assert snapshot.pages == 0
    assert snapshot.words == 0
    assert snapshot.prices == []
    assert snapshot.entities == []
    assert snapshot.titles == []


def test_summarize_site_picks_up_brazilian_prices(tmp_path):
    directory = _site(
        tmp_path,
        "lojaA",
        {"index.html": _page("Loja", "<p>Notebook: R$ 1.234,56</p>")},
    )

    snapshot = comp.summarize_site("lojaA", directory)

    assert snapshot.prices == [pytest.approx(1234.56)]
    assert list(snapshot.price_labels.values()) == [pytest.approx(1234.56)]


def test_summarize_site_never_invents_entities_without_ai(tmp_path, monkeypatch):
    directory = _site(
        tmp_path,
        "lojaA",
        {"index.html": _page("Loja", "<p>Notebook: R$ 1.234,56</p>")},
    )
    monkeypatch.setattr(comp, "is_available", lambda: False)

    async def _must_not_be_called(*args, **kwargs):
        raise AssertionError("a IA não pode ser chamada quando está indisponível")

    monkeypatch.setattr(comp, "extract_entities", _must_not_be_called)

    snapshot = comp.summarize_site("lojaA", directory)

    assert snapshot.entities == []
    assert snapshot.prices == [pytest.approx(1234.56)]


def test_summarize_site_uses_the_ai_entities_when_available(tmp_path, monkeypatch):
    directory = _site(
        tmp_path,
        "lojaA",
        {"index.html": _page("Loja", "<p>A Acme vende notebooks.</p>")},
    )
    seen: list[str] = []

    async def _fake_extract(text, max_chars: int = 8000) -> dict:
        seen.append(text)
        return {"entities": [_entity("Acme")], "counts": {"organization": 1}}

    monkeypatch.setattr(comp, "is_available", lambda: True)
    monkeypatch.setattr(comp, "extract_entities", _fake_extract)

    snapshot = comp.summarize_site("lojaA", directory)

    assert [entity["name"] for entity in snapshot.entities] == ["Acme"]
    assert "Acme" in seen[0]


async def test_summarize_site_works_inside_a_running_loop(tmp_path):
    directory = _site(
        tmp_path,
        "lojaA",
        {"index.html": _page("Loja", "<p>Notebook: R$ 1.234,56</p>")},
    )

    snapshot = comp.summarize_site("lojaA", directory)

    assert snapshot.pages == 1
    assert snapshot.prices == [pytest.approx(1234.56)]


# ── compare ───────────────────────────────────────────────────────────────

def test_compare_splits_shared_and_unique_entities():
    a = _snapshot("lojaA", entities=[_entity("Acme"), _entity("Zeta", "product")])
    b = _snapshot("lojaB", entities=[_entity("acme"), _entity("Loja B")])

    comparison = comp.compare([a, b])

    assert comparison.shared_entities == ["Acme"]
    assert comparison.unique_entities["lojaA"] == ["Zeta"]
    assert comparison.unique_entities["lojaB"] == ["Loja B"]


def test_price_spread_reports_min_max_mean_and_cheapest(tmp_path):
    cheap = _site(tmp_path, "lojaA", {"index.html": _page("A", "<p>Notebook: R$ 3.199,00</p>")})
    pricey = _site(tmp_path, "lojaB", {"index.html": _page("B", "<p>Notebook: R$ 3.499,00</p>")})

    comparison = comp.compare(
        [comp.summarize_site("lojaA", cheap), comp.summarize_site("lojaB", pricey)]
    )

    assert len(comparison.price_spread) == 1
    label, stats = next(iter(comparison.price_spread.items()))
    assert label.lower() == "notebook"
    assert stats["min"] == pytest.approx(3199.0)
    assert stats["max"] == pytest.approx(3499.0)
    assert stats["mean"] == pytest.approx(3349.0)
    assert stats["cheapest"] == "lojaA"
    assert stats["values"]["lojaA"] == pytest.approx(3199.0)
    assert stats["values"]["lojaB"] == pytest.approx(3499.0)
    assert "lojaA" in comparison.summary


def test_price_spread_ignores_a_label_only_one_site_has():
    a = _snapshot("lojaA", prices=[10.0], price_labels={"caneta": 10.0})
    b = _snapshot("lojaB", prices=[20.0], price_labels={"cadeira": 20.0})

    comparison = comp.compare([a, b])

    assert comparison.price_spread == {}


def test_content_gaps_flags_a_site_with_far_fewer_pages(tmp_path):
    small = _site(tmp_path, "lojaA", {"index.html": _page("A", "<p>Uma página só</p>")})
    big = _site(
        tmp_path,
        "lojaB",
        {
            "index.html": _page("B", "<p>Conteúdo</p>"),
            "a.html": _page("A", "<p>Conteúdo</p>"),
            "b.html": _page("B", "<p>Conteúdo</p>"),
            "c.html": _page("C", "<p>Conteúdo</p>"),
        },
    )

    comparison = comp.compare(
        [comp.summarize_site("lojaA", small), comp.summarize_site("lojaB", big)]
    )

    assert len(comparison.content_gaps) == 1
    gap = comparison.content_gaps[0]
    assert "lojaA" in gap
    assert "1" in gap and "4" in gap
    assert "lojaA" in comparison.summary and "lojaB" in comparison.summary


def test_content_gaps_is_empty_for_comparable_sites(tmp_path):
    pages = {"index.html": _page("Loja", "<p>Notebook: R$ 1.234,56 com garantia</p>")}

    comparison = comp.compare(
        [
            comp.summarize_site("lojaA", _site(tmp_path, "lojaA", pages)),
            comp.summarize_site("lojaB", _site(tmp_path, "lojaB", pages)),
        ]
    )

    assert comparison.content_gaps == []
    assert "lojaA" in comparison.summary and "lojaB" in comparison.summary


def test_content_gaps_reports_a_site_without_prices():
    a = _snapshot("lojaA", pages=2, words=40, prices=[10.0], price_labels={"caneta": 10.0})
    b = _snapshot("lojaB", pages=2, words=40)

    comparison = comp.compare([a, b])

    assert comparison.content_gaps == ["lojaB has no detected price."]


def test_compare_with_one_site_returns_an_empty_analysis():
    only = _snapshot("lojaA", prices=[10.0], entities=[_entity("Acme")])

    comparison = comp.compare([only])

    assert comparison.sites == [only]
    assert comparison.price_spread == {}
    assert comparison.shared_entities == []
    assert comparison.unique_entities == {}
    assert comparison.content_gaps == []
    assert comparison.summary == ""


def test_compare_without_sites_does_not_raise():
    comparison = comp.compare([])

    assert comparison.sites == []
    assert comparison.summary == ""
    assert comp.to_markdown(comparison).strip()
    assert json.loads(json.dumps(comp.to_json(comparison)))["sites"] == []


# ── Rendering ─────────────────────────────────────────────────────────────

def test_to_markdown_lists_sites_and_price_values():
    a = _snapshot(
        "lojaA", pages=2, words=40, prices=[3199.0], price_labels={"Notebook": 3199.0},
        titles=["Loja A"],
    )
    b = _snapshot(
        "lojaB", pages=2, words=40, prices=[3499.0], price_labels={"Notebook": 3499.0},
        titles=["Loja B"],
    )

    markdown = comp.to_markdown(comp.compare([a, b]))

    assert "## lojaA" in markdown and "## lojaB" in markdown
    assert "3199.00" in markdown
    assert "3499.00" in markdown
    assert "3349.00" in markdown
    assert "Notebook" in markdown
    assert "| lojaA |" in markdown


def test_to_json_round_trips_through_json():
    a = _snapshot("lojaA", prices=[3199.0], price_labels={"Notebook": 3199.0}, titles=["Loja A"])
    b = _snapshot("lojaB", prices=[3499.0], price_labels={"Notebook": 3499.0}, titles=["Loja B"])

    comparison = comp.compare([a, b])
    payload = comp.to_json(comparison)

    assert isinstance(payload, dict)
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["sites"][0]["site"] == "lojaA"
    assert round_tripped["sites"][0]["titles"] == ["Loja A"]
    assert round_tripped["price_spread"]["Notebook"]["cheapest"] == "lojaA"
    assert round_tripped["summary"] == comparison.summary


# ── compare_directories ───────────────────────────────────────────────────

async def test_compare_directories_wires_summarize_and_compare(tmp_path):
    a = _site(tmp_path, "lojaA", {"index.html": _page("A", "<p>Notebook: R$ 3.199,00</p>")})
    b = _site(tmp_path, "lojaB", {"index.html": _page("B", "<p>Notebook: R$ 3.499,00</p>")})

    comparison = await comp.compare_directories({"lojaA": a, "lojaB": b})

    assert isinstance(comparison, comp.Comparison)
    assert [snapshot.site for snapshot in comparison.sites] == ["lojaA", "lojaB"]
    assert [snapshot.pages for snapshot in comparison.sites] == [1, 1]
    assert [snapshot.words for snapshot in comparison.sites] == [3, 3]
    assert comparison.sites[0].titles == ["A"]
    assert comparison.price_spread["Notebook"]["cheapest"] == "lojaA"
    assert comparison.summary


async def test_compare_directories_awaits_the_ai_per_site(tmp_path, monkeypatch):
    a = _site(tmp_path, "lojaA", {"index.html": _page("A", "<p>A Acme vende notebooks.</p>")})
    b = _site(tmp_path, "lojaB", {"index.html": _page("B", "<p>A Acme vende cadeiras.</p>")})
    calls: list[str] = []

    async def _fake_extract(text, max_chars: int = 8000) -> dict:
        calls.append(text)
        return {"entities": [_entity("Acme")], "counts": {"organization": 1}}

    monkeypatch.setattr(comp, "is_available", lambda: True)
    monkeypatch.setattr(comp, "extract_entities", _fake_extract)

    comparison = await comp.compare_directories({"lojaA": a, "lojaB": b})

    assert len(calls) == 2
    assert comparison.shared_entities == ["Acme"]
    assert comparison.unique_entities == {"lojaA": [], "lojaB": []}
