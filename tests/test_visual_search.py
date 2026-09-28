"""Tests for the descriptive search over the catalog.

The embedding path is exercised with a stub vector map: what matters is that the
ranking works, that the lexical fallback answers when no model is configured, and that
the description is stable — not that a particular provider is reachable.
"""

from __future__ import annotations

import time

import pytest

from zfrog.catalog import Card, Catalog
from zfrog.visual_search import describe, search


def _card(card_id: str, tokens: dict, **overrides) -> Card:
    card = Card(
        id=card_id,
        url=f"https://{card_id}.exemplo.com/",
        site=f"{card_id}.exemplo.com",
        title=f"Site {card_id}",
        created_at=time.time(),
        tokens=tokens,
    )
    for key, value in overrides.items():
        setattr(card, key, value)
    return card


DARK_ROUNDED = {
    "palette": [{"hex": "#0B120E", "count": 90, "role": "primary"}],
    "fonts": [{"family": "Inter", "count": 10}],
    "radii": [["16px", 12]],
    "shadows": [["0px 8px 32px rgba(0,0,0,.35)", 4]],
}

LIGHT_SQUARE = {
    "palette": [{"hex": "#FFFFFF", "count": 90, "role": "primary"}],
    "fonts": [{"family": "Georgia, serif", "count": 10}],
    "radii": [["0px", 40]],
    "shadows": [],
}


class TestDescribe:
    def test_dark_background_becomes_searchable_words(self):
        text = describe(_card("escuro", DARK_ROUNDED))
        assert "muito escuro" in text
        assert "neutro" in text

    def test_rounding_and_shadows_are_described(self):
        text = describe(_card("escuro", DARK_ROUNDED))
        assert "cantos muito arredondados" in text
        assert "sombras amplas" in text

    def test_serif_is_detected_from_the_family_name(self):
        assert "serifada" in describe(_card("claro", LIGHT_SQUARE))

    def test_square_corners_are_described_as_such(self):
        text = describe(_card("claro", LIGHT_SQUARE))
        assert "cantos retos" in text
        assert "sem sombras" in text

    def test_vivid_colour_gets_hue_and_vividness(self):
        tokens = {"palette": [{"hex": "#3BD487", "count": 5, "role": "accent"}]}
        text = describe(_card("verde", tokens))
        assert "verde" in text
        assert "vivo" in text

    def test_description_is_stable_across_calls(self):
        """A drifting description would silently invalidate stored embeddings."""
        card = _card("escuro", DARK_ROUNDED)
        assert describe(card) == describe(card)

    def test_tags_and_note_are_searchable(self):
        card = _card("x", DARK_ROUNDED, tags=["dashboard"], note="hero com gradiente")
        text = describe(card)
        assert "dashboard" in text
        assert "gradiente" in text

    def test_card_without_tokens_still_describes_itself(self):
        text = describe(_card("vazio", {}))
        assert "Site vazio" in text
        assert "vazio.exemplo.com" in text

    def test_unreadable_hex_is_skipped(self):
        tokens = {"palette": [{"hex": "nope", "count": 1, "role": "primary"}]}
        assert "cor" not in describe(_card("x", tokens))


class TestSearch:
    @pytest.fixture()
    def catalog(self, tmp_path):
        cat = Catalog(tmp_path / "catalog.db")
        cat.save(_card("escuro", DARK_ROUNDED))
        cat.save(_card("claro", LIGHT_SQUARE))
        return cat

    def test_lexical_fallback_matches_words(self, catalog):
        """With no embeddings at all, a search still answers."""
        hits = search(catalog, "escuro arredondado")
        assert hits
        assert hits[0].card.id == "escuro"

    def test_lexical_fallback_ranks_by_overlap(self, catalog):
        hits = search(catalog, "serifada")
        assert [hit.card.id for hit in hits] == ["claro"]

    def test_empty_query_returns_nothing(self, catalog):
        assert search(catalog, "") == []
        assert search(catalog, "   ") == []

    def test_empty_catalog_returns_nothing(self, tmp_path):
        assert search(Catalog(tmp_path / "vazio.db"), "escuro") == []

    def test_vectors_are_used_when_the_query_is_embedded(self, catalog):
        """The ranking must follow cosine similarity, not word overlap."""
        # "claro" points the same way as the query, "escuro" only partially — which is
        # the opposite of what the lexical ranking says, so a passing test proves the
        # vector path is what decided the order.
        vectors = {
            "escuro": ([0.8, 0.6], "stub"),
            "claro": ([1.0, 0.0], "stub"),
        }
        hits = search(catalog, "claro", vectors=vectors, query_vector=[1.0, 0.0])
        assert [hit.card.id for hit in hits] == ["claro", "escuro"]
        assert hits[0].score == pytest.approx(1.0)

    def test_orthogonal_matches_are_dropped(self, catalog):
        """Cosine 0 means unrelated; reporting it as a hit would be noise."""
        vectors = {"escuro": ([1.0, 0.0], "stub"), "claro": ([0.0, 1.0], "stub")}
        hits = search(catalog, "escuro", vectors=vectors, query_vector=[0.0, 1.0])
        assert [hit.card.id for hit in hits] == ["claro"]

    def test_mismatched_vector_lengths_score_zero(self, catalog):
        """A vector from a different model must not be compared as if it matched."""
        vectors = {"escuro": ([1.0, 0.0, 0.0], "outro-modelo")}
        hits = search(catalog, "escuro", vectors=vectors, query_vector=[1.0, 0.0])
        assert "escuro" not in {hit.card.id for hit in hits}

    def test_cards_without_a_vector_fall_back_to_words(self, catalog):
        vectors = {"claro": ([0.0, 1.0], "stub")}
        hits = search(catalog, "escuro", vectors=vectors, query_vector=[0.0, 1.0])
        ids = {hit.card.id for hit in hits}
        assert ids == {"claro", "escuro"}

    def test_limit_is_respected(self, catalog):
        assert len(search(catalog, "site", limit=1)) == 1

    def test_no_hit_when_nothing_matches(self, catalog):
        assert search(catalog, "zebra amarela xilofone") == []
