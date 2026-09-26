"""Tests for the Ask engine.

The engine used to answer through `ai.rag.SimpleRAG`, a word-overlap search that
ignored the embeddings it imported. It now uses `MultiSiteIndex` — the same
semantic index `chat` uses — so these tests pin that wiring rather than the
retrieval quality (which `test_multisite.py` covers).
"""

import json
from pathlib import Path

import pytest

from zfrog.engines.ask import AskEngine
from zfrog.models import JobCreate


@pytest.fixture(autouse=True)
def _isolated_output(tmp_path, monkeypatch):
    from zfrog.config import settings

    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")


@pytest.mark.asyncio
async def test_ask_basic(static_page_url, tmp_path):
    engine = AskEngine()
    job = JobCreate(url=static_page_url, mode="ask")
    output_dir = tmp_path / "ask"

    result = await engine.execute(job, output_dir)

    assert result.output_dir.exists()
    assert len(result.files) >= 2

    report = json.loads((output_dir / "ask_result.json").read_text(encoding="utf-8"))
    assert "query" in report
    assert "answer" in report
    assert "sources" in report


@pytest.mark.asyncio
async def test_ask_indexes_the_page_and_returns_citations(static_page_url, tmp_path, monkeypatch):
    """The page is indexed and the answer carries citations from the index."""
    from zfrog.ai import multisite as multisite_mod
    from zfrog.ai.client import is_available as real_is_available

    monkeypatch.setattr(multisite_mod, "is_available", lambda: False)
    monkeypatch.setattr(multisite_mod, "complete", _fake_complete)

    engine = AskEngine()
    job = JobCreate(url=static_page_url, mode="ask")
    output_dir = tmp_path / "ask"

    result = await engine.execute(job, output_dir)

    report = json.loads((output_dir / "ask_result.json").read_text(encoding="utf-8"))
    # The index found the page, so the answer cites it instead of coming back empty.
    assert report["sources"], "the indexed page should be cited"
    assert report["context"], "the citations should carry excerpts"
    assert any("chunk" in log or "Indexed" in log for log in result.logs)


@pytest.mark.asyncio
async def test_ask_degrades_without_ai(static_page_url, tmp_path, monkeypatch):
    """No model configured: the job still completes and says why."""
    from zfrog.engines import ask as ask_mod

    monkeypatch.setattr(ask_mod, "is_available", lambda: False, raising=False)

    engine = AskEngine()
    job = JobCreate(url=static_page_url, mode="ask")
    output_dir = tmp_path / "ask"

    result = await engine.execute(job, output_dir)

    assert result.output_dir.exists()
    report = json.loads((output_dir / "ask_result.json").read_text(encoding="utf-8"))
    assert report["answer"]


async def _fake_complete(messages, **kwargs):
    return "Resposta de teste."
