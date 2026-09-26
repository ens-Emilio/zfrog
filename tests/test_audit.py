"""Tests for the append-only JSONL audit trail."""

from __future__ import annotations

import json
import logging
import stat
from datetime import datetime

import pytest

from zfrog.config import settings
from zfrog.utils.audit import AuditLog, audited, client_identity


@pytest.fixture(autouse=True)
def _isolated_audit(tmp_path, monkeypatch):
    """Every test writes its own audit file."""
    monkeypatch.setattr(settings, "audit_log", tmp_path / "audit.log")


def test_write_then_read_round_trips_every_field():
    log = AuditLog()

    written = log.write(
        action="job.create",
        actor="203.0.113.7",
        target="https://example.test/docs",
        outcome="ok",
        detail="trabalho criado",
        metadata={"job_id": "abc123", "nested": {"mode": "mirror", "tags": ["a", "b"]}},
    )

    entries = log.read()
    assert len(entries) == 1
    entry = entries[0]
    assert entry == written
    assert entry.action == "job.create"
    assert entry.actor == "203.0.113.7"
    assert entry.target == "https://example.test/docs"
    assert entry.outcome == "ok"
    assert entry.detail == "trabalho criado"
    assert entry.metadata == {"job_id": "abc123", "nested": {"mode": "mirror", "tags": ["a", "b"]}}
    assert datetime.fromisoformat(entry.timestamp).tzinfo is not None


def test_entries_are_appended_and_read_newest_first():
    log = AuditLog()
    log.write("job.create", target="one")
    log.write("job.delete", target="two")
    log.write("config.update", target="three")

    assert log.count() == 3
    entries = log.read()
    assert [entry.target for entry in entries] == ["three", "two", "one"]
    assert [entry.action for entry in entries] == ["config.update", "job.delete", "job.create"]


def test_file_holds_one_json_object_per_line():
    log = AuditLog()
    log.write("job.create", target="one")
    log.write("job.delete", target="two")

    lines = [line for line in settings.audit_log.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 2
    assert [json.loads(line)["target"] for line in lines] == ["one", "two"]


def test_read_filters_by_action_and_actor():
    log = AuditLog()
    log.write("job.create", actor="cli", target="one")
    log.write("job.create", actor="10.0.0.5", target="two")
    log.write("job.delete", actor="cli", target="three")

    assert [e.target for e in log.read(action="job.create")] == ["two", "one"]
    assert [e.target for e in log.read(actor="cli")] == ["three", "one"]
    assert [e.target for e in log.read(action="job.create", actor="cli")] == ["one"]
    assert log.read(action="nothing.happened") == []


def test_read_limit_returns_the_most_recent():
    log = AuditLog()
    for index in range(5):
        log.write("job.create", target=f"job-{index}")

    assert [e.target for e in log.read(limit=2)] == ["job-4", "job-3"]
    assert len(log.read(limit=100)) == 5
    assert log.read(limit=0) == []


def test_log_file_is_owner_only():
    AuditLog().write("job.create", target="one")

    assert stat.S_IMODE(settings.audit_log.stat().st_mode) == 0o600


def test_corrupt_line_is_skipped(caplog):
    log = AuditLog()
    log.write("job.create", target="one")
    log.write("job.delete", target="two")
    with open(settings.audit_log, "a", encoding="utf-8") as handle:
        handle.write("{ this is not json\n")
        handle.write('["also", "not", "an", "object"]\n')
    log.write("config.update", target="three")

    assert log.count() == 3  # the two bad lines are not counted

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="zfrog.utils.audit"):
        entries = log.read()

    assert [e.target for e in entries] == ["three", "two", "one"]
    assert [e.action for e in entries] == ["config.update", "job.delete", "job.create"]
    assert len(caplog.records) == 2  # one warning per corrupt line
    assert all(record.levelno == logging.WARNING for record in caplog.records)


def test_missing_file_reads_as_empty():
    log = AuditLog()

    assert log.read() == []
    assert log.count() == 0
    assert not settings.audit_log.exists()


def test_write_to_unwritable_path_logs_and_does_not_raise(tmp_path, caplog):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    log = AuditLog(blocker / "audit.log")

    with caplog.at_level(logging.WARNING, logger="zfrog.utils.audit"):
        entry = log.write("job.create", actor="cli", target="https://example.test")

    assert entry.action == "job.create"
    assert entry.outcome == "ok"
    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert str(blocker) in caplog.records[0].getMessage()


def test_client_identity_prefers_the_first_forwarded_hop():
    assert client_identity({"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}) == "203.0.113.7"
    assert client_identity({"x-forwarded-for": " 198.51.100.9 , 10.0.0.1"}) == "198.51.100.9"
    assert client_identity({"X-Forwarded-For": "203.0.113.7", "X-Real-IP": "198.51.100.4"}) == (
        "203.0.113.7"
    )


def test_client_identity_falls_back_through_real_ip_and_user_agent():
    assert client_identity({"X-Real-IP": "198.51.100.4"}) == "198.51.100.4"
    assert client_identity({"X-Forwarded-For": "   ", "X-Real-IP": "198.51.100.4"}) == "198.51.100.4"
    assert client_identity({"User-Agent": "curl/8.4.0"}) == "curl/8.4.0"
    assert client_identity({"user-agent": "curl/8.4.0"}) == "curl/8.4.0"


def test_client_identity_truncates_long_user_agent():
    identity = client_identity({"User-Agent": "Mozilla/5.0 " + "x" * 500})

    assert len(identity) == 80
    assert identity == ("Mozilla/5.0 " + "x" * 500)[:80]


def test_client_identity_never_returns_empty():
    assert client_identity() == "local"
    assert client_identity({}) == "local"
    assert client_identity({"X-Forwarded-For": "", "X-Real-IP": "", "User-Agent": ""}) == "local"
    assert client_identity({}, fallback="api") == "api"
    assert client_identity({}, fallback="   ") == "local"


def test_audited_writes_ok_on_success():
    with audited("job.create", actor="cli", target="job-1", metadata={"mode": "mirror"}):
        pass

    entries = AuditLog().read()
    assert len(entries) == 1
    assert entries[0].action == "job.create"
    assert entries[0].actor == "cli"
    assert entries[0].target == "job-1"
    assert entries[0].outcome == "ok"
    assert entries[0].detail == ""
    assert entries[0].metadata == {"mode": "mirror"}


def test_audited_writes_error_and_reraises():
    with pytest.raises(ValueError, match="boom"):
        with audited("job.delete", actor="10.0.0.5", target="job-1"):
            raise ValueError("boom")

    entries = AuditLog().read()
    assert len(entries) == 1
    assert entries[0].action == "job.delete"
    assert entries[0].outcome == "error"
    assert entries[0].detail == "boom"
    assert entries[0].actor == "10.0.0.5"


def test_audited_uses_the_given_log(tmp_path):
    log = AuditLog(tmp_path / "custom.log")

    with audited("job.create", target="job-9", log=log):
        pass

    assert not settings.audit_log.exists()
    assert [entry.target for entry in log.read()] == ["job-9"]
