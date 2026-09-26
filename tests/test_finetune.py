"""Tests for fine-tuning dataset construction (no real model required)."""

from __future__ import annotations

import json
import stat

import pytest

import zfrog.finetune as finetune_mod
from zfrog.ai import entities as entities_mod
from zfrog.ai import extraction as extraction_mod
from zfrog.config import settings
from zfrog.finetune import (
    MIN_OUTPUT_CHARS,
    SUMMARY_MAX_CHARS,
    DatasetBuilder,
    TrainingExample,
    alpaca_format,
    chat_format,
    dataset_summary,
    load_dataset,
    validate_example,
)

PAGE_A_TEXT = (
    "Entrega e devolução\n"
    "A loja entrega em todo o Brasil em até cinco dias úteis após a confirmação do pagamento.\n"
    "\n"
    "Prazo de garantia\n"
    "A garantia cobre doze meses a partir da data da nota fiscal do produto.\n"
    "\n"
    "O atendimento funciona de segunda a sexta, das nove às dezoito horas, pelo telefone de suporte.\n"
    "Os pedidos feitos depois das dezoito horas são processados no dia útil seguinte pela equipa.\n"
)

PAGE_B_TEXT = (
    "## Suporte\n"
    "O suporte responde em até um dia útil por correio eletrónico para todos os clientes registados.\n"
    "\n"
    "Devoluções\n"
    "O cliente pode devolver qualquer artigo no prazo de trinta dias corridos após a compra.\n"
    "O reembolso é processado no mesmo meio de pagamento usado na compra original.\n"
    "Pedidos de reembolso acima de mil reais são analisados manualmente pela equipa financeira.\n"
)

PAGES = [
    {"url": "https://ex.com/a", "path": "a/index.html", "title": "Loja A", "text": PAGE_A_TEXT},
    {"url": "https://ex.com/b", "path": "b/index.html", "title": "Loja B", "text": PAGE_B_TEXT},
]

PAGE_HTML = (
    "<html><body>"
    "<h2>Frete</h2>"
    "<p>O frete é gratuito para compras acima de duzentos reais em todo o país.</p>"
    "</body></html>"
)


@pytest.fixture
def no_ai(monkeypatch):
    """Force the deterministic path: no model available."""
    monkeypatch.setattr(finetune_mod, "is_available", lambda: False)


def _example(**overrides) -> TrainingExample:
    base = {
        "instruction": "Extraia os dados principais da página em JSON.",
        "input": "A loja entrega em todo o Brasil em até cinco dias úteis.",
        "output": "A loja entrega em todo o Brasil em até cinco dias úteis após o pagamento.",
        "source": "https://ex.com/a",
        "kind": "extraction",
    }
    base.update(overrides)
    return TrainingExample(**base)


# ── shapes ────────────────────────────────────────────────────────────────


def test_chat_format_shape():
    example = _example()
    payload = chat_format(example)

    assert set(payload) == {"messages"}
    messages = payload["messages"]
    assert [message["role"] for message in messages] == ["system", "user", "assistant"]
    assert messages[2]["content"] == example.output
    assert example.instruction in messages[1]["content"]
    assert example.input in messages[1]["content"]
    assert messages[1]["content"] == f"{example.instruction}\n\n{example.input}"


def test_chat_format_without_context_keeps_only_the_instruction():
    payload = chat_format(_example(input=""))

    assert payload["messages"][1]["content"] == "Extraia os dados principais da página em JSON."


def test_alpaca_format_shape():
    example = _example()

    assert alpaca_format(example) == {
        "instruction": example.instruction,
        "input": example.input,
        "output": example.output,
    }


# ── validation ────────────────────────────────────────────────────────────


def test_validate_accepts_a_good_example():
    assert validate_example(_example()) == []


def test_validate_flags_empty_instruction():
    problems = validate_example(_example(instruction="   "))

    assert any("instrução vazia" in problem for problem in problems)


def test_validate_flags_empty_output():
    problems = validate_example(_example(output=""))

    assert any("saída vazia" in problem for problem in problems)


def test_validate_flags_whitespace_only_output():
    problems = validate_example(_example(output="  \n\t "))

    assert any("saída vazia" in problem for problem in problems)


def test_validate_flags_output_identical_to_input():
    text = "O prazo de entrega é de cinco dias úteis em todo o território nacional."
    problems = validate_example(_example(input=text, output=text))

    assert any("idêntica" in problem for problem in problems)


def test_validate_flags_output_shorter_than_the_minimum():
    problems = validate_example(_example(output="Curto."))

    assert len("Curto.") < MIN_OUTPUT_CHARS
    assert any(str(MIN_OUTPUT_CHARS) in problem for problem in problems)

# ── building ──────────────────────────────────────────────────────────────


def test_add_pages_counts_the_kinds_added(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)

    assert builder.add_pages(PAGES, kind="extraction") == 2
    added_qa = builder.add_pages(PAGES, kind="qa")

    assert added_qa > 0
    counts = builder.counts()
    assert counts["extraction"] == 2
    assert counts["qa"] == added_qa
    assert counts["summary"] == 0
    assert counts["entities"] == 0
    assert set(counts) == {"extraction", "qa", "summary", "entities"}


def test_unknown_kind_raises(tmp_path, no_ai):
    with pytest.raises(ValueError):
        DatasetBuilder(tmp_path).add_pages(PAGES, kind="poetry")


def test_qa_examples_come_from_the_page_headings(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)

    assert builder.add_pages(PAGES[:1], kind="qa") == 2

    examples = builder.examples()
    assert {example.instruction for example in examples} == {
        "O que o documento diz sobre «Entrega e devolução»?",
        "O que o documento diz sobre «Prazo de garantia»?",
    }
    for example in examples:
        assert example.output in PAGE_A_TEXT
        assert example.kind == "qa"
        assert example.source == "https://ex.com/a"


def test_html_page_is_read_when_text_is_missing(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)

    assert builder.add_pages([{"url": "https://ex.com/c", "html": PAGE_HTML}], kind="qa") == 1

    example = builder.examples()[0]
    assert "«Frete»" in example.instruction
    assert "duzentos reais" in example.output


def test_extraction_fallback_is_built_from_the_page(tmp_path, monkeypatch, no_ai):
    async def boom(*args, **kwargs):
        raise AssertionError("o modelo não deve ser chamado quando está indisponível")

    monkeypatch.setattr(extraction_mod, "extract_structured", boom, raising=False)

    builder = DatasetBuilder(tmp_path)
    assert builder.add_pages(PAGES[:1], kind="extraction") == 1

    example = builder.examples()[0]
    payload = json.loads(example.output)
    assert payload["titulo"] == "Loja A"
    assert payload["url"] == "https://ex.com/a"
    assert "cinco dias úteis" in example.output
    assert payload["trecho"] in PAGE_A_TEXT
    assert validate_example(example) == []


def test_summary_is_extractive_and_bounded(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)

    assert builder.add_pages(PAGES, kind="summary") == 2

    for example in builder.examples():
        page_text = PAGE_A_TEXT if example.source == "https://ex.com/a" else PAGE_B_TEXT
        assert example.output in page_text
        assert 0 < len(example.output) <= SUMMARY_MAX_CHARS
        assert example.kind == "summary"
        assert validate_example(example) == []


def test_entities_are_skipped_when_the_ai_is_unavailable(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)

    assert builder.add_pages(PAGES, kind="entities") == 0

    assert builder.examples() == []
    assert builder.counts()["entities"] == 0
    assert builder.stats()["invalid"] == 0


async def test_entities_use_the_model_when_it_is_available(tmp_path, monkeypatch):
    monkeypatch.setattr(finetune_mod, "is_available", lambda: True)

    async def fake_extract_entities(text, max_chars=8000):
        assert "cinco dias úteis" in text
        return {
            "entities": [{"name": "Loja A", "type": "organization", "confidence": 0.9}],
            "counts": {"organization": 1},
        }

    monkeypatch.setattr(entities_mod, "extract_entities", fake_extract_entities)

    builder = DatasetBuilder(tmp_path)
    assert builder.add_pages(PAGES[:1], kind="entities") == 1

    example = builder.examples()[0]
    assert json.loads(example.output) == [{"nome": "Loja A", "tipo": "organization"}]
    assert example.kind == "entities"


def test_extraction_uses_the_model_when_it_is_available(tmp_path, monkeypatch):
    monkeypatch.setattr(finetune_mod, "is_available", lambda: True)

    async def fake_extract_structured(text, url=""):
        return {"titulo": "Loja A", "preco": "R$ 10,00", "url": url}

    monkeypatch.setattr(extraction_mod, "extract_structured", fake_extract_structured, raising=False)

    builder = DatasetBuilder(tmp_path)
    assert builder.add_pages(PAGES[:1], kind="extraction") == 1

    payload = json.loads(builder.examples()[0].output)
    assert payload == {"titulo": "Loja A", "preco": "R$ 10,00", "url": "https://ex.com/a"}


def test_examples_are_persisted_and_reloaded(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)
    builder.add_pages(PAGES, kind="extraction")

    stored = tmp_path / "examples.json"
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600

    reloaded = DatasetBuilder(tmp_path)
    assert reloaded.examples() == builder.examples()
    assert reloaded.counts() == builder.counts()


def test_default_root_comes_from_settings(tmp_path, monkeypatch, no_ai):
    monkeypatch.setattr(settings, "finetune_dir", tmp_path / "ft")

    builder = DatasetBuilder()
    builder.add_pages(PAGES, kind="extraction")

    assert builder.root == tmp_path / "ft"
    assert (tmp_path / "ft" / "examples.json").is_file()

# ── exporting ─────────────────────────────────────────────────────────────


def test_export_writes_one_line_per_valid_example(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)
    builder.add_pages(PAGES, kind="extraction")
    builder.add_pages([{"url": "https://ex.com/curta", "text": "Curto."}], kind="summary")

    stats = builder.stats()
    assert stats["valid"] == 2
    assert stats["invalid"] == 1

    path = builder.export()
    records = load_dataset(path)

    assert len(records) == stats["valid"] == 2
    assert builder.last_export["written"] == 2
    assert builder.last_export["skipped"] == 1
    assert builder.last_export["format"] == "chat"
    assert all(set(record) == {"messages"} for record in records)
    assert path.read_text(encoding="utf-8").count("\n") == 2


def test_export_alpaca_writes_the_alpaca_keys(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)
    builder.add_pages(PAGES, kind="extraction")

    path = builder.export(fmt="alpaca")
    records = load_dataset(path)

    assert len(records) == 2
    assert all(set(record) == {"instruction", "input", "output"} for record in records)
    assert records[0]["instruction"].startswith("Extraia os dados principais")
    assert "cinco dias úteis" in records[0]["output"]


def test_export_with_unknown_format_raises(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)
    builder.add_pages(PAGES, kind="extraction")

    with pytest.raises(ValueError):
        builder.export(fmt="csv")


def test_export_twice_never_overwrites_the_first_file(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)
    builder.add_pages(PAGES, kind="extraction")

    first = builder.export()
    second = builder.export()

    assert first != second
    assert first.name == "dataset-1.jsonl"
    assert second.name == "dataset-2.jsonl"
    assert first.exists() and second.exists()
    assert len(load_dataset(first)) == len(load_dataset(second)) == 2


def test_stats_add_up(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)
    builder.add_pages(PAGES, kind="extraction")
    builder.add_pages(PAGES, kind="qa")
    builder.add_pages([{"url": "https://ex.com/curta", "text": "Curto."}], kind="summary")

    stats = builder.stats()

    assert stats["examples"] == len(builder.examples())
    assert stats["valid"] + stats["invalid"] == stats["examples"]
    assert stats["invalid"] == 1
    assert sum(stats["by_kind"].values()) == stats["examples"]
    assert stats["by_kind"]["extraction"] == 2
    assert stats["chars"] > 0


# ── reading back ──────────────────────────────────────────────────────────


def test_load_dataset_skips_corrupt_lines(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text(
        '{"instruction": "a", "input": "", "output": "b"}\n'
        "{quebrado\n"
        "\n"
        "[1, 2]\n",
        encoding="utf-8",
    )

    records = load_dataset(path)

    assert records == [{"instruction": "a", "input": "", "output": "b"}]


def test_dataset_summary_mentions_count_and_kinds(tmp_path, no_ai):
    builder = DatasetBuilder(tmp_path)
    builder.add_pages(PAGES, kind="extraction")
    builder.add_pages(PAGES, kind="summary")

    path = builder.export()
    summary = dataset_summary(path)

    assert "com 4 exemplos" in summary
    assert "2 de extração" in summary
    assert "2 de resumo" in summary


def test_dataset_summary_of_an_empty_file(tmp_path):
    path = tmp_path / "vazio.jsonl"
    path.write_text("", encoding="utf-8")

    assert "sem exemplos" in dataset_summary(path)


