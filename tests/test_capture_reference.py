"""Tests for the capture step that turns a finished job into a reference card.

The browser pass itself needs Chromium and a live page, so what is tested here is the
part that decides *what gets recorded*: which page represents the capture, how the
screenshot path is stored, how tags are normalised, and that a catalog failure does not
lose the capture.
"""

from __future__ import annotations

import pytest

from zfrog.catalog import Catalog
from zfrog.pipeline.reference import (
    DESIGN_MODES,
    parse_tags,
    register_reference,
    screenshot_reference,
)
from zfrog.pipeline.screenshot import CaptureReport, _entry_page
from zfrog.tokens import ColorUse, DesignTokens


def _tokens(title: str = "Exemplo") -> DesignTokens:
    return DesignTokens(
        url="https://exemplo.com/",
        title=title,
        palette=[ColorUse("#0B120E", 10, {"backgroundColor": 10}, role="primary")],
        element_count=5,
    )


class TestEntryPage:
    """Which page a capture is *about* — the one the card describes."""

    def test_index_html_wins_over_alphabetical_order(self, tmp_path):
        (tmp_path / "about.html").write_text("<html></html>")
        (tmp_path / "index.html").write_text("<html></html>")
        files = sorted(tmp_path.glob("*.html"))
        assert _entry_page(files, tmp_path).name == "index.html"

    def test_shallowest_page_wins_without_an_index(self, tmp_path):
        (tmp_path / "deep").mkdir()
        (tmp_path / "deep" / "pagina.html").write_text("<html></html>")
        (tmp_path / "sobre.html").write_text("<html></html>")
        files = sorted(tmp_path.rglob("*.html"))
        assert _entry_page(files, tmp_path).name == "sobre.html"

    def test_index_in_a_subdirectory_still_wins(self, tmp_path):
        """A site whose entry is not at the root: the index is still the entry."""
        (tmp_path / "blog").mkdir()
        (tmp_path / "blog" / "index.html").write_text("<html></html>")
        (tmp_path / "a.html").write_text("<html></html>")
        files = sorted(tmp_path.rglob("*.html"))
        assert _entry_page(files, tmp_path).name == "index.html"


class TestScreenshotReference:
    def test_path_inside_the_media_root_is_stored_relative(self, tmp_path):
        shot = tmp_path / "output" / "job1" / "screenshots" / "index.png"
        shot.parent.mkdir(parents=True)
        shot.write_bytes(b"x")

        ref = screenshot_reference(shot, tmp_path / "output")
        assert ref == "job1/screenshots/index.png"

    def test_path_outside_the_root_keeps_the_absolute_path(self, tmp_path):
        """The endpoint's containment check decides servability, not this function."""
        shot = tmp_path / "fora" / "index.png"
        shot.parent.mkdir(parents=True)
        shot.write_bytes(b"x")

        ref = screenshot_reference(shot, tmp_path / "output")
        assert ref == str(shot)

    def test_missing_screenshot_becomes_empty(self, tmp_path):
        assert screenshot_reference(tmp_path / "nao-existe.png", tmp_path) == ""

    def test_none_becomes_empty(self, tmp_path):
        assert screenshot_reference(None, tmp_path) == ""


class TestParseTags:
    def test_comma_separated_string(self):
        assert parse_tags("Dark, fintech , #dash") == ["dark", "fintech", "dash"]

    def test_list_input(self):
        assert parse_tags(["Dark", " #Dash "]) == ["dark", "dash"]

    def test_empty_entries_are_dropped(self):
        assert parse_tags("dark,,  ,fintech") == ["dark", "fintech"]

    def test_none_and_empty(self):
        assert parse_tags(None) == []
        assert parse_tags("") == []
        assert parse_tags([]) == []


class TestRegisterReference:
    @pytest.fixture()
    def catalog(self, tmp_path):
        return Catalog(tmp_path / "catalog.db")

    @pytest.fixture()
    def shot(self, tmp_path):
        path = tmp_path / "output" / "job1" / "screenshots" / "index.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"png-bytes")
        return path

    def test_writes_a_card_with_tokens_and_screenshot(self, catalog, shot, tmp_path):
        card = register_reference(
            url="https://www.exemplo.com.br/dash",
            mode="auto",
            engine="playwright",
            tokens=_tokens("Dashboard"),
            screenshot=shot,
            job_id="job1",
            tags=["Dash", "#escuro"],
            catalog=catalog,
        )

        assert card is not None
        assert card.site == "exemplo.com.br"
        assert card.title == "Dashboard"
        assert card.tags == ["dash", "escuro"]
        assert card.dominant == "#0B120E"
        assert catalog.count() == 1

    def test_card_without_a_screenshot_still_records_the_tokens(self, catalog):
        """A missing thumbnail must not lose the extraction."""
        card = register_reference(
            url="https://exemplo.com/",
            mode="auto",
            engine="static_file",
            tokens=_tokens(),
            screenshot=None,
            catalog=catalog,
        )

        assert card is not None
        assert card.screenshot == ""
        assert card.tokens["element_count"] == 5

    def test_two_captures_of_the_same_url_make_two_cards(self, catalog, shot):
        """Re-capturing is a new reference, not an update — the catalog keeps history."""
        first = register_reference(
            url="https://exemplo.com/", mode="auto", engine="static_file",
            tokens=_tokens("A"), screenshot=shot, catalog=catalog,
        )
        second = register_reference(
            url="https://exemplo.com/", mode="auto", engine="static_file",
            tokens=_tokens("B"), screenshot=shot, catalog=catalog,
        )

        assert first is not None and second is not None
        assert first.id != second.id
        assert catalog.count() == 2
        assert {card.title for card in catalog.list()} == {"A", "B"}

    def test_catalog_failure_returns_none_instead_of_raising(self, tmp_path):
        """The capture is on disk; a broken index must not fail the job."""

        class Broken(Catalog):
            def save(self, card):  # type: ignore[override]
                raise RuntimeError("catálogo indisponível")

        card = register_reference(
            url="https://exemplo.com/",
            mode="auto",
            engine="static_file",
            tokens=_tokens(),
            catalog=Broken(tmp_path / "quebrado.db"),
        )

        assert card is None

    def test_card_carries_the_job_id_for_traceability(self, catalog):
        card = register_reference(
            url="https://exemplo.com/", mode="scrape", engine="playwright",
            tokens=_tokens(), job_id="abc123", catalog=catalog,
        )
        assert card is not None and card.job_id == "abc123"


class TestDesignModes:
    def test_capture_modes_are_covered(self):
        for mode in ("auto", "mirror", "scrape", "singlepage", "delta"):
            assert mode in DESIGN_MODES

    def test_analysis_modes_are_not(self):
        """A palette from a text-analysis engine would be noise."""
        for mode in ("analyze", "compare", "ask", "summarize", "pdf", "entities"):
            assert mode not in DESIGN_MODES

    def test_jump_is_not_here_because_it_registers_its_own_card(self):
        """Routing jump through the pipeline too would write two cards per capture."""
        assert "jump" not in DESIGN_MODES


class TestCaptureReport:
    def test_defaults_are_empty(self):
        report = CaptureReport()
        assert report.screenshots == []
        assert report.tokens is None
        assert report.entry_screenshot is None
        assert report.token_source == ""

    def test_carries_the_entry_screenshot_used_by_the_card(self, tmp_path):
        path = tmp_path / "index.png"
        report = CaptureReport(entry_screenshot=path, tokens=_tokens())
        assert report.entry_screenshot == path
