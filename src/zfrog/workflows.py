"""Saved pipelines ("workflows") that chain extraction steps.

A workflow is a named list of steps, persisted as one JSON file under
``settings.output_dir/workflows`` (see :class:`WorkflowStore`). Every step may
declare the steps it ``needs``, which turns the pipeline into a small dependency
graph: :func:`execution_waves` layers it topologically and :func:`run_workflow`
runs one wave at a time, in parallel (never more than
``settings.max_parallel_steps`` at once), because the steps of a wave are
independent by construction::

    probe ──► clone ──► summarize ──┐
                 └───► search       └──► commit

Steps carry a small context — the site URL, the directory holding the cloned
site and the last probe result — and it flows along the dependency edges: a step
starts from the context of every step it ``needs``, while a step without
``needs`` starts from an empty context and must name everything it uses itself.

Step types, their parameters and the graph are validated strictly, both when a
workflow is saved and when it runs, so a typo in a parameter name, a dependency
on a step that does not exist or a cycle is reported instead of being silently
ignored. A failing step does not abort the run: the steps that depend on it are
recorded as ``"skipped"``, the independent ones still run, and
:func:`run_workflow` still returns a result (it never raises).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from zfrog.config import settings
from zfrog.diff import capture_snapshot
from zfrog.engines import get_engine
from zfrog.models import JobCreate, ProbeResult
from zfrog.orchestrator import run_job
from zfrog.probe import probe_url
from zfrog.utils.http import create_client

logger = logging.getLogger(__name__)

#: Accepted parameter names per step type.
STEP_PARAMS: dict[str, frozenset[str]] = {
    "probe": frozenset({"url"}),
    "clone": frozenset({"url", "mode", "max_depth"}),
    "summarize": frozenset({"url"}),
    "analyze": frozenset({"url"}),
    "extract": frozenset({"url", "max_depth"}),
    "compare": frozenset({"url"}),
    "pdf": frozenset({"url", "pdf_filename"}),
    "search": frozenset(),
    "commit": frozenset({"message"}),
}

#: Parameters a step must supply itself (everything else may come from context).
REQUIRED_PARAMS: dict[str, frozenset[str]] = {
    "probe": frozenset({"url"}),
}

#: Steps that run one engine directly, mapped to the engine they use.
STEP_ENGINES: dict[str, str] = {
    "summarize": "summarize",
    "analyze": "analyze",
    "extract": "scrapy",
    "compare": "compare",
    "pdf": "pdf",
}

#: Mode used by a ``clone`` step that does not name one.
DEFAULT_CLONE_MODE = "auto"

#: Engine recorded on snapshots produced by a workflow run.
WORKFLOW_ENGINE = "workflow"

_VALID_ID = re.compile(r"[0-9a-f]{8}")

@dataclass
class Step:
    """One step of a workflow.

    ``needs`` lists the ids of the steps that must finish before this one runs;
    ``id`` is an optional label, auto-assigned as ``step-<index>`` when it is
    empty. Both are wiring metadata, so they stay out of equality: a step still
    compares equal to a bare ``Step("commit", {})``.

    ``needs`` has three meaningful values:

    ``None`` (omitted)
        Linear default: this step waits for the step declared just before it.
        This is what a plain pipeline means, and it is why workflows saved
        before dependencies existed keep running in order.
    ``[]`` (explicitly empty)
        No dependency at all — the step may run in parallel with anything.
    ``["step-0", ...]``
        Exactly these steps, and nothing else.
    """

    type: str
    params: dict[str, Any] = field(default_factory=dict)
    needs: list[str] | None = field(default=None, compare=False)
    id: str = field(default="", compare=False)

@dataclass
class Workflow:
    """A named pipeline of steps, in declaration order (see :class:`Step`)."""

    id: str
    name: str
    steps: list[Step]

@dataclass
class StepResult:
    """Outcome of a single step inside a run."""

    type: str
    status: str
    detail: str
    output: str | None = None

@dataclass
class RunResult:
    """Outcome of a whole workflow run."""

    workflow_id: str
    status: str
    steps: list[StepResult]
    error: str | None = None

def validate_steps(steps: list[dict]) -> list[Step]:
    """Validate raw step dictionaries and return them as :class:`Step` objects.

    Rejects an empty list, an unknown step type, an unknown field, an unknown
    parameter name and a missing required parameter, always with a
    :class:`ValueError` naming the offending step. Every step also gets an ``id``
    (the author's, or ``step-<index>``) and the graph is checked here too: a
    ``needs`` entry naming a step that does not exist, a repeated ``id`` and a
    cycle are refused, the cycle showing its path.
    """
    if not steps:
        raise ValueError("the workflow needs at least one step")

    validated: list[Step] = []
    for index, raw in enumerate(steps, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"step {index}: expected an object with 'type' and 'params'")

        step_type = raw.get("type")
        if step_type not in STEP_PARAMS:
            raise ValueError(f"step {index}: unknown step type: {step_type!r}")

        params = raw.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError(f"step {index} ({step_type}): 'params' must be an object")

        unknown_fields = sorted(set(raw) - {"type", "params", "id", "needs"})
        if unknown_fields:
            raise ValueError(
                f"step {index} ({step_type}): unknown field: {unknown_fields[0]!r}"
            )

        unknown = sorted(set(params) - STEP_PARAMS[step_type])
        if unknown:
            raise ValueError(
                f"step {index} ({step_type}): unknown parameter: {unknown[0]!r}"
            )

        for required in sorted(REQUIRED_PARAMS.get(step_type, frozenset())):
            if not params.get(required):
                raise ValueError(f"step {index} ({step_type}): missing parameter {required!r}")

        validated.append(
            Step(
                type=step_type,
                params=dict(params),
                needs=_parse_needs(raw, index, step_type),
                id=_parse_id(raw, index, step_type, index - 1),
            )
        )

    # A step that does not declare `needs` keeps the linear meaning it always
    # had: it waits for the step declared before it. Workflows saved before
    # dependencies existed therefore keep running in order, and a step opts into
    # parallelism by declaring `needs: []` (or its own list of ids).
    for position, step in enumerate(validated):
        if step.needs is None:
            step.needs = [validated[position - 1].id] if position else []

    # The graph is checked here as well, so an unknown dependency, a repeated id
    # or a cycle is refused before anything is saved or run.
    _wave_indices(validated)
    return validated

def _parse_id(raw: dict, index: int, step_type: str, position: int) -> str:
    """Return the label of a step, falling back to ``step-<position>``."""
    label = raw.get("id")
    if label is None or label == "":
        return f"step-{position}"
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"step {index} ({step_type}): 'id' must be non-empty text")
    return label.strip()

def _parse_needs(raw: dict, index: int, step_type: str) -> list[str] | None:
    """Return the ids a step waits for.

    ``None`` means the key was absent, which the caller turns into the linear
    default (wait for the previous step); an explicit empty list means no
    dependency at all.
    """
    needs = raw.get("needs")
    if needs is None:
        return None
    if not isinstance(needs, list) or any(not isinstance(item, str) for item in needs):
        raise ValueError(
            f"step {index} ({step_type}): 'needs' must be a list of ids"
        )

    cleaned = [item.strip() for item in needs]
    if any(not item for item in cleaned):
        raise ValueError(f"step {index} ({step_type}): 'needs' has an empty id")
    return cleaned

def execution_waves(steps: list[Step]) -> list[list[Step]]:
    """Layer ``steps`` into waves that can run at the same time.

    A wave holds every step whose ``needs`` are satisfied by the previous waves,
    keeping the declaration order inside the wave, so a linear chain yields one
    step per wave, two steps without dependencies yield a single wave and a
    diamond (``a``; ``b`` and ``c`` needing ``a``; ``d`` needing ``b`` and ``c``)
    yields ``[[a], [b, c], [d]]``.

    Raises :class:`ValueError` when a step needs an id that does not exist, when
    two steps share an id, or when the graph has a cycle — the message shows the
    cycle path.
    """
    return [[steps[index] for index in wave] for wave in _wave_indices(steps)]

def _wave_indices(steps: list[Step]) -> list[list[int]]:
    """Return the wave each step belongs to, as positions in ``steps``."""
    index_by_id = _index_by_id(steps)
    done: set[str] = set()
    pending = list(range(len(steps)))
    waves: list[list[int]] = []

    while pending:
        ready = [
            index for index in pending if all(need in done for need in steps[index].needs)
        ]
        if not ready:
            cycle = _find_cycle(steps, pending, index_by_id)
            raise ValueError(_cycle_message(steps, cycle))

        waves.append(ready)
        done.update(_step_id(steps[index], index) for index in ready)
        settled = set(ready)
        pending = [index for index in pending if index not in settled]

    return waves

def _step_id(step: Step, position: int) -> str:
    """Return the id of ``step``, falling back to its position (``step-<index>``)."""
    return step.id or f"step-{position}"

def _index_by_id(steps: list[Step]) -> dict[str, int]:
    """Map every step id to its position, refusing repeated ids and unknown needs."""
    index_by_id: dict[str, int] = {}
    for position, step in enumerate(steps):
        step_id = _step_id(step, position)
        if step_id in index_by_id:
            raise ValueError(
                f"step {position + 1} ({step.type}): duplicate id: {step_id!r}"
            )
        index_by_id[step_id] = position

    for position, step in enumerate(steps):
        for need in step.needs:
            if need not in index_by_id:
                raise ValueError(
                    f"step {position + 1} ({step.type}): 'needs' points to a step "
                    f"nonexistent: {need!r}"
                )
    return index_by_id

def _find_cycle(
    steps: list[Step], pending: list[int], index_by_id: dict[str, int]
) -> list[int]:
    """Return the positions of one dependency cycle among ``pending`` (empty when none)."""
    settled: set[int] = set()
    for root in pending:
        if root in settled:
            continue

        path: list[int] = []
        stack: list[tuple[int, int]] = [(root, 0)]
        while stack:
            position, cursor = stack[-1]
            if cursor == 0:
                path.append(position)

            needs = [index_by_id[need] for need in steps[position].needs]
            if cursor < len(needs):
                stack[-1] = (position, cursor + 1)
                target = needs[cursor]
                if target in path:
                    return path[path.index(target) :]
                if target not in settled:
                    stack.append((target, 0))
                continue

            path.pop()
            settled.add(position)
            stack.pop()

    return []

def _cycle_message(steps: list[Step], cycle: list[int]) -> str:
    """Describe a dependency cycle the way it can be read back to the author."""
    labels = [f"{_step_id(steps[index], index)} ({steps[index].type})" for index in cycle]
    if not labels:
        return "cycle in the workflow"
    return "cycle in the workflow: " + " → ".join(labels + labels[:1])

class WorkflowStore:
    """One JSON file per workflow under ``root`` (default ``settings.output_dir/workflows``)."""

    def __init__(self, root: Path | None = None):
        self.root = (
            Path(root) if root is not None else Path(settings.output_dir) / "workflows"
        )

    # ── CRUD ────────────────────────────────────────────────────────

    def save(self, name: str, steps: list[dict]) -> Workflow:
        """Validate ``steps`` and store them under ``name``.

        Saving a name that already exists replaces that workflow in place, so
        the id stays stable. Raises :class:`ValueError` for an empty name or
        invalid steps; nothing is written in that case.
        """
        cleaned_name = name.strip() if isinstance(name, str) else ""
        if not cleaned_name:
            raise ValueError("workflow requires a name")

        validated = validate_steps(steps)
        workflow_id = self._id_for_name(cleaned_name) or self._new_id()
        workflow = Workflow(id=workflow_id, name=cleaned_name, steps=validated)

        self._write_atomic(self._path(workflow_id), _to_payload(workflow))
        logger.info("Workflow %s saved (%d steps)", workflow_id, len(validated))
        return workflow
    def list(self) -> list[Workflow]:
        """Return every stored workflow, sorted by name (unreadable files skipped)."""
        if not self.root.is_dir():
            return []
        workflows = [
            workflow
            for workflow in (self._read(path) for path in sorted(self.root.glob("*.json")))
            if workflow is not None
        ]
        return sorted(workflows, key=lambda workflow: workflow.name)

    def get(self, id: str) -> Workflow | None:
        """Return the workflow with ``id``, or None when it does not exist."""
        if not _VALID_ID.fullmatch(id or ""):
            return None
        return self._read(self._path(id))

    def remove(self, id: str) -> bool:
        """Delete the workflow with ``id``, returning True when a file was removed."""
        if not _VALID_ID.fullmatch(id or ""):
            return False
        path = self._path(id)
        if not path.is_file():
            return False
        path.unlink()
        logger.info("Fluxo %s removido", id)
        return True

    # ── internals ───────────────────────────────────────────────────

    def _path(self, workflow_id: str) -> Path:
        return self.root / f"{workflow_id}.json"

    def _id_for_name(self, name: str) -> str | None:
        """Return the id of the workflow already saved under ``name``, if any."""
        for workflow in self.list():
            if workflow.name == name:
                return workflow.id
        return None

    def _new_id(self) -> str:
        """Return an unused 8-hex-character workflow id."""
        while True:
            candidate = uuid.uuid4().hex[:8]
            if not self._path(candidate).exists():
                return candidate

    def _write_atomic(self, path: Path, payload: dict) -> None:
        """Write ``payload`` to ``path`` via a temporary file plus ``os.replace``."""
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    def _read(self, path: Path) -> Workflow | None:
        """Read one workflow file, returning None (and logging) when it is unusable."""
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            steps = [
                Step(
                    type=str(raw["type"]),
                    params=dict(raw.get("params") or {}),
                    needs=(
                        [str(item) for item in raw["needs"]]
                        if isinstance(raw.get("needs"), list)
                        else None
                    ),
                    id=str(raw.get("id") or f"step-{position}"),
                )
                for position, raw in enumerate(payload["steps"])
            ]
            return Workflow(id=str(payload["id"]), name=str(payload["name"]), steps=steps)
        except Exception as exc:
            logger.warning("Skipping unreadable workflow %s: %s", path, exc)
            return None

def _to_payload(workflow: Workflow) -> dict:
    """Serialise a workflow into its on-disk JSON shape."""
    return {
        "id": workflow.id,
        "name": workflow.name,
        "steps": [
            {
                "id": _step_id(step, position),
                "type": step.type,
                "params": step.params,
                "needs": list(step.needs) if step.needs is not None else None,
            }
            for position, step in enumerate(workflow.steps)
        ],
    }

@dataclass
class _Context:
    """State one step produces for the steps that depend on it."""

    workflow_id: str
    run_id: str
    url: str | None = None
    output_dir: Path | None = None
    probe: ProbeResult | None = None

    def inherit(self, parent: _Context) -> None:
        """Take over the values a dependent step reads from ``parent``."""
        if parent.url:
            self.url = parent.url
        if parent.output_dir is not None:
            self.output_dir = parent.output_dir
        if parent.probe is not None:
            self.probe = parent.probe

@dataclass
class _Run:
    """What every wave of one run shares: the graph, the contexts and the limit."""

    workflow_id: str
    run_id: str
    index_by_id: dict[str, int]
    contexts: dict[int, _Context]
    semaphore: asyncio.Semaphore
    on_progress: Callable[[str], Any] | None

def preview_steps(steps: list[dict]) -> dict:
    """Explain a pipeline without running it.

    Used by the dashboard so the user sees what each step will do — and, more
    importantly, which steps cannot work yet: a step with no url, or a `search`/
    `commit` with no producing step among its `needs`, only fails once the run
    starts.

    Returns:
        ``{"steps": [{"index","type","summary","warnings"}], "warnings": [...],
        "total": int}``. Raises ValueError when the pipeline itself is invalid.
    """
    validated = validate_steps(steps)
    waves = execution_waves(validated)
    positions = {_step_id(step, index): index for index, step in enumerate(validated)}
    summaries = {
        "probe": "Discovers how the site is built.",
        "clone": "Downloads the site in the chosen mode.",
        "summarize": "Writes a short summary of the page.",
        "analyze": "Checks SEO, accessibility and performance.",
        "extract": "Separates title, text, links and images.",
        "compare": "Measures how faithful the copy is to the original.",
        "pdf": "Saves the page as a PDF file.",
        "search": "Makes what was downloaded searchable.",
        "commit": "Saves the result as a version in the history.",
    }

    preview: list[dict] = []
    all_warnings: list[str] = []

    for index, step in enumerate(validated):
        warnings: list[str] = []
        label = f"Step {index + 1} ({step.type})"
        needs = list(step.needs or [])
        # A step that reads a URL needs one from its params or from a `probe` it waits for.
        if step.type in ("clone", "summarize", "analyze", "extract", "compare", "pdf", "probe"):
            has_param_url = bool(step.params.get("url"))
            probes = [need for need in needs if validated[positions[need]].type == "probe"]
            if not has_param_url and not probes:
                warnings.append(
                    f"{label}: no address — provide 'url' or declare a 'probe' step in 'needs'."
                )

        # `search`/`commit` read the output of the steps they wait for.
        if step.type in ("search", "commit"):
            producers = [
                need
                for need in needs
                if validated[positions[need]].type in ("clone", "pdf", "extract", "compare", "analyze")
            ]
            if not producers:
                warnings.append(
                    f"{label}: receives no directory — declare in 'needs' the step that downloads the site."
                )

        if step.type == "commit" and not step.params.get("message"):
            warnings.append(f"{label}: without 'message' — the version will have no description.")

        summary = summaries.get(step.type, step.type)
        if step.params.get("url"):
            summary += f" ({step.params['url']})"

        preview.append(
            {
                "index": index,
                "type": step.type,
                "summary": summary,
                "warnings": warnings,
            }
        )
        all_warnings.extend(warnings)

    parallel = [wave for wave in waves if len(wave) > 1]
    if parallel:
        first = parallel[0]
        all_warnings.append(
            "Independent steps run in parallel: "
            + ", ".join(f"step {positions[_step_id(step, 0)] + 1}" for step in first)
            + "."
        )
    return {"steps": preview, "warnings": all_warnings, "total": len(validated)}


async def run_workflow(
    workflow: Workflow,
    on_progress: Callable[[str], Any] | None = None,
) -> RunResult:
    """Run every step of ``workflow``, one wave of the graph at a time.

    ``on_progress`` receives one message per step, e.g. ``"Step 2/5: clone"``.
    The steps of a wave run together, at most ``settings.max_parallel_steps`` at
    a time, and each of them starts from the context of the steps it ``needs``.
    A failing step marks the run ``"failed"`` and records the steps that depend
    on it as ``"skipped"``; independent steps still run. This function never
    raises: an unexpected error — or an invalid step or graph — is reported
    through the returned :class:`RunResult`.
    """
    results: list[StepResult] = []
    try:
        return await _run_steps(workflow, on_progress, results)
    except Exception as exc:
        logger.exception("Unexpected failure in workflow %s", workflow.id)
        return RunResult(
            workflow_id=workflow.id,
            status="failed",
            steps=results,
            error=f"unexpected failure: {exc}",
        )
async def _run_steps(
    workflow: Workflow,
    on_progress: Callable[[str], Any] | None,
    results: list[StepResult],
) -> RunResult:
    """Validate and execute ``workflow``, keeping ``results`` in declaration order."""
    try:
        steps = validate_steps(
            [
                {
                    "type": step.type,
                    "params": step.params,
                    "needs": list(step.needs) if step.needs is not None else None,
                    "id": step.id,
                }
                for step in workflow.steps
            ]
        )
        waves = _wave_indices(steps)
    except ValueError as exc:
        return RunResult(
            workflow_id=workflow.id, status="failed", steps=[], error=str(exc)
        )

    total = len(steps)
    run = _Run(
        workflow_id=workflow.id,
        run_id=uuid.uuid4().hex[:8],
        index_by_id=_index_by_id(steps),
        contexts={},
        semaphore=asyncio.Semaphore(max(1, int(settings.max_parallel_steps))),
        on_progress=on_progress,
    )
    outcomes: list[StepResult | None] = [None] * total
    statuses: dict[int, str] = {}

    for wave in waves:
        runnable: list[int] = []
        for index in wave:
            step = steps[index]
            if run.on_progress is not None:
                run.on_progress(f"Step {index + 1}/{total}: {step.type}")
            blocked_by = _blocking_dependency(step, run.index_by_id, statuses)
            if blocked_by is None:
                runnable.append(index)
                continue

            statuses[index] = "skipped"
            outcomes[index] = _skipped_result(step, blocked_by, steps, statuses)
        if runnable:
            finished = await asyncio.gather(
                *(_run_step(run, index, steps[index]) for index in runnable)
            )
            for index, outcome, context in finished:
                outcomes[index] = outcome
                statuses[index] = outcome.status
                run.contexts[index] = context

        results[:] = [outcome for outcome in outcomes if outcome is not None]

    failed = [index for index in range(total) if statuses.get(index) == "failed"]
    if not failed:
        return RunResult(workflow_id=workflow.id, status="ok", steps=list(results))

    error = "; ".join(
        f"step {index + 1} ({steps[index].type}) failed: {outcomes[index].detail}"
        for index in failed
    )
    return RunResult(
        workflow_id=workflow.id, status="failed", steps=list(results), error=error
    )

async def _run_step(
    run: _Run, index: int, step: Step
) -> tuple[int, StepResult, _Context]:
    """Run one step within the concurrency limit and report the context it leaves."""
    context = _step_context(run, step)
    async with run.semaphore:
        try:
            outcome = await _execute_step(step, context, index + 1, run.on_progress)
        except Exception as exc:
            detail = str(exc) or exc.__class__.__name__
            logger.warning("Step %d (%s) failed: %s", index + 1, step.type, detail)
            outcome = StepResult(type=step.type, status="failed", detail=detail)

    return index, outcome, context

def _step_context(run: _Run, step: Step) -> _Context:
    """Build the context a step starts from: what the steps it needs produced."""
    context = _Context(workflow_id=run.workflow_id, run_id=run.run_id)
    for need in step.needs:
        parent = run.contexts.get(run.index_by_id[need])
        if parent is not None:
            context.inherit(parent)
    return context

def _blocking_dependency(
    step: Step, index_by_id: dict[str, int], statuses: dict[int, str]
) -> int | None:
    """Return the first step this one waits for that did not succeed, if any."""
    for need in step.needs:
        index = index_by_id[need]
        if statuses.get(index) != "ok":
            return index
    return None

def _skipped_result(
    step: Step, blocked_by: int, steps: list[Step], statuses: dict[int, str]
) -> StepResult:
    """Record a step whose dependency failed (or was itself skipped)."""
    blocker = steps[blocked_by]
    fate = "failed" if statuses.get(blocked_by) == "failed" else "was skipped"
    return StepResult(
        type=step.type,
        status="skipped",
        detail=f"skipped: depends on step {blocked_by + 1} ({blocker.type}) which {fate}",
    )

async def _execute_step(
    step: Step,
    context: _Context,
    index: int,
    on_progress: Callable[[str], Any] | None,
) -> StepResult:
    """Dispatch one validated step to its handler."""
    if step.type == "probe":
        return await _run_probe(step, context)
    if step.type == "clone":
        return await _run_clone(step, context)
    if step.type in STEP_ENGINES:
        return await _run_engine(step, context, index, on_progress)
    if step.type == "search":
        return _run_search(context)
    return _run_commit(step, context)

async def _run_probe(step: Step, context: _Context) -> StepResult:
    """Probe the step's URL and remember the result in the context."""
    url = _resolve_url(step, context)
    client = create_client(proxy=settings.proxy_url)
    try:
        probe = await probe_url(url, client)
    finally:
        await client.aclose()
    context.probe = probe
    return StepResult(
        type="probe",
        status="ok",
        detail=f"suggested engine: {probe.suggested_engine}",
    )
async def _run_clone(step: Step, context: _Context) -> StepResult:
    """Clone the context URL and make the job output directory the current one."""
    url = _resolve_url(step, context)
    mode = step.params.get("mode") or DEFAULT_CLONE_MODE
    result = await run_job(_build_job(url, mode, step.params))

    output_dir = Path(result.output_path).parent
    context.output_dir = output_dir
    return StepResult(
        type="clone",
        status="ok",
        detail=f"{_count_files(output_dir)} files in {output_dir}",
        output=str(output_dir),
    )
async def _run_engine(
    step: Step,
    context: _Context,
    index: int,
    on_progress: Callable[[str], Any] | None,
) -> StepResult:
    """Run one engine into a fresh per-step directory."""
    url = _resolve_url(step, context)
    step_dir = Path(settings.output_dir) / "workflow-runs" / context.run_id / f"{index}-{step.type}"
    step_dir.mkdir(parents=True, exist_ok=True)

    engine = get_engine(STEP_ENGINES[step.type])
    await engine.execute(_build_job(url, step.type, step.params), step_dir, on_progress)

    return StepResult(
        type=step.type,
        status="ok",
        detail=f"{_count_files(step_dir)} files in {step_dir}",
        output=str(step_dir),
    )
def _run_search(context: _Context) -> StepResult:
    """Index the current output directory."""
    if context.output_dir is None:
        raise ValueError(
            "the 'search' step needs an output directory: declare in 'needs' a "
            "'clone' step that produces it"
        )

    from zfrog.search import SearchIndex

    indexed = SearchIndex().index_directory(context.output_dir, url=context.url)
    detail = (
        f"{indexed} pages indexed in {context.output_dir}"
        if isinstance(indexed, int)
        else f"index updated at {context.output_dir}"
    )
    return StepResult(type="search", status="ok", detail=detail)
def _run_commit(step: Step, context: _Context) -> StepResult:
    """Snapshot the current output directory and commit it to the version store."""
    if context.output_dir is None:
        raise ValueError(
            "the 'commit' step needs an output directory: declare in 'needs' a "
            "'clone' step that produces it"
        )
    if not context.url:
        raise ValueError(
            "the 'commit' step needs a URL: declare a 'probe' step in 'needs'"
        )

    from zfrog.versioning import VersionStore

    snapshot_path, _previous = capture_snapshot(context.output_dir, context.url, WORKFLOW_ENGINE)
    message = step.params.get("message") or f"workflow {context.workflow_id}"
    version = VersionStore().commit(context.url, snapshot_path, context.output_dir, message)

    return StepResult(
        type="commit",
        status="ok",
        detail=f"version {version.id} created",
        output=str(version.id),
    )

def _resolve_url(step: Step, context: _Context) -> str:
    """Return the URL a step works on, updating the context when it is explicit."""
    url = step.params.get("url") or context.url
    if not url:
        raise ValueError(
            f"the '{step.type}' step needs a URL: provide it in params.url "
            f"or declare a 'probe' step in 'needs' that provides it"
        )
    context.url = url
    return url
def _build_job(url: str, mode: str, params: dict[str, Any]) -> JobCreate:
    """Build the :class:`JobCreate` for a step, forwarding only the params it accepts."""
    kwargs: dict[str, Any] = {"url": url, "mode": mode}
    if params.get("max_depth") is not None:
        kwargs["max_depth"] = params["max_depth"]
    if params.get("pdf_filename"):
        kwargs["pdf_filename"] = params["pdf_filename"]
    return JobCreate(**kwargs)

def _count_files(directory: Path) -> int:
    """Count the files under ``directory`` (0 when it does not exist)."""
    if not directory.is_dir():
        return 0
    return sum(1 for path in directory.rglob("*") if path.is_file())
