"""Tests for the ROI report built on top of the metrics store and the cost model."""

from __future__ import annotations

import json

import pytest

from zfrog.analytics import MetricsStore, estimate_cost, rates_from_settings
from zfrog.config import settings
from zfrog.roi import (
    RoiInputs,
    break_even_pages,
    compute_roi,
    inputs_from_settings,
    roi_from_metrics,
    to_json,
    to_markdown,
)

#: Hand-computable tariff, identical in shape to the one used by the cost tests.
RATES = {
    "cost_per_gb_transfer": 0.09,
    "cost_per_cpu_hour": 0.36,
    "cost_per_gb_month": 0.023,
}

#: Three recorded runs: (engine, duration_s, total_bytes, files).
RUNS = [
    ("wget", 1800.0, 2_000_000_000, 12),
    ("wget", 900.0, 1_000_000_000, 4),
    ("httrack", 600.0, 500_000_000, 2),
]

#: 30 per hour, 2 minutes per page, in BRL: 18 pages -> 18.0 of avoided manual work.
HOURLY_RATE = 30.0
MINUTES_PER_PAGE = 2.0

@pytest.fixture(autouse=True)
def _isolated_roi_settings(tmp_path, monkeypatch):
    """Every test gets its own metrics database, tariff and ROI assumptions."""
    monkeypatch.setattr(settings, "metrics_db", tmp_path / "metrics.db")
    monkeypatch.setattr(settings, "cost_currency", "BRL")
    monkeypatch.setattr(settings, "roi_hourly_rate", HOURLY_RATE)
    monkeypatch.setattr(settings, "roi_manual_minutes_per_page", MINUTES_PER_PAGE)
    for name, value in RATES.items():
        monkeypatch.setattr(settings, name, value)

def _hand_priced(duration_s: float, total_bytes: int) -> float:
    """The price of one run, computed independently of the code under test."""
    gigabytes = total_bytes / 1e9
    transfer = gigabytes * RATES["cost_per_gb_transfer"]
    compute = duration_s / 3600.0 * RATES["cost_per_cpu_hour"]
    storage = gigabytes * RATES["cost_per_gb_month"]
    return round(transfer + compute + storage, 6)

def _recorded_store() -> MetricsStore:
    """A store holding :data:`RUNS`, all completed."""
    store = MetricsStore()
    for engine, duration_s, total_bytes, files in RUNS:
        store.record(engine, "completed", duration_s, total_bytes, files, "https://x.test", "clone")
    return store

def _inputs(hourly_rate: float = HOURLY_RATE, minutes: float = MINUTES_PER_PAGE) -> RoiInputs:
    return RoiInputs(hourly_rate=hourly_rate, minutes_per_page=minutes, currency="BRL")

def test_compute_roi_matches_hand_computed_values():
    result = compute_roi(120, 40.0, _inputs())
    assert result.value == pytest.approx(120 * 2.0 / 60 * 30.0)  # 120.0
    assert result.value == pytest.approx(120.0)
    assert result.cost == pytest.approx(40.0)
    assert result.net == pytest.approx(80.0)
    assert result.ratio == pytest.approx(3.0)
    assert result.pages == 120
    assert result.currency == "BRL"
    assert result.inputs == _inputs()

def test_compute_roi_carries_the_run_figures_through():
    result = compute_roi(5, 1.0, _inputs(), runs=3, bytes_=2048, duration_s=12.5)
    assert (result.runs, result.bytes, result.duration_s) == (3, 2048, 12.5)

def test_all_zero_inputs_give_zero_value_a_negative_net_and_no_ratio():
    result = compute_roi(0, 25.0, RoiInputs(hourly_rate=0.0, minutes_per_page=0.0, currency="BRL"))
    assert result.value == 0.0
    assert result.cost == pytest.approx(25.0)
    assert result.net == pytest.approx(-25.0)
    assert result.ratio is None  # nothing to compare: no rate, no minutes, no value

def test_zero_cost_keeps_the_value_and_reports_no_ratio():
    result = compute_roi(18, 0.0, _inputs())
    assert result.value == pytest.approx(18.0)
    assert result.cost == 0.0
    assert result.ratio is None  # a division by zero is not an infinite return
    assert result.net == pytest.approx(result.value)

def test_negative_inputs_are_clamped_instead_of_going_negative():
    result = compute_roi(-5, -10.0, _inputs(hourly_rate=-30.0, minutes=-2.0), runs=-3, bytes_=-1)
    assert result.pages == 0
    assert result.value == 0.0
    assert result.cost == 0.0
    assert result.net == 0.0
    assert result.ratio is None
    assert result.runs == 0 and result.bytes == 0
    # the echoed assumptions are the effective (clamped) ones, so the report cannot lie
    assert result.inputs.hourly_rate == 0.0
    assert result.inputs.minutes_per_page == 0.0

def test_break_even_pages_rounds_up_the_exact_quotient():
    # 60 per hour with 2 minutes per page -> 2.0 of value per page
    assert break_even_pages(100.0, _inputs(hourly_rate=60.0)) == 50
    assert break_even_pages(101.0, _inputs(hourly_rate=60.0)) == 51
    assert break_even_pages(99.0, _inputs(hourly_rate=60.0)) == 50
    assert break_even_pages(0.0, _inputs()) == 0

def test_break_even_pages_is_none_when_the_question_is_meaningless():
    assert break_even_pages(100.0, _inputs(hourly_rate=0.0)) is None
    assert break_even_pages(100.0, _inputs(minutes=0.0)) is None
    assert break_even_pages(100.0, RoiInputs(0.0, 0.0, "BRL")) is None

def test_inputs_from_settings_picks_up_the_monkeypatched_settings(monkeypatch):
    assert inputs_from_settings() == RoiInputs(30.0, 2.0, "BRL")
    monkeypatch.setattr(settings, "roi_hourly_rate", 55.5)
    monkeypatch.setattr(settings, "roi_manual_minutes_per_page", 3.5)
    monkeypatch.setattr(settings, "cost_currency", "USD")
    assert inputs_from_settings() == RoiInputs(55.5, 3.5, "USD")

def test_roi_from_metrics_reports_the_recorded_runs_and_the_cost_model():
    store = _recorded_store()
    result = roi_from_metrics(store=store)

    assert result.runs == len(RUNS)
    assert result.bytes == sum(run[2] for run in RUNS)
    assert result.duration_s == pytest.approx(sum(run[1] for run in RUNS))
    assert result.pages == sum(run[3] for run in RUNS)  # the documented page proxy

    expected_cost = sum(_hand_priced(run[1], run[2]) for run in RUNS)
    assert result.cost == pytest.approx(expected_cost)
    assert result.value == pytest.approx(18 * 2.0 / 60 * 30.0)  # 18 files -> 18.0
    assert result.net == pytest.approx(result.value - expected_cost)
    assert result.ratio == pytest.approx(result.value / expected_cost)
    assert result.currency == "BRL"
    assert result.inputs == _inputs()

    assert [row["engine"] for row in result.per_engine] == ["wget", "httrack"]
    assert result.per_engine[0]["runs"] == 2
    assert result.per_engine[0]["bytes"] == 3_000_000_000
    assert sum(row["cost"] for row in result.per_engine) == pytest.approx(expected_cost)

def test_per_engine_rows_carry_the_value_side_and_sum_to_the_totals():
    result = roi_from_metrics(store=_recorded_store())

    wget, httrack = result.per_engine
    # the cost-model keys survive untouched
    assert set(wget) == {"engine", "runs", "bytes", "duration_s", "cost", "cost_per_run",
                         "pages", "value", "net"}
    # the page proxy is split per engine and adds back up to the report's page count
    assert (wget["pages"], httrack["pages"]) == (16, 2)
    assert sum(row["pages"] for row in result.per_engine) == result.pages
    # 16 pages × 2 min ÷ 60 × R$ 30/h = 16.0; net = value − that engine's cost
    assert wget["value"] == pytest.approx(16.0)
    assert wget["net"] == pytest.approx(wget["value"] - wget["cost"])
    assert sum(row["value"] for row in result.per_engine) == pytest.approx(result.value)
    assert sum(row["net"] for row in result.per_engine) == pytest.approx(result.net)

def test_roi_from_metrics_note_says_the_page_count_is_an_estimate():
    note = roi_from_metrics(store=_recorded_store()).note
    assert "pages estimated by the files generated" in note
    assert "min per page" in note
    assert "BRL" in note

def test_roi_from_metrics_without_any_run_is_zero_and_not_an_error():
    result = roi_from_metrics(store=MetricsStore())
    assert (result.runs, result.pages, result.bytes) == (0, 0, 0)
    assert result.value == 0.0
    assert result.cost == 0.0
    assert result.net == 0.0
    assert result.ratio is None
    assert result.per_engine == []

def test_roi_from_metrics_does_not_create_the_database_it_reports_on(monkeypatch, tmp_path):
    missing = tmp_path / "nested" / "absent.db"
    monkeypatch.setattr(settings, "metrics_db", missing)
    result = roi_from_metrics()
    assert result.runs == 0
    assert result.cost == 0.0
    assert not missing.exists()

def test_roi_from_metrics_uses_the_settings_by_default():
    _recorded_store()
    assert roi_from_metrics().runs == len(RUNS)

def test_to_json_is_serialisable_and_nests_the_inputs():
    result = compute_roi(120, 40.0, _inputs(), runs=2, bytes_=10, duration_s=1.0)
    payload = to_json(result)
    encoded = json.dumps(payload)
    assert json.loads(encoded)["inputs"] == {
        "hourly_rate": 30.0,
        "minutes_per_page": 2.0,
        "currency": "BRL",
    }
    assert payload["value"] == pytest.approx(120.0)
    assert payload["ratio"] == pytest.approx(3.0)
    assert payload["per_engine"] == []

def test_to_markdown_shows_value_cost_assumptions_and_the_engine_table():
    report = to_markdown(roi_from_metrics(store=_recorded_store()))
    assert "R$ 18.00" in report  # value: 18 pages × 2 min ÷ 60 × R$ 30/h
    assert "R$ 0.73" in report  # cost: 0.7255 rounded to cents for display
    assert "R$ 17.27" in report  # net
    assert "24.81×" in report  # ratio
    assert "Assumptions" in report
    assert "Minutes per page: 2" in report
    assert "R$ 30.00" in report
    assert "BRL" in report
    assert "| wget | 2 | 16 | 3000000000 | 2700 | R$ 16.00 |" in report
    assert "| httrack | 1 | 2 | 500000000 | 600 | R$ 2.00 |" in report

def test_to_markdown_renders_a_dash_for_a_missing_ratio():
    report = to_markdown(compute_roi(18, 0.0, _inputs()))
    assert "| Return (value ÷ cost) | — |" in report
    assert "No runs recorded." in report

def test_to_markdown_of_a_zero_cost_report_still_shows_the_value():
    report = to_markdown(compute_roi(0, 0.0, _inputs()))
    assert "| Avoided manual work value | R$ 0.0000 |" in report
    assert "| Estimated cost | R$ 0.0000 |" in report

def test_rates_from_settings_are_the_ones_priced_into_the_report():
    assert rates_from_settings().currency == "BRL"
    breakdown = estimate_cost(1800.0, 2_000_000_000)
    assert breakdown.total == pytest.approx(_hand_priced(1800.0, 2_000_000_000))
