"""Tests for AI translation and the translate engine (no real model — all calls mocked)."""

from __future__ import annotations

import json

import httpx
import respx

from zfrog.ai import translate as translate_mod
from zfrog.ai.schemas import TranslationResult
from zfrog.ai.translate import split_for_translation, translate_text
from zfrog.config import settings
from zfrog.engines import translate as engine_mod
from zfrog.engines.translate import TranslateEngine, resolve_target
from zfrog.models import JobCreate, ProbeResult

PAGE_URL = "https://example.com/noticia"
PAGE_HTML = (
    "<html><head><title>Feira de tecnologia</title></head>"
    "<body><p>João Souza announced the Zeta product.</p></body></html>"
)

LONG_TEXT = "\n\n".join(
    f"Parágrafo {index} " + " ".join(f"palavra{index}-{word}" for word in range(60))
    for index in range(1, 7)
)
# A page well past the 6000-char default budget.
LONG_PAGE = "\n\n".join(
    f"Secção {index} " + " ".join(f"palavra{index}-{word}" for word in range(60))
    for index in range(1, 25)
)


async def _no_ai_call(*args, **kwargs):
    raise AssertionError("the AI must not be called")


def _words(text: str) -> str:
    """Whitespace-collapsed text — the comparable form of a chunk list."""
    return " ".join(text.split())


# ── split_for_translation ─────────────────────────────────────────────────


def test_split_keeps_every_word_across_several_chunks():
    chunks = split_for_translation(LONG_TEXT, max_chars=400)

    assert len(chunks) > 1
    assert all(len(chunk) <= 400 for chunk in chunks)
    assert _words("\n\n".join(chunks)) == _words(LONG_TEXT)


def test_split_default_budget_breaks_a_long_page_into_several_chunks():
    chunks = split_for_translation(LONG_PAGE)

    assert len(chunks) > 1
    assert all(len(chunk) <= 6000 for chunk in chunks)
    assert _words("\n\n".join(chunks)) == _words(LONG_PAGE)


def test_split_never_breaks_a_word():
    text = " ".join(f"palavra{i:04d}" for i in range(200))

    chunks = split_for_translation(text, max_chars=120)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 120
        for word in chunk.split():
            assert word in text.split()
    assert _words("\n\n".join(chunks)) == _words(text)


def test_split_keeps_a_word_longer_than_the_budget_without_losing_characters():
    text = f"antes {('x' * 250)} depois"

    chunks = split_for_translation(text, max_chars=100)

    assert all(len(chunk) <= 100 for chunk in chunks)
    assert "".join("".join(chunks).split()) == "".join(text.split())


def test_split_of_blank_text_is_empty():
    assert split_for_translation("   \n\t \n ") == []


# ── translate_text ────────────────────────────────────────────────────────


async def test_blank_text_returns_empty_without_calling_ai(monkeypatch):
    monkeypatch.setattr(translate_mod, "is_available", lambda: True)
    monkeypatch.setattr(translate_mod, "complete_structured", _no_ai_call)
    monkeypatch.setattr(translate_mod, "complete", _no_ai_call)

    result = await translate_text("   \n\t ", target="en", source="pt")

    assert result == {"text": "", "source_language": "pt", "target_language": "en"}


async def test_unavailable_ai_reports_error_without_raising(monkeypatch):
    monkeypatch.setattr(translate_mod, "is_available", lambda: False)
    monkeypatch.setattr(translate_mod, "complete_structured", _no_ai_call)
    monkeypatch.setattr(translate_mod, "complete", _no_ai_call)

    result = await translate_text("Hello world", target="pt")

    assert result["text"] == ""
    assert result["error"] == "AI indisponível"
    assert result["target_language"] == "pt"


async def test_structured_result_lands_in_the_returned_text_and_languages(monkeypatch):
    seen: dict[str, object] = {}

    async def fake_structured(messages, response_model, **kwargs):
        seen["model"] = response_model
        seen["content"] = messages[-1]["content"]
        return TranslationResult(
            text="Olá mundo.",
            source_language="en",
            target_language="pt",
        )

    monkeypatch.setattr(translate_mod, "is_available", lambda: True)
    monkeypatch.setattr(translate_mod, "complete_structured", fake_structured)
    monkeypatch.setattr(translate_mod, "complete", _no_ai_call)

    result = await translate_text("Hello world.")

    assert seen["model"] is TranslationResult
    assert "Hello world." in str(seen["content"])
    assert result["text"] == "Olá mundo."
    assert result["source_language"] == "en"
    assert result["target_language"] == "pt"
    assert "error" not in result


async def test_target_defaults_to_the_setting(monkeypatch):
    seen: dict[str, str] = {}

    async def fake_structured(messages, response_model, **kwargs):
        seen["content"] = messages[-1]["content"]
        return TranslationResult(text="Hallo Welt.")

    monkeypatch.setattr(settings, "translation_target", "de")
    monkeypatch.setattr(translate_mod, "is_available", lambda: True)
    monkeypatch.setattr(translate_mod, "complete_structured", fake_structured)

    result = await translate_text("Hello world.")

    assert result["target_language"] == "de"
    assert "Idioma de destino: de" in seen["content"]


async def test_long_input_triggers_one_call_per_chunk(monkeypatch):
    calls: list[str] = []

    async def fake_structured(messages, response_model, **kwargs):
        calls.append(messages[-1]["content"])
        return TranslationResult(text=f"[{len(calls)}]", target_language="pt")

    monkeypatch.setattr(translate_mod, "is_available", lambda: True)
    monkeypatch.setattr(translate_mod, "complete_structured", fake_structured)
    monkeypatch.setattr(translate_mod, "complete", _no_ai_call)

    chunks = split_for_translation(LONG_TEXT, max_chars=400)
    result = await translate_text(LONG_TEXT, target="pt", max_chars=400)

    assert len(calls) == len(chunks) > 1
    assert result["text"] == "\n\n".join(f"[{index}]" for index in range(1, len(chunks) + 1))
    assert all(len(call) <= 400 + 200 for call in calls)


async def test_structured_failure_falls_back_to_the_plain_reply(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("modelo não disponível")

    async def fake_complete(messages, **kwargs):
        return "  Texto traduzido.  "

    monkeypatch.setattr(translate_mod, "is_available", lambda: True)
    monkeypatch.setattr(translate_mod, "complete_structured", boom)
    monkeypatch.setattr(translate_mod, "complete", fake_complete)

    result = await translate_text("Some text.", target="pt", source="en")

    assert result["text"] == "Texto traduzido."
    assert result["source_language"] == "en"
    assert "error" not in result


async def test_both_ai_paths_failing_keeps_the_original_text_and_reports(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("provider fora do ar")

    monkeypatch.setattr(translate_mod, "is_available", lambda: True)
    monkeypatch.setattr(translate_mod, "complete_structured", boom)
    monkeypatch.setattr(translate_mod, "complete", boom)

    result = await translate_text("Some text.", target="pt")

    assert result["text"] == "Some text."
    assert "provider fora do ar" in result["error"]


# ── TranslateEngine ───────────────────────────────────────────────────────


async def test_engine_writes_json_and_markdown(tmp_path, monkeypatch):
    seen: dict[str, str] = {}

    async def fake_translate(text, target="", source="", max_chars=6000):
        seen["text"] = text
        seen["target"] = target
        return {"text": "João Souza anunciou o produto Zeta.", "source_language": "en", "target_language": target}

    monkeypatch.setattr(engine_mod, "translate_text", fake_translate)
    output_dir = tmp_path / "job"

    with respx.mock(assert_all_called=True) as mock:
        mock.get(PAGE_URL).mock(
            return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE_HTML)
        )
        result = await TranslateEngine().execute(JobCreate(url=PAGE_URL, mode="translate"), output_dir)

    assert seen["text"] == "João Souza announced the Zeta product."
    assert seen["target"] == settings.translation_target
    assert {path.name for path in result.files} == {"translation.json", "translation.md"}
    assert all(path.exists() for path in result.files)
    assert result.total_bytes == sum(path.stat().st_size for path in result.files)

    payload = json.loads((output_dir / "translation.json").read_text(encoding="utf-8"))
    assert payload == {
        "url": PAGE_URL,
        "target": settings.translation_target,
        "source_language": "en",
        "text": "João Souza anunciou o produto Zeta.",
    }

    md = (output_dir / "translation.md").read_text(encoding="utf-8")
    assert md.startswith(f"# {PAGE_URL}\n")
    assert "João Souza anunciou o produto Zeta." in md


async def test_engine_uses_the_job_target_language(tmp_path, monkeypatch):
    seen: dict[str, str] = {}

    async def fake_translate(text, target="", source="", max_chars=6000):
        seen["target"] = target
        return {"text": "Hallo Welt.", "source_language": "en", "target_language": target}

    monkeypatch.setattr(settings, "translation_target", "de")
    monkeypatch.setattr(engine_mod, "translate_text", fake_translate)
    output_dir = tmp_path / "job"
    job = JobCreate(url=PAGE_URL, mode="translate", translate_target="fr")

    with respx.mock(assert_all_called=True) as mock:
        mock.get(PAGE_URL).mock(
            return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE_HTML)
        )
        await TranslateEngine().execute(job, output_dir)

    payload = json.loads((output_dir / "translation.json").read_text(encoding="utf-8"))
    assert seen["target"] == "fr"
    assert payload["target"] == "fr"
    assert resolve_target(JobCreate(url=PAGE_URL, mode="translate")) == "de"


async def test_engine_with_unreachable_url_still_writes_both_files(tmp_path, monkeypatch):
    async def fake_translate(text, target="", source="", max_chars=6000):
        return {"text": "", "source_language": "", "target_language": target}

    monkeypatch.setattr(engine_mod, "translate_text", fake_translate)
    output_dir = tmp_path / "job"

    with respx.mock(assert_all_called=False) as mock:
        mock.get(PAGE_URL).mock(side_effect=httpx.ConnectError("sem rede"))
        result = await TranslateEngine().execute(JobCreate(url=PAGE_URL, mode="translate"), output_dir)

    assert {path.name for path in result.files} == {"translation.json", "translation.md"}
    assert all(path.exists() for path in result.files)
    assert any("Falha ao buscar" in line for line in result.logs)

    payload = json.loads((output_dir / "translation.json").read_text(encoding="utf-8"))
    assert payload["url"] == PAGE_URL
    assert payload["text"] == ""
    assert "Nenhum texto traduzido." in (output_dir / "translation.md").read_text(encoding="utf-8")


async def test_engine_surfaces_ai_error_in_both_files(tmp_path, monkeypatch):
    monkeypatch.setattr(translate_mod, "is_available", lambda: False)
    monkeypatch.setattr(engine_mod, "translate_text", translate_mod.translate_text)
    output_dir = tmp_path / "job"

    with respx.mock(assert_all_called=True) as mock:
        mock.get(PAGE_URL).mock(
            return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE_HTML)
        )
        result = await TranslateEngine().execute(JobCreate(url=PAGE_URL, mode="translate"), output_dir)

    payload = json.loads((output_dir / "translation.json").read_text(encoding="utf-8"))
    assert payload["error"] == "AI indisponível"
    assert payload["text"] == ""
    assert "AI indisponível" in (output_dir / "translation.md").read_text(encoding="utf-8")
    assert any("AI indisponível" in line for line in result.logs)


async def test_engine_reports_progress_and_translates_through_the_ai_module(tmp_path, monkeypatch):
    async def fake_structured(messages, response_model, **kwargs):
        return TranslationResult(text="João Souza anunciou o produto Zeta.", source_language="en")

    monkeypatch.setattr(translate_mod, "is_available", lambda: True)
    monkeypatch.setattr(translate_mod, "complete_structured", fake_structured)
    monkeypatch.setattr(engine_mod, "translate_text", translate_mod.translate_text)
    messages: list[str] = []
    output_dir = tmp_path / "job"

    with respx.mock(assert_all_called=True) as mock:
        mock.get(PAGE_URL).mock(
            return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE_HTML)
        )
        await TranslateEngine().execute(
            JobCreate(url=PAGE_URL, mode="translate"),
            output_dir,
            on_progress=messages.append,
        )

    assert messages == ["Traduzindo...", "Tradução concluída"]
    payload = json.loads((output_dir / "translation.json").read_text(encoding="utf-8"))
    assert payload["text"] == "João Souza anunciou o produto Zeta."
    assert payload["source_language"] == "en"


def test_engine_can_handle_any_probe():
    assert TranslateEngine().can_handle(ProbeResult(url=PAGE_URL)) is True
    assert TranslateEngine.name == "translate"
