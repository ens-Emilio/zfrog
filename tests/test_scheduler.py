"""Tests for the cron parser/describer and the recurring schedule store."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from zfrog.config import settings
from zfrog.cron import describe, parse_cron
from zfrog.scheduler import (
    Schedule,
    ScheduleStore,
    daemon,
    due_schedules,
    next_run_for,
    run_due,
)

UTC = timezone.utc
PAST = "2020-01-01T00:00:00+00:00"
FUTURE = "2999-01-01T00:00:00+00:00"


def _use_store_file(tmp_path, monkeypatch):
    """Point the default schedule file at a tmp_path and return its path."""
    path = tmp_path / "schedules.json"
    monkeypatch.setattr(settings, "schedules_file", path)
    return path


def _force(store: ScheduleStore, schedule: Schedule, *, next_run=None, enabled=None) -> Schedule:
    """Persist a schedule with a forced next_run/enabled state."""
    if next_run is not None:
        schedule.next_run = next_run
    if enabled is not None:
        schedule.enabled = enabled
    assert store.update(schedule)
    return schedule


def _live_tasks() -> set[asyncio.Task]:
    """Return the tasks currently running besides this one."""
    return {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}


class TestParseCron:
    """Field expansion and validation."""

    def test_expands_every_accepted_form(self):
        nightly = parse_cron("0 2 * * *")
        assert nightly.minute == frozenset({0})
        assert nightly.hour == frozenset({2})
        assert nightly.dom == frozenset(range(1, 32))
        assert nightly.month == frozenset(range(1, 13))
        assert nightly.dow == frozenset(range(7))
        assert nightly.expr == "0 2 * * *"

        assert parse_cron("*/15 * * * *").minute == frozenset({0, 15, 30, 45})
        assert parse_cron("0 0 1,15 * *").dom == frozenset({1, 15})
        assert parse_cron("5-25/10 * * * *").minute == frozenset({5, 15, 25})

        business = parse_cron("30 9-17 * * 1-5")
        assert business.hour == frozenset(range(9, 18))
        assert business.dow == frozenset({1, 2, 3, 4, 5})

    def test_accepts_seven_as_sunday(self):
        assert parse_cron("0 0 * * 7").dow == frozenset({0})
        assert parse_cron("0 0 * * 5-7").dow == frozenset({5, 6, 0})

    @pytest.mark.parametrize(
        "expr",
        [
            "60 0 * * *",
            "0 24 * * *",
            "0 0 32 * *",
            "0 0 * 13 *",
            "0 0 * * 8",
            "0 0 * *",
            "0 0 * * * *",
            "x * * * *",
            "*/0 * * * *",
            "5-1 * * * *",
            "0 0 -1 * *",
            "",
        ],
    )
    def test_rejects_invalid_expressions(self, expr):
        with pytest.raises(ValueError):
            parse_cron(expr)


class TestMatches:
    """Minute-resolution matching, including the dom/dow rule."""

    def test_matches_exact_minute_only(self):
        nightly = parse_cron("0 2 * * *")
        assert nightly.matches(datetime(2026, 3, 5, 2, 0))
        assert not nightly.matches(datetime(2026, 3, 5, 2, 1))
        assert not nightly.matches(datetime(2026, 3, 5, 3, 0))

    def test_matches_respects_weekdays(self):
        business = parse_cron("30 9 * * 1-5")
        assert business.matches(datetime(2026, 9, 21, 9, 30))  # segunda-feira
        assert not business.matches(datetime(2026, 9, 20, 9, 30))  # domingo
        assert not business.matches(datetime(2026, 9, 21, 9, 31))

    def test_dom_and_dow_restricted_match_on_either(self):
        friday_or_13th = parse_cron("0 0 13 * 5")
        assert friday_or_13th.matches(datetime(2026, 3, 13, 0, 0))  # sexta e dia 13
        assert friday_or_13th.matches(datetime(2026, 3, 6, 0, 0))  # sexta, dia 6
        assert friday_or_13th.matches(datetime(2026, 5, 13, 0, 0))  # quarta, dia 13
        assert not friday_or_13th.matches(datetime(2026, 3, 19, 0, 0))  # quinta, dia 19

    def test_restricted_field_alone_decides_when_the_other_is_wildcard(self):
        thirteenth = parse_cron("0 0 13 * *")
        assert thirteenth.matches(datetime(2026, 5, 13, 0, 0))
        assert not thirteenth.matches(datetime(2026, 3, 6, 0, 0))

        fridays = parse_cron("0 0 * * 5")
        assert fridays.matches(datetime(2026, 3, 6, 0, 0))
        assert not fridays.matches(datetime(2026, 5, 13, 0, 0))


class TestNextAfter:
    """Next firing minute computation."""

    def test_crosses_day_and_month_boundaries(self):
        nightly = parse_cron("0 2 * * *")
        assert nightly.next_after(datetime(2026, 3, 5, 3, 0)) == datetime(2026, 3, 6, 2, 0)
        assert nightly.next_after(datetime(2026, 3, 5, 2, 0)) == datetime(2026, 3, 6, 2, 0)

        monthly = parse_cron("0 0 1 * *")
        assert monthly.next_after(datetime(2026, 3, 15, 10, 0)) == datetime(2026, 4, 1, 0, 0)

    def test_is_strictly_after_and_keeps_timezone(self):
        every_minute = parse_cron("* * * * *")
        now = datetime(2026, 3, 5, 12, 30, 45, 123456)
        assert every_minute.next_after(now) == datetime(2026, 3, 5, 12, 31)

        aware = datetime(2026, 3, 5, 12, 30, tzinfo=UTC)
        assert every_minute.next_after(aware) == datetime(2026, 3, 5, 12, 31, tzinfo=UTC)

    def test_impossible_schedule_returns_none(self):
        assert parse_cron("0 0 30 2 *").next_after(datetime(2026, 1, 1, 0, 0)) is None


class TestScheduleStore:
    """Persistence of schedules."""

    def test_round_trip_through_a_real_file(self, tmp_path, monkeypatch):
        path = _use_store_file(tmp_path, monkeypatch)
        store = ScheduleStore()

        schedule = store.add("0 2 * * *", "https://example.com", mode="mirror", max_depth=2)
        assert len(schedule.id) == 8
        int(schedule.id, 16)  # id is hexadecimal
        assert schedule.enabled is True
        assert schedule.last_run is None
        assert datetime.fromisoformat(schedule.next_run) > datetime.now(UTC)

        stored = store.get(schedule.id)
        assert stored is not None
        assert (stored.cron, stored.url, stored.mode, stored.max_depth) == (
            "0 2 * * *",
            "https://example.com",
            "mirror",
            2,
        )
        assert [item.id for item in store.list()] == [schedule.id]

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, list)
        assert payload[0]["id"] == schedule.id

        assert store.set_enabled(schedule.id, False) is True
        assert store.get(schedule.id).enabled is False
        assert json.loads(path.read_text(encoding="utf-8"))[0]["enabled"] is False
        assert store.set_enabled("deadbeef", False) is False

        assert store.set_enabled(schedule.id, True) is True
        reenabled = store.get(schedule.id)
        assert reenabled.enabled is True
        assert datetime.fromisoformat(reenabled.next_run) > datetime.now(UTC)

        assert store.remove(schedule.id) is True
        assert store.remove(schedule.id) is False
        assert store.get(schedule.id) is None
        assert json.loads(path.read_text(encoding="utf-8")) == []

        # the atomic write leaves no temp files behind
        assert sorted(item.name for item in tmp_path.iterdir()) == ["schedules.json"]

    def test_explicit_path_creates_missing_directories(self, tmp_path):
        path = tmp_path / "nested" / "schedules.json"
        store = ScheduleStore(path)

        schedule = store.add("0 0 * * *", "https://explicit.example")
        assert path.exists()
        assert [item.id for item in ScheduleStore(path).list()] == [schedule.id]

    def test_add_rejects_a_bad_cron_without_touching_the_file(self, tmp_path, monkeypatch):
        path = _use_store_file(tmp_path, monkeypatch)
        store = ScheduleStore()

        with pytest.raises(ValueError):
            store.add("nope", "https://example.com")

        assert not path.exists()
        assert store.list() == []


class TestDueSchedules:
    """Selection of schedules that must run now."""

    def test_returns_only_enabled_and_due_entries(self, tmp_path, monkeypatch):
        _use_store_file(tmp_path, monkeypatch)
        store = ScheduleStore()

        due = _force(store, store.add("0 2 * * *", "https://due.example"), next_run=PAST)
        _force(store, store.add("0 2 * * *", "https://later.example"), next_run=FUTURE)
        _force(store, store.add("0 2 * * *", "https://paused.example"), next_run=PAST, enabled=False)

        result = due_schedules(datetime(2026, 3, 5, 12, 0, tzinfo=UTC))
        assert [item.id for item in result] == [due.id]


class TestRunDue:
    """Firing jobs for due schedules."""

    async def test_starts_one_job_per_due_schedule(self, tmp_path, monkeypatch):
        _use_store_file(tmp_path, monkeypatch)
        store = ScheduleStore()

        first = _force(
            store, store.add("0 2 * * *", "https://a.example", max_depth=2), next_run=PAST
        )
        second = _force(store, store.add("0 2 * * *", "https://b.example"), next_run=PAST)
        untouched = _force(store, store.add("0 2 * * *", "https://c.example"), next_run=FUTURE)

        started = []

        async def fake_run_job(job):
            started.append(job)
            return SimpleNamespace(job_id="job-1", files_count=3)

        monkeypatch.setattr("zfrog.scheduler.run_job", fake_run_job)

        now = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)
        before = _live_tasks()
        job_ids = await run_due(now)
        await asyncio.gather(*(_live_tasks() - before))

        assert len(job_ids) == 2
        assert len(set(job_ids)) == 2
        assert [str(job.url) for job in started] == ["https://a.example/", "https://b.example/"]
        assert [job.max_depth for job in started] == [2, 1]

        stored = {item.id: item for item in store.list()}
        assert stored[first.id].last_run == now.isoformat()
        assert datetime.fromisoformat(stored[first.id].next_run) > now
        assert stored[second.id].last_run == now.isoformat()
        assert datetime.fromisoformat(stored[second.id].next_run) > now
        assert stored[untouched.id].last_run is None
        assert stored[untouched.id].next_run == FUTURE

    async def test_a_failing_job_does_not_break_the_others(self, tmp_path, monkeypatch, caplog):
        _use_store_file(tmp_path, monkeypatch)
        store = ScheduleStore()

        failing = _force(store, store.add("0 2 * * *", "https://boom.example"), next_run=PAST)
        healthy = _force(store, store.add("0 2 * * *", "https://healthy.example"), next_run=PAST)

        started = []

        async def fake_run_job(job):
            started.append(str(job.url))
            if "boom" in str(job.url):
                raise RuntimeError("crawl falhou")
            return SimpleNamespace(job_id="job-ok", files_count=1)

        monkeypatch.setattr("zfrog.scheduler.run_job", fake_run_job)

        now = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)
        with caplog.at_level(logging.ERROR, logger="zfrog.scheduler"):
            before = _live_tasks()
            job_ids = await run_due(now)
            await asyncio.gather(*(_live_tasks() - before), return_exceptions=True)

        assert len(job_ids) == 2
        assert sorted(started) == ["https://boom.example/", "https://healthy.example/"]
        assert "falhou" in caplog.text
        assert failing.id in caplog.text
        assert datetime.fromisoformat(store.get(healthy.id).next_run) > now


class TestDaemon:
    """The polling loop."""

    async def test_fires_due_jobs_and_stops_on_the_event(self, tmp_path, monkeypatch):
        _use_store_file(tmp_path, monkeypatch)
        store = ScheduleStore()
        schedule = _force(store, store.add("* * * * *", "https://loop.example"), next_run=PAST)

        started = []
        stop = asyncio.Event()

        async def fake_run_job(job):
            started.append(job)
            stop.set()
            return SimpleNamespace(job_id="job-loop", files_count=1)

        monkeypatch.setattr("zfrog.scheduler.run_job", fake_run_job)

        await asyncio.wait_for(daemon(interval_s=30, stop_event=stop), timeout=5)

        assert [str(job.url) for job in started] == ["https://loop.example/"]
        refreshed = store.get(schedule.id)
        assert refreshed.last_run is not None
        assert datetime.fromisoformat(refreshed.next_run) > datetime.now(UTC)

    async def test_keeps_running_after_a_transient_error(self, tmp_path, monkeypatch, caplog):
        path = _use_store_file(tmp_path, monkeypatch)
        path.write_text("{ isto não é json", encoding="utf-8")

        stop = asyncio.Event()
        with caplog.at_level(logging.ERROR, logger="zfrog.scheduler"):
            task = asyncio.create_task(daemon(interval_s=30, stop_event=stop))
            await asyncio.sleep(0.05)
            stop.set()
            await asyncio.wait_for(task, timeout=5)

        assert "Falha ao verificar os agendamentos" in caplog.text


class TestNextRunFor:
    """ISO-8601 computation."""

    def test_returns_iso_utc_string(self):
        schedule = Schedule(id="abc12345", cron="0 2 * * *", url="https://x.example", mode="mirror", max_depth=1)
        assert next_run_for(schedule, datetime(2026, 3, 5, 3, 0, tzinfo=UTC)) == "2026-03-06T02:00:00+00:00"

        naive = next_run_for(schedule, datetime(2026, 3, 5, 3, 0))
        assert naive == "2026-03-06T02:00:00+00:00"

    def test_returns_none_for_an_invalid_cron(self):
        schedule = Schedule(id="abc12345", cron="nope", url="https://x.example", mode="mirror", max_depth=1)
        assert next_run_for(schedule, datetime(2026, 3, 5, tzinfo=UTC)) is None


class TestDescribe:
    """Portuguese descriptions."""

    def test_describes_common_expressions(self):
        assert describe("0 2 * * *") == "todo dia às 02:00"
        assert describe("*/15 * * * *") == "a cada 15 minutos"
        assert describe("0 0 1,15 * *") == "no dia 1 e 15 de cada mês às 00:00"

    def test_business_hours_mentions_the_weekdays(self):
        text = describe("30 9-17 * * 1-5")
        assert "segunda" in text and "sexta" in text
        assert "09:30" in text

    def test_weekday_lists(self):
        assert describe("0 0 * * 6,0") == "nos fins de semana às 00:00"
        assert describe("0 0 * * 1,3,5") == "nos dias segunda, quarta e sexta, às 00:00"
        assert describe("0 0 * * 5") == "às sextas, às 00:00"

    def test_output_is_non_empty_and_specific(self):
        assert describe("0 2 * * *") != describe("*/15 * * * *")
        for expr in ("* * * * *", "0 0 * * 0", "0 0 1 1 *", "0 */6 * * *", "0 0 * * 1,3,5", "*/30 8-18 * * 1-5"):
            assert describe(expr).strip()

    def test_rejects_invalid_expression(self):
        with pytest.raises(ValueError):
            describe("todo dia")
