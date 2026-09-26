"""Tests for the multi-site RAG index (chunking, ranking, citations)."""

from __future__ import annotations

import json
import re
import zlib
from pathlib import Path

import pytest

from zfrog.ai import multisite
from zfrog.ai.multisite import Citation, MultiSiteIndex
from zfrog.config import settings
from zfrog.utils.text import extract_text

QUANTUM_URL = "https://quantum.test"
GARDEN_URL = "https://garden.test"

QUANTUM_TEXT = (
    "Quantum entanglement links particles across a distance, and the superconductor "
    "lattice experiment measured the correlation at very low temperature. The "
    "entanglement correlation survived for microseconds inside the cryostat."
)
GARDEN_TEXT = (
    "Tomato seedlings need compost, sunlight and steady watering. Compost feeds the "
    "soil and the tomato roots absorb the nutrients. Water the seedlings every morning "
    "and prune the lower leaves."
)

EMBED_DIM = 64


def _page(title: str, body: str) -> str:
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{title}</title></head><body><h1>{title}</h1><p>{body}</p></body></html>"
    )


def _write_site(root: Path, name: str, pages: dict[str, str]) -> Path:
    """Create a fake cloned site directory with the given relative pages."""
    site = root / name
    for rel, html in pages.items():
        target = site / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
    return site


def _tokens(text: str) -> list[str]:
    return re.findall(r"[0-9a-z]+", text.lower())


def _bag_vector(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Deterministic stand-in for a real embedding provider."""
    vector = [0.0] * dim
    for token in _tokens(text):
        vector[zlib.crc32(token.encode()) % dim] += 1.0
    return vector


async def _fake_embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    return [_bag_vector(text) for text in texts]


@pytest.fixture
def index(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    return MultiSiteIndex()


def test_add_site_indexes_html_tree(index, tmp_path):
    site = _write_site(
        tmp_path,
        "quantum",
        {"index.html": _page("Quantum", QUANTUM_TEXT), "docs/page.html": _page("Docs", QUANTUM_TEXT)},
    )

    added = index.add_site(QUANTUM_URL, site)

    assert added > 0
    assert index.root == tmp_path / "output" / ".rag-multi"
    assert index.sites() == [{"url": QUANTUM_URL, "pages": 2, "chunks": added}]
    assert index.stats()["sites"] == 1
    assert index.stats()["pages"] == 2
    assert index.stats()["chunks"] == added
    assert {c["url"] for c in index.chunks} == {
        f"{QUANTUM_URL}/index.html",
        f"{QUANTUM_URL}/docs/page.html",
    }
    assert all(c["site"] == QUANTUM_URL and c["text"].strip() for c in index.chunks)


def test_add_site_twice_replaces_chunks(index, tmp_path):
    site = _write_site(tmp_path, "quantum", {"index.html": _page("Quantum", QUANTUM_TEXT)})

    first = index.add_site(QUANTUM_URL, site)
    second = index.add_site(QUANTUM_URL, site)

    assert first > 0
    assert second == first
    assert len(index.chunks) == first
    assert index.sites() == [{"url": QUANTUM_URL, "pages": 1, "chunks": first}]


def test_remove_site_drops_only_that_site(index, tmp_path):
    quantum = _write_site(tmp_path, "quantum", {"index.html": _page("Quantum", QUANTUM_TEXT)})
    garden = _write_site(tmp_path, "garden", {"index.html": _page("Garden", GARDEN_TEXT)})
    quantum_chunks = index.add_site(QUANTUM_URL, quantum)
    garden_chunks = index.add_site(GARDEN_URL, garden)

    removed = index.remove_site(QUANTUM_URL)

    assert removed == quantum_chunks
    assert len(index.chunks) == garden_chunks
    assert [s["url"] for s in index.sites()] == [GARDEN_URL]
    assert all(c["site"] == GARDEN_URL for c in index.chunks)


def test_directory_named_html_is_not_indexed(index, tmp_path):
    site = _write_site(tmp_path, "decoy", {"index.html": _page("Real", QUANTUM_TEXT)})
    decoy_dir = site / "foo.html"
    decoy_dir.mkdir()
    (decoy_dir / "hidden.html").write_text(_page("Decoy", GARDEN_TEXT), encoding="utf-8")

    added = index.add_site("https://decoy.test", site)

    assert added > 0
    paths = {c["path"] for c in index.chunks}
    assert "foo.html" not in paths, "the directory itself is never a page"
    assert "index.html" in paths
    assert all((site / path).is_file() for path in paths)
    assert any("Quantum entanglement" in c["text"] for c in index.chunks)


async def test_query_without_llm_still_returns_citations(index, tmp_path, monkeypatch):
    monkeypatch.setattr(multisite, "is_available", lambda: False)
    site = _write_site(tmp_path, "quantum", {"index.html": _page("Quantum", QUANTUM_TEXT)})
    index.add_site(QUANTUM_URL, site)

    result = await index.query("quantum entanglement superconductor")

    assert result["answer"].strip()
    assert result["sites"] == [QUANTUM_URL]
    assert result["citations"], "citations must be returned even without an LLM"
    citation = result["citations"][0]
    assert isinstance(citation, Citation)
    assert citation.site == QUANTUM_URL
    assert citation.url == f"{QUANTUM_URL}/index.html"
    assert citation.path == "index.html"
    assert "entanglement" in citation.snippet
    assert citation.score > 0


async def test_query_returns_model_answer_with_citations(index, tmp_path, monkeypatch):
    monkeypatch.setattr(multisite, "is_available", lambda: True)
    monkeypatch.setattr(multisite, "embed", _fake_embed)
    prompts: list[list[dict]] = []

    async def fake_complete(messages, **kwargs):
        prompts.append(messages)
        return "O entrelaçamento quântico foi medido no criostato [1]."

    monkeypatch.setattr(multisite, "complete", fake_complete)
    site = _write_site(tmp_path, "quantum", {"index.html": _page("Quantum", QUANTUM_TEXT)})
    index.add_site(QUANTUM_URL, site)

    result = await index.query("entanglement")

    assert result["answer"] == "O entrelaçamento quântico foi medido no criostato [1]."
    assert len(prompts) == 1
    assert "[1]" in prompts[0][-1]["content"], "context must be numbered for [n] citations"
    citations = result["citations"]
    assert citations
    for citation in citations:
        assert citation.url.startswith(QUANTUM_URL)
        assert citation.path
        assert citation.snippet
        assert isinstance(citation.score, float)


async def test_query_ranks_matching_site_first(index, tmp_path, monkeypatch):
    monkeypatch.setattr(multisite, "is_available", lambda: False)
    quantum = _write_site(tmp_path, "quantum", {"index.html": _page("Quantum", QUANTUM_TEXT)})
    garden = _write_site(tmp_path, "garden", {"index.html": _page("Garden", GARDEN_TEXT)})
    index.add_site(QUANTUM_URL, quantum)
    index.add_site(GARDEN_URL, garden)

    result = await index.query("superconductor entanglement cryostat")

    assert result["citations"][0].site == QUANTUM_URL
    assert result["sites"][0] == QUANTUM_URL
    assert all(c.site != GARDEN_URL for c in result["citations"])


async def test_embedding_ranking_prefers_matching_site(index, tmp_path, monkeypatch):
    monkeypatch.setattr(multisite, "is_available", lambda: True)
    embed_batches: list[list[str]] = []

    async def recording_embed(texts, model=None):
        embed_batches.append(list(texts))
        return [_bag_vector(text) for text in texts]

    async def fake_complete(messages, **kwargs):
        return "resposta"

    monkeypatch.setattr(multisite, "embed", recording_embed)
    monkeypatch.setattr(multisite, "complete", fake_complete)
    quantum = _write_site(tmp_path, "quantum", {"index.html": _page("Quantum", QUANTUM_TEXT)})
    garden = _write_site(tmp_path, "garden", {"index.html": _page("Garden", GARDEN_TEXT)})
    index.add_site(QUANTUM_URL, quantum)
    index.add_site(GARDEN_URL, garden)

    result = await index.query("compost tomato seedlings")

    assert result["citations"][0].site == GARDEN_URL
    stored = json.loads(index.embeddings_file.read_text(encoding="utf-8"))
    assert set(stored) == {c["chunk_id"] for c in index.chunks}
    assert len(embed_batches) == 2, "chunks embedded once, then the question"

    await index.query("compost tomato seedlings")
    assert len(embed_batches) == 3, "existing embeddings must be reused"


def test_long_page_is_chunked_without_overlap_or_loss(index, tmp_path):
    sentences = [f"Sentence {n} about the superconductor lattice." for n in range(90)]
    body = " ".join(sentences)
    site = _write_site(tmp_path, "long", {"index.html": _page("Long", body)})

    added = index.add_site(QUANTUM_URL, site)

    chunks = [c["text"] for c in index.chunks]
    assert added == len(chunks) > 1
    assert all(len(chunk) <= multisite.CHUNK_CHARS for chunk in chunks)
    expected = " ".join(extract_text(_page("Long", body)).split())
    assert " ".join(chunks) == expected
    assert len({c["chunk_id"] for c in index.chunks}) == added


async def test_query_on_empty_index(index):
    result = await index.query("anything")

    assert result["answer"].strip()
    assert result["citations"] == []
    assert result["sites"] == []


def test_index_persists_across_instances(index, tmp_path):
    site = _write_site(tmp_path, "quantum", {"index.html": _page("Quantum", QUANTUM_TEXT)})
    added = index.add_site(QUANTUM_URL, site)

    reloaded = MultiSiteIndex(index.root)

    assert len(reloaded.chunks) == added
    assert reloaded.sites() == [{"url": QUANTUM_URL, "pages": 1, "chunks": added}]
    assert reloaded.remove_site(QUANTUM_URL) == added
    assert MultiSiteIndex(index.root).chunks == []
