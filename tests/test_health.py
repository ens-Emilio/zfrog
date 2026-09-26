"""`/health` must be able to say "no".

The container healthcheck polls this endpoint, so an endpoint that always answers
`{"status": "healthy"}` keeps a broken instance in the load balancer. These tests
pin the two failures that break every request — an unreachable broker and an
unwritable state volume — and pin that the happy path still reports healthy.
"""

from __future__ import annotations

import stat

import pytest
from fastapi.testclient import TestClient

from zfrog import api as api_module
from zfrog.config import settings

app = api_module.app


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "data_dir", tmp_path)


@pytest.fixture
def broker_ok(monkeypatch):
    """Pretend the broker answers, so the healthy case does not need a live Redis.

    `health_check` does `import redis` locally, so patching the attribute on the
    installed module is the seam — and it keeps this test from depending on a
    service the suite is designed to run without.
    """
    import redis

    class _Client:
        def ping(self):
            return True

        def close(self):
            pass

    monkeypatch.setattr(redis, "from_url", lambda *a, **k: _Client())


def test_health_is_healthy_when_everything_answers(broker_ok, tmp_path):
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["checks"]["redis"]["ok"] is True
    assert body["checks"]["data_dir"]["ok"] is True
    assert set(body) >= {"status", "checks", "memory", "timestamp"}


def test_health_answers_503_when_the_broker_is_unreachable(monkeypatch, tmp_path):
    """The regression: a dead Redis still reported healthy."""
    # Port 1 has nothing listening on it.
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")

    response = TestClient(app).get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"]["ok"] is False
    assert body["checks"]["redis"]["error"]


def test_health_answers_503_when_the_state_volume_is_not_writable(monkeypatch, tmp_path):
    """A read-only or full mount loses keys, sessions and versions silently."""
    blocked = tmp_path / "somente-leitura"
    blocked.mkdir()
    blocked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    monkeypatch.setattr(settings, "data_dir", blocked)

    try:
        response = TestClient(app).get("/health")
    finally:
        blocked.chmod(stat.S_IRWXU)

    # Root ignores the permission bits, so this only asserts off root.
    import os

    if os.geteuid() == 0:
        pytest.skip("root ignora as permissões do diretório")

    assert response.status_code == 503
    assert response.json()["checks"]["data_dir"]["ok"] is False


def test_health_never_leaks_the_broker_password(monkeypatch, tmp_path):
    """The body is served without a credential, so it must stay safe to expose."""
    secret = "senha-do-broker"
    monkeypatch.setattr(settings, "redis_url", f"redis://:{secret}@127.0.0.1:1/0")

    response = TestClient(app).get("/health")

    assert secret not in response.text


def test_health_stays_reachable_without_a_credential(monkeypatch, tmp_path):
    """It is the probe: it cannot require the thing it exists to report on."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "api_keys_file", tmp_path / "keys.json")

    assert TestClient(app).get("/health").status_code in (200, 503)


# ── /metrics reports something real ──

def test_metrics_reports_the_engine_runs_that_were_recorded(tmp_path, monkeypatch):
    """The regression: /metrics used to answer `{"metrics": {}}` forever.

    It read an in-process collector that nothing incremented. It now reads the
    analytics store, which records a row per engine run — so a recorded run has to
    show up here.
    """
    from zfrog.analytics import MetricsStore

    monkeypatch.setattr(settings, "metrics_db", tmp_path / "metrics.db")
    MetricsStore().record("wget", "completed", duration_s=2.0, total_bytes=1000, files=3)

    response = TestClient(app).get("/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["runs"] == 1
    assert [engine["engine"] for engine in body["engines"]] == ["wget"]


def test_metrics_is_empty_but_well_formed_before_anything_ran(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "metrics_db", tmp_path / "metrics.db")

    body = TestClient(app).get("/metrics").json()

    assert body["totals"]["runs"] == 0
    assert body["engines"] == []
    assert "timestamp" in body
