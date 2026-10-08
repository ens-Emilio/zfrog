"""Tests for domain-specialised prompting (no real model — every AI call is mocked)."""

from __future__ import annotations

import copy
import json

import pytest

from zfrog.ai import domains as domains_mod
from zfrog.ai.domains import (
    DEFAULT_BASE_PROMPT,
    MAX_PROMPT_CHARS,
    DomainProfile,
    DomainProfileStore,
    apply,
    extract_with_profile,
    few_shot_messages,
    resolve,
    suggest_profile,
    system_prompt,
)
from zfrog.ai.schemas import ExtractedItem, ExtractionResult
from zfrog.config import settings

TERMINOLOGY = {"cláusula": "disposição contratual", "prazo": "data-limite de um ato"}

EXAMPLES = [
    {"input": "Cláusula 5ª: prazo de 30 dias.", "output": "prazo = 30 dias"},
    {"input": "Cláusula 9ª: multa de 2%.", "output": "multa = 2%"},
    {"input": "Cláusula 10ª: foro da comarca.", "output": "foro = comarca"},
]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A profile store rooted in ``tmp_path`` (never the repo's real ``domains/``)."""
    root = tmp_path / "domains"
    monkeypatch.setattr(settings, "domain_profiles_dir", root)
    return DomainProfileStore()


@pytest.fixture
def profile() -> DomainProfile:
    return DomainProfile(
        id="contratos",
        name="Contratos",
        description="Contratos de prestação de serviço.",
        terminology=dict(TERMINOLOGY),
        examples=copy.deepcopy(EXAMPLES),
        instructions="Extraia cláusulas com a numeração original.",
        entity_types=["cláusula", "prazo"],
        tags=["juridico"],
    )


async def _no_ai_call(*args, **kwargs):
    raise AssertionError("the AI must not be called")


# ── builtin ───────────────────────────────────────────────────────────────


def test_builtin_profiles_are_substantive(store):
    profiles = {item.id: item for item in store.builtin()}

    assert set(profiles) == {"legal", "ecommerce", "news"}
    for builtin in profiles.values():
        assert builtin.name and builtin.description and builtin.instructions
        assert builtin.terminology
        assert len(builtin.examples) >= 2
        assert builtin.entity_types
        assert all(example["input"] and example["output"] for example in builtin.examples)

    legal = profiles["legal"]
    assert "cláusula" in legal.terminology
    assert "jurisprudência" in legal.terminology
    assert {"parte", "prazo"} <= set(legal.entity_types)

    ecommerce = profiles["ecommerce"]
    assert "SKU" in ecommerce.terminology
    assert {"produto", "preço", "frete"} <= set(ecommerce.entity_types)

    news = profiles["news"]
    assert "veículo" in news.terminology
    assert {"título", "autor", "data"} <= set(news.entity_types)


def test_builtin_profiles_are_not_written_to_disk(store):
    store.builtin()
    store.builtin()

    assert not store.root.exists()


def test_builtin_profiles_are_independent_copies(store):
    first, second = store.builtin()[0], store.builtin()[0]

    first.terminology["novo"] = "algo"
    assert "novo" not in second.terminology


# ── store ─────────────────────────────────────────────────────────────────


def test_save_slugifies_missing_id_and_persists_json(store):
    stored = store.save({"name": "Dados Abertos", "description": "Portal de dados"})

    assert stored.id == "dados-abertos"
    assert stored.created_at and stored.updated_at
    path = store.root / "dados-abertos.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["id"] == "dados-abertos"
    assert payload["name"] == "Dados Abertos"
    assert payload["description"] == "Portal de dados"


def test_save_requires_an_id_or_a_name(store):
    with pytest.raises(ValueError):
        store.save({"description": "sem nome nenhum"})

    assert not store.root.exists()


def test_save_upserts_and_keeps_created_at(store):
    store.save({"id": "noticias", "name": "Notícias", "created_at": "2020-01-01T00:00:00+00:00"})
    updated = store.save({"id": "noticias", "name": "Notícias Regionais", "tags": ["jornal"]})

    assert updated.id == "noticias"
    assert updated.name == "Notícias Regionais"
    assert updated.created_at == "2020-01-01T00:00:00+00:00"
    assert updated.updated_at != "2020-01-01T00:00:00+00:00"
    assert updated.tags == ["jornal"]

    on_disk = store.get("noticias")
    assert on_disk is not None and on_disk.name == "Notícias Regionais"
    assert len(store.list()) == 1


def test_get_list_remove_round_trip(store, profile):
    store.save(profile)
    store.save({"name": "Zeta"})
    store.save({"name": "Alfa"})

    assert [item.id for item in store.list()] == ["alfa", "contratos", "zeta"]
    fetched = store.get("contratos")
    assert fetched is not None
    assert fetched.terminology == TERMINOLOGY
    assert fetched.examples == EXAMPLES
    assert fetched.entity_types == ["cláusula", "prazo"]

    assert store.remove("zeta") is True
    assert store.get("zeta") is None
    assert store.remove("zeta") is False
    assert store.get("") is None
    assert [item.id for item in store.list()] == ["alfa", "contratos"]


def test_store_skips_unreadable_files(store):
    store.save({"name": "Bom"})
    (store.root / "quebrado.json").write_text("{ não é json", encoding="utf-8")

    assert [item.id for item in store.list()] == ["bom"]


# ── resolve ───────────────────────────────────────────────────────────────


def test_resolve_finds_stored_then_builtin(store, profile):
    store.save(profile)

    assert resolve("contratos", store) is not None
    assert resolve("contratos", store).instructions.startswith("Extraia cláusulas")
    assert resolve("legal", store).id == "legal"
    assert resolve("nao-existe", store) is None
    assert resolve(None, store) is None
    assert resolve("", store) is None


def test_resolve_builtin_does_not_touch_disk(tmp_path):
    absent = tmp_path / "sem-perfis"
    store = DomainProfileStore(absent)

    resolved = resolve("news", store)

    assert resolved is not None and resolved.id == "news"
    assert not absent.exists()


# ── system_prompt ─────────────────────────────────────────────────────────


def test_system_prompt_includes_instructions_terminology_and_entities(profile):
    prompt = system_prompt(profile, base="Base do sistema.")

    assert prompt.startswith("Base do sistema.")
    assert "Extraia cláusulas com a numeração original." in prompt
    assert "cláusula: disposição contratual" in prompt
    assert "prazo: data-limite de um ato" in prompt
    assert "Entity types to look for: cláusula, prazo." in prompt
    assert len(prompt) <= MAX_PROMPT_CHARS


def test_system_prompt_without_profile_returns_base_or_default(profile):
    assert system_prompt(None, "Só a base.") == "Só a base."
    assert system_prompt(None) == DEFAULT_BASE_PROMPT
    assert system_prompt(profile) .startswith(DEFAULT_BASE_PROMPT)


def test_system_prompt_truncates_huge_terminology():
    huge = DomainProfile(
        id="enorme",
        name="Enorme",
        instructions="Extraia tudo.",
        entity_types=["campo"],
        terminology={f"termo-{index:03d}": f"significado suficientemente longo {index}" for index in range(300)},
    )

    prompt = system_prompt(huge, base="Base.")

    assert len(prompt) <= MAX_PROMPT_CHARS
    assert "omitidos" in prompt
    assert "termo-000: significado suficientemente longo 0" in prompt
    assert "termo-299" not in prompt


def test_system_prompt_clips_an_oversized_base_prompt():
    prompt = system_prompt(None, "x" * (MAX_PROMPT_CHARS + 500))

    assert len(prompt) <= MAX_PROMPT_CHARS


# ── few_shot_messages ─────────────────────────────────────────────────────


def test_few_shot_messages_respects_limit(profile):
    pairs = few_shot_messages(profile, limit=2)

    assert [message["role"] for message in pairs] == ["user", "assistant", "user", "assistant"]
    assert pairs[0]["content"] == EXAMPLES[0]["input"]
    assert pairs[1]["content"] == EXAMPLES[0]["output"]
    assert pairs[2]["content"] == EXAMPLES[1]["input"]
    assert few_shot_messages(profile, limit=0) == []


def test_few_shot_messages_skips_incomplete_examples(profile):
    profile.examples = [{"input": "só entrada"}, {"input": "ok", "output": "certo"}]

    assert few_shot_messages(profile, limit=5) == [
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "certo"},
    ]


# ── apply ─────────────────────────────────────────────────────────────────


def test_apply_prepends_system_and_inserts_examples_before_last_user(profile):
    messages = [
        {"role": "system", "content": "instrução antiga"},
        {"role": "user", "content": "primeira pergunta"},
        {"role": "assistant", "content": "primeira resposta"},
        {"role": "user", "content": "pergunta final"},
    ]
    original = copy.deepcopy(messages)

    prepared = apply(profile, messages, base_prompt="Base do sistema.")

    assert prepared is not messages
    assert prepared[0] == {"role": "system", "content": system_prompt(profile, "Base do sistema.")}
    assert "instrução antiga" not in prepared[0]["content"]
    assert prepared[1] == {"role": "user", "content": "primeira pergunta"}
    assert prepared[2] == {"role": "assistant", "content": "primeira resposta"}
    assert prepared[3] == {"role": "user", "content": EXAMPLES[0]["input"]}
    assert prepared[4] == {"role": "assistant", "content": EXAMPLES[0]["output"]}
    assert prepared[5] == {"role": "user", "content": EXAMPLES[1]["input"]}
    assert prepared[6] == {"role": "assistant", "content": EXAMPLES[1]["output"]}
    assert prepared[7] == {"role": "user", "content": "pergunta final"}
    assert messages == original


def test_apply_without_user_message_appends_examples(profile):
    prepared = apply(profile, [{"role": "assistant", "content": "só isso"}], limit=1)

    assert prepared[0]["role"] == "system"
    assert prepared[1] == {"role": "assistant", "content": "só isso"}
    assert prepared[2]["role"] == "user"
    assert prepared[3]["role"] == "assistant"


def test_apply_without_profile_returns_equal_distinct_copy(profile):
    messages = [{"role": "system", "content": "manter"}, {"role": "user", "content": "oi"}]

    prepared = apply(None, messages)

    assert prepared == messages
    assert prepared is not messages
    assert prepared[0] is not messages[0]


# ── suggest_profile ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "text", "expected"),
    [
        ("https://www.jusbrasil.com.br/processo/1", "", "legal"),
        ("https://court.example.com/decisao", "", "legal"),
        ("https://loja.exemplo.com.br/tenis", "", "ecommerce"),
        ("https://shop.example.com/item", "", "ecommerce"),
        ("https://news.example.com/2024/01", "", "news"),
        ("https://meublog.com/post", "", "news"),
        ("https://example.com/pagina", "Acórdão do tribunal sobre a jurisprudência do prazo", "legal"),
        ("https://example.com/pagina", "Frete grátis e carrinho de compras", "ecommerce"),
        ("https://example.com/pagina", "Reportagem do jornal sobre a cidade", "news"),
        ("https://example.com/pagina", "Texto genérico sobre futebol de várzea", None),
        ("https://example.com/pagina", "", None),
    ],
)
def test_suggest_profile_maps_hints(url, text, expected):
    assert suggest_profile(url, text) == expected


# ── extract_with_profile ──────────────────────────────────────────────────


async def test_extract_with_profile_blank_text_skips_the_ai(monkeypatch):
    monkeypatch.setattr(domains_mod, "is_available", lambda: True)
    monkeypatch.setattr(domains_mod, "complete_structured", _no_ai_call)

    result = await extract_with_profile("   \n\t ", None)

    assert result["items"] == []
    assert result["summary"] == ""
    assert result["page_title"] == ""
    assert result["error"] == "Empty text"


async def test_extract_with_profile_reports_unavailable_ai(monkeypatch):
    monkeypatch.setattr(domains_mod, "is_available", lambda: False)
    monkeypatch.setattr(domains_mod, "complete_structured", _no_ai_call)

    result = await extract_with_profile("Cláusula 5ª: prazo de 30 dias.", None)

    assert result["items"] == []
    assert result["error"] == "AI unavailable"


async def test_extract_with_profile_carries_terminology_in_the_prompt(monkeypatch, store, profile):
    captured: dict = {}

    async def fake_structured(messages, response_model, **kwargs):
        captured["messages"] = messages
        captured["response_model"] = response_model
        return ExtractionResult(
            items=[ExtractedItem(label="prazo", value="30 dias", confidence=0.9)],
            summary="Contrato com prazo.",
            page_title="Contrato de serviço",
        )

    monkeypatch.setattr(domains_mod, "is_available", lambda: True)
    monkeypatch.setattr(domains_mod, "complete_structured", fake_structured)

    result = await extract_with_profile("Cláusula 5ª: prazo de 30 dias.", profile)

    assert captured["response_model"] is ExtractionResult
    system = captured["messages"][0]
    assert system["role"] == "system"
    assert system["content"].startswith(domains_mod.BASE_EXTRACTION_PROMPT)
    assert "cláusula: disposição contratual" in system["content"]
    assert "prazo: data-limite de um ato" in system["content"]
    assert "Entity types to look for: cláusula, prazo." in system["content"]
    assert captured["messages"][-1]["role"] == "user"
    assert "Cláusula 5ª" in captured["messages"][-1]["content"]

    assert result["items"] == [{"label": "prazo", "value": "30 dias", "confidence": 0.9}]
    assert result["summary"] == "Contrato com prazo."
    assert result["page_title"] == "Contrato de serviço"
    assert "error" not in result


async def test_extract_with_profile_uses_builtin_when_resolved(monkeypatch, store):
    captured: dict = {}

    async def fake_structured(messages, response_model, **kwargs):
        captured["messages"] = messages
        return ExtractionResult(summary="ok")

    monkeypatch.setattr(domains_mod, "is_available", lambda: True)
    monkeypatch.setattr(domains_mod, "complete_structured", fake_structured)

    legal = resolve("legal")
    result = await extract_with_profile("Cláusula 5ª do contrato.", legal)

    assert result["items"] == []
    assert "jurisprudência" in captured["messages"][0]["content"]


async def test_extract_with_profile_normalizes_dict_results(monkeypatch, profile):
    async def fake_structured(messages, response_model, **kwargs):
        return {
            "items": [{"label": "preço", "value": "R$ 10,00"}, {"label": "", "value": ""}],
            "summary": "Preço encontrado",
            "page_title": "Loja",
        }

    monkeypatch.setattr(domains_mod, "is_available", lambda: True)
    monkeypatch.setattr(domains_mod, "complete_structured", fake_structured)

    result = await extract_with_profile("R$ 10,00", profile)

    assert result["items"] == [{"label": "preço", "value": "R$ 10,00", "confidence": 1.0}]
    assert result["summary"] == "Preço encontrado"
    assert result["page_title"] == "Loja"


async def test_extract_with_profile_never_raises_on_failure(monkeypatch, profile):
    async def boom(*args, **kwargs):
        raise RuntimeError("modelo fora do ar")

    monkeypatch.setattr(domains_mod, "is_available", lambda: True)
    monkeypatch.setattr(domains_mod, "complete_structured", boom)

    result = await extract_with_profile("Cláusula 5ª.", profile)

    assert result["items"] == []
    assert result["summary"] == ""
    assert "modelo fora do ar" in result["error"]


async def test_extract_with_profile_truncates_the_text(monkeypatch, profile):
    captured: dict = {}

    async def fake_structured(messages, response_model, **kwargs):
        captured["messages"] = messages
        return ExtractionResult()

    monkeypatch.setattr(domains_mod, "is_available", lambda: True)
    monkeypatch.setattr(domains_mod, "complete_structured", fake_structured)

    await extract_with_profile("a" * 500, profile, max_chars=100)

    assert captured["messages"][-1]["content"].endswith("a" * 100)
    assert "a" * 101 not in captured["messages"][-1]["content"]
