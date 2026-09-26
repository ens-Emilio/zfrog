"""Tests for the read-only GraphQL API (parser, executor, schema, real stores)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from zfrog import graphql_api
from zfrog.ai.chat import ChatSession, Conversation, Turn
from zfrog.ai.multisite import MultiSiteIndex
from zfrog.analytics import MetricsStore
from zfrog.config import settings
from zfrog.diff import capture_snapshot
from zfrog.graphql_api import GraphQLError, execute, parse_query, schema_sdl
from zfrog.models import Job, JobResult, JobStatus
from zfrog.scheduler import ScheduleStore
from zfrog.search import SearchIndex
from zfrog.versioning import VersionStore

SITE_URL = "https://quantum.test"
ROOT_FIELDS = (
    "jobs",
    "job",
    "snapshots",
    "versions",
    "schedules",
    "engines",
    "analytics",
    "search",
    "sites",
    "conversations",
)
PAGE_HTML = (
    "<html><head><title>Superconductors</title></head>"
    "<body><p>Quantum entanglement in a superconductor lattice.</p></body></html>"
)

@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Point every store the API reads at tmp_path — never the repo's output/."""
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(settings, "versions_dir", tmp_path / "versions")
    monkeypatch.setattr(settings, "schedules_file", tmp_path / "schedules.json")
    monkeypatch.setattr(settings, "search_db", tmp_path / "search.db")
    monkeypatch.setattr(settings, "metrics_db", tmp_path / "metrics.db")
    return tmp_path

def _job(job_id: str = "job-1", status: JobStatus = JobStatus.COMPLETED, minutes: int = 0) -> Job:
    """A real Job model, as the orchestrator stores it."""
    return Job(
        id=job_id,
        url=SITE_URL,
        mode="mirror",
        max_depth=2,
        status=status,
        created_at=datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes),
        output_path=f"/tmp/{job_id}",
    )

def _result(job_id: str = "job-1") -> JobResult:
    """A real JobResult model for a finished job."""
    return JobResult(
        job_id=job_id,
        output_path=f"/tmp/{job_id}",
        files_count=7,
        total_size_bytes=4096,
        engine_used="wget",
        duration_seconds=1.25,
    )

def _serve(monkeypatch, jobs: list[Job], results: dict[str, JobResult] | None = None) -> None:
    """Serve the orchestrator lookups from in-memory models."""
    by_id = {job.id: job for job in jobs}
    results = results or {}
    monkeypatch.setattr(graphql_api, "list_jobs", lambda: list(jobs))
    monkeypatch.setattr(graphql_api, "get_job", lambda job_id: by_id.get(job_id))
    monkeypatch.setattr(graphql_api, "get_result", lambda job_id: results.get(job_id))

def _write_clone(root, name: str = "index.html") -> None:
    """A tiny cloned page for the snapshot/version/search stores."""
    page = root / name
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(PAGE_HTML, encoding="utf-8")

class TestParseQuery:
    """The parser: selections, aliases, arguments and rejections."""

    def test_bare_selection_set(self):
        document = parse_query("{ jobs { id url } }")
        assert document["operation"] == "query"
        assert [field["name"] for field in document["fields"]] == ["jobs"]
        jobs = document["fields"][0]
        assert jobs["args"] == {}
        assert [field["name"] for field in jobs["selection"]] == ["id", "url"]
        assert jobs["selection"][0]["selection"] == []

    def test_aliases_nesting_and_typed_arguments(self):
        document = parse_query(
            '{ a: jobs(limit: 2, status: "completed", tags: ["x", "y"], flag: true) '
            "{ id result { filesCount } } }"
        )
        jobs = document["fields"][0]
        assert jobs["alias"] == "a"
        assert jobs["name"] == "jobs"
        assert jobs["args"] == {"limit": 2, "status": "completed", "tags": ["x", "y"], "flag": True}
        nested = jobs["selection"][1]
        assert nested["name"] == "result"
        assert nested["selection"][0]["name"] == "filesCount"

    def test_operation_name_variables_and_arguments(self):
        document = parse_query('query One($id: String!, $limit: Int = 3) { job(id: $id) { id } }')
        assert [definition["name"] for definition in document["variables"]] == ["id", "limit"]
        assert document["variables"][1]["default"] == 3
        argument = document["fields"][0]["args"]["id"]
        assert argument == graphql_api.Variable("id")

    def test_comments_and_commas_are_ignored(self):
        document = parse_query("# leading comment\n{ jobs, { id, } }")
        assert document["fields"][0]["name"] == "jobs"
        assert [field["name"] for field in document["fields"][0]["selection"]] == ["id"]

    def test_mutation_is_rejected_as_read_only(self):
        with pytest.raises(GraphQLError) as error:
            parse_query("mutation { createJob(url: \"x\") { id } }")
        assert "read-only" in error.value.message
        assert error.value.locations == [{"line": 1, "column": 1}]

    def test_subscription_is_rejected(self):
        with pytest.raises(GraphQLError) as error:
            parse_query("subscription { jobs { id } }")
        assert "read-only" in error.value.message

    def test_unterminated_selection_reports_position(self):
        with pytest.raises(GraphQLError) as error:
            parse_query("{ jobs { id }")
        assert "unterminated selection set" in error.value.message
        assert error.value.locations == [{"line": 1, "column": 1}]

    def test_unterminated_string_and_empty_query(self):
        with pytest.raises(GraphQLError):
            parse_query('{ jobs(status: "open) { id } }')
        with pytest.raises(GraphQLError) as error:
            parse_query("   ")
        assert "empty" in error.value.message

    def test_trailing_content_is_a_syntax_error(self):
        with pytest.raises(GraphQLError) as error:
            parse_query("{ jobs { id } } { engines { name } }")
        assert "end of input" in error.value.message

class TestExecute:
    """The executor: pruning, arguments, aliases and partial failures."""

    async def test_returns_only_requested_fields(self, monkeypatch):
        _serve(monkeypatch, [_job()])
        outcome = await execute("{ jobs { id } }")
        assert outcome.errors == []
        assert outcome.data == {"jobs": [{"id": "job-1"}]}
        assert "url" not in outcome.data["jobs"][0]

    async def test_aliases_and_sibling_fields(self, monkeypatch):
        _serve(monkeypatch, [_job()])
        outcome = await execute("{ a: jobs { id } b: engines { name } }")
        assert outcome.errors == []
        assert set(outcome.data) == {"a", "b"}
        assert outcome.data["a"] == [{"id": "job-1"}]
        assert any(engine["name"] == "wget" for engine in outcome.data["b"])

    async def test_limit_and_status_arguments(self, monkeypatch):
        _serve(
            monkeypatch,
            [_job("job-1", JobStatus.COMPLETED), _job("job-2", JobStatus.FAILED, minutes=5)],
        )
        limited = await execute("{ jobs(limit: 1) { id } }")
        assert len(limited.data["jobs"]) == 1

        filtered = await execute('{ jobs(status: "failed") { id status } }')
        assert filtered.data["jobs"] == [{"id": "job-2", "status": "failed"}]

    async def test_unknown_argument_is_an_error(self, monkeypatch):
        _serve(monkeypatch, [_job()])
        outcome = await execute("{ jobs(limit: 1, nope: 2) { id } }")
        assert outcome.data["jobs"] is None
        assert "nope" in outcome.errors[0]["message"]
        assert outcome.errors[0]["path"] == ["jobs"]

    async def test_failing_resolver_nulls_only_its_field(self, monkeypatch):
        def _explode():
            raise RuntimeError("boom")

        monkeypatch.setattr(graphql_api, "list_jobs", _explode)
        outcome = await execute("{ jobs { id } engines { name } }")
        assert outcome.data["jobs"] is None
        assert any(engine["name"] == "wget" for engine in outcome.data["engines"])
        assert len(outcome.errors) == 1
        assert "boom" in outcome.errors[0]["message"]

    async def test_unknown_field_names_it(self, monkeypatch):
        _serve(monkeypatch, [_job()])
        outcome = await execute("{ nope { id } }")
        assert outcome.data["nope"] is None
        assert "nope" in outcome.errors[0]["message"]

    async def test_missing_required_argument(self, monkeypatch):
        _serve(monkeypatch, [_job()])
        outcome = await execute("{ job { id } }")
        assert outcome.data["job"] is None
        assert "'id'" in outcome.errors[0]["message"]
        assert "required" in outcome.errors[0]["message"]

    async def test_unknown_nested_field_is_an_error(self, monkeypatch):
        _serve(monkeypatch, [_job()])
        outcome = await execute("{ jobs { id nope } }")
        assert outcome.data["jobs"] is None
        assert "Cannot query field 'nope' on type 'Job'" in outcome.errors[0]["message"]

    async def test_object_field_without_selection_is_an_error(self, monkeypatch):
        _serve(monkeypatch, [_job()])
        outcome = await execute("{ jobs }")
        assert outcome.data["jobs"] is None
        assert "must have a selection of subfields" in outcome.errors[0]["message"]

    async def test_variables_are_resolved_and_missing_ones_reported(self, monkeypatch):
        _serve(monkeypatch, [_job("job-7")], {"job-7": _result("job-7")})
        query = "query One($id: String!) { job(id: $id) { id result { filesCount } } }"
        outcome = await execute(query, {"id": "job-7"})
        assert outcome.errors == []
        assert outcome.data["job"] == {"id": "job-7", "result": {"filesCount": 7}}

        missing = await execute(query)
        assert missing.data["job"] is None
        assert "$id" in missing.errors[0]["message"]

    async def test_typename_and_nested_selection(self, monkeypatch):
        _serve(monkeypatch, [_job("job-3")], {"job-3": _result("job-3")})
        outcome = await execute(
            '{ __typename job(id: "job-3") { __typename id result { engineUsed } } }'
        )
        assert outcome.errors == []
        assert outcome.data["__typename"] == "Query"
        assert outcome.data["job"]["__typename"] == "Job"
        assert outcome.data["job"]["result"] == {"engineUsed": "wget"}

    async def test_unknown_job_is_null_without_errors(self, monkeypatch):
        _serve(monkeypatch, [])
        outcome = await execute('{ job(id: "missing") { id } }')
        assert outcome.data == {"job": None}
        assert outcome.errors == []

    async def test_syntax_error_is_reported_not_raised(self):
        outcome = await execute("{ jobs { id }")
        assert outcome.data == {}
        assert outcome.errors[0]["locations"] == [{"line": 1, "column": 1}]

    async def test_bad_variable_type_is_an_error(self, monkeypatch):
        _serve(monkeypatch, [_job()])
        outcome = await execute("{ jobs(limit: $limit) { id } }", {"limit": "many"})
        assert outcome.data["jobs"] is None
        assert "Int" in outcome.errors[0]["message"]

class TestSchemaSdl:
    """The SDL rendering mirrors SCHEMA."""

    def test_sdl_lists_every_root_field(self):
        sdl = schema_sdl()
        assert sdl.strip()
        for name in ROOT_FIELDS:
            assert name in sdl
        assert "type Query {" in sdl
        assert "jobs(limit: Int = 20, status: String): [Job!]!" in sdl
        assert 'search(query: String!, mode: String = "fulltext", limit: Int = 20)' in sdl

    def test_sdl_declares_nested_object_types(self):
        sdl = schema_sdl()
        for type_name in ("type Job {", "type JobResult {", "type Schedule {", "type SearchHit {"):
            assert type_name in sdl
        assert "filesCount: Int!" in sdl

    def test_schema_declares_exactly_the_root_fields(self):
        assert set(graphql_api.SCHEMA) == set(ROOT_FIELDS)


class TestRealStores:
    """End to end: the resolvers read the real stores, isolated under tmp_path."""

    async def test_jobs_and_result_from_orchestrator(self, monkeypatch, stores):
        _serve(monkeypatch, [_job("job-42")], {"job-42": _result("job-42")})
        outcome = await execute(
            '{ jobs { id url status maxDepth createdAt } '
            'job(id: "job-42") { id result { filesCount totalBytes engineUsed durationSeconds } } }'
        )
        assert outcome.errors == []
        (listed,) = outcome.data["jobs"]
        assert listed["url"] == SITE_URL
        assert listed["status"] == "completed"
        assert listed["maxDepth"] == 2
        assert listed["createdAt"].startswith("2024-05-01T12:00:00")
        assert outcome.data["job"]["result"] == {
            "filesCount": 7,
            "totalBytes": 4096,
            "engineUsed": "wget",
            "durationSeconds": 1.25,
        }

    async def test_snapshots_read_from_disk(self, stores):
        clone = stores / "output" / "clone"
        _write_clone(clone)
        capture_snapshot(clone, SITE_URL, "wget")

        outcome = await execute(
            '{ snapshots(url: "https://quantum.test") { url engine pages path } }'
        )
        assert outcome.errors == []
        (entry,) = outcome.data["snapshots"]
        assert entry["url"] == SITE_URL
        assert entry["engine"] == "wget"
        assert entry["pages"] == 1
        assert Path(entry["path"]).is_file()

    async def test_versions_from_version_store(self, stores):
        clone = stores / "output" / "clone"
        _write_clone(clone)
        snapshot_path, _ = capture_snapshot(clone, SITE_URL, "wget")
        VersionStore().commit(SITE_URL, snapshot_path, clone, message="primeiro clone")

        outcome = await execute(
            '{ versions(url: "https://quantum.test") { id url branch message pages parent } }'
        )
        assert outcome.errors == []
        (entry,) = outcome.data["versions"]
        assert entry["message"] == "primeiro clone"
        assert entry["branch"] == "main"
        assert entry["url"] == SITE_URL
        assert entry["pages"] == 1
        assert entry["parent"] is None

    async def test_schedules_from_store(self, stores):
        ScheduleStore().add("0 2 * * *", SITE_URL, mode="mirror", max_depth=3)

        outcome = await execute("{ schedules { id cron url mode maxDepth enabled } }")
        assert outcome.errors == []
        (entry,) = outcome.data["schedules"]
        assert entry["cron"] == "0 2 * * *"
        assert entry["url"] == SITE_URL
        assert entry["mode"] == "mirror"
        assert entry["maxDepth"] == 3
        assert entry["enabled"] is True

    async def test_search_over_an_indexed_clone(self, stores):
        clone = stores / "clone"
        _write_clone(clone)
        assert SearchIndex().index_directory(clone, url=SITE_URL) >= 1

        outcome = await execute('{ search(query: "superconductor") { path url title score } }')
        assert outcome.errors == []
        assert outcome.data["search"], "the indexed page must be found"
        hit = outcome.data["search"][0]
        assert hit["title"] == "Superconductors"
        assert hit["score"] > 0

    async def test_analytics_from_metrics_store(self, stores):
        MetricsStore().record("wget", "completed", 2.5, total_bytes=2048, files=4, url=SITE_URL)

        outcome = await execute(
            '{ analytics(engine: "wget") { engine runs succeeded failed successRate totalBytes } }'
        )
        assert outcome.errors == []
        (entry,) = outcome.data["analytics"]
        assert entry["engine"] == "wget"
        assert entry["runs"] == 1
        assert entry["succeeded"] == 1
        assert entry["failed"] == 0
        assert entry["successRate"] == 1.0
        assert entry["totalBytes"] == 2048

    async def test_sites_from_multi_site_index(self, stores):
        added = MultiSiteIndex().add_text(SITE_URL, "Quantum entanglement links distant particles.")
        assert added >= 1

        outcome = await execute("{ sites { url pages chunks } }")
        assert outcome.errors == []
        assert outcome.data["sites"] == [{"url": SITE_URL, "pages": 1, "chunks": added}]

    async def test_conversations_from_chat_history(self, stores):
        session = ChatSession()
        session.conversation = Conversation(
            id="chat-1",
            sites=[SITE_URL],
            turns=[
                Turn(role="user", content="O que é entrelaçamento?"),
                Turn(role="assistant", content="Uma correlação quântica."),
            ],
        )
        session.save()

        outcome = await execute("{ conversations { id sites turns createdAt } }")
        assert outcome.errors == []
        (entry,) = outcome.data["conversations"]
        assert entry["id"] == "chat-1"
        assert entry["sites"] == [SITE_URL]
        assert entry["turns"] == 2
        assert entry["createdAt"]

    async def test_engines_from_the_real_registry(self, stores):
        outcome = await execute("{ engines { name source } }")
        assert outcome.errors == []
        sources = {entry["name"]: entry["source"] for entry in outcome.data["engines"]}
        assert sources["wget"] == "built-in"
        assert "playwright" in sources

    async def test_empty_stores_return_empty_lists(self, stores):
        outcome = await execute(
            '{ jobs { id } snapshots { path } versions(url: "https://none.test") { id } '
            "schedules { id } conversations { id } }"
        )
        assert outcome.errors == []
        assert outcome.data == {
            "jobs": [],
            "snapshots": [],
            "versions": [],
            "schedules": [],
            "conversations": [],
        }
