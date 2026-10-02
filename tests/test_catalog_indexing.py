"""Tests for the catalog's embedding pass.

The provider call is never made here: what is tested is the *reporting*, which is the
part that decides what a user sees when indexing cannot happen. A failure used to raise
and surface as a traceback in the middle of a command that had another answer ready.
"""

from __future__ import annotations

import time

import pytest

from zfrog.catalog import Card, Catalog
from zfrog.visual_search import IndexResult, embed_catalog


def _card(card_id: str = "c1") -> Card:
    return Card(
        id=card_id,
        url=f"https://{card_id}.exemplo.com/",
        site=f"{card_id}.exemplo.com",
        title="Exemplo",
        created_at=time.time(),
        tokens={"palette": [{"hex": "#0B120E", "count": 9, "role": "primary"}]},
    )


@pytest.fixture()
def catalog(tmp_path):
    store = Catalog(tmp_path / "catalog.db")
    store.save(_card())
    return store


class TestIndexResult:
    def test_ok_when_there_is_no_reason(self):
        assert IndexResult(indexed=3).ok is True

    def test_not_ok_when_a_reason_is_given(self):
        assert IndexResult(reason="nada").ok is False


class TestEmbedCatalogReporting:
    async def test_no_embedding_model_is_reported_not_raised(self, catalog, monkeypatch):
        monkeypatch.setattr("zfrog.ai.client.embedding_configured", lambda: False)

        result = await embed_catalog(catalog)

        assert result.indexed == 0
        assert "ZFROG_AI_EMBEDDING" in result.reason

    async def test_empty_catalog_says_so_instead_of_blaming_the_model(self, tmp_path, monkeypatch):
        """Three different situations need three different actions from the user."""
        monkeypatch.setattr("zfrog.ai.client.embedding_configured", lambda: True)

        result = await embed_catalog(Catalog(tmp_path / "vazio.db"))

        assert result.indexed == 0
        assert "vazio" in result.reason
        assert "EMBEDDING" not in result.reason

    async def test_a_failing_model_is_reported_with_its_first_line(self, catalog, monkeypatch):
        monkeypatch.setattr("zfrog.ai.client.embedding_configured", lambda: True)

        async def boom(*args, **kwargs):
            raise RuntimeError("provider not provided\n" + "documentation " * 50)

        monkeypatch.setattr("zfrog.ai.client.embed", boom)

        result = await embed_catalog(catalog)

        assert result.indexed == 0
        assert "provider not provided" in result.reason
        # The provider's trailing documentation must not reach the message.
        assert "documentation" not in result.reason
        assert "\n" not in result.reason

    async def test_already_indexed_is_reported(self, catalog, monkeypatch):
        monkeypatch.setattr("zfrog.ai.client.embedding_configured", lambda: True)
        catalog.store_embedding("c1", [1.0, 0.0], model="m")

        result = await embed_catalog(catalog)

        assert result.indexed == 0
        assert "indexadas" in result.reason

    async def test_force_reindexes_an_already_indexed_card(self, catalog, monkeypatch):
        monkeypatch.setattr("zfrog.ai.client.embedding_configured", lambda: True)
        catalog.store_embedding("c1", [1.0, 0.0], model="antigo")

        async def fake_embed(texts, model=None):
            return [[0.0, 1.0] for _ in texts]

        monkeypatch.setattr("zfrog.ai.client.embed", fake_embed)
        monkeypatch.setattr("zfrog.ai.client.get_embedding_model", lambda: "novo")

        result = await embed_catalog(catalog, force=True)

        assert result.indexed == 1
        assert result.ok is True
        vector, model = catalog.embeddings()["c1"]
        assert list(vector) == pytest.approx([0.0, 1.0])
        assert model == "novo"

    async def test_only_cards_without_vectors_are_embedded(self, tmp_path, monkeypatch):
        store = Catalog(tmp_path / "catalog.db")
        store.save(_card("com"))
        store.save(_card("sem"))
        store.store_embedding("com", [1.0], model="m")
        monkeypatch.setattr("zfrog.ai.client.embedding_configured", lambda: True)

        seen: list[str] = []

        async def fake_embed(texts, model=None):
            seen.extend(texts)
            return [[0.5] for _ in texts]

        monkeypatch.setattr("zfrog.ai.client.embed", fake_embed)

        result = await embed_catalog(store)

        assert result.indexed == 1
        assert len(seen) == 1
        assert "sem.exemplo.com" in seen[0]
