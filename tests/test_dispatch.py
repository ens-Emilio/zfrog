"""Tests for worker dispatch: URL building, sending jobs, dry-run planning."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from zfrog.config import settings
from zfrog.dispatch import (
    Dispatcher,
    DispatchResult,
    dispatch_summary,
    plan_dispatch,
    worker_base_url,
)
from zfrog.workers import NO_WORKER_REASON, Worker, WorkerRegistry

JOBS_URL = "http://w1:8000/jobs"


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """A registry in a temp dir, in the ``local`` region, with a reachable worker API."""
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    monkeypatch.setattr(settings, "workers_heartbeat_ttl_s", 60)
    monkeypatch.setattr(settings, "region", "local")
    monkeypatch.setattr(settings, "worker_regions", "")
    monkeypatch.setattr(settings, "worker_id", "")
    monkeypatch.setattr(settings, "worker_api_scheme", "http")
    monkeypatch.setattr(settings, "worker_api_port", 8000)
    monkeypatch.setattr(settings, "dispatch_timeout_s", 5)
    return WorkerRegistry()


def _worker(worker_id: str, region: str = "local") -> Worker:
    """A worker record for the URL-builder tests (no registry involved)."""
    return Worker(id=worker_id, region=region, capacity=1, running=0, last_seen="", started_at="")


# ── worker URL ───────────────────────────────────────────────────────────────


def test_worker_base_url_builds_scheme_id_and_port(registry):
    assert worker_base_url(_worker("w1")) == "http://w1:8000"


def test_worker_base_url_reads_scheme_and_port_from_settings(registry, monkeypatch):
    monkeypatch.setattr(settings, "worker_api_scheme", "https")
    monkeypatch.setattr(settings, "worker_api_port", 8443)

    assert worker_base_url(_worker("w1")) == "https://w1:8443"


def test_worker_base_url_respects_explicit_scheme_and_port(registry):
    assert worker_base_url(_worker("w1"), scheme="https", port=9443) == "https://w1:9443"


def test_worker_base_url_uses_a_host_like_id_as_the_host(registry, monkeypatch):
    monkeypatch.setattr(settings, "worker_api_port", 8100)

    assert worker_base_url(_worker("10.0.0.7")) == "http://10.0.0.7:8100"
    assert (
        worker_base_url(_worker("worker-a.sa-east.internal"))
        == "http://worker-a.sa-east.internal:8100"
    )


def test_worker_base_url_keeps_a_port_embedded_in_the_id(registry):
    assert worker_base_url(_worker("10.0.0.7:9000")) == "http://10.0.0.7:9000"


# ── sending ──────────────────────────────────────────────────────────────────


async def test_send_posts_the_job_and_returns_the_job_id(registry):
    registry.register("w1", "local", capacity=2)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(JOBS_URL).mock(return_value=httpx.Response(200, json={"job_id": "job-1"}))
        dispatcher = Dispatcher(registry=registry)
        result = await dispatcher.send(
            "https://example.com", mode="mirror", max_depth=2, extra={"priority": 5}
        )
        await dispatcher.aclose()

    assert (result.job_id, result.worker, result.region, result.accepted) == (
        "job-1",
        "w1",
        "local",
        True,
    )
    assert "job-1" in result.detail
    assert json.loads(route.calls[0].request.content) == {
        "url": "https://example.com",
        "mode": "mirror",
        "max_depth": 2,
        "priority": 5,
    }


async def test_send_marks_the_worker_busy_until_complete(registry):
    registry.register("w1", "local", capacity=2)
    dispatcher = Dispatcher(registry=registry)

    with respx.mock(assert_all_called=True) as mock:
        mock.post(JOBS_URL).mock(return_value=httpx.Response(200, json={"job_id": "job-1"}))
        result = await dispatcher.send("https://example.com")

    assert result.accepted is True
    assert registry.get("w1").running == 1

    await dispatcher.complete("w1")

    assert registry.get("w1").running == 0
    await dispatcher.aclose()


async def test_send_reports_an_error_status_and_leaves_the_worker_free(registry):
    registry.register("w1", "local", capacity=1)
    dispatcher = Dispatcher(registry=registry)

    with respx.mock(assert_all_called=True) as mock:
        mock.post(JOBS_URL).mock(return_value=httpx.Response(500, text="boom"))
        result = await dispatcher.send("https://example.com")

    await dispatcher.aclose()

    assert result.accepted is False
    assert "500" in result.detail
    assert result.job_id == ""
    assert registry.get("w1").running == 0


async def test_send_survives_a_transport_error(registry):
    registry.register("w1", "local", capacity=1)
    dispatcher = Dispatcher(registry=registry)

    with respx.mock(assert_all_called=True) as mock:
        mock.post(JOBS_URL).mock(side_effect=httpx.ConnectError("sem rota"))
        result = await dispatcher.send("https://example.com")

    await dispatcher.aclose()

    assert result.accepted is False
    assert "sem rota" in result.detail
    assert result.worker == "w1"
    assert registry.get("w1").running == 0


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, json={"status": "ok"}),
        httpx.Response(200, json={"job_id": "   "}),
        httpx.Response(200, text="<html>nada aqui</html>"),
    ],
)
async def test_send_rejects_an_answer_without_job_id(registry, answer):
    registry.register("w1", "local", capacity=1)
    dispatcher = Dispatcher(registry=registry)

    with respx.mock(assert_all_called=True) as mock:
        mock.post(JOBS_URL).mock(return_value=answer)
        result = await dispatcher.send("https://example.com")

    await dispatcher.aclose()

    assert result.accepted is False
    assert result.job_id == ""
    assert "job_id" in result.detail
    assert registry.get("w1").running == 0


async def test_send_without_workers_reports_the_registry_reason(registry):
    dispatcher = Dispatcher(registry=registry)

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(url__regex=r".*/jobs").mock(
            return_value=httpx.Response(200, json={"job_id": "nunca"})
        )
        result = await dispatcher.send("https://example.com")

    await dispatcher.aclose()

    assert result.accepted is False
    assert result.detail == NO_WORKER_REASON
    assert result.worker == ""
    assert route.called is False
    assert mock.calls == []


async def test_send_honours_the_preferred_region(registry):
    registry.register("w-local", "local", capacity=1)
    registry.register("w-sa", "sa-east", capacity=1)
    dispatcher = Dispatcher(registry=registry)

    with respx.mock(assert_all_called=False) as mock:
        sa = mock.post("http://w-sa:8000/jobs").mock(
            return_value=httpx.Response(200, json={"job_id": "j-sa"})
        )
        local = mock.post("http://w-local:8000/jobs").mock(
            return_value=httpx.Response(200, json={"job_id": "j-local"})
        )
        result = await dispatcher.send("https://example.com", preferred_region="sa-east")

    await dispatcher.aclose()

    assert (result.worker, result.region, result.job_id) == ("w-sa", "sa-east", "j-sa")
    assert sa.call_count == 1
    assert local.call_count == 0


# ── batches ──────────────────────────────────────────────────────────────────


async def test_send_many_returns_one_result_per_job_and_keeps_going(registry):
    registry.register("w1", "local", capacity=4)
    jobs = [
        {"url": "https://a.example", "max_depth": 2},
        {"url": "https://b.example"},
        {"url": "   "},
        {"url": "https://d.example", "mode": "single"},
    ]
    dispatcher = Dispatcher(registry=registry)

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(JOBS_URL).mock(
            side_effect=[
                httpx.Response(200, json={"job_id": "j1"}),
                httpx.ConnectError("sem rota"),
                httpx.Response(200, json={"job_id": "j4"}),
            ]
        )
        results = await dispatcher.send_many(jobs)

    await dispatcher.aclose()

    assert [result.accepted for result in results] == [True, False, False, True]
    assert [result.job_id for result in results] == ["j1", "", "", "j4"]
    assert route.call_count == 3
    assert registry.get("w1").running == 2

    bodies = [json.loads(call.request.content) for call in route.calls]
    assert [body["url"] for body in bodies] == [
        "https://a.example",
        "https://b.example",
        "https://d.example",
    ]
    assert bodies[0]["max_depth"] == 2
    assert bodies[2]["mode"] == "single"


async def test_send_many_passes_the_batch_region_and_lets_a_job_override_it(registry):
    registry.register("w-sa", "sa-east", capacity=2)
    registry.register("w-us", "us-east", capacity=2)
    dispatcher = Dispatcher(registry=registry)

    with respx.mock(assert_all_called=False) as mock:
        sa = mock.post("http://w-sa:8000/jobs").mock(
            return_value=httpx.Response(200, json={"job_id": "j"})
        )
        us = mock.post("http://w-us:8000/jobs").mock(
            return_value=httpx.Response(200, json={"job_id": "j"})
        )
        results = await dispatcher.send_many(
            [
                {"url": "https://a.example"},
                {"url": "https://b.example", "preferred_region": "us-east"},
            ],
            preferred_region="sa-east",
        )

    await dispatcher.aclose()

    assert [result.region for result in results] == ["sa-east", "us-east"]
    assert (sa.call_count, us.call_count) == (1, 1)


# ── dry run ──────────────────────────────────────────────────────────────────


def test_plan_dispatch_reports_the_target_without_any_http_call(registry):
    registry.register("w-sa", "sa-east", capacity=2)

    with respx.mock(assert_all_called=False) as mock:
        plan = plan_dispatch(
            [{"url": "https://a.example", "preferred_region": "sa-east"}], registry
        )
        assert mock.calls == []

    assert len(plan) == 1
    assert plan[0]["worker"] == "w-sa"
    assert plan[0]["region"] == "sa-east"
    assert plan[0]["target"] == "http://w-sa:8000"
    assert plan[0]["accepted"] is True
    assert plan[0]["url"] == "https://a.example"
    assert "w-sa" in plan[0]["reason"]
    assert registry.get("w-sa").running == 0


def test_plan_dispatch_without_workers_says_why(registry):
    plan = plan_dispatch([{"url": "https://a.example"}], registry)

    assert plan[0]["accepted"] is False
    assert plan[0]["worker"] == ""
    assert plan[0]["target"] == ""
    assert plan[0]["reason"] == NO_WORKER_REASON


# ── lifecycle of the HTTP client ─────────────────────────────────────────────


async def test_aclose_leaves_an_injected_client_open(registry):
    registry.register("w1", "local", capacity=1)

    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=True) as mock:
            mock.post(JOBS_URL).mock(return_value=httpx.Response(200, json={"job_id": "j1"}))
            dispatcher = Dispatcher(registry=registry, client=client)
            await dispatcher.send("https://example.com")

        assert dispatcher.client is client
        await dispatcher.aclose()
        assert client.is_closed is False


async def test_aclose_closes_a_client_it_created(registry):
    dispatcher = Dispatcher(registry=registry)
    owned = dispatcher.client

    assert owned.is_closed is False

    await dispatcher.aclose()

    assert owned.is_closed is True


# ── summary ──────────────────────────────────────────────────────────────────


def test_dispatch_summary_counts_the_accepted_and_names_the_regions():
    results = [
        DispatchResult("j1", "w1", "local", True, "ok"),
        DispatchResult("j2", "w2", "sa-east", True, "ok"),
        DispatchResult("", "w3", "sa-east", False, "erro"),
    ]

    summary = dispatch_summary(results)

    assert "2 de 3" in summary
    assert "local: 1" in summary
    assert "sa-east: 1" in summary
    assert "1 falhou" in summary
    assert summary.endswith(".") and summary.count(".") == 1


def test_dispatch_summary_without_a_single_acceptance():
    summary = dispatch_summary(
        [
            DispatchResult("", "w1", "local", False, "erro"),
            DispatchResult("", "w2", "local", False, "erro"),
        ]
    )

    assert "Nenhum dos 2 jobs foi aceito" in summary
    assert "2 falharam" in summary


def test_dispatch_summary_of_an_empty_batch():
    assert dispatch_summary([]) == "Nenhum job para enviar."
