"""Tests for saved workflows (pipelines of extraction steps)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from zfrog import workflows
from zfrog.config import settings
from zfrog.engines.base import EngineResult
from zfrog.models import JobCreate, JobResult, ProbeResult
from zfrog.workflows import (
    Step,
    Workflow,
    WorkflowStore,
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
def probes(monkeypatch):
    """Record probed URLs and answer with a canned probe result."""
    probed: list[str] = []

    async def fake_probe(url, client):
        probed.append(url)
        return ProbeResult(url=url, suggested_engine="wget", status_code=200)

    monkeypatch.setattr(workflows, "probe_url", fake_probe)
    return probed

@pytest.fixture
def jobs(output_dir, monkeypatch):
    """Record every ``run_job`` call and return a finished job under ``output_dir``."""
    calls: list[JobCreate] = []

    async def fake_run_job(job):
        calls.append(job)
        job_dir = output_dir / "jobs" / f"job{len(calls)}"
        (job_dir / "site").mkdir(parents=True, exist_ok=True)
        (job_dir / "site" / "index.html").write_text(
            "<html><head><title>página</title></head><body>olá</body></html>",
            encoding="utf-8",
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
    """Record every engine run as ``(name, output_dir, job)`` and write one file."""
    calls: list[tuple[str, Path, JobCreate]] = []

    class RecordingEngine:
        def __init__(self, name: str) -> None:
            self.name = name

        async def execute(self, job, output_dir, on_progress=None):
            output_dir.mkdir(parents=True, exist_ok=True)
            written = output_dir / f"{self.name}.txt"
            written.write_text(str(job.url), encoding="utf-8")
            calls.append((self.name, output_dir, job))
            return EngineResult(output_dir=output_dir, files=[written])

    monkeypatch.setattr(workflows, "get_engine", lambda name: RecordingEngine(name))
    return calls

# ── validate_steps ──────────────────────────────────────────────────

class TestValidateSteps:
    """The validation shared by ``WorkflowStore.save`` and ``run_workflow``."""

    def test_accepts_every_documented_step_and_param(self):
        steps = validate_steps(
            [
                {"type": "probe", "params": {"url": "https://example.com"}},
                {"type": "clone", "params": {"url": "https://example.com", "mode": "scrape", "max_depth": 2}},
                {"type": "summarize", "params": {"url": "https://example.com"}},
                {"type": "analyze", "params": {"url": "https://example.com"}},
                {"type": "extract", "params": {"url": "https://example.com", "max_depth": 4}},
                {"type": "compare", "params": {"url": "https://example.com"}},
                {"type": "pdf", "params": {"url": "https://example.com", "pdf_filename": "site"}},
                {"type": "search", "params": {}},
                {"type": "commit", "params": {"message": "first version"}},
            ]
        )

        assert [step.type for step in steps] == [
            "probe",
            "clone",
            "summarize",
            "analyze",
            "extract",
            "compare",
            "pdf",
            "search",
            "commit",
        ]
        assert steps[1].params == {"url": "https://example.com", "mode": "scrape", "max_depth": 2}
        assert steps[7].params == {}

    def test_missing_params_default_to_empty(self):
        steps = validate_steps([{"type": "search"}, {"type": "clone"}])

        assert [step.params for step in steps] == [{}, {}]

    def test_rejects_unknown_step_type(self):
        with pytest.raises(ValueError, match="unknown"):
            validate_steps([{"type": "teleport", "params": {}}])

    def test_rejects_unknown_param_key(self):
        with pytest.raises(ValueError, match="max_pages"):
            validate_steps([{"type": "clone", "params": {"max_pages": 5}}])

    def test_rejects_params_a_step_does_not_take(self):
        with pytest.raises(ValueError, match="url"):
            validate_steps([{"type": "search", "params": {"url": "https://example.com"}}])

    def test_rejects_empty_step_list(self):
        with pytest.raises(ValueError, match="step"):
            validate_steps([])

    def test_rejects_probe_without_url(self):
        with pytest.raises(ValueError, match="url"):
            validate_steps([{"type": "probe", "params": {}}])

    def test_names_the_offending_step(self):
        with pytest.raises(ValueError, match="step 2"):
            validate_steps([{"type": "search"}, {"type": "clone", "params": {"depth": 1}}])

# ── WorkflowStore ───────────────────────────────────────────────────

class TestWorkflowStore:
    """Persistence of workflows as one JSON file per workflow."""

    def test_default_root_sits_under_the_output_dir(self, output_dir):
        store = WorkflowStore()

        saved = store.save("diário", [{"type": "search"}])

        assert (output_dir / "workflows" / f"{saved.id}.json").is_file()
        assert store.get(saved.id).name == "diário"

    def test_round_trip(self, tmp_path):
        store = WorkflowStore(root=tmp_path / "flows")

        saved = store.save(
            "diário",
            [
                {"type": "probe", "params": {"url": "https://example.com"}},
                {"type": "commit", "params": {}},
            ],
        )

        assert len(saved.id) == 8
        assert all(character in "0123456789abcdef" for character in saved.id)
        assert [workflow.id for workflow in store.list()] == [saved.id]

        loaded = store.get(saved.id)
        assert loaded == saved
        assert loaded.steps[1] == Step("commit", {})

        assert store.remove(saved.id) is True
        assert store.get(saved.id) is None
        assert store.list() == []
        assert store.remove(saved.id) is False

    def test_saving_the_same_name_replaces_it(self, tmp_path):
        store = WorkflowStore(root=tmp_path)

        first = store.save("diário", [{"type": "search"}])
        second = store.save(
            "diário", [{"type": "probe", "params": {"url": "https://example.com"}}]
        )

        assert second.id == first.id
        assert [workflow.name for workflow in store.list()] == ["diário"]
        assert store.list()[0].steps == [Step("probe", {"url": "https://example.com"})]
        # One file only, and no leftover temporary file from the atomic write.
        assert [path.name for path in tmp_path.iterdir()] == [f"{second.id}.json"]

    def test_list_is_sorted_by_name(self, tmp_path):
        store = WorkflowStore(root=tmp_path)

        store.save("zulu", [{"type": "search"}])
        store.save("alfa", [{"type": "search"}])

        assert [workflow.name for workflow in store.list()] == ["alfa", "zulu"]

    def test_save_rejects_invalid_steps_without_writing(self, tmp_path):
        store = WorkflowStore(root=tmp_path)

        with pytest.raises(ValueError, match="unknown"):
            store.save("ruim", [{"type": "teleport", "params": {}}])

        assert list(tmp_path.glob("*.json")) == []

    def test_save_rejects_an_empty_name(self, tmp_path):
        store = WorkflowStore(root=tmp_path)

        with pytest.raises(ValueError, match="name"):
            store.save("   ", [{"type": "search"}])

        assert list(tmp_path.glob("*.json")) == []

    def test_unreadable_files_are_ignored(self, tmp_path):
        root = tmp_path / "flows"
        root.mkdir()
        (root / "deadbeef.json").write_text("{ this is not json", encoding="utf-8")
        store = WorkflowStore(root=root)

        assert store.list() == []
        assert store.get("deadbeef") is None

    def test_unsafe_ids_are_refused(self, tmp_path):
        store = WorkflowStore(root=tmp_path)

        assert store.get("../../etc/passwd") is None
        assert store.remove("nao-e-id") is False

    def test_missing_root_is_an_empty_store(self, tmp_path):
        store = WorkflowStore(root=tmp_path / "nunca-criado")

        assert store.list() == []
        assert store.get("aaaaaaaa") is None
        assert store.remove("aaaaaaaa") is False

# ── run_workflow ────────────────────────────────────────────────────

class TestRunWorkflow:
    """Running a workflow, threading the context through its steps."""

    async def test_pipeline_records_one_result_per_step(self, output_dir, probes, jobs, engines):
        workflow = Workflow(
            "aaaaaaaa",
            "pipeline",
            [
                Step("probe", {"url": "https://example.com"}),
                Step("clone", {}),
                Step("summarize", {}),
            ],
        )

        messages: list[str] = []
        result = await run_workflow(workflow, on_progress=messages.append)

        assert result.workflow_id == "aaaaaaaa"
        assert result.status == "ok"
        assert result.error is None
        assert [step.type for step in result.steps] == ["probe", "clone", "summarize"]
        assert [step.status for step in result.steps] == ["ok", "ok", "ok"]

        assert probes == ["https://example.com"]
        assert result.steps[1].output == str(output_dir / "jobs" / "job1")
        assert jobs[0].mode == "auto"

        summarize_dir = Path(result.steps[2].output)
        assert summarize_dir.name == "3-summarize"
        assert summarize_dir.parent.parent == output_dir / "workflow-runs"
        assert (summarize_dir / "summarize.txt").is_file()
        assert [call[0] for call in engines] == ["summarize"]
        assert engines[0][1] == summarize_dir
        assert engines[0][2].url.host == "example.com"

        # Exactly one progress message per step.
        assert messages == [
            "Step 1/3: probe",
            "Step 2/3: clone",
            "Step 3/3: summarize",
        ]

    async def test_clone_output_dir_reaches_a_later_search(self, output_dir, probes, jobs, monkeypatch):
        recorded: dict = {}

        class FakeIndex:
            def index_directory(self, directory, url=None):
                recorded["directory"] = Path(directory)
                recorded["url"] = url
                return 4

        monkeypatch.setitem(sys.modules, "zfrog.search", SimpleNamespace(SearchIndex=FakeIndex))

        workflow = Workflow(
            "bbbbbbbb",
            "indexar",
            [
                Step("probe", {"url": "https://example.com"}),
                Step("clone", {}),
                Step("search", {}),
            ],
        )

        result = await run_workflow(workflow)

        assert result.status == "ok"
        assert recorded["directory"] == output_dir / "jobs" / "job1"
        assert recorded["url"] == "https://example.com"
        assert "4 pages indexed" in result.steps[2].detail

    async def test_clone_output_dir_reaches_a_later_commit(self, output_dir, probes, jobs, monkeypatch):
        commits: list[tuple] = []

        class FakeVersionStore:
            def commit(self, url, snapshot_path, output_dir, message=None):
                commits.append((url, Path(snapshot_path), Path(output_dir), message))
                return SimpleNamespace(id="v7")

        monkeypatch.setitem(
            sys.modules, "zfrog.versioning", SimpleNamespace(VersionStore=FakeVersionStore)
        )

        workflow = Workflow(
            "cccccccc",
            "versionar",
            [
                Step("probe", {"url": "https://example.com/site"}),
                Step("clone", {}),
                Step("commit", {"message": "first version"}),
            ],
        )

        result = await run_workflow(workflow)

        assert result.status == "ok"
        assert result.steps[2].output == "v7"
        assert "v7" in result.steps[2].detail

        url, snapshot_path, committed_dir, message = commits[0]
        assert url == "https://example.com/site"
        assert committed_dir == output_dir / "jobs" / "job1"
        assert message == "first version"
        assert snapshot_path.is_file()
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert snapshot["engine"] == "workflow"
        assert [page["path"] for page in snapshot["pages"]] == ["site/index.html"]

    async def test_failing_step_skips_the_rest(self, output_dir, jobs, engines, monkeypatch):
        async def broken_probe(url, client):
            raise RuntimeError("rede fora do ar")

        monkeypatch.setattr(workflows, "probe_url", broken_probe)

        workflow = Workflow(
            "dddddddd",
            "quebrado",
            [
                Step("probe", {"url": "https://example.com"}),
                Step("clone", {}),
                Step("summarize", {}),
            ],
        )

        messages: list[str] = []
        result = await run_workflow(workflow, on_progress=messages.append)

        assert result.status == "failed"
        assert [step.status for step in result.steps] == ["failed", "skipped", "skipped"]
        assert "rede fora do ar" in result.steps[0].detail
        # The skip detail must say what it was waiting for and why; the exact
        # wording is not part of the contract.
        assert "skipped" in result.steps[1].detail
        assert "step 1" in result.steps[1].detail
        assert result.error is not None
        assert "probe" in result.error and "rede fora do ar" in result.error
        assert jobs == []
        assert engines == []
        assert len(messages) == 3

    async def test_clone_without_any_url_fails_clearly(self, output_dir, jobs):
        workflow = Workflow("eeeeeeee", "sem url", [Step("clone", {})])

        result = await run_workflow(workflow)

        assert result.status == "failed"
        assert result.steps[0].status == "failed"
        assert "URL" in result.steps[0].detail
        assert jobs == []

    async def test_invalid_step_fails_without_raising(self, output_dir):
        workflow = Workflow("ffffffff", "invalid", [Step("teleport", {})])

        result = await run_workflow(workflow)

        assert result.status == "failed"
        assert result.steps == []
        assert result.error is not None and "teleport" in result.error

    async def test_engine_step_uses_its_own_url_when_given(self, output_dir, probes, engines):
        workflow = Workflow(
            "11111111",
            "override",
            [
                Step("probe", {"url": "https://example.com"}),
                Step("summarize", {"url": "https://outro.example/pagina"}),
            ],
        )

        result = await run_workflow(workflow)

        assert result.status == "ok"
        assert engines[0][2].url.host == "outro.example"
        assert Path(result.steps[1].output).name == "2-summarize"

    @pytest.mark.parametrize(
        ("step_type", "engine_name"),
        [
            ("summarize", "summarize"),
            ("analyze", "analyze"),
            ("extract", "scrapy"),
            ("compare", "compare"),
            ("pdf", "pdf"),
        ],
    )
    async def test_engine_step_types_map_to_engines(
        self, output_dir, probes, engines, step_type, engine_name
    ):
        workflow = Workflow(
            "22222222",
            step_type,
            [
                Step("probe", {"url": "https://example.com"}),
                Step(step_type, {}),
            ],
        )

        result = await run_workflow(workflow)

        assert result.status == "ok"
        assert [call[0] for call in engines] == [engine_name]
        assert engines[0][2].mode == step_type
        assert Path(result.steps[1].output).name == f"2-{step_type}"

    async def test_clone_forwards_mode_and_depth(self, output_dir, probes, jobs):
        workflow = Workflow(
            "33333333",
            "clone fundo",
            [
                Step("probe", {"url": "https://example.com"}),
                Step("clone", {"mode": "scrape", "max_depth": 2}),
            ],
        )

        await run_workflow(workflow)

        assert jobs[0].mode == "scrape"
        assert jobs[0].max_depth == 2

    async def test_pdf_step_forwards_the_filename(self, output_dir, probes, engines):
        workflow = Workflow(
            "44444444",
            "pdf",
            [
                Step("probe", {"url": "https://example.com"}),
                Step("pdf", {"pdf_filename": "site"}),
            ],
        )

        await run_workflow(workflow)

        assert engines[0][2].pdf_filename == "site"
