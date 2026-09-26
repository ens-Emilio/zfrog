"""Tests for AI summarization (no real model required — all calls mocked)."""

from pathlib import Path

import pytest

from zfrog.ai import summarize as summarize_mod
from zfrog.ai.schemas import SummaryResult


@pytest.mark.asyncio
async def test_summarize_text_empty():
    result = await summarize_mod.summarize_text("")

    assert result["summary"] == ""
    assert result["key_points"] == []


@pytest.mark.asyncio
async def test_summarize_text_unavailable(monkeypatch):
    monkeypatch.setattr(summarize_mod, "is_available", lambda: False)

    result = await summarize_mod.summarize_text("x" * 100)

    assert result["error"] == "AI indisponível"
    assert result["summary"] == ""


@pytest.mark.asyncio
async def test_summarize_text_structured(monkeypatch):
    async def fake_structured(messages, response_model, **kwargs):
        assert response_model is SummaryResult
        assert "conteúdo" in messages[1]["content"].lower()
        return SummaryResult(title="T", summary="S", key_points=["k1"])

    monkeypatch.setattr(summarize_mod, "is_available", lambda: True)
    monkeypatch.setattr(summarize_mod, "complete_structured", fake_structured)

    result = await summarize_mod.summarize_text("conteúdo da página")

    assert result["summary"] == "S"
    assert result["key_points"] == ["k1"]
    assert result["title"] == "T"
    assert "error" not in result


@pytest.mark.asyncio
async def test_summarize_text_fallback_unstructured(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("structured failed")

    async def fake_complete(messages, **kwargs):
        return '```json\n{"title": "T2", "summary": "S2", "key_points": ["k2"]}\n```'

    monkeypatch.setattr(summarize_mod, "is_available", lambda: True)
    monkeypatch.setattr(summarize_mod, "complete_structured", boom)
    monkeypatch.setattr(summarize_mod, "complete", fake_complete)

    result = await summarize_mod.summarize_text("conteúdo")

    assert result["summary"] == "S2"
    assert result["key_points"] == ["k2"]


@pytest.mark.asyncio
async def test_summarize_directory(tmp_path, monkeypatch):
    (tmp_path / "a.html").write_text(
        "<html><head><title>A</title></head><body><p>Página A com conteúdo.</p></body></html>",
        encoding="utf-8",
    )
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.html").write_text(
        "<html><head><title>B</title></head><body><p>Página B com conteúdo.</p></body></html>",
        encoding="utf-8",
    )

    calls: list[str] = []

    async def fake_summarize_text(text, url="", max_chars=6000):
        calls.append(text)
        return {"title": f"T{len(calls)}", "summary": f"S{len(calls)}", "key_points": []}

    monkeypatch.setattr(summarize_mod, "summarize_text", fake_summarize_text)

    result = await summarize_mod.summarize_directory(tmp_path, "https://example.com")

    assert [p["path"] for p in result["pages"]] == ["a.html", "sub/b.html"]
    assert result["pages"][0]["summary"] == "S1"
    # 2 pages + 1 global summary
    assert len(calls) == 3
    assert result["global_summary"]["summary"] == "S3"
    assert result["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_summarize_directory_empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(summarize_mod, "is_available", lambda: False)

    result = await summarize_mod.summarize_directory(tmp_path, "https://example.com")

    assert result["pages"] == []
    assert result["global_summary"] == {}


@pytest.mark.asyncio
async def test_summarize_directory_surfaces_ai_error(tmp_path, monkeypatch):
    """AI down + pages present must report why, not an empty global summary."""
    (tmp_path / "a.html").write_text(
        "<html><head><title>A</title></head><body><p>Conteúdo A.</p></body></html>", encoding="utf-8"
    )
    monkeypatch.setattr(summarize_mod, "is_available", lambda: False)

    result = await summarize_mod.summarize_directory(tmp_path, "https://example.com")

    assert len(result["pages"]) == 1
    assert result["global_summary"]["error"] == "AI indisponível"
    assert "AI indisponível" in summarize_mod.to_markdown(
        "https://example.com", result["global_summary"], result["pages"]
    )


def test_to_markdown_includes_points_and_error():
    md = summarize_mod.to_markdown(
        "https://example.com",
        {"title": "T", "summary": "S", "key_points": ["k1", "k2"], "error": "AI indisponível"},
    )

    assert "https://example.com" in md
    assert "AI indisponível" in md
    assert "- k1" in md
    assert "S" in md
