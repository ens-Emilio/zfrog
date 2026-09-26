"""Tests for the workflow dependency graph: ``needs``/``id``, waves and parallelism."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from zfrog import workflows
from zfrog.config import settings
from zfrog.engines.base import EngineResult
from zfrog.models import JobResult, ProbeResult
from zfrog.workflows import (
    Step,
    Workflow,
    WorkflowStore,
    execution_waves,
    run_workflow,
    validate_steps,
)

# ── fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def output_dir(tmp_path, monkeypatch):
    """Isolate every workflow artefact under ``tmp_path/output``."""
    target = tmp_path / "output"
    monkeypatch.setattr(settings, "output_dir", target)
    return target

@pytest.fixture
def jobs(output_dir, monkeypatch):
    """Record every ``run_job`` call and return a finished job under ``output_dir``."""
    calls: list = []

    async def fake_run_job(job):
        calls.append(job)
        job_dir = output_dir / "jobs" / f"job{len(calls)}"
        (job_dir / "site").mkdir(parents=True, exist_ok=True)
        (job_dir / "site" / "index.html").write_text(
            "<html><body>olá</body></html>", encoding="utf-8"
        )
        archive = job_dir / "archive.zip"
        archive.write_bytes(b"PK\x03\x04")
        return JobResult(
            job_id=f"job{len(calls)}",
            output_path=str(archive),
            files_count=2,
            total_size_bytes=4,
            engine_used="wget",
            duration_seconds=0.1,
        )

    monkeypatch.setattr(workflows, "run_job", fake_run_job)
    return calls

@pytest.fixture
def engines(monkeypatch):
    """Record every engine run with its timing and the highest concurrency seen."""
    log: dict = {"calls": [], "active": 0, "peak": 0, "fail_on": None, "delay": 0.02}

    class RecordingEngine:
        def __init__(self, name: str) -> None:
            self.name = name

        async def execute(self, job, output_dir, on_progress=None):
            label = output_dir.name
            log["active"] += 1
            log["peak"] = max(log["peak"], log["active"])
            started = time.monotonic()
            await asyncio.sleep(log["delay"])
            finished = time.monotonic()
            log["active"] -= 1
            log["calls"].append(
                {"label": label, "url": str(job.url), "started": started, "finished": finished}
            )

            if log["fail_on"] and str(job.url).endswith(log["fail_on"]):
                raise RuntimeError(f"motor caiu em {job.url}")

            output_dir.mkdir(parents=True, exist_ok=True)
            written = output_dir / f"{self.name}.txt"
            written.write_text(str(job.url), encoding="utf-8")
            return EngineResult(output_dir=output_dir, files=[written])

    monkeypatch.setattr(workflows, "get_engine", lambda name: RecordingEngine(name))
    return log

def call_of(engines: dict, label: str) -> dict:
    """Return the recorded engine call for the step whose directory is ``label``."""
    for call in engines["calls"]:
        if call["label"] == label:
            return call
    raise AssertionError(f"o passo {label} não rodou (rodaram: {[c['label'] for c in engines['calls']]})")

# ── execution_waves ─────────────────────────────────────────────────

class TestExecutionWaves:
    """Layering the graph into waves of steps that are independent."""

    def test_linear_chain_gives_one_step_per_wave(self):
        steps = validate_steps(
            [
                {"type": "summarize", "params": {"url": "https://example.com"}, "id": "a"},
                {"type": "analyze", "params": {"url": "https://example.com"}, "id": "b", "needs": ["a"]},
                {"type": "extract", "params": {"url": "https://example.com"}, "id": "c", "needs": ["b"]},
            ]
        )

        waves = execution_waves(steps)

        assert [[step.id for step in wave] for wave in waves] == [["a"], ["b"], ["c"]]

    def test_independent_steps_share_one_wave(self):
        # Parallelism is opt-in: `needs: []` says "nothing to wait for", while an
        # omitted `needs` keeps the linear default (see the linear tests below).
        steps = validate_steps(
            [
                {"type": "summarize", "params": {"url": "https://example.com/a"}, "needs": []},
                {"type": "analyze", "params": {"url": "https://example.com/b"}, "needs": []},
            ]
        )

        waves = execution_waves(steps)

        assert len(waves) == 1
        assert [step.id for step in waves[0]] == ["step-0", "step-1"]

    def test_omitted_needs_keeps_the_linear_default(self):
        """A pipeline without `needs` stays sequential, as it always was."""
        steps = validate_steps(
            [
                {"type": "summarize", "params": {"url": "https://example.com/a"}},
                {"type": "analyze", "params": {"url": "https://example.com/b"}},
                {"type": "extract", "params": {"url": "https://example.com/c"}},
            ]
        )

        waves = execution_waves(steps)

        assert [[step.id for step in wave] for wave in waves] == [["step-0"], ["step-1"], ["step-2"]]

    def test_diamond_layers(self):
        steps = validate_steps(
            [
                {"type": "summarize", "params": {"url": "https://example.com"}, "id": "a"},
                {"type": "analyze", "params": {"url": "https://example.com"}, "id": "b", "needs": ["a"]},
                {"type": "extract", "params": {"url": "https://example.com"}, "id": "c", "needs": ["a"]},
                {"type": "compare", "params": {"url": "https://example.com"}, "id": "d", "needs": ["b", "c"]},
            ]
        )

        waves = execution_waves(steps)

        assert [[step.id for step in wave] for wave in waves] == [["a"], ["b", "c"], ["d"]]

    def test_a_step_may_need_one_declared_after_it(self):
        steps = validate_steps(
            [
                {
                    "type": "analyze",
                    "params": {"url": "https://example.com"},
                    "id": "b",
                    "needs": ["a"],
                },
                {
                    "type": "summarize",
                    "params": {"url": "https://example.com"},
                    "id": "a",
                    "needs": [],
                },
            ]
        )

        waves = execution_waves(steps)

        assert [[step.id for step in wave] for wave in waves] == [["a"], ["b"]]

    def test_cycle_is_refused_with_its_path(self):
        steps = [
            Step("summarize", {"url": "https://example.com"}, needs=["step-1"], id="step-0"),
            Step("analyze", {"url": "https://example.com"}, needs=["step-0"], id="step-1"),
        ]

        with pytest.raises(ValueError) as error:
            execution_waves(steps)

        message = str(error.value)
        assert "ciclo" in message
        assert "step-0" in message and "step-1" in message

    def test_unknown_dependency_is_refused(self):
        steps = [Step("search", {}, needs=["passo-inexistente"], id="sonda")]

        with pytest.raises(ValueError, match="passo-inexistente"):
            execution_waves(steps)

# ── validate_steps ──────────────────────────────────────────────────

class TestValidateStepsGraph:
    """Validation of the new ``id``/``needs`` fields."""

    def test_rejects_needs_naming_a_missing_step(self):
        with pytest.raises(ValueError, match="step-9"):
            validate_steps(
                [
                    {"type": "search", "params": {}},
                    {"type": "commit", "params": {}, "needs": ["step-9"]},
                ]
            )

    def test_accepts_auto_assigned_ids(self):
        steps = validate_steps(
            [
                {"type": "search", "params": {}},
                {"type": "commit", "params": {}, "needs": ["step-0"]},
            ]
        )

        assert [step.id for step in steps] == ["step-0", "step-1"]
        assert steps[1].needs == ["step-0"]

    def test_accepts_explicit_ids(self):
        steps = validate_steps(
            [
                {"type": "clone", "params": {"url": "https://example.com"}, "id": " coleta "},
                {"type": "search", "params": {}, "id": "busca", "needs": ["coleta"]},
            ]
        )

        assert [step.id for step in steps] == ["coleta", "busca"]
        assert steps[1].needs == ["coleta"]

    def test_rejects_a_cycle(self):
        with pytest.raises(ValueError, match="ciclo"):
            validate_steps(
                [
                    {"type": "summarize", "params": {"url": "https://example.com"}, "needs": ["step-1"]},
                    {"type": "analyze", "params": {"url": "https://example.com"}, "needs": ["step-0"]},
                ]
            )

    def test_rejects_a_step_that_needs_itself(self):
        with pytest.raises(ValueError, match="ciclo"):
            validate_steps([{"type": "search", "params": {}, "needs": ["step-0"]}])

    def test_rejects_needs_that_is_not_a_list_of_ids(self):
        with pytest.raises(ValueError, match="needs"):
            validate_steps([{"type": "search", "params": {}, "needs": "step-0"}])

    def test_rejects_a_repeated_id(self):
        with pytest.raises(ValueError, match="repetido"):
            validate_steps(
                [
                    {"type": "search", "params": {}, "id": "x"},
                    {"type": "commit", "params": {}, "id": "x"},
                ]
            )

    def test_rejects_an_unknown_top_level_field(self):
        with pytest.raises(ValueError, match="neds"):
            validate_steps([{"type": "search", "params": {}, "neds": ["step-0"]}])

# ── WorkflowStore ───────────────────────────────────────────────────

class TestWorkflowStoreGraph:
    """The graph survives a save/load round trip."""

    def test_round_trips_ids_and_needs(self, tmp_path):
        root = tmp_path / "flows"
        store = WorkflowStore(root=root)

        saved = store.save(
            "encadeado",
            [
                {"type": "clone", "params": {"url": "https://example.com"}, "id": "coleta"},
                {"type": "summarize", "params": {}, "id": "resumo", "needs": ["coleta"]},
                {"type": "commit", "params": {}, "needs": ["coleta", "resumo"]},
            ],
        )

        loaded = store.get(saved.id)

        assert loaded == saved
        assert [step.id for step in loaded.steps] == ["coleta", "resumo", "step-2"]
        assert [step.needs for step in loaded.steps] == [[], ["coleta"], ["coleta", "resumo"]]

        payload = json.loads((root / f"{saved.id}.json").read_text(encoding="utf-8"))
        assert payload["steps"][2]["id"] == "step-2"
        assert payload["steps"][2]["needs"] == ["coleta", "resumo"]

    def test_reloading_keeps_the_graph_runnable(self, tmp_path):
        store = WorkflowStore(root=tmp_path / "flows")
        saved = store.save(
            "losango",
            [
                {"type": "summarize", "params": {"url": "https://example.com"}, "id": "a"},
                {"type": "analyze", "params": {"url": "https://example.com"}, "id": "b", "needs": ["a"]},
            ],
        )

        waves = execution_waves(store.get(saved.id).steps)

        assert [[step.id for step in wave] for wave in waves] == [["a"], ["b"]]

    def test_a_file_without_ids_loads_with_positional_ids(self, tmp_path):
        root = tmp_path / "flows"
        root.mkdir()
        (root / "deadbeef.json").write_text(
            json.dumps(
                {
                    "id": "deadbeef",
                    "name": "antigo",
                    "steps": [{"type": "search", "params": {}}, {"type": "commit", "params": {}}],
                }
            ),
            encoding="utf-8",
        )

        workflow = WorkflowStore(root=root).get("deadbeef")

        assert [step.id for step in workflow.steps] == ["step-0", "step-1"]
        # A file saved before `needs` existed keeps its linear meaning.
        assert [step.needs for step in workflow.steps] == [None, None]

    def test_save_refuses_a_cyclic_graph(self, tmp_path):
        store = WorkflowStore(root=tmp_path / "flows")

        with pytest.raises(ValueError, match="ciclo"):
            store.save(
                "ruim",
                [
                    {"type": "search", "params": {}, "needs": ["step-1"]},
                    {"type": "commit", "params": {}, "needs": ["step-0"]},
                ],
            )

        assert list((tmp_path / "flows").glob("*.json")) == []

# ── run_workflow ────────────────────────────────────────────────────

class TestRunWorkflowGraph:
    """Executing the graph: waves, parallelism and failure handling."""

    async def test_diamond_runs_the_middle_wave_together(self, output_dir, engines):
        workflow = Workflow(
            "aaaaaaaa",
            "losango",
            [
                Step("summarize", {"url": "https://example.com/a"}, id="a"),
                Step("summarize", {"url": "https://example.com/b"}, id="b", needs=["a"]),
                Step("analyze", {"url": "https://example.com/c"}, id="c", needs=["a"]),
                Step("compare", {"url": "https://example.com/d"}, id="d", needs=["b", "c"]),
            ],
        )

        result = await run_workflow(workflow)

        assert result.status == "ok"
        assert [step.status for step in result.steps] == ["ok", "ok", "ok", "ok"]
        assert [step.type for step in result.steps] == ["summarize", "summarize", "analyze", "compare"]

        first = call_of(engines, "1-summarize")
        second = call_of(engines, "2-summarize")
        third = call_of(engines, "3-analyze")
        fourth = call_of(engines, "4-compare")

        # b and c are in the same wave: their execution windows overlap.
        assert second["started"] < third["finished"]
        assert third["started"] < second["finished"]
        # d waits for both of them.
        assert fourth["started"] >= max(second["finished"], third["finished"])
        # a runs before its two dependants.
        assert first["finished"] <= min(second["started"], third["started"])

    async def test_failing_step_skips_only_its_dependants(self, output_dir, engines):
        engines["fail_on"] = "/ruim"
        workflow = Workflow(
            "bbbbbbbb",
            "falha",
            [
                Step("summarize", {"url": "https://example.com/ruim"}, id="a"),
                Step("analyze", {"url": "https://example.com/b"}, id="b", needs=["a"]),
                Step("compare", {"url": "https://example.com/c"}, id="c", needs=[]),
                Step("extract", {"url": "https://example.com/d"}, id="d", needs=["b"]),
            ],
        )

        messages: list[str] = []
        result = await run_workflow(workflow, on_progress=messages.append)

        assert result.status == "failed"
        assert [step.status for step in result.steps] == ["failed", "skipped", "ok", "skipped"]
        assert "rede" not in result.steps[0].detail and "motor caiu" in result.steps[0].detail

        assert "passo 1" in result.steps[1].detail
        assert "summarize" in result.steps[1].detail
        assert "falhou" in result.steps[1].detail
        # d waits on a step that was itself skipped.
        assert "passo 2" in result.steps[3].detail and "pulado" in result.steps[3].detail

        assert result.error is not None
        assert "passo 1" in result.error and "motor caiu" in result.error

        # The independent branch still ran, the dependants never started.
        assert sorted(call["label"] for call in engines["calls"]) == ["1-summarize", "3-compare"]
        # One progress message per step, including the skipped ones.
        assert len(messages) == 4

    async def test_concurrency_respects_max_parallel_steps(self, output_dir, engines, monkeypatch):
        workflow = Workflow(
            "cccccccc",
            "paralelo",
            [
                Step("summarize", {"url": "https://example.com/1"}, id="um", needs=[]),
                Step("summarize", {"url": "https://example.com/2"}, id="dois", needs=[]),
                Step("summarize", {"url": "https://example.com/3"}, id="tres", needs=[]),
            ],
        )

        monkeypatch.setattr(settings, "max_parallel_steps", 1)
        sequential = await run_workflow(workflow)

        assert sequential.status == "ok"
        assert engines["peak"] == 1
        windows = sorted((call["started"], call["finished"]) for call in engines["calls"])
        assert len(windows) == 3
        assert all(windows[index][1] <= windows[index + 1][0] for index in range(2))

        engines["calls"].clear()
        engines["peak"] = 0
        monkeypatch.setattr(settings, "max_parallel_steps", 2)
        capped = await run_workflow(workflow)

        assert capped.status == "ok"
        assert engines["peak"] == 2
        assert sorted(call["label"] for call in engines["calls"]) == [
            "1-summarize",
            "2-summarize",
            "3-summarize",
        ]

    async def test_progress_reports_every_step_once(self, output_dir, engines):
        workflow = Workflow(
            "dddddddd",
            "progresso",
            [
                Step("summarize", {"url": "https://example.com/a"}, id="a", needs=[]),
                Step("analyze", {"url": "https://example.com/b"}, id="b", needs=["a"]),
                Step("extract", {"url": "https://example.com/c"}, id="c", needs=[]),
            ],
        )

        messages: list[str] = []
        await run_workflow(workflow, on_progress=messages.append)

        # Wave 1 holds steps 1 and 3, wave 2 holds step 2.
        assert messages == [
            "Passo 1/3: summarize",
            "Passo 3/3: extract",
            "Passo 2/3: analyze",
        ]

    async def test_a_dependent_step_sees_the_clone_output_dir(self, output_dir, jobs, monkeypatch):
        from zfrog import search as search_mod

        monkeypatch.setattr(settings, "search_db", output_dir / "search.db")
        monkeypatch.setattr(search_mod, "is_available", lambda: False)

        workflow = Workflow(
            "eeeeeeee",
            "indexar",
            [
                Step("clone", {"url": "https://example.com"}, id="coleta"),
                Step("search", {}, needs=["coleta"]),
            ],
        )

        result = await run_workflow(workflow)

        assert result.status == "ok"
        assert "1 páginas indexadas" in result.steps[1].detail
        assert str(output_dir / "jobs" / "job1") in result.steps[1].detail

        hits = search_mod.SearchIndex().search("olá")
        assert [hit.url for hit in hits] == ["https://example.com/site/index.html"]

    async def test_url_flows_from_a_needed_probe(self, output_dir, jobs, monkeypatch):
        async def fake_probe(url, client):
            return ProbeResult(url=url, suggested_engine="wget", status_code=200)

        monkeypatch.setattr(workflows, "probe_url", fake_probe)

        workflow = Workflow(
            "77777777",
            "sonda",
            [
                Step("probe", {"url": "https://example.com/site"}, id="sonda"),
                Step("clone", {}, id="coleta", needs=["sonda"]),
            ],
        )

        result = await run_workflow(workflow)

        assert result.status == "ok"
        assert [step.status for step in result.steps] == ["ok", "ok"]
        assert jobs[0].url.host == "example.com"

    async def test_a_step_with_needs_empty_does_not_see_the_clone_output_dir(self, output_dir, jobs):
        """`needs: []` opts out of the linear default, so nothing is inherited."""
        workflow = Workflow(
            "88888888",
            "sem dependência",
            [
                Step("clone", {"url": "https://example.com"}, id="coleta"),
                Step("search", {}, needs=[]),
            ],
        )

        result = await run_workflow(workflow)

        assert result.status == "failed"
        assert result.steps[1].status == "failed"
        assert "clone" in result.steps[1].detail

    async def test_invalid_graph_is_reported_without_raising(self, output_dir, engines):
        workflow = Workflow(
            "99999999",
            "grafo ruim",
            [Step("search", {}, needs=["step-7"])],
        )

        result = await run_workflow(workflow)

        assert result.status == "failed"
        assert result.steps == []
        assert result.error is not None and "step-7" in result.error
        assert engines["calls"] == []
