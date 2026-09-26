"""Tests for named-entity extraction (no real model required — all calls mocked)."""

from __future__ import annotations

import json

import httpx
import respx

from zfrog.ai import entities as entities_mod
from zfrog.ai.entities import entity_counts, extract_entities, merge_entities
from zfrog.ai.schemas import Entity, EntityResult
from zfrog.engines import entities as engine_mod
from zfrog.engines.entities import EntitiesEngine
from zfrog.models import JobCreate, ProbeResult

PAGE_URL = "https://example.com/noticia"
PAGE_HTML = (
    "<html><head><title>Feira de tecnologia</title></head>"
    "<body><p>João Souza, da Acme, anunciou o produto Zeta em 12 de março de 2024.</p></body></html>"
)


async def _no_ai_call(*args, **kwargs):
    raise AssertionError("the AI must not be called")


# ── extract_entities ──────────────────────────────────────────────────────


async def test_blank_text_returns_empty_without_calling_ai(monkeypatch):
    monkeypatch.setattr(entities_mod, "is_available", lambda: True)
    monkeypatch.setattr(entities_mod, "complete_structured", _no_ai_call)
    monkeypatch.setattr(entities_mod, "complete", _no_ai_call)

    result = await extract_entities("   \n\t ")

    assert result == {"entities": [], "counts": {}}


async def test_unavailable_ai_reports_error_without_raising(monkeypatch):
    monkeypatch.setattr(entities_mod, "is_available", lambda: False)
    monkeypatch.setattr(entities_mod, "complete_structured", _no_ai_call)
    monkeypatch.setattr(entities_mod, "complete", _no_ai_call)

    result = await extract_entities("João Souza trabalha na Acme.")

    assert result["entities"] == []
    assert result["counts"] == {}
    assert result["error"] == "AI indisponível"


async def test_structured_result_is_returned_with_counts(monkeypatch):
    async def fake_structured(messages, response_model, **kwargs):
        assert response_model is EntityResult
        assert "João Souza" in messages[-1]["content"]
        return EntityResult(
            entities=[
                Entity(name="João Souza", type="person", confidence=0.9),
                Entity(name="Acme", type="organization", confidence=0.7),
                Entity(name="Zeta", type="product", confidence=0.6),
            ]
        )

    monkeypatch.setattr(entities_mod, "is_available", lambda: True)
    monkeypatch.setattr(entities_mod, "complete_structured", fake_structured)
    monkeypatch.setattr(entities_mod, "complete", _no_ai_call)

    result = await extract_entities("João Souza, da Acme, anunciou o produto Zeta.")

    assert result["entities"] == [
        {"name": "João Souza", "type": "person", "confidence": 0.9},
        {"name": "Acme", "type": "organization", "confidence": 0.7},
        {"name": "Zeta", "type": "product", "confidence": 0.6},
    ]
    assert result["counts"] == {"organization": 1, "person": 1, "product": 1}
    assert "error" not in result


async def test_text_is_truncated_to_max_chars(monkeypatch):
    seen: dict[str, str] = {}

    async def fake_structured(messages, response_model, **kwargs):
        seen["content"] = messages[-1]["content"]
        return EntityResult(entities=[])

    monkeypatch.setattr(entities_mod, "is_available", lambda: True)
    monkeypatch.setattr(entities_mod, "complete_structured", fake_structured)

    await extract_entities("x" * 40 + "FIM", max_chars=40)

    assert "FIM" not in seen["content"]
    assert seen["content"].endswith("x" * 40)


async def test_falls_back_to_loose_json_when_structured_fails(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("modelo não disponível")

    async def fake_complete(messages, **kwargs):
        return '```json\n{"entities": [{"name": "João Souza", "type": "Person", "confidence": 0.55}]}\n```'

    monkeypatch.setattr(entities_mod, "is_available", lambda: True)
    monkeypatch.setattr(entities_mod, "complete_structured", boom)
    monkeypatch.setattr(entities_mod, "complete", fake_complete)

    result = await extract_entities("João Souza é da Beta.")

    assert result["entities"] == [{"name": "João Souza", "type": "person", "confidence": 0.55}]
    assert result["counts"] == {"person": 1}


async def test_both_ai_paths_failing_returns_error_without_raising(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("provider fora do ar")

    monkeypatch.setattr(entities_mod, "is_available", lambda: True)
    monkeypatch.setattr(entities_mod, "complete_structured", boom)
    monkeypatch.setattr(entities_mod, "complete", boom)

    result = await extract_entities("João Souza é da Beta.")

    assert result["entities"] == []
    assert result["counts"] == {}
    assert "provider fora do ar" in result["error"]


# ── merge_entities / entity_counts ────────────────────────────────────────


def test_merge_entities_dedupes_case_insensitively_and_sorts_by_confidence():
    merged = merge_entities(
        [
            {"name": "acme", "type": "organization", "confidence": 0.4},
            {"name": "Acme", "type": "organization", "confidence": 0.9},
            {"name": "João Souza", "type": "person", "confidence": 0.5},
            {"name": "   ", "type": "person", "confidence": 1.0},
        ]
    )

    assert [entity["name"] for entity in merged] == ["Acme", "João Souza"]
    assert [entity["confidence"] for entity in merged] == [0.9, 0.5]
    assert merged[0]["type"] == "organization"


def test_merge_entities_keeps_the_type_of_the_best_occurrence():
    merged = merge_entities(
        [
            {"name": "Zeta", "type": "other", "confidence": 0.2},
            {"name": "ZETA", "type": "product", "confidence": 0.8},
        ]
    )

    assert merged == [{"name": "ZETA", "type": "product", "confidence": 0.8}]


def test_entity_counts_is_sorted_by_type():
    counts = entity_counts(
        [
            {"name": "Ana", "type": "person"},
            {"name": "12/03/2024", "type": "date"},
            {"name": "Bruno", "type": "person"},
            {"name": "Acme", "type": "organization"},
        ]
    )

    assert counts == {"date": 1, "organization": 1, "person": 2}
    assert list(counts) == ["date", "organization", "person"]


# ── EntitiesEngine ────────────────────────────────────────────────────────


async def test_engine_writes_json_and_markdown(tmp_path, monkeypatch):
    async def fake_extract(text, max_chars=8000):
        assert "João Souza" in text  # text really came out of the fetched page
        return {
            "entities": [
                {"name": "João Souza", "type": "person", "confidence": 0.91},
                {"name": "Acme", "type": "organization", "confidence": 0.8},
            ],
            "counts": {"organization": 1, "person": 1},
        }

    monkeypatch.setattr(engine_mod, "extract_entities", fake_extract)
    output_dir = tmp_path / "job"
    progress: list[str] = []

    with respx.mock(assert_all_called=True) as mock:
        mock.get(PAGE_URL).mock(
            return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE_HTML)
        )
        result = await EntitiesEngine().execute(
            JobCreate(url=PAGE_URL, mode="entities"),
            output_dir,
            on_progress=progress.append,
        )

    assert {path.name for path in result.files} == {"entities.json", "entities.md"}
    assert all(path.exists() for path in result.files)
    assert result.total_bytes == sum(path.stat().st_size for path in result.files)
    assert progress == ["Extraindo entidades...", "Entidades concluídas"]

    raw = (output_dir / "entities.json").read_text(encoding="utf-8")
    assert "João Souza" in raw  # ensure_ascii=False keeps accents readable
    assert json.loads(raw) == {
        "url": PAGE_URL,
        "entities": [
            {"name": "João Souza", "type": "person", "confidence": 0.91},
            {"name": "Acme", "type": "organization", "confidence": 0.8},
        ],
        "counts": {"organization": 1, "person": 1},
    }

    md = (output_dir / "entities.md").read_text(encoding="utf-8")
    assert PAGE_URL in md
    assert "| João Souza | person | 0.91 |" in md
    assert "| Acme | organization | 0.80 |" in md
    assert "- person: 1" in md
    assert "- organization: 1" in md


async def test_engine_with_unreachable_url_still_writes_both_files(tmp_path, monkeypatch):
    monkeypatch.setattr(entities_mod, "complete_structured", _no_ai_call)
    monkeypatch.setattr(entities_mod, "complete", _no_ai_call)
    output_dir = tmp_path / "job"

    with respx.mock(assert_all_called=False) as mock:
        mock.get(PAGE_URL).mock(side_effect=httpx.ConnectError("sem rede"))
        result = await EntitiesEngine().execute(JobCreate(url=PAGE_URL, mode="entities"), output_dir)

    assert {path.name for path in result.files} == {"entities.json", "entities.md"}
    assert all(path.exists() for path in result.files)
    assert any("Falha ao buscar" in line for line in result.logs)

    payload = json.loads((output_dir / "entities.json").read_text(encoding="utf-8"))
    assert payload == {"url": PAGE_URL, "entities": [], "counts": {}}

    md = (output_dir / "entities.md").read_text(encoding="utf-8")
    assert "Nenhuma entidade encontrada." in md


async def test_engine_surfaces_ai_error_in_both_files(tmp_path, monkeypatch):
    monkeypatch.setattr(entities_mod, "is_available", lambda: False)
    output_dir = tmp_path / "job"

    with respx.mock(assert_all_called=True) as mock:
        mock.get(PAGE_URL).mock(
            return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE_HTML)
        )
        result = await EntitiesEngine().execute(JobCreate(url=PAGE_URL, mode="entities"), output_dir)

    payload = json.loads((output_dir / "entities.json").read_text(encoding="utf-8"))
    assert payload["error"] == "AI indisponível"
    assert payload["entities"] == []
    assert "AI indisponível" in (output_dir / "entities.md").read_text(encoding="utf-8")
    assert any("AI indisponível" in line for line in result.logs)


def test_engine_can_handle_any_probe():
    assert EntitiesEngine().can_handle(ProbeResult(url=PAGE_URL)) is True
    assert EntitiesEngine.name == "entities"
