"""Tests for per-engine execution metrics (SQLite-backed)."""

from __future__ import annotations

import logging

import pytest

from zfrog.analytics import EngineStats, MetricsStore, format_engine_table
from zfrog.config import settings
from zfrog.engines.base import EngineResult
from zfrog.models import JobResult


@pytest.fixture(autouse=True)
def _isolated_metrics(tmp_path, monkeypatch):
    """Every test gets its own metrics database."""
    monkeypatch.setattr(settings, "metrics_db", tmp_path / "metrics.db")


def _seed_three_runs(store: MetricsStore) -> None:
    """Two successful wget runs and one failed one."""
    store.record("wget", "completed", 10.0, 1000, 4, "https://a.test", "mirror")
    store.record("wget", "completed", 20.0, 3000, 8, "https://b.test", "mirror")
    store.record("wget", "failed", 30.0, 0, 0, "https://c.test", "scrape")


def test_engine_stats_counts_and_success_rate():
    store = MetricsStore()
    _seed_three_runs(store)
    store.record("playwright", "completed", 5.0, 500, 2)

    stats = store.engine_stats()

    assert [s.engine for s in stats] == ["wget", "playwright"]  # runs descending
    wget = stats[0]
    assert (wget.runs, wget.succeeded, wget.failed) == (3, 2, 1)
    assert wget.success_rate == round(2 / 3, 3) == 0.667

    playwright = stats[1]
    assert (playwright.runs, playwright.succeeded, playwright.failed) == (1, 1, 0)
    assert playwright.success_rate == 1.0


def test_engine_stats_filters_by_engine():
    store = MetricsStore()
    _seed_three_runs(store)
    store.record("playwright", "completed", 5.0, 500, 2)

    stats = store.engine_stats("wget")

    assert len(stats) == 1
    assert stats[0].engine == "wget"
    assert stats[0].runs == 3
    assert store.engine_stats("scrapy") == []


def test_averages_are_arithmetic_means():
    store = MetricsStore()
    store.record("wget", "completed", 10.0, 100, 1)
    store.record("wget", "completed", 20.0, 200, 2)
    store.record("wget", "failed", 30.0, 300, 3)

    stat = store.engine_stats("wget")[0]

    assert stat.avg_duration_s == pytest.approx(20.0)
    assert stat.avg_bytes == pytest.approx(200.0)
    assert stat.avg_files == pytest.approx(2.0)
    assert stat.total_bytes == 600


def test_totals_across_engines():
    store = MetricsStore()
    _seed_three_runs(store)
    store.record("playwright", "completed", 5.0, 500, 2)
    store.record("playwright", "cancelled", 15.0, 0, 0)

    totals = store.totals()

    assert totals["runs"] == 5
    assert totals["succeeded"] == 3
    assert totals["failed"] == 2
    assert totals["bytes"] == 1000 + 3000 + 500
    assert totals["avg_duration_s"] == pytest.approx((10 + 20 + 30 + 5 + 15) / 5)
    assert totals["success_rate"] == round(3 / 5, 3) == 0.6


def test_empty_store_reports_zeroes():
    store = MetricsStore()

    assert store.engine_stats() == []
    assert store.recent() == []

    totals = store.totals()

    assert totals == {
        "runs": 0,
        "succeeded": 0,
        "failed": 0,
        "success_rate": 0.0,
        "bytes": 0,
        "avg_duration_s": 0.0,
        "cost": 0.0,
        "currency": settings.cost_currency,
    }


def test_recent_is_newest_first_and_honours_limit():
    store = MetricsStore()
    for index in range(5):
        store.record("wget", "completed", float(index), 100 * index, index, f"https://{index}.test")

    recent = store.recent(limit=3)

    assert [row["url"] for row in recent] == [
        "https://4.test",
        "https://3.test",
        "https://2.test",
    ]
    assert recent[0]["total_bytes"] == 400
    assert recent[0]["files"] == 4
    assert recent[0]["engine"] == "wget"
    assert recent[0]["created_at"]
    assert len(store.recent()) == 5
    assert store.recent(limit=0) == []


def test_reset_empties_the_table():
    store = MetricsStore()
    _seed_three_runs(store)

    store.reset()

    assert store.engine_stats() == []
    assert store.recent() == []
    assert store.totals()["runs"] == 0


def test_record_from_result_accepts_job_result(tmp_path):
    store = MetricsStore()
    result = JobResult(
        job_id="job-1",
        output_path=str(tmp_path / "out"),
        files_count=12,
        total_size_bytes=4096,
        engine_used="wget",
        duration_seconds=7.5,
    )

    store.record_from_result("wget", result)

    stat = store.engine_stats("wget")[0]
    assert (stat.runs, stat.succeeded) == (1, 1)
    assert stat.total_bytes == 4096
    assert stat.avg_files == pytest.approx(12.0)
    assert stat.avg_duration_s == pytest.approx(7.5)


def test_record_from_result_accepts_engine_result_without_duration(tmp_path):
    store = MetricsStore()
    result = EngineResult(
        output_dir=tmp_path / "out",
        files=[tmp_path / "a.html", tmp_path / "b.html", tmp_path / "c.html"],
        total_bytes=2048,
    )

    store.record_from_result("playwright", result, status="failed")

    stat = store.engine_stats("playwright")[0]
    assert (stat.runs, stat.succeeded, stat.failed) == (1, 0, 1)
    assert stat.total_bytes == 2048
    assert stat.avg_files == pytest.approx(3.0)
    assert stat.avg_duration_s == 0.0  # an engine result carries no duration


def test_record_into_unwritable_path_logs_and_does_not_raise(tmp_path, caplog):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    store = MetricsStore(blocker / "metrics.db")

    with caplog.at_level(logging.WARNING, logger="zfrog.analytics"):
        store.record("wget", "completed", 1.0, 10, 1)

    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert "metrics" in caplog.records[0].getMessage().lower()


def test_two_stores_see_the_same_disk_state():
    first = MetricsStore()
    _seed_three_runs(first)

    second = MetricsStore()

    assert settings.metrics_db.exists()
    assert second.totals()["runs"] == 3
    assert second.engine_stats("wget")[0].succeeded == 2
    assert len(second.recent()) == 3


def test_format_engine_table_renders_percentage_string():
    store = MetricsStore()
    _seed_three_runs(store)

    rows = format_engine_table(store.engine_stats())

    assert len(rows) == 1
    row = rows[0]
    assert row["engine"] == "wget"
    assert row["runs"] == 3
    assert row["failed"] == 1
    assert row["success_rate"] == "66.7%"
    assert isinstance(row["success_rate"], str)
    assert set(row) == {
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
    }
    assert format_engine_table([]) == []
    assert isinstance(store.engine_stats()[0], EngineStats)
