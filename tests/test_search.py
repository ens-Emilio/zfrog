"""Tests for full-text and semantic search (SQLite FTS5 index)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import zfrog.search as search_mod
from zfrog.config import settings
from zfrog.search import SearchIndex


def _html(title: str, body: str) -> str:
    return f"<html><head><title>{title}</title></head><body><p>{body}</p></body></html>"


def _tree(root: Path, files: dict[str, str]) -> Path:
    """Write a small content tree and return its root."""
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _isolated_index(tmp_path, monkeypatch):
    """Own database per test, and never call a real embedding model."""
    monkeypatch.setattr(settings, "search_db", tmp_path / "search.db")
    monkeypatch.setattr(search_mod, "is_available", lambda: False)


async def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic stand-in for the embedding model: known phrases map to fixed vectors.

    "sea creatures" (the query) and any text about the ocean land on the same direction,
    while the text that merely repeats the query words lands somewhere else entirely.
    """
    vectors = []
    for text in texts:
        low = text.lower()
        if low.strip() == "sea creatures" or "ocean" in low:
            vectors.append([1.0, 0.0, 0.0])
        elif "salmon" in low:
            vectors.append([0.0, 1.0, 0.0])
        else:
            vectors.append([0.0, 0.0, 1.0])
    return vectors


def test_index_directory_counts_pages_and_is_idempotent(tmp_path):
    root = _tree(
        tmp_path / "site",
        {
            "alpha.html": _html("Alpha", "unicorn sighting in the park today"),
            "beta.html": _html("Beta", "regular city news about traffic"),
            "docs/gamma.html": _html("Gamma", "more city news about the weather"),
        },
    )
    index = SearchIndex()

    assert index.index_directory(root, url="https://example.com") == 3
    assert index.stats()["pages"] == 3

    # Unchanged content: same count, still three rows.
    assert index.index_directory(root, url="https://example.com") == 3
    assert index.stats()["pages"] == 3

    # Changed content replaces the row instead of adding one.
    (root / "alpha.html").write_text(_html("Alpha", "hippogriff spotted downtown"), encoding="utf-8")
    assert index.index_directory(root, url="https://example.com") == 3
    assert index.stats()["pages"] == 3

    hits = index.search("hippogriff")
    assert [Path(hit.path).name for hit in hits] == ["alpha.html"]
    assert index.search("unicorn") == []


def test_fulltext_search_returns_path_and_snippet(tmp_path):
    root = _tree(
        tmp_path / "site",
        {
            "alpha.html": _html("Alpha", "a unicorn was sighted in the park this morning"),
            "beta.html": _html("Beta", "the council approved a new bike lane"),
        },
    )
    index = SearchIndex()
    index.index_directory(root)

    hits = index.search("unicorn")

    assert [Path(hit.path).name for hit in hits] == ["alpha.html"]
    hit = hits[0]
    assert hit.title == "Alpha"
    assert "unicorn" in hit.snippet.lower()
    assert 0 < len(hit.snippet) <= 200
    assert hit.score > 0


def test_fulltext_search_with_hostile_input_falls_back_to_like(tmp_path):
    root = _tree(
        tmp_path / "site",
        {
            "alpha.html": _html("Alpha", "the keyword unbalanced appears right here"),
            "beta.html": _html("Beta", "nothing of interest"),
        },
    )
    index = SearchIndex()
    index.index_directory(root)

    hits = index.search('"unbalanced')  # invalid FTS5 syntax on purpose

    assert [Path(hit.path).name for hit in hits] == ["alpha.html"]
    assert "unbalanced" in hits[0].snippet.lower()


def test_directory_named_like_a_page_is_not_indexed(tmp_path):
    root = tmp_path / "tree"
    _tree(root, {"real.html": _html("Real", "a needle in the haystack")})
    (root / "foo.html").mkdir()

    index = SearchIndex()

    assert index.index_directory(root) == 1
    assert index.stats()["pages"] == 1
    assert [Path(hit.path).name for hit in index.search("needle")] == ["real.html"]


def test_only_content_files_are_indexed(tmp_path):
    root = _tree(
        tmp_path / "site",
        {
            "page.html": _html("Page", "searchable html body"),
            "notes.md": "# Notes\n\nsearchable markdown body",
            "data.json": '{"text": "searchable json body"}',
            "logo.png": "searchable png bytes",
        },
    )
    index = SearchIndex()

    assert index.index_directory(root) == 2
    assert index.stats()["pages"] == 2
    assert index.index_file(root / "logo.png") is False
    assert index.index_file(root / "notes.md") is False  # already indexed, unchanged
    extra = tmp_path / "extra.md"
    extra.write_text("searchable extra body", encoding="utf-8")
    assert index.index_file(extra) is True
    assert index.index_file(extra) is False  # unchanged
    assert index.stats()["pages"] == 3
    indexed = {Path(hit.path).name for hit in index.search("searchable")}
    assert indexed == {"page.html", "notes.md", "extra.md"}


def test_semantic_search_ranks_by_meaning_not_keywords(tmp_path, monkeypatch):
    root = _tree(
        tmp_path / "site",
        {
            "waves.html": _html("Waves", "the ocean rises and falls twice a day"),
            "salmon.html": _html("Salmon", "salmon sea creatures salmon sea creatures"),
            "traffic.html": _html("Traffic", "cars queue on the ring road"),
        },
    )
    monkeypatch.setattr(search_mod, "is_available", lambda: True)
    monkeypatch.setattr(search_mod, "embed", _fake_embed)

    index = SearchIndex()
    assert index.index_directory(root) == 3
    assert index.stats()["embeddings"] == 3  # one chunk per short page

    # Keyword matching only sees the page that literally repeats the query words.
    lexical = index.search("sea creatures", mode="fulltext")
    assert [Path(hit.path).name for hit in lexical] == ["salmon.html"]

    semantic = index.search("sea creatures", mode="semantic")
    assert [Path(hit.path).name for hit in semantic][0] == "waves.html"
    assert "ocean" in semantic[0].snippet
    assert semantic[0].score == pytest.approx(1.0)
    assert semantic[1].score == pytest.approx(0.0)

    # Re-indexing changed content replaces the vectors instead of stacking new ones.
    (root / "waves.html").write_text(
        _html("Waves", "the ocean is calm and the tide is low"), encoding="utf-8"
    )
    index.index_directory(root)
    assert index.stats()["embeddings"] == 3
    assert "calm" in index.search("calm")[0].snippet


def test_semantic_search_uses_the_closest_chunk_of_a_long_page(tmp_path, monkeypatch):
    filler = "lorem ipsum dolor sit amet " * 100  # pushes the page past several chunks
    body = f"PREFACE {filler} the ocean rises and falls twice a day {filler}"
    root = _tree(
        tmp_path / "site",
        {
            "long.html": _html("Long", body),
            "other.html": _html("Other", "cars queue on the ring road"),
        },
    )
    monkeypatch.setattr(search_mod, "is_available", lambda: True)
    monkeypatch.setattr(search_mod, "embed", _fake_embed)

    index = SearchIndex()
    index.index_directory(root)

    assert index.stats()["embeddings"] > 2  # the long page was split into several chunks

    hits = index.search("sea creatures", mode="semantic")

    assert [Path(hit.path).name for hit in hits][0] == "long.html"
    assert hits[0].score == pytest.approx(1.0)
    assert len(hits[0].snippet) <= 200
    # The excerpt comes from the chunk that matched, not from the top of the page.
    assert "PREFACE" not in hits[0].snippet


def test_semantic_search_without_vectors_returns_nothing(tmp_path, monkeypatch):
    root = _tree(tmp_path / "site", {"alpha.html": _html("Alpha", "the ocean is wide")})
    index = SearchIndex()
    index.index_directory(root)

    # No AI model configured: nothing is embedded and semantic search stays empty.
    assert index.stats()["embeddings"] == 0
    assert index.search("sea creatures", mode="semantic") == []

    # Model available but still no stored vectors: same empty result, no exception.
    monkeypatch.setattr(search_mod, "is_available", lambda: True)
    assert index.search("sea creatures", mode="semantic") == []


@pytest.mark.asyncio
async def test_semantic_search_inside_a_running_event_loop(tmp_path, monkeypatch):
    """The API endpoint indexes and searches from async code — the bridge must hold."""
    root = _tree(tmp_path / "site", {"waves.html": _html("Waves", "the ocean is wide")})
    monkeypatch.setattr(search_mod, "is_available", lambda: True)
    monkeypatch.setattr(search_mod, "embed", _fake_embed)

    index = SearchIndex()

    assert index.index_directory(root) == 1
    hits = index.search("sea creatures", mode="semantic")
    assert [Path(hit.path).name for hit in hits] == ["waves.html"]


def test_drop_site_removes_pages_fts_and_embeddings(tmp_path, monkeypatch):
    monkeypatch.setattr(search_mod, "is_available", lambda: True)
    monkeypatch.setattr(search_mod, "embed", _fake_embed)

    site_a = _tree(tmp_path / "a", {"index.html": _html("A", "a unicorn grazes in the meadow")})
    site_b = _tree(tmp_path / "b", {"index.html": _html("B", "traffic jam on the ring road")})

    index = SearchIndex()
    assert index.index_directory(site_a, url="https://a.example", site="a.example") == 1
    assert index.index_directory(site_b, url="https://b.example", site="b.example") == 1
    assert index.sites() == ["a.example", "b.example"]
    assert index.stats() == {
        "pages": 2,
        "sites": 2,
        "embeddings": 2,
        "db": str(settings.search_db),
    }
    assert index.search("unicorn")

    assert index.drop_site("a.example") == 1

    assert index.sites() == ["b.example"]
    assert index.stats()["pages"] == 1
    assert index.stats()["embeddings"] == 1
    assert index.search("unicorn") == []
    assert [Path(hit.path).name for hit in index.search("traffic")] == ["index.html"]

    with sqlite3.connect(index.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM embeddings WHERE path LIKE ?", (f"{site_a}%",)
            ).fetchone()[0]
            == 0
        )
        # The FTS index must still agree with the surviving content.
        conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('integrity-check')")
