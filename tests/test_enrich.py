"""Tests for content enrichment (sentiment + tags) — no real model required."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from zfrog.ai import enrich as enrich_mod
from zfrog.ai.enrich import analyze_sentiment, suggest_tags
from zfrog.ai.schemas import SentimentResult, TagResult
from zfrog.engines import enrich as engine_mod
from zfrog.engines.enrich import EnrichEngine
from zfrog.models import JobCreate, ProbeResult

PAGE_URL = "https://example.com/produto"
PAGE_HTML = (
    "<html><head><title>Promoção de verão</title></head>"
    "<body><p>O preço do produto caiu e a promoção de verão é excelente.</p></body></html>"
)

NEUTRAL = {"sentiment": "neutral", "score": 0.0, "rationale": ""}


async def _no_ai_call(*args, **kwargs):
    raise AssertionError("the AI must not be called")


# ── analyze_sentiment / suggest_tags ──────────────────────────────────────


async def test_blank_text_returns_neutral_defaults_without_calling_ai(monkeypatch):
    monkeypatch.setattr(enrich_mod, "is_available", lambda: True)
    monkeypatch.setattr(enrich_mod, "complete_structured", _no_ai_call)
    monkeypatch.setattr(enrich_mod, "complete", _no_ai_call)

    assert await analyze_sentiment("  \n\t ") == NEUTRAL
    assert await suggest_tags("") == {"tags": []}


async def test_unavailable_ai_reports_error_without_raising(monkeypatch):
    monkeypatch.setattr(enrich_mod, "is_available", lambda: False)
    monkeypatch.setattr(enrich_mod, "complete_structured", _no_ai_call)
    monkeypatch.setattr(enrich_mod, "complete", _no_ai_call)

    sentiment = await analyze_sentiment("O preço caiu e a promoção é excelente.")
    tags = await suggest_tags("O preço caiu e a promoção é excelente.")

    assert sentiment == {**NEUTRAL, "error": "AI unavailable"}
    assert tags == {"tags": [], "error": "AI unavailable"}


async def test_structured_sentiment_is_normalised_and_clamped(monkeypatch):
    seen: dict[str, object] = {}

    async def fake_structured(messages, response_model, **kwargs):
        seen["response_model"] = response_model
        seen["temperature"] = kwargs.get("temperature")
        seen["content"] = messages[-1]["content"]
        # Providers do return out-of-range scores; pydantic would reject them here,
        # so build the model without validation to prove the clamp still happens.
        return SentimentResult.model_construct(sentiment="positivo", score=5.0, rationale="Ótimo")

    monkeypatch.setattr(enrich_mod, "is_available", lambda: True)
    monkeypatch.setattr(enrich_mod, "complete_structured", fake_structured)
    monkeypatch.setattr(enrich_mod, "complete", _no_ai_call)

    result = await analyze_sentiment("promoção excelente")

    assert seen["response_model"] is SentimentResult
    assert seen["temperature"] == 0.0
    assert "promoção excelente" in seen["content"]
    assert result == {"sentiment": "positive", "score": 1.0, "rationale": "Ótimo"}
    assert "error" not in result


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("positivo", "positive"),
        ("NEGATIVO", "negative"),
        ("neutro", "neutral"),
        ("positive", "positive"),
        ("muito negativo", "negative"),
        ("talvez", "neutral"),
        (None, "neutral"),
    ],
)
async def test_sentiment_labels_are_mapped(monkeypatch, label, expected):
    async def fake_structured(messages, response_model, **kwargs):
        return SentimentResult.model_construct(sentiment=label, score=-3.5, rationale="")

    monkeypatch.setattr(enrich_mod, "is_available", lambda: True)
    monkeypatch.setattr(enrich_mod, "complete_structured", fake_structured)

    result = await analyze_sentiment("conteúdo")

    assert result["sentiment"] == expected
    assert result["score"] == -1.0


async def test_structured_tags_are_cleaned_and_capped(monkeypatch):
    seen: dict[str, object] = {}

    async def fake_structured(messages, response_model, **kwargs):
        seen["response_model"] = response_model
        seen["temperature"] = kwargs.get("temperature")
        return TagResult(tags=[" Preço ", "preço", "", "Promoção", "promoção ", "Verão"])

    monkeypatch.setattr(enrich_mod, "is_available", lambda: True)
    monkeypatch.setattr(enrich_mod, "complete_structured", fake_structured)
    monkeypatch.setattr(enrich_mod, "complete", _no_ai_call)

    result = await suggest_tags("texto", max_tags=3)

    assert seen["response_model"] is TagResult
    assert seen["temperature"] == 0.0
    assert result == {"tags": ["preço", "promoção", "verão"]}
    assert "error" not in result


async def test_fallback_to_loose_json_from_complete(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("structured failed")

    async def fake_complete(messages, **kwargs):
        assert kwargs.get("temperature") == 0.0
        return '```json\n{"sentiment": "negativo", "score": -0.4, "rationale": "reclamações"}\n```'

    monkeypatch.setattr(enrich_mod, "is_available", lambda: True)
    monkeypatch.setattr(enrich_mod, "complete_structured", boom)
    monkeypatch.setattr(enrich_mod, "complete", fake_complete)

    result = await analyze_sentiment("péssimo atendimento")

    assert result == {"sentiment": "negative", "score": -0.4, "rationale": "reclamações"}


async def test_tag_fallback_accepts_a_bare_json_array(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("structured failed")

    async def fake_complete(messages, **kwargs):
        return 'Claro!\n```json\n[" Preço ", "PREÇO", "Promoção"]\n```'

    monkeypatch.setattr(enrich_mod, "is_available", lambda: True)
    monkeypatch.setattr(enrich_mod, "complete_structured", boom)
    monkeypatch.setattr(enrich_mod, "complete", fake_complete)

    result = await suggest_tags("texto")

    assert result == {"tags": ["preço", "promoção"]}


async def test_both_attempts_failing_returns_defaults_with_error(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("modelo fora do ar")

    monkeypatch.setattr(enrich_mod, "is_available", lambda: True)
    monkeypatch.setattr(enrich_mod, "complete_structured", boom)
    monkeypatch.setattr(enrich_mod, "complete", boom)

    sentiment = await analyze_sentiment("conteúdo")
    tags = await suggest_tags("conteúdo")

    assert sentiment["sentiment"] == "neutral"
    assert sentiment["score"] == 0.0
    assert "Sentiment analysis failed" in sentiment["error"]
    assert "modelo fora do ar" in sentiment["error"]
    assert tags["tags"] == []
    assert "Tag suggestion failed" in tags["error"]


async def test_reply_without_json_returns_defaults_with_error(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("structured failed")

    async def fake_complete(messages, **kwargs):
        return "Desculpe, não consigo ajudar com isso."

    monkeypatch.setattr(enrich_mod, "is_available", lambda: True)
    monkeypatch.setattr(enrich_mod, "complete_structured", boom)
    monkeypatch.setattr(enrich_mod, "complete", fake_complete)

    assert await analyze_sentiment("conteúdo") == {
        **NEUTRAL,
        "error": "AI response without valid JSON",
    }
    assert await suggest_tags("conteúdo") == {
        "tags": [],
        "error": "AI response without valid JSON",
    }


async def test_text_is_truncated_to_max_chars(monkeypatch):
    seen: dict[str, str] = {}

    async def fake_structured(messages, response_model, **kwargs):
        seen["content"] = messages[-1]["content"]
        return SentimentResult(sentiment="neutral", score=0.0)

    monkeypatch.setattr(enrich_mod, "is_available", lambda: True)
    monkeypatch.setattr(enrich_mod, "complete_structured", fake_structured)

    await analyze_sentiment("x" * 500, max_chars=40)

    assert seen["content"].endswith("x" * 40)
    assert "x" * 41 not in seen["content"]


# ── EnrichEngine ──────────────────────────────────────────────────────────


async def test_engine_writes_json_and_markdown(tmp_path, monkeypatch):
    seen: dict[str, str] = {}

    async def fake_sentiment(text, max_chars=6000):
        seen["sentiment_text"] = text
        return {"sentiment": "positive", "score": 0.75, "rationale": "promoção vantajosa"}

    async def fake_tags(text, max_tags=8, max_chars=6000):
        seen["tags_text"] = text
        return {"tags": ["preço", "promoção"]}

    monkeypatch.setattr(engine_mod, "analyze_sentiment", fake_sentiment)
    monkeypatch.setattr(engine_mod, "suggest_tags", fake_tags)
    output_dir = tmp_path / "job"
    progress: list[str] = []

    with respx.mock(assert_all_called=True) as mock:
        mock.get(PAGE_URL).mock(
            return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE_HTML)
        )
        result = await EnrichEngine().execute(
            JobCreate(url=PAGE_URL, mode="sentiment"),
            output_dir,
            on_progress=progress.append,
        )

    assert "promoção de verão é excelente" in seen["sentiment_text"]
    assert seen["tags_text"] == seen["sentiment_text"]

    assert {path.name for path in result.files} == {"enrichment.json", "enrichment.md"}
    assert all(path.exists() for path in result.files)
    assert result.total_bytes == sum(path.stat().st_size for path in result.files)
    assert progress == ["Analyzing sentiment and topics...", "Enrichment complete"]

    payload = json.loads((output_dir / "enrichment.json").read_text(encoding="utf-8"))
    assert payload == {
        "url": PAGE_URL,
        "sentiment": {"sentiment": "positive", "score": 0.75, "rationale": "promoção vantajosa"},
        "tags": ["preço", "promoção"],
        "errors": [],
    }

    md = (output_dir / "enrichment.md").read_text(encoding="utf-8")
    assert PAGE_URL in md
    assert "- Sentiment: positive" in md
    assert "- Score: 0.75" in md
    assert "- Rationale: promoção vantajosa" in md
    assert "- preço" in md
    assert "- promoção" in md
    assert "## Erros" not in md


async def test_engine_with_unreachable_url_still_writes_both_files(tmp_path, monkeypatch):
    # The engine imports the real AI helpers: blank text must short-circuit before any AI call.
    monkeypatch.setattr(enrich_mod, "is_available", _no_ai_call)
    monkeypatch.setattr(enrich_mod, "complete_structured", _no_ai_call)
    monkeypatch.setattr(enrich_mod, "complete", _no_ai_call)
    output_dir = tmp_path / "job"

    with respx.mock(assert_all_called=False) as mock:
        mock.get(PAGE_URL).mock(side_effect=httpx.ConnectError("sem rede"))
        result = await EnrichEngine().execute(JobCreate(url=PAGE_URL, mode="sentiment"), output_dir)

    assert {path.name for path in result.files} == {"enrichment.json", "enrichment.md"}
    assert all(path.exists() for path in result.files)
    assert any("Failed to fetch" in line for line in result.logs)

    payload = json.loads((output_dir / "enrichment.json").read_text(encoding="utf-8"))
    assert payload == {"url": PAGE_URL, "sentiment": NEUTRAL, "tags": [], "errors": []}

    md = (output_dir / "enrichment.md").read_text(encoding="utf-8")
    assert "- Sentiment: neutral" in md
    assert "No topics identified." in md


async def test_engine_surfaces_ai_errors_in_both_files(tmp_path, monkeypatch):
    async def failing_sentiment(text, max_chars=6000):
        return {**NEUTRAL, "error": "AI unavailable"}

    async def failing_tags(text, max_tags=8, max_chars=6000):
        return {"tags": [], "error": "AI unavailable"}

    monkeypatch.setattr(engine_mod, "analyze_sentiment", failing_sentiment)
    monkeypatch.setattr(engine_mod, "suggest_tags", failing_tags)
    output_dir = tmp_path / "job"

    with respx.mock(assert_all_called=True) as mock:
        mock.get(PAGE_URL).mock(
            return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE_HTML)
        )
        result = await EnrichEngine().execute(JobCreate(url=PAGE_URL, mode="sentiment"), output_dir)

    payload = json.loads((output_dir / "enrichment.json").read_text(encoding="utf-8"))
    assert payload["errors"] == ["AI unavailable"]
    assert payload["sentiment"]["error"] == "AI unavailable"
    assert payload["tags"] == []

    assert any("AI (sentiment): AI unavailable" in line for line in result.logs)
    assert any("AI (topics): AI unavailable" in line for line in result.logs)

    md = (output_dir / "enrichment.md").read_text(encoding="utf-8")
    assert "## Errors" in md
    assert "- AI unavailable" in md


def test_engine_can_handle_any_probe():
    assert EnrichEngine().can_handle(ProbeResult(url=PAGE_URL)) is True
    assert EnrichEngine.name == "enrich"
