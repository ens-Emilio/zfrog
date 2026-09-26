"""Tests for market trends over a site's snapshot history."""

import json
from pathlib import Path

import pytest

from zfrog import diff as diff_mod
from zfrog.analysis import trends as trends_mod
from zfrog.config import settings

URL = "https://loja.example"


@pytest.fixture(autouse=True)
def _isolated_output(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")


def _paragraphs(term: str, count: int) -> str:
    return "".join(f"<p>{term}</p>" for _ in range(count))


def _html(*blocks: str) -> str:
    return f"<html><body>{''.join(blocks)}</body></html>"


def _capture(url: str, html: str, tmp_path: Path, name: str) -> Path:
    """Crawl-output dir with one real page, then a real snapshot of it."""
    job = tmp_path / name
    job.mkdir(parents=True, exist_ok=True)
    (job / "index.html").write_text(html, encoding="utf-8")
    path, _ = diff_mod.capture_snapshot(job, url, "wget")
    return path


def _points(*values: float) -> list[trends_mod.TrendPoint]:
    return [
        trends_mod.TrendPoint(captured_at=f"2026-01-{index + 1:02d}T00:00:00Z", value=float(value))
        for index, value in enumerate(values)
    ]


def test_mention_counts_tracks_a_term_across_snapshots(tmp_path):
    paths = [_capture(URL, _html(_paragraphs("preço", n)), tmp_path, f"job{n}") for n in (1, 3, 5)]

    points = trends_mod.mention_counts(URL, "preço")

    assert [point.value for point in points] == [1.0, 3.0, 5.0]
    assert [point.captured_at for point in points] == [
        json.loads(path.read_text(encoding="utf-8"))["captured_at"] for path in paths
    ]

    trend = trends_mod.compute_trend("preço", points)
    assert trend.direction == "rising"
    assert trend.change_pct == pytest.approx(400.0)
    assert (trend.first, trend.last, trend.samples) == (1.0, 5.0, 3)


def test_term_match_ignores_case_and_accents_both_ways(tmp_path):
    _capture(URL, _html(_paragraphs("Preço", 1)), tmp_path, "accented")
    _capture(URL, _html(_paragraphs("preco", 2)), tmp_path, "plain")

    assert [point.value for point in trends_mod.mention_counts(URL, "preco")] == [1.0, 2.0]
    assert [point.value for point in trends_mod.mention_counts(URL, "PREÇO")] == [1.0, 2.0]
    assert [point.value for point in trends_mod.mention_counts(URL, "PrEcO")] == [1.0, 2.0]


def test_absent_term_counts_zero_instead_of_failing(tmp_path):
    for n in (1, 3, 5):
        _capture(URL, _html(_paragraphs("preço", n)), tmp_path, f"job{n}")

    points = trends_mod.mention_counts(URL, "inexistente")
    assert [point.value for point in points] == [0.0, 0.0, 0.0]

    trend = trends_mod.compute_trend("inexistente", points)
    assert trend.direction == "flat"
    assert trend.change_pct == 0.0
    assert trend.samples == 3


def test_mention_counts_caps_at_limit(tmp_path):
    for n in (1, 3, 5):
        _capture(URL, _html(_paragraphs("preço", n)), tmp_path, f"job{n}")

    assert [point.value for point in trends_mod.mention_counts(URL, "preço", limit=2)] == [1.0, 3.0]
    assert trends_mod.mention_counts(URL, "preço", limit=0) == []
    assert trends_mod.mention_counts("https://nada.example", "preço") == []


def test_compute_trend_rising_and_falling():
    up = trends_mod.compute_trend("preço", _points(2, 3, 4))
    assert up.direction == "rising"
    assert up.change_pct == pytest.approx(100.0)
    assert (up.first, up.last, up.samples) == (2.0, 4.0, 3)
    assert [point.value for point in up.points] == [2.0, 3.0, 4.0]

    down = trends_mod.compute_trend("preço", _points(10, 7, 5))
    assert down.direction == "falling"
    assert down.change_pct == pytest.approx(-50.0)


def test_flat_band_edges():
    assert trends_mod.compute_trend("t", _points(100, 104)).direction == "flat"
    assert trends_mod.compute_trend("t", _points(100, 105)).direction == "flat"
    assert trends_mod.compute_trend("t", _points(100, 106)).direction == "rising"
    assert trends_mod.compute_trend("t", _points(100, 96)).direction == "flat"
    assert trends_mod.compute_trend("t", _points(100, 94)).direction == "falling"
    # the same numbers under a wider band are flat
    assert trends_mod.compute_trend("t", _points(100, 120), flat_band_pct=25.0).direction == "flat"


def test_fewer_than_two_points_is_unknown_not_flat():
    single = trends_mod.compute_trend("t", _points(7))
    assert single.direction == "unknown"
    assert single.change_pct == 0.0
    assert (single.first, single.last, single.samples) == (7.0, 7.0, 1)

    empty = trends_mod.compute_trend("t", [])
    assert empty.direction == "unknown"
    assert empty.change_pct == 0.0
    assert (empty.first, empty.last, empty.samples) == (0.0, 0.0, 0)
    assert empty.points == []


def test_zero_baseline_with_a_positive_last_is_100_pct():
    trend = trends_mod.compute_trend("t", _points(0, 3))
    assert trend.change_pct == 100.0
    assert trend.direction == "rising"
    assert trends_mod.compute_trend("t", _points(0, 0)).direction == "flat"


def test_rising_and_falling_filter_sort_and_respect_min_samples():
    up_strong = trends_mod.compute_trend("a", _points(1, 5))  # +400%
    up_mild = trends_mod.compute_trend("b", _points(100, 120))  # +20%
    down = trends_mod.compute_trend("c", _points(100, 40))  # -60%
    flat = trends_mod.compute_trend("d", _points(100, 101))
    short = trends_mod.compute_trend("e", _points(5))  # 1 sample
    long_up = trends_mod.compute_trend("f", _points(1, 2, 3))  # 3 samples, +200%

    all_trends = [flat, down, up_mild, up_strong, short, long_up]

    assert [trend.term for trend in trends_mod.rising(all_trends)] == ["a", "f", "b"]
    assert [trend.term for trend in trends_mod.falling(all_trends)] == ["c"]
    assert [trend.term for trend in trends_mod.rising(all_trends, min_samples=3)] == ["f"]
    assert trends_mod.falling(all_trends, min_samples=3) == []


def test_trends_returns_one_per_known_term_in_the_order_asked(tmp_path):
    for n in (1, 3, 5):
        _capture(
            URL,
            _html(_paragraphs("preço", n), _paragraphs("entrega", 2)),
            tmp_path,
            f"job{n}",
        )

    result = trends_mod.trends(URL, ["entrega", "preço", "ausente"])

    assert [trend.term for trend in result] == ["entrega", "preço"]
    assert result[0].direction == "flat"
    assert result[1].direction == "rising"
    assert result[1].samples == 3


def test_trends_without_snapshots_is_empty(tmp_path):
    assert trends_mod.trends("https://nada.example", ["preço"]) == []


def test_to_markdown_lists_each_term_and_notes_short_history():
    rising_trend = trends_mod.compute_trend("preço", _points(1, 5))
    short = trends_mod.compute_trend("entrega", _points(2))

    md = trends_mod.to_markdown(URL, [rising_trend, short])

    assert URL in md
    assert "| preço | 1 | 5 | +400.0% | rising |" in md
    assert "| entrega | 2 | 2 | +0.0% | unknown |" in md
    assert "apenas 1 amostra" in md
    assert "Nenhum termo" in trends_mod.to_markdown(URL, [])


def test_summarize_names_the_strongest_mover():
    strong = trends_mod.compute_trend("preço", _points(1, 5))
    mild = trends_mod.compute_trend("entrega", _points(100, 110))

    text = trends_mod.summarize([mild, strong])

    assert "preço" in text
    assert "entrega" not in text
    assert "400.0%" in text
    assert "alta" in text

    fall = trends_mod.summarize([trends_mod.compute_trend("preço", _points(10, 4))])
    assert "queda" in fall


def test_summarize_admits_when_history_is_too_short():
    text = trends_mod.summarize([trends_mod.compute_trend("preço", _points(3))])

    assert "insuficiente" in text
    assert "preço" not in text
    assert trends_mod.summarize([]) == text


def test_price_series_reads_a_real_price_tracker(tmp_path, monkeypatch):
    pricing = pytest.importorskip("zfrog.pricing")
    monkeypatch.setattr(settings, "analysis_dir", tmp_path / "analysis")
    tracker = pricing.PriceTracker(root=tmp_path / "prices")

    tracker.record(
        URL,
        [
            pricing.Price(
                label="Notebook", value=3499.0, currency="BRL", raw="R$ 3.499,00", context=""
            )
        ],
        captured_at="2026-01-01T00:00:00Z",
    )
    tracker.record(
        URL,
        [
            pricing.Price(
                label="Notebook", value=3199.0, currency="BRL", raw="R$ 3.199,00", context=""
            )
        ],
        captured_at="2026-02-01T00:00:00Z",
    )

    points = trends_mod.price_series(URL, "Notebook", tracker)

    assert [point.value for point in points] == [3499.0, 3199.0]
    assert [point.captured_at for point in points] == [
        "2026-01-01T00:00:00Z",
        "2026-02-01T00:00:00Z",
    ]
    assert trends_mod.compute_trend("Notebook", points).direction == "falling"

    # label lookup ignores case, and an unknown label is empty rather than an error
    by_case = trends_mod.price_series(URL, "notebook", tracker)
    assert [point.value for point in by_case] == [3499.0, 3199.0]
    assert trends_mod.price_series(URL, "outro", tracker) == []


def test_price_series_uses_the_default_tracker_root(tmp_path, monkeypatch):
    pricing = pytest.importorskip("zfrog.pricing")
    monkeypatch.setattr(settings, "analysis_dir", tmp_path / "analysis")

    pricing.PriceTracker().record(
        URL,
        [pricing.Price(label="Notebook", value=100.0, currency="BRL", raw="R$ 100", context="")],
        captured_at="2026-01-01T00:00:00Z",
    )

    points = trends_mod.price_series(URL, "Notebook")

    assert [point.value for point in points] == [100.0]
    assert (tmp_path / "analysis" / "prices").exists()


def test_price_series_matches_a_label_spelled_differently(tmp_path, monkeypatch):
    pricing = pytest.importorskip("zfrog.pricing")
    monkeypatch.setattr(settings, "analysis_dir", tmp_path / "analysis")
    tracker = pricing.PriceTracker(root=tmp_path / "prices")

    # The tracker keys by the label as given, so the stored key keeps its accent.
    tracker.record(
        URL,
        [pricing.Price(label="Preço médio", value=42.0, currency="BRL", raw="R$ 42", context="")],
        captured_at="2026-01-01T00:00:00Z",
    )
    tracker.record(
        URL,
        [pricing.Price(label="Frete", value=19.9, currency="BRL", raw="R$ 19,90", context="")],
        captured_at="2026-01-01T00:00:00Z",
    )

    assert [point.value for point in trends_mod.price_series(URL, "preco medio", tracker)] == [42.0]
    assert [point.value for point in trends_mod.price_series(URL, "PREÇO MÉDIO", tracker)] == [42.0]
    # An unknown label must not fall back to whichever series happens to exist.
    assert trends_mod.price_series(URL, "seguro", tracker) == []
    assert trends_mod.price_series(URL, "", tracker) == []
