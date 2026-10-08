"""Tests for the worker registry: heartbeats, liveness, assignment and stats."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from zfrog.config import settings
from zfrog.regions import route
from zfrog.workers import (
    WorkerRegistry,
    current_worker_id,
    heartbeat_loop,
    ready_workers_for,
)


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """A registry in a temp dir, with a 1 second heartbeat TTL and local routing."""
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    monkeypatch.setattr(settings, "workers_heartbeat_ttl_s", 1)
    monkeypatch.setattr(settings, "worker_id", "")
    monkeypatch.setattr(settings, "region", "local")
    monkeypatch.setattr(settings, "worker_regions", "")
    return WorkerRegistry()


def _registry_file(tmp_path: Path) -> Path:
    return tmp_path / "workers.json"


def _stale() -> str:
    """A ``last_seen`` one hour in the past."""
    return (datetime.now(timezone.utc) - timedelta(seconds=3600)).isoformat()


def _patch(tmp_path: Path, worker_id: str, **fields: object) -> None:
    """Edit one record in the registry file on disk (no sleeping, no private API)."""
    path = _registry_file(tmp_path)
    records = json.loads(path.read_text(encoding="utf-8"))
    assert any(record["id"] == worker_id for record in records), worker_id
    for record in records:
        if record["id"] == worker_id:
            record.update(fields)
    path.write_text(json.dumps(records), encoding="utf-8")


# ── registration ─────────────────────────────────────────────────────────────


def test_register_creates_and_refreshes_a_worker(registry, tmp_path):
    created = registry.register("w1", "sa-east", capacity=2, version="1.0", tags=["fast"])

    assert (created.id, created.region, created.capacity, created.running) == ("w1", "sa-east", 2, 0)
    assert created.version == "1.0"
    assert created.tags == ["fast"]
    assert created.enabled is True
    assert created.free() == 2
    assert created.started_at == created.last_seen

    refreshed = registry.register("w1", "sa-east", capacity=5, version="2.0")

    assert refreshed.capacity == 5
    assert refreshed.version == "2.0"
    assert refreshed.started_at == created.started_at
    assert refreshed.tags == ["fast"]
    assert registry.get("w1").capacity == 5
    assert len(registry.list(alive_only=False)) == 1
    assert len(json.loads(_registry_file(tmp_path).read_text(encoding="utf-8"))) == 1


def test_unregister_reports_whether_the_worker_existed(registry):
    registry.register("w1", "local")

    assert registry.unregister("w1") is True
    assert registry.get("w1") is None
    assert registry.unregister("w1") is False


# ── heartbeats and liveness ──────────────────────────────────────────────────


def test_heartbeat_updates_last_seen_and_running(registry):
    registered = registry.register("w1", "local")

    updated = registry.heartbeat("w1", running=3)

    assert updated.running == 3
    assert updated.last_seen >= registered.last_seen
    assert registry.get("w1").running == 3

    kept = registry.heartbeat("w1")
    assert kept.running == 3

    with pytest.raises(ValueError):
        registry.heartbeat("ghost")


def test_alive_until_the_heartbeat_expires(registry, tmp_path):
    registry.register("w1", "local")

    assert registry.alive("w1") is True
    assert registry.alive("ghost") is False

    _patch(tmp_path, "w1", last_seen=_stale())
    assert registry.alive("w1") is False


def test_list_filters_by_region_and_liveness(registry, tmp_path):
    registry.register("sa-1", "sa-east")
    registry.register("sa-2", "sa-east")
    registry.register("us-1", "us-east")
    _patch(tmp_path, "us-1", last_seen=_stale())

    assert [worker.id for worker in registry.list()] == ["sa-1", "sa-2"]
    assert [worker.id for worker in registry.list(alive_only=False)] == ["sa-1", "sa-2", "us-1"]
    assert [worker.id for worker in registry.list(region="us-east", alive_only=False)] == ["us-1"]
    assert registry.list(region="us-east") == []
    assert [worker.id for worker in registry.list(region="sa-east")] == ["sa-1", "sa-2"]


def test_reap_removes_only_the_expired_workers(registry, tmp_path):
    registry.register("old", "sa-east")
    _patch(tmp_path, "old", last_seen=_stale())
    registry.register("fresh", "sa-east")

    assert registry.reap() == ["old"]
    assert [worker.id for worker in registry.list(alive_only=False)] == ["fresh"]
    assert registry.reap() == []
    assert registry.alive("fresh") is True


# ── assignment ───────────────────────────────────────────────────────────────


def test_assign_prefers_the_worker_with_most_free_capacity(registry):
    registry.register("busy", "local", capacity=4)
    registry.register("idle", "local", capacity=2)
    registry.heartbeat("busy", running=3)

    assignment = registry.assign("https://example.com")

    assert assignment.worker is not None
    assert assignment.worker.id == "idle"
    assert assignment.region == "local"
    assert "idle" in assignment.reason


def test_assign_is_deterministic_on_equal_capacity(registry):
    registry.register("b-worker", "local", capacity=2)
    registry.register("a-worker", "local", capacity=2)

    first = registry.assign("https://example.com")
    second = registry.assign("https://example.com")

    assert first.worker is not None
    assert first.worker.id == second.worker.id == "a-worker"


def test_assign_falls_back_when_the_routed_region_has_no_alive_worker(registry, monkeypatch):
    monkeypatch.setattr(settings, "region", "us-east")
    monkeypatch.setattr(settings, "worker_regions", "sa-east:20:4")
    registry.register("us-1", "us-east")

    assert route("https://example.com").region == "sa-east"

    assignment = registry.assign("https://example.com")

    assert assignment.worker is not None
    assert assignment.worker.id == "us-1"
    assert assignment.region == "us-east"
    assert "sa-east" in assignment.reason
    assert "us-east" in assignment.reason


def test_assign_without_workers_does_not_raise(registry):
    assignment = registry.assign("https://example.com")

    assert assignment.worker is None
    assert assignment.region == "local"
    assert assignment.reason == "no worker available"


def test_preferred_region_overrides_routing(registry, monkeypatch):
    monkeypatch.setattr(settings, "worker_regions", "sa-east:20:4")
    registry.register("local-1", "local")
    registry.register("sa-1", "sa-east")

    assert route("https://example.com").region == "sa-east"

    assignment = registry.assign("https://example.com", preferred_region="local")

    assert assignment.worker is not None
    assert assignment.worker.id == "local-1"
    assert assignment.region == "local"


def test_assign_skips_disabled_workers(registry, tmp_path):
    registry.register("drained", "local", capacity=8)
    registry.register("active", "local", capacity=1)
    _patch(tmp_path, "drained", enabled=False)

    assignment = registry.assign("https://example.com", preferred_region="local")

    assert assignment.worker is not None
    assert assignment.worker.id == "active"


def test_ready_workers_for_skips_disabled_full_and_dead_workers(registry, tmp_path):
    registry.register("sa-1", "sa-east", capacity=1)
    registry.register("sa-2", "sa-east", capacity=1)
    registry.register("sa-3", "sa-east", capacity=1)
    registry.register("us-1", "us-east", capacity=1)
    registry.start("sa-1")
    _patch(tmp_path, "sa-2", enabled=False)
    _patch(tmp_path, "us-1", last_seen=_stale())

    assert [worker.id for worker in ready_workers_for("sa-east", registry)] == ["sa-3"]
    assert ready_workers_for("us-east", registry) == []


# ── job lifecycle ────────────────────────────────────────────────────────────


def test_start_and_finish_adjust_running_without_going_negative(registry):
    registered = registry.register("w1", "local", capacity=2)

    assert registry.start("w1").running == 1
    started = registry.start("w1")
    assert started.running == 2
    assert started.last_seen >= registered.last_seen
    assert registry.get("w1").free() == 0

    assert registry.finish("w1").running == 1
    assert registry.finish("w1").running == 0
    assert registry.finish("w1").running == 0
    assert registry.get("w1").running == 0

    with pytest.raises(ValueError):
        registry.start("ghost")
    with pytest.raises(ValueError):
        registry.finish("ghost")


def test_stats_aggregate_the_alive_workers(registry, tmp_path):
    registry.register("sa-1", "sa-east", capacity=4)
    registry.register("sa-2", "sa-east", capacity=2)
    registry.register("us-1", "us-east", capacity=8)
    registry.heartbeat("sa-1", running=3)
    _patch(tmp_path, "us-1", last_seen=_stale())

    stats = registry.stats()

    assert stats["workers"] == 3
    assert stats["alive"] == 2
    assert stats["capacity"] == 6
    assert stats["running"] == 3
    assert stats["free"] == 3
    assert stats["by_region"] == {
        "sa-east": {"workers": 2, "capacity": 6, "running": 3, "free": 3},
    }


# ── persistence ──────────────────────────────────────────────────────────────


def test_registry_file_is_private_and_corruption_is_survivable(registry, tmp_path, caplog):
    registry.register("w1", "local")
    path = _registry_file(tmp_path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    path.write_text("{not json", encoding="utf-8")
    with caplog.at_level("WARNING"):
        recovered = WorkerRegistry()
        assert recovered.list(alive_only=False) == []
        assert recovered.get("w1") is None
        assert recovered.reap() == []
    assert "Unreadable" in caplog.text

    recovered.register("w2", "local")

    assert [worker.id for worker in WorkerRegistry().list(alive_only=False)] == ["w2"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_registry_file_survives_an_unusable_record(registry, tmp_path, caplog):
    registry.register("w1", "local")
    path = _registry_file(tmp_path)
    records = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps([*records, {"region": "sa-east"}, "nonsense"]), encoding="utf-8")

    with caplog.at_level("WARNING"):
        loaded = WorkerRegistry().list(alive_only=False)

    assert [worker.id for worker in loaded] == ["w1"]
    assert "invalid" in caplog.text


# ── identity and the background loop ─────────────────────────────────────────


def test_current_worker_id_prefers_settings_then_hostname(monkeypatch):
    monkeypatch.setattr(settings, "worker_id", "worker-7")
    assert current_worker_id() == "worker-7"

    monkeypatch.setattr(settings, "worker_id", "")
    fallback = current_worker_id()

    assert fallback.startswith(socket.gethostname())
    assert str(os.getpid()) in fallback


async def test_heartbeat_loop_registers_until_stopped(registry):
    stop = asyncio.Event()
    task = asyncio.create_task(
        heartbeat_loop("loop-1", interval_s=1, stop_event=stop, registry=registry)
    )

    for _ in range(100):
        if registry.get("loop-1") is not None:
            break
        await asyncio.sleep(0.01)
    assert registry.get("loop-1") is not None

    stop.set()
    await asyncio.wait_for(task, timeout=5)

    worker = registry.get("loop-1")
    assert worker is not None
    assert worker.region == "local"
    assert registry.alive("loop-1") is True
