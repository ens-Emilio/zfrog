"""Tests for content-aware change alerts (no real model required)."""

import hashlib
import json
from pathlib import Path

import pytest

from zfrog.ai import significance as sig
from zfrog.ai.schemas import SignificanceResult
from zfrog.config import settings
from zfrog.diff import diff_snapshots, snapshots_dir, url_slug

FOOTER_URL = "https://rodape.example.com"
PRICE_URL = "https://loja.example.com"

# A date bump in the footer: same text, three characters differ.
FOOTER_PAGE = "Notebook Pro 14\nPreço sob consulta.\nÚltima atualização: 01/01/2026"
FOOTER_PAGE_NEW = "Notebook Pro 14\nPreço sob consulta.\nÚltima atualização: 15/06/2026"

# A real change: price and availability.
PRICE_PAGE = "Notebook Pro 14\nPreço: R$ 4.999,00\nEm estoque, envio imediato."
PRICE_PAGE_NEW = "Notebook Pro 14\nPreço: R$ 5.999,00\nEsgotado, reposição em 30 dias."


@pytest.fixture(autouse=True)
def _isolated_output(tmp_path, monkeypatch):
    """Never touch the repo's real output/ directory."""
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")


def _page(path: str, text: str, title: str = "") -> dict:
    return {
        "path": path,
        "url": f"https://example.com/{path}",
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "size_bytes": len(text.encode("utf-8")),
        "title": title,
        "text": text,
        "etag": "",
        "last_modified": "",
    }


def _write_snapshot(url: str, captured_at: str, pages: list[dict]) -> Path:
    """Write a real snapshot JSON under the (monkeypatched) output dir."""
    directory = snapshots_dir() / url_slug(url)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{captured_at.replace('-', '').replace(':', '')}.json"
    snapshot = {"url": url, "captured_at": captured_at, "engine": "wget", "pages": pages}
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _candidate(path: str, before: str, after: str, title: str = "", diff_lines: int = 0):
    return sig.ChangeCandidate(
        path=path, title=title, before=before, after=after, diff_lines=diff_lines
    )


# ── text_similarity ──


def test_text_similarity_identical_ignores_whitespace():
    assert sig.text_similarity("mesmo texto", "mesmo texto") == 1.0
    assert sig.text_similarity("Preço: R$ 4.999,00", "  Preço:   R$ 4.999,00\n\n") == 1.0
    assert sig.text_similarity("a\nb\tc", "a b  c") == 1.0


def test_text_similarity_unrelated_text():
    ratio = sig.text_similarity(
        "Produto disponível para envio imediato.", "zzz qqq 999 000 xxx"
    )
    assert ratio < 0.3


def test_text_similarity_empty_inputs():
    assert sig.text_similarity("", "") == 1.0
    assert sig.text_similarity("   \n\t ", "") == 1.0
    assert sig.text_similarity("", "qualquer coisa") == 0.0
    assert sig.text_similarity("qualquer coisa", "   ") == 0.0


def test_text_similarity_partial_change():
    ratio = sig.text_similarity(PRICE_PAGE, PRICE_PAGE_NEW)
    assert 0.0 < ratio < 1.0
    assert sig.change_ratio(PRICE_PAGE, PRICE_PAGE_NEW) == pytest.approx(1 - ratio)


# ── select_candidates ──


def _multi_page_diff() -> tuple[sig.DiffReport, dict, dict]:
    """A diff with a big change, a small change and a below-min_change change."""
    long_about = (
        "Sobre nós\nSomos uma empresa de tecnologia fundada em 2010 e atendemos todo o "
        "Brasil com suporte dedicado, garantia estendida e entrega rápida para milhares "
        "de clientes todos os meses.\n"
    ) * 3 + "Última atualização: 01/01/2026"
    long_about_new = long_about.replace("01/01/2026", "15/06/2026")

    pages_a = [
        _page("index.html", PRICE_PAGE, title="Loja"),
        _page("precos.html", "Preço do plano básico: R$ 99,00 por mês, sem fidelidade."),
        _page("sobre.html", long_about),
    ]
    pages_b = [
        _page("index.html", PRICE_PAGE_NEW, title="Loja"),
        _page("precos.html", "Preço do plano básico: R$ 119,00 por mês, sem fidelidade."),
        _page("sobre.html", long_about_new),
    ]
    snapshot_a = _write_snapshot(PRICE_URL, "2026-01-01T00:00:00Z", pages_a)
    snapshot_b = _write_snapshot(PRICE_URL, "2026-06-15T00:00:00Z", pages_b)
    report = diff_snapshots(snapshot_a, snapshot_b)
    return report, {"pages": pages_a}, {"pages": pages_b}


def test_select_candidates_ranks_biggest_change_first():
    report, data_a, data_b = _multi_page_diff()

    candidates = sig.select_candidates(report, data_a, data_b)

    assert [candidate.path for candidate in candidates] == ["index.html", "precos.html"]
    assert candidates[0].title == "Loja"
    assert candidates[0].before == PRICE_PAGE
    assert candidates[0].after == PRICE_PAGE_NEW
    assert candidates[0].diff_lines > 0
    # The footer-only date bump of the long page stays below min_change.
    assert "sobre.html" in report.changed


def test_select_candidates_honours_max_candidates():
    report, data_a, data_b = _multi_page_diff()

    assert [c.path for c in sig.select_candidates(report, data_a, data_b, max_candidates=1)] == [
        "index.html"
    ]
    assert sig.select_candidates(report, data_a, data_b, max_candidates=0) == []


def test_select_candidates_skips_pages_missing_from_a_snapshot():
    report, data_a, data_b = _multi_page_diff()
    # Only in the older snapshot / only in the newer one: neither can be judged.
    data_a = {"pages": data_a["pages"] + [_page("antiga.html", "só na versão antiga")]}
    data_b = {"pages": data_b["pages"] + [_page("nova.html", "só na versão nova")]}
    report.changed = ["index.html", "antiga.html", "nova.html"]

    candidates = sig.select_candidates(report, data_a, data_b)

    assert [candidate.path for candidate in candidates] == ["index.html"]


def test_select_candidates_honours_min_change():
    report, data_a, data_b = _multi_page_diff()

    candidates = sig.select_candidates(report, data_a, data_b, min_change=0.1)

    assert [candidate.path for candidate in candidates] == ["index.html"]


# ── heuristic ──


def test_heuristic_significance_empty():
    assert sig.heuristic_significance([]) == {
        "significant": False,
        "score": 0.0,
        "summary": "",
        "reasons": [],
    }


def test_heuristic_significance_summary_names_most_changed_page():
    candidates = [
        _candidate("precos.html", "R$ 99,00", "R$ 119,00"),
        _candidate("index.html", PRICE_PAGE, PRICE_PAGE_NEW),
    ]

    result = sig.heuristic_significance(candidates, threshold=0.1)

    assert result["score"] > 0.1
    assert result["significant"] is True
    assert "index.html" in result["summary"]
    assert result["reasons"][0].startswith("index.html:")
    assert "precos.html:" in result["reasons"][1]
    assert result["score"] <= 1.0


# ── judge_significance ──


async def test_judge_significance_empty_never_calls_ai(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the AI must not be consulted for empty candidates")

    monkeypatch.setattr(sig, "can_call", boom)
    monkeypatch.setattr(sig, "complete_structured", boom)

    assert await sig.judge_significance([]) == {
        "significant": False,
        "score": 0.0,
        "summary": "",
        "reasons": [],
    }


async def test_judge_significance_without_ai_uses_heuristic(monkeypatch):
    candidates = [_candidate("index.html", PRICE_PAGE, PRICE_PAGE_NEW)]

    async def boom(*args, **kwargs):
        raise AssertionError("no model call when the AI is unavailable")

    monkeypatch.setattr(sig, "can_call", lambda: False)
    monkeypatch.setattr(sig, "complete_structured", boom)

    monkeypatch.setattr(settings, "significance_threshold", 0.05)
    low = await sig.judge_significance(candidates, url=PRICE_URL)

    monkeypatch.setattr(settings, "significance_threshold", 0.9)
    high = await sig.judge_significance(candidates, url=PRICE_URL)

    assert low["significant"] is True
    assert high["significant"] is False
    assert low["score"] == high["score"] == sig.heuristic_significance(candidates)["score"]
    assert low["error"] == "AI unavailable"
    assert "index.html" in low["summary"]


async def test_judge_significance_uses_model_result(monkeypatch):
    candidates = [_candidate("index.html", PRICE_PAGE, PRICE_PAGE_NEW, title="Loja")]
    seen: dict = {}

    async def fake_structured(messages, response_model, **kwargs):
        seen["messages"] = messages
        seen["response_model"] = response_model
        seen["kwargs"] = kwargs
        return SignificanceResult(
            significant=True,
            score=0.9,
            summary="O preço subiu e o produto saiu de estoque.",
            reasons=["preço de R$ 4.999,00 passou a R$ 5.999,00", "produto esgotado"],
        )

    def no_heuristic(*args, **kwargs):
        raise AssertionError("the model answered; the heuristic must not run")

    monkeypatch.setattr(sig, "can_call", lambda: True)
    monkeypatch.setattr(sig, "complete_structured", fake_structured)
    monkeypatch.setattr(sig, "heuristic_significance", no_heuristic)

    result = await sig.judge_significance(candidates, url=PRICE_URL)

    assert result == {
        "significant": True,
        "score": 0.9,
        "summary": "O preço subiu e o produto saiu de estoque.",
        "reasons": ["preço de R$ 4.999,00 passou a R$ 5.999,00", "produto esgotado"],
    }
    assert seen["response_model"] is SignificanceResult
    assert seen["kwargs"]["temperature"] == 0.0
    prompt = seen["messages"][1]["content"]
    assert "index.html" in prompt
    assert "R$ 4.999,00" in prompt and "R$ 5.999,00" in prompt
    assert PRICE_URL in prompt


async def test_judge_significance_model_failure_falls_back_to_heuristic(monkeypatch):
    candidates = [_candidate("index.html", PRICE_PAGE, PRICE_PAGE_NEW)]

    async def boom(*args, **kwargs):
        raise RuntimeError("nenhum modelo disponível")

    monkeypatch.setattr(sig, "can_call", lambda: True)
    monkeypatch.setattr(sig, "complete_structured", boom)

    result = await sig.judge_significance(candidates, url=PRICE_URL)
    expected = sig.heuristic_significance(candidates)

    assert result["score"] == expected["score"]
    assert result["significant"] == expected["significant"]
    assert "Significance evaluation failed" in result["error"]
    assert "nenhum modelo disponível" in result["error"]


async def test_judge_significance_error_text_is_bounded(monkeypatch):
    candidates = [_candidate("index.html", PRICE_PAGE, PRICE_PAGE_NEW)]

    async def boom(*args, **kwargs):
        raise RuntimeError("falha no provedor\n" + "detalhe irrelevante " * 100)

    monkeypatch.setattr(sig, "can_call", lambda: True)
    monkeypatch.setattr(sig, "complete_structured", boom)

    result = await sig.judge_significance(candidates)

    assert "\n" not in result["error"]
    assert result["error"].endswith("…")
    assert len(result["error"]) < sig.MAX_ERROR_CHARS + 60


async def test_judge_significance_prompt_is_bounded(monkeypatch):
    before = "A" * 50_000 + " fim do texto antigo"
    after = "B" * 50_000 + " fim do texto novo"
    candidates = [_candidate("grande.html", before, after)]
    seen: dict = {}

    async def fake_structured(messages, response_model, **kwargs):
        seen["prompt"] = messages[1]["content"]
        return SignificanceResult(significant=False, score=0.0, summary="", reasons=[])

    monkeypatch.setattr(sig, "can_call", lambda: True)
    monkeypatch.setattr(sig, "complete_structured", fake_structured)

    await sig.judge_significance(candidates)

    prompt = seen["prompt"]
    assert len(prompt) < 4000
    assert prompt.startswith(f"Site: (unknown)\n\n### Page 1: grande.html")
    # Head and tail of both sides survive, so an end-of-page change is visible.
    assert "A" * 100 in prompt and "fim do texto antigo" in prompt
    assert "B" * 100 in prompt and "fim do texto novo" in prompt


# ── significant_change ──


async def test_significant_change_price_beats_footer(monkeypatch):
    monkeypatch.setattr(sig, "can_call", lambda: False)

    footer_prev = _write_snapshot(
        FOOTER_URL, "2026-01-01T00:00:00Z", [_page("produto.html", FOOTER_PAGE)]
    )
    footer_new = _write_snapshot(
        FOOTER_URL, "2026-06-15T00:00:00Z", [_page("produto.html", FOOTER_PAGE_NEW)]
    )
    price_prev = _write_snapshot(
        PRICE_URL, "2026-01-01T00:00:00Z", [_page("produto.html", PRICE_PAGE)]
    )
    price_new = _write_snapshot(
        PRICE_URL, "2026-06-15T00:00:00Z", [_page("produto.html", PRICE_PAGE_NEW)]
    )

    footer = await sig.significant_change(FOOTER_URL, footer_prev, footer_new)
    price = await sig.significant_change(PRICE_URL, price_prev, price_new)

    assert footer is not None and price is not None
    assert footer["score"] < price["score"]
    assert footer["error"] == "AI unavailable" and price["error"] == "AI unavailable"
    assert "produto.html" in price["summary"]


async def test_significant_change_identical_snapshots_returns_none(monkeypatch):
    monkeypatch.setattr(sig, "can_call", lambda: False)

    prev = _write_snapshot(PRICE_URL, "2026-01-01T00:00:00Z", [_page("produto.html", PRICE_PAGE)])
    new = _write_snapshot(PRICE_URL, "2026-06-15T00:00:00Z", [_page("produto.html", PRICE_PAGE)])

    assert await sig.significant_change(PRICE_URL, prev, new) is None


async def test_significant_change_unreadable_snapshot_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(sig, "can_call", lambda: False)

    prev = _write_snapshot(PRICE_URL, "2026-01-01T00:00:00Z", [_page("produto.html", PRICE_PAGE)])
    missing = tmp_path / "nao-existe.json"

    assert await sig.significant_change(PRICE_URL, prev, missing) is None


async def test_significant_change_ignores_footer_only_change_of_a_long_page(monkeypatch):
    """Nothing worth alerting about: the only changed page is a huge page + a date."""
    monkeypatch.setattr(sig, "can_call", lambda: False)

    body = "Conteúdo estável da página institucional. " * 40
    prev = _write_snapshot(
        FOOTER_URL,
        "2026-01-01T00:00:00Z",
        [_page("sobre.html", body + "\nÚltima atualização: 01/01/2026")],
    )
    new = _write_snapshot(
        FOOTER_URL,
        "2026-06-15T00:00:00Z",
        [_page("sobre.html", body + "\nÚltima atualização: 15/06/2026")],
    )

    assert await sig.significant_change(FOOTER_URL, prev, new) is None
