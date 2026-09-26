"""Tests for the cost model on top of the per-engine metrics store."""

from __future__ import annotations

import logging
from dataclasses import asdict

import pytest

from zfrog.analytics import (
    CostBreakdown,
    CostRates,
    MetricsStore,
    estimate_cost,
    format_cost,
    rates_from_settings,
)
from zfrog.config import settings

#: Hand-computable tariff: 0.09 per GB of egress, 0.36 per CPU-hour, 0.023 per GB-month.
RATES = CostRates(
    per_gb_transfer=0.09,
    per_cpu_hour=0.36,
    per_gb_month=0.023,
    currency="BRL",
)

#: One run of 2 GB that took half an hour, priced by the formula in ``estimate_cost``.
TWO_GB_HALF_HOUR = 0.18 + 0.18 + 0.046


@pytest.fixture(autouse=True)
def _isolated_cost_settings(tmp_path, monkeypatch):
    """Every test gets its own metrics database and a known tariff."""
    monkeypatch.setattr(settings, "metrics_db", tmp_path / "metrics.db")
    monkeypatch.setattr(settings, "cost_per_gb_transfer", RATES.per_gb_transfer)
    monkeypatch.setattr(settings, "cost_per_cpu_hour", RATES.per_cpu_hour)
    monkeypatch.setattr(settings, "cost_per_gb_month", RATES.per_gb_month)
    monkeypatch.setattr(settings, "cost_currency", RATES.currency)


def _run_cost(duration_s: float, total_bytes: int, rates: CostRates = RATES) -> float:
    """Independent hand-rolled price of one run, rounded like ``estimate_cost`` does."""
    gigabytes = total_bytes / 1e9
    return round(
        gigabytes * rates.per_gb_transfer
        + duration_s / 3600 * rates.per_cpu_hour
        + gigabytes * rates.per_gb_month,
        6,
    )


def test_estimate_cost_matches_hand_computed_components():
    breakdown = estimate_cost(1800.0, 2_000_000_000, RATES)

    assert isinstance(breakdown, CostBreakdown)
    assert breakdown.transfer == pytest.approx(0.18)  # 2 GB * 0.09
    assert breakdown.compute == pytest.approx(0.18)  # 0.5 h * 0.36
    assert breakdown.storage == pytest.approx(0.046)  # 2 GB * 0.023
    assert breakdown.total == pytest.approx(TWO_GB_HALF_HOUR) == pytest.approx(0.406)
    assert breakdown.currency == "BRL"


def test_estimate_cost_reads_the_settings_when_no_rates_are_given():
    breakdown = estimate_cost(1800.0, 2_000_000_000)

    assert breakdown.total == pytest.approx(TWO_GB_HALF_HOUR)
    assert breakdown.currency == "BRL"
    assert breakdown == estimate_cost(1800.0, 2_000_000_000, rates_from_settings())


def test_zero_rates_never_invent_money(monkeypatch):
    for name in ("cost_per_gb_transfer", "cost_per_cpu_hour", "cost_per_gb_month"):
        monkeypatch.setattr(settings, name, 0.0)

    breakdown = estimate_cost(3600.0, 10_000_000_000)

    assert (breakdown.transfer, breakdown.compute, breakdown.storage) == (0.0, 0.0, 0.0)
    assert breakdown.total == 0.0
    assert estimate_cost(3600.0, 10_000_000_000, CostRates()).total == 0.0


def test_negative_inputs_clamp_to_zero():
    breakdown = estimate_cost(-1800.0, -2_000_000_000, RATES)

    assert (breakdown.transfer, breakdown.compute, breakdown.storage) == (0.0, 0.0, 0.0)
    assert breakdown.total == 0.0

    refund = CostRates(per_gb_transfer=-1.0, per_cpu_hour=-2.0, per_gb_month=-3.0)

    assert estimate_cost(3600.0, 1_000_000_000, refund).total == 0.0


def test_rates_from_settings_picks_up_the_monkeypatched_settings():
    rates = rates_from_settings()

    assert rates == RATES
    assert rates.per_gb_transfer == 0.09
    assert rates.per_cpu_hour == 0.36
    assert rates.per_gb_month == 0.023
    assert rates.currency == "BRL"


def test_broken_settings_degrade_to_zero_and_do_not_raise(monkeypatch, caplog):
    monkeypatch.setattr(settings, "cost_per_gb_transfer", "not-a-number")
    monkeypatch.setattr(settings, "cost_per_cpu_hour", None)
    monkeypatch.setattr(settings, "cost_per_gb_month", float("nan"))

    with caplog.at_level(logging.WARNING, logger="zfrog.analytics"):
        rates = rates_from_settings()
        store = MetricsStore()
        store.record("wget", "completed", 10.0, 1_000_000, 1)
        totals = store.totals()
        garbage = estimate_cost("abc", None, rates)

    assert (rates.per_gb_transfer, rates.per_cpu_hour, rates.per_gb_month) == (0.0, 0.0, 0.0)
    assert totals["cost"] == 0.0
    assert totals["currency"] == "BRL"
    assert garbage.total == 0.0
    assert any("custo" in record.getMessage() for record in caplog.records)


def test_engine_stats_costs_agree_with_the_hand_computed_price():
    store = MetricsStore()
    runs = [("wget", 10.0, 1_000_000), ("wget", 20.0, 2_000_000), ("wget", 30.0, 3_000_000)]
    for engine, duration, size in runs:
        store.record(engine, "completed", duration, size, 1)

    stat = store.engine_stats("wget")[0]

    expected = sum(_run_cost(duration, size) for _, duration, size in runs)

    assert expected > 0.0
    assert stat.runs == 3
    assert stat.total_cost == pytest.approx(expected, abs=1e-9)
    assert stat.avg_cost == pytest.approx(expected / 3, abs=1e-9)
    # the per-run totals estimate_cost reports add up to the same figure
    assert stat.total_cost == pytest.approx(
        sum(estimate_cost(duration, size, RATES).total for _, duration, size in runs),
        abs=1e-9,
    )


def test_engine_stats_append_the_cost_fields_after_the_existing_ones():
    store = MetricsStore()
    store.record("wget", "completed", 10.0, 1000, 1)

    stat = store.engine_stats()[0]

    assert list(asdict(stat)) == [
        "engine",
        "runs",
        "succeeded",
        "failed",
        "success_rate",
        "avg_duration_s",
        "avg_bytes",
        "total_bytes",
        "avg_files",
        "total_cost",
        "avg_cost",
    ]
    assert stat.total_cost > 0.0
    assert stat.avg_cost == pytest.approx(stat.total_cost, abs=1e-9)  # a single run


def test_cost_by_engine_is_sorted_by_cost_and_divides_per_run():
    store = MetricsStore()
    store.record("wget", "completed", 60.0, 1_000_000_000, 5)
    store.record("wget", "completed", 120.0, 1_000_000_000, 5)
    store.record("playwright", "completed", 10.0, 0, 2)

    rows = store.cost_by_engine(RATES)

    assert [row["engine"] for row in rows] == ["wget", "playwright"]

    wget, playwright = rows
    assert (wget["runs"], wget["bytes"], wget["duration_s"]) == (2, 2_000_000_000, 180.0)
    expected_wget = _run_cost(60.0, 1_000_000_000) + _run_cost(120.0, 1_000_000_000)
    assert wget["cost"] == pytest.approx(expected_wget, abs=1e-9)
    assert wget["cost_per_run"] == pytest.approx(expected_wget / 2, abs=1e-9)

    assert (playwright["runs"], playwright["bytes"], playwright["duration_s"]) == (1, 0, 10.0)
    assert playwright["cost"] == pytest.approx(0.001, abs=1e-9)  # 10 s of CPU-hour only
    assert playwright["cost_per_run"] == pytest.approx(0.001, abs=1e-9)

    assert set(wget) == {"engine", "runs", "bytes", "duration_s", "cost", "cost_per_run"}


def test_cost_by_engine_without_a_tariff_is_zero_and_not_an_error(monkeypatch):
    for name in ("cost_per_gb_transfer", "cost_per_cpu_hour", "cost_per_gb_month"):
        monkeypatch.setattr(settings, name, 0.0)
    store = MetricsStore()
    store.record("wget", "completed", 10.0, 1_000, 1)

    assert store.cost_by_engine() == [
        {
            "engine": "wget",
            "runs": 1,
            "bytes": 1_000,
            "duration_s": 10.0,
            "cost": 0.0,
            "cost_per_run": 0.0,
        }
    ]


def test_totals_cost_sums_the_per_engine_costs():
    store = MetricsStore()
    store.record("wget", "completed", 60.0, 1_000_000_000, 5)
    store.record("playwright", "completed", 10.0, 0, 2)

    totals = store.totals()
    per_engine = store.cost_by_engine()

    assert totals["currency"] == "BRL"
    assert totals["cost"] == pytest.approx(sum(row["cost"] for row in per_engine), abs=1e-9)
    assert totals["cost"] == pytest.approx(_run_cost(60.0, 1_000_000_000) + 0.001, abs=1e-9)
    assert per_engine[0]["engine"] == "wget"  # the expensive engine leads


def test_empty_store_reports_zero_cost_and_no_engines():
    store = MetricsStore()

    totals = store.totals()

    assert totals["cost"] == 0.0
    assert totals["currency"] == "BRL"
    assert store.cost_by_engine() == []
    assert store.engine_stats() == []


def test_format_cost_renders_known_currencies():
    assert format_cost(0.0042, "BRL") == "R$ 0.0042"
    assert format_cost(1.2, "USD") == "$ 1.20"
    assert format_cost(0.0042, "usd") == "$ 0.0042"
    assert format_cost(12.5, "BRL") == "R$ 12.50"


def test_format_cost_threshold_and_fallback():
    assert format_cost(0.0099, "USD") == "$ 0.0099"  # below a cent: four decimals
    assert format_cost(0.01, "USD") == "$ 0.01"  # at a cent: two
    assert format_cost(1.2, "XYZ") == "XYZ 1.20"
    assert format_cost(0.5, "XYZ") == "XYZ 0.50"
    assert format_cost(1.2) == "1.20"
    assert format_cost(0.0, "BRL") == "R$ 0.0000"
