"""Tests for per-organization data isolation (workspaces)."""

import json
from pathlib import Path

import pytest

from zfrog.config import settings
from zfrog.diff import url_slug
from zfrog.utils.audit import AuditLog
from zfrog.versioning import VersionStore
from zfrog.workspaces import (
    DIRECTORY_NAMES,
    Workspace,
    WorkspaceManager,
    get_workspace,
    scoped,
    slug_org,
    store_paths,
)

URL = "https://example.com"

SCOPED_FIELDS = (
    "output_dir",
    "versions_dir",
    "schedules_file",
    "marketplace_dir",
    "integrations_dir",
    "search_db",
    "metrics_db",
    "audit_log",
    "sessions_dir",
    "sessions_key_file",
    "annotations_dir",
    "domain_profiles_dir",
)


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Nenhum teste toca o output/, audit.log, users.json ou orgs.json reais do repositório."""
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(settings, "audit_log", tmp_path / "audit.log")
    monkeypatch.setattr(settings, "users_file", tmp_path / "users.json")
    monkeypatch.setattr(settings, "orgs_file", tmp_path / "orgs.json")
    return tmp_path


@pytest.fixture
def manager() -> WorkspaceManager:
    return WorkspaceManager()


def _snapshot(tmp_path: Path, name: str = "snap.json") -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "url": URL,
                "captured_at": "2026-09-24T03:10:27Z",
                "engine": "wget",
                "pages": [{"path": "index.html", "sha256": "a" * 64}],
            }
        ),
        encoding="utf-8",
    )
    return path


# ── layout ──


def test_for_org_creates_the_tree(tmp_path, manager):
    workspace = manager.for_org("Acme Corp")

    assert workspace.org == "Acme Corp"
    assert workspace.slug == "acme-corp"
    assert workspace.root == tmp_path / "output" / "orgs" / "acme-corp"
    assert workspace.root.is_dir()

    for name in DIRECTORY_NAMES:
        assert (workspace.root / name).is_dir(), name

    assert manager.list() == ["acme-corp"]
    assert manager.exists("Acme Corp") is True
    assert manager.exists("Outra Org") is False


def test_properties_match_the_documented_layout(manager):
    workspace = manager.for_org("acme-corp")

    assert workspace.output_dir == workspace.root / "output"
    assert workspace.versions_dir == workspace.root / "versions"
    assert workspace.schedules_file == workspace.root / "schedules.json"
    assert workspace.workflows_dir == workspace.root / "workflows"
    assert workspace.marketplace_dir == workspace.root / "marketplace"
    assert workspace.integrations_dir == workspace.root / "integrations"
    assert workspace.search_db == workspace.root / "search.db"
    assert workspace.metrics_db == workspace.root / "metrics.db"
    assert workspace.audit_log == workspace.root / "audit.log"
    assert workspace.multisite_dir == workspace.root / ".rag-multi"
    assert workspace.chats_dir == workspace.root / "chats"
    assert workspace.sessions_dir == workspace.root / "sessions"
    assert workspace.annotations_dir == workspace.root / "annotations"
    assert workspace.domains_dir == workspace.root / "domains"


def test_every_data_path_is_inside_the_root_and_identity_is_not(manager):
    workspace = manager.for_org("Acme Corp")
    data = workspace.data_paths()

    # Compare against the module's own list instead of a hand-copied one: the
    # point of this test is that every declared data path lives under root, not
    # that the list has a particular length.
    from zfrog.workspaces import _DATA_PROPERTIES

    assert set(data) == set(_DATA_PROPERTIES)
    assert "analysis_dir" in data and "finetune_dir" in data
    for name, path in data.items():
        assert workspace.root in path.parents, name

    # Identity is global: a user belongs to many orgs, so its files never live in one.
    assert workspace.users_file == settings.users_file
    assert workspace.orgs_file == settings.orgs_file
    for shared in (workspace.users_file, workspace.orgs_file):
        with pytest.raises(ValueError):
            shared.relative_to(workspace.root)


def test_two_orgs_are_disjoint(tmp_path, manager):
    first = manager.for_org("Acme Corp")
    second = manager.for_org("Globex")

    assert first.root != second.root
    assert first.root.is_dir() and second.root.is_dir()
    with pytest.raises(ValueError):
        first.root.relative_to(second.root)
    with pytest.raises(ValueError):
        second.root.relative_to(first.root)

    (first.output_dir / "index.html").write_text("<html>acme</html>", encoding="utf-8")
    assert (first.output_dir / "index.html").is_file()
    assert not (second.output_dir / "index.html").exists()

    AuditLog(path=first.audit_log).write("org.test", actor="acme", target="job-1")
    assert AuditLog(path=second.audit_log).count() == 0
    assert AuditLog(path=first.audit_log).count() == 1

    assert manager.list() == ["acme-corp", "globex"]


# ── slug ──


def test_slug_org_normalises_names():
    assert slug_org("Acme Corp") == "acme-corp"
    assert slug_org("  ACME   Corp!!  ") == "acme-corp"
    assert slug_org("globex") == "globex"


def test_slug_org_falls_back_to_the_default_org(monkeypatch):
    monkeypatch.setattr(settings, "default_org", "acme")
    assert slug_org("") == "acme"
    assert slug_org("   ") == "acme"


def test_slug_org_rejects_traversal():
    for evil in ("../..", "../../etc/passwd", "..", "a/b", "a\\b", "org\x00name"):
        with pytest.raises(ValueError):
            slug_org(evil)


def test_manager_refuses_traversal_instead_of_escaping(tmp_path, manager):
    manager.for_org("Acme Corp")

    for evil in ("../..", "../../etc/passwd"):
        with pytest.raises(ValueError):
            manager.for_org(evil)
        with pytest.raises(ValueError):
            manager.exists(evil)
        with pytest.raises(ValueError):
            manager.remove(evil)

    # Nothing was created outside the orgs/ directory, and nothing was deleted.
    assert manager.list() == ["acme-corp"]
    assert manager.exists("Acme Corp") is True
    assert not list(tmp_path.rglob("etc"))
    assert not list(tmp_path.rglob("passwd"))


# ── lifecycle ──


def test_manager_list_ignores_files_and_unknown_names(tmp_path, manager):
    manager.for_org("Acme Corp")
    manager.for_org("Globex")
    stray = manager.orgs_dir / "not-a-dir.txt"
    stray.write_text("oi", encoding="utf-8")
    (manager.orgs_dir / "Outra").mkdir()

    assert manager.list() == ["acme-corp", "globex"]


def test_remove_deletes_the_org_tree_only(tmp_path, manager):
    first = manager.for_org("Acme Corp")
    second = manager.for_org("Globex")
    settings.users_file.write_text(json.dumps({"users": ["ana"]}), encoding="utf-8")
    settings.orgs_file.write_text(json.dumps({"orgs": ["acme-corp"]}), encoding="utf-8")

    assert manager.remove("Acme Corp") is True

    assert not first.root.exists()
    assert second.root.is_dir()
    assert manager.exists("acme-corp") is False
    assert manager.list() == ["globex"]
    assert manager.remove("Acme Corp") is False

    # Identity survives: it is shared, not part of the org tree.
    assert json.loads(settings.users_file.read_text(encoding="utf-8")) == {"users": ["ana"]}
    assert json.loads(settings.orgs_file.read_text(encoding="utf-8")) == {"orgs": ["acme-corp"]}


def test_remove_refuses_when_identity_lives_inside_the_tree(tmp_path, manager, monkeypatch):
    workspace = manager.for_org("Acme Corp")
    monkeypatch.setattr(settings, "users_file", workspace.root / "users.json")
    (workspace.root / "users.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError):
        manager.remove("Acme Corp")
    assert workspace.root.is_dir()
    assert (workspace.root / "users.json").is_file()


def test_get_workspace_defaults_to_the_default_org(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "default_org", "acme")

    assert get_workspace().root == tmp_path / "output" / "orgs" / "acme"
    assert get_workspace().root.is_dir()
    assert get_workspace("").slug == "acme"
    assert get_workspace("Globex Inc").root == tmp_path / "output" / "orgs" / "globex-inc"


# ── store wiring ──


def test_store_paths_names_the_argument_each_store_needs(manager):
    workspace = manager.for_org("Acme Corp")
    paths = store_paths(workspace)

    assert paths == {
        "VersionStore": {"root": workspace.versions_dir},
        "ScheduleStore": {"path": workspace.schedules_file},
        "WorkflowStore": {"root": workspace.workflows_dir},
        "Marketplace": {"root": workspace.marketplace_dir},
        "DestinationStore": {"root": workspace.integrations_dir},
        "SearchIndex": {"db_path": workspace.search_db},
        "MetricsStore": {"db_path": workspace.metrics_db},
        "AuditLog": {"path": workspace.audit_log},
        "MultiSiteIndex": {"root": workspace.multisite_dir},
        "ChatSession": {"history_dir": workspace.chats_dir},
        "SessionStore": {"root": workspace.sessions_dir},
        "AnnotationStore": {"root": workspace.annotations_dir},
        "DomainProfileStore": {"root": workspace.domains_dir},
    }


def test_store_paths_wire_real_stores_inside_the_workspace(tmp_path, manager):
    workspace = manager.for_org("Acme Corp")
    other = manager.for_org("Globex")
    paths = store_paths(workspace)

    job = tmp_path / "job"
    job.mkdir()
    (job / "index.html").write_text("<html>v1</html>", encoding="utf-8")

    history = VersionStore(**paths["VersionStore"])
    version = history.commit(URL, _snapshot(tmp_path), job, message="primeiro")

    assert history.root == workspace.versions_dir
    assert [entry.id for entry in history.log(URL)] == [version.id]
    assert (workspace.versions_dir / url_slug(URL) / "refs.json").is_file()
    assert not (other.versions_dir / url_slug(URL)).exists()

    audit = AuditLog(**paths["AuditLog"])
    audit.write("workspace.test", actor="acme", target="job-1")
    assert audit.count() == 1
    assert workspace.audit_log.is_file()
    assert not other.audit_log.exists()
    assert not Path(settings.audit_log).exists()


# ── scoped ──


def test_scoped_points_settings_at_the_workspace_and_restores(manager):
    workspace = manager.for_org("Acme Corp")
    before = {name: getattr(settings, name) for name in SCOPED_FIELDS}

    with scoped(workspace) as current:
        assert current is workspace
        assert settings.output_dir == workspace.output_dir
        assert settings.versions_dir == workspace.versions_dir
        assert settings.schedules_file == workspace.schedules_file
        assert settings.marketplace_dir == workspace.marketplace_dir
        assert settings.integrations_dir == workspace.integrations_dir
        assert settings.search_db == workspace.search_db
        assert settings.metrics_db == workspace.metrics_db
        assert settings.audit_log == workspace.audit_log
        assert settings.sessions_dir == workspace.sessions_dir
        assert settings.sessions_key_file == workspace.sessions_dir / ".key"
        assert settings.annotations_dir == workspace.annotations_dir
        assert settings.domain_profiles_dir == workspace.domains_dir

        # A default-constructed store now lands inside the workspace.
        AuditLog().write("scoped.test", actor="acme")
        assert workspace.audit_log.is_file()

    assert {name: getattr(settings, name) for name in SCOPED_FIELDS} == before
    assert not Path(settings.audit_log).exists()


def test_scoped_restores_after_an_exception(manager):
    workspace = manager.for_org("Acme Corp")
    before = {name: getattr(settings, name) for name in SCOPED_FIELDS}

    with pytest.raises(RuntimeError):
        with scoped(workspace):
            assert settings.output_dir == workspace.output_dir
            raise RuntimeError("falhou")

    assert {name: getattr(settings, name) for name in SCOPED_FIELDS} == before


def test_workspace_is_a_plain_dataclass(tmp_path):
    workspace = Workspace(org="Acme Corp", root=tmp_path / "acme")

    assert workspace.slug == "acme"
    assert workspace.root == tmp_path / "acme"
    assert workspace.users_file == settings.users_file
