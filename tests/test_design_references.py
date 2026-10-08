"""Tests for component extraction and the reference catalog.

Both are tested at their interpretation layer: the browser pass needs Chromium, but
everything that decides what the user sees — label, style grouping, default filtering,
catalog filtering — is pure and covered here.
"""

from __future__ import annotations

import time

import pytest

from zfrog.catalog import Card, Catalog, normalize_tag, site_of
from zfrog.components import build_extract, component_to_json, component_to_markdown, summarize


def _raw(**overrides):
    """A collector result with sensible defaults, so each test states only its point."""
    raw = {
        "found": True,
        "count": 1,
        "html": '<div class="hero"><p>Oi</p></div>',
        "text": "Oi",
        "tag": "div",
        "id": "",
        "cls": "hero",
        "computed": {
            "display": "grid",
            "position": "static",
            "width": "300px",
            "backgroundColor": "rgb(11, 18, 14)",
            "color": "rgb(233, 242, 236)",
            "fontFamily": "Inter, sans-serif",
            "fontSize": "16px",
            "boxShadow": "none",
            "opacity": "1",
            "borderRadius": "16px",
        },
        "box": {"x": 10.0, "y": 20.0, "width": 300.0, "height": 200.0},
        "children": [
            {
                "tag": "p",
                "cls": "",
                "text": "Oi",
                "display": "block",
                "width": "280",
                "height": "24",
            }
        ],
    }
    raw.update(overrides)
    return raw


class TestBuildExtract:
    def test_no_match_returns_none(self):
        """Distinguishes "matched nothing" from "matched, but empty"."""
        assert build_extract({"found": False, "count": 0}) is None
        assert build_extract({}) is None

    def test_label_prefers_the_id(self):
        assert build_extract(_raw(id="main", cls="hero big"), selector=".hero").label == "div#main"

    def test_label_uses_up_to_two_classes(self):
        component = build_extract(_raw(cls="hero big extra"), selector=".hero")
        assert component.label == "div.hero.big"

    def test_label_falls_back_to_the_tag(self):
        assert build_extract(_raw(cls=""), selector=".hero").label == "div"

    def test_html_is_sanitised(self):
        raw = _raw(html='<div><script>alert(1)</script><p onclick="x()">Oi</p></div>')
        component = build_extract(raw, selector="div")
        assert "<script" not in component.html
        assert "onclick" not in component.html
        assert "Oi" in component.html

    def test_fragment_keeps_its_shape(self):
        """The parser must not wrap a component in <html><body>."""
        component = build_extract(_raw(html="<a href='#'>x</a>"), selector="a")
        assert component.html == '<a href="#">x</a>'

    def test_oversized_html_is_truncated_and_flagged(self):
        raw = _raw(html="<div>" + "x" * 25_000 + "</div>")
        component = build_extract(raw, selector="div")
        assert component.truncated is True
        assert "<!-- truncado -->" in component.html
        assert len(component.html) < 25_000

    def test_match_count_is_preserved(self):
        assert build_extract(_raw(count=7), selector="li").match_count == 7


class TestInteresting:
    def test_defaults_are_left_out(self):
        styles = build_extract(_raw(), selector="div").interesting()
        assert "position" not in styles  # static
        assert "boxShadow" not in styles  # none
        assert "opacity" not in styles  # 1
        assert styles["display"] == "grid"
        assert styles["borderRadius"] == "16px"

    def test_full_computed_stays_available(self):
        """Filtered from the summary, never from the record."""
        component = build_extract(_raw(), selector="div")
        assert component.computed["position"] == "static"
        assert "position" not in summarize(component)["layout"]


class TestSummarize:
    def test_groups_cover_layout_paint_and_type(self):
        groups = summarize(build_extract(_raw(), selector="div"))
        assert set(groups) == {"layout", "paint", "typography"}
        assert groups["layout"]["display"] == "grid"
        assert groups["paint"]["backgroundColor"] == "rgb(11, 18, 14)"
        assert groups["typography"]["fontFamily"] == "Inter, sans-serif"


class TestComponentReport:
    def test_markdown_shows_geometry_styles_children_and_markup(self):
        component = build_extract(_raw(), selector=".hero")
        report = component_to_markdown(component)
        assert "# Component — div.hero" in report
        assert "300×200 px" in report
        assert "```html" in report
        assert "Direct children" in report

    def test_multiple_matches_are_disclosed(self):
        report = component_to_markdown(build_extract(_raw(count=3), selector=".card"))
        assert "3 match(es)" in report

    def test_json_round_trips(self):
        import json

        component = build_extract(_raw(), selector=".hero")
        payload = json.loads(component_to_json(component))
        assert payload["tag"] == "div"
        assert payload["box"]["width"] == 300.0
        assert payload["styles"]["display"] == "grid"


class TestSiteOf:
    def test_strips_www(self):
        assert site_of("https://www.exemplo.com.br/pagina") == "exemplo.com.br"
        assert site_of("https://exemplo.com/") == "exemplo.com"

    def test_url_without_host_returns_empty(self):
        assert site_of("not a url") == ""


class TestNormalizeTag:
    def test_lowercases_trims_and_drops_the_hash(self):
        assert normalize_tag("  #DashBoard ") == "dashboard"
        assert normalize_tag("") == ""


@pytest.fixture()
def catalog(tmp_path):
    return Catalog(tmp_path / "catalog.db")


def _card(**overrides):
    card = Card(
        id="c1",
        url="https://www.exemplo.com.br/dash",
        site="",
        title="Dashboard escuro",
        mode="jump",
        engine="jump",
        job_id="j1",
        screenshot="screenshots/desktop.png",
        created_at=time.time(),
        bytes=1000,
        tags=["Dash", "#dark"],
        tokens={
            "palette": [
                {"hex": "#0B120E", "count": 90, "role": "primary"},
                {"hex": "#3BD487", "count": 12, "role": "accent"},
            ],
            "fonts": [{"family": "Inter", "count": 10}],
        },
    )
    for key, value in overrides.items():
        setattr(card, key, value)
    return card


class TestCatalog:
    def test_save_fills_site_normalises_tags_and_reports_the_dominant_colour(self, catalog):
        saved = catalog.save(_card())
        assert saved.site == "exemplo.com.br"
        assert saved.tags == ["dark", "dash"]
        assert saved.dominant == "#0B120E"
        assert saved.palette == ["#0B120E", "#3BD487"]

    def test_saving_twice_updates_instead_of_duplicating(self, catalog):
        catalog.save(_card())
        catalog.save(_card(title="Outro"))
        assert catalog.count() == 1
        assert catalog.get("c1").title == "Outro"

    def test_filters_combine_with_and(self, catalog):
        catalog.save(_card())
        catalog.save(
            _card(
                id="c2",
                url="https://outro.com/loja",
                site="outro.com",
                tags=["loja"],
                tokens={"palette": [{"hex": "#FFFFFF", "count": 5}]},
            )
        )
        assert {c.id for c in catalog.list(tag="dark")} == {"c1"}
        assert {c.id for c in catalog.list(color="#FFFFFF")} == {"c2"}
        assert {c.id for c in catalog.list(site="outro.com")} == {"c2"}
        # No single card is both dark-tagged and white-dominant.
        assert catalog.list(tag="dark", color="#FFFFFF") == []

    def test_query_searches_url_title_and_note(self, catalog):
        catalog.save(_card())
        assert len(catalog.list(query="dash")) == 1
        assert len(catalog.list(query="Dashboard")) == 1
        assert len(catalog.list(query="inexistente")) == 0

    def test_date_range_filter(self, catalog):
        now = time.time()
        catalog.save(_card(id="old", created_at=now - 86_400 * 10))
        catalog.save(_card(id="new", created_at=now))
        assert {c.id for c in catalog.list(since=now - 86_400)} == {"new"}
        assert {c.id for c in catalog.list(until=now - 86_400)} == {"old"}

    def test_ordering_is_newest_first(self, catalog):
        now = time.time()
        catalog.save(_card(id="old", created_at=now - 100))
        catalog.save(_card(id="new", created_at=now))
        assert [c.id for c in catalog.list()] == ["new", "old"]

    def test_tag_adds_and_replaces(self, catalog):
        catalog.save(_card())
        assert catalog.tag("c1", ["novo"]) == ["dark", "dash", "novo"]
        assert catalog.tag("c1", ["so"], replace=True) == ["so"]

    def test_note_is_editable(self, catalog):
        catalog.save(_card())
        catalog.note("c1", "Falta a dobra inferior")
        assert catalog.get("c1").note == "Falta a dobra inferior"

    def test_aggregates_report_tags_colours_and_sites(self, catalog):
        catalog.save(_card())
        assert ("dark", 1) in catalog.tags()
        assert ("#3BD487", 1) in catalog.colors()
        assert ("exemplo.com.br", 1) in catalog.sites()

    def test_embedding_round_trips(self, catalog):
        catalog.save(_card())
        catalog.store_embedding("c1", [0.5, 0.25, 0.125], model="teste")
        vectors = catalog.embeddings()
        assert list(vectors["c1"][0]) == pytest.approx([0.5, 0.25, 0.125])
        assert vectors["c1"][1] == "teste"

    def test_embedding_is_replaced_not_duplicated(self, catalog):
        catalog.save(_card())
        catalog.store_embedding("c1", [1.0, 0.0], model="a")
        catalog.store_embedding("c1", [0.0, 1.0], model="b")
        vectors = catalog.embeddings()
        assert len(vectors) == 1
        assert list(vectors["c1"][0]) == pytest.approx([0.0, 1.0])

    def test_delete_removes_the_card_and_its_indexes(self, catalog):
        catalog.save(_card())
        catalog.store_embedding("c1", [1.0])
        assert catalog.delete("c1") is True
        assert catalog.count() == 0
        assert catalog.get("c1") is None
        assert catalog.tags() == []
        assert catalog.colors() == []
        assert catalog.embeddings() == {}

    def test_deleting_something_absent_reports_false(self, catalog):
        assert catalog.delete("nope") is False

    def test_missing_card_returns_none(self, catalog):
        assert catalog.get("nope") is None

    def test_empty_catalog_lists_nothing(self, catalog):
        assert catalog.list() == []
        assert catalog.count() == 0

    def test_limit_and_offset_paginate(self, catalog):
        now = time.time()
        for index in range(5):
            catalog.save(_card(id=f"c{index}", created_at=now + index))
        assert [c.id for c in catalog.list(limit=2)] == ["c4", "c3"]
        assert [c.id for c in catalog.list(limit=2, offset=2)] == ["c2", "c1"]
