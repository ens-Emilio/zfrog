"""Organization isolation through the API.

The API key decides which organization a caller belongs to, and every store the
API writes is scoped to that organization's workspace. These tests pin the two
things that could silently break it: the key's org being ignored, and a store
being constructed with its global default instead of the workspace path.
"""

import pytest
from fastapi.testclient import TestClient

from zfrog.api import app
from zfrog.auth import ApiKeyStore
from zfrog.config import settings


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Every store the API touches goes into tmp_path."""
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(settings, "api_keys_file", tmp_path / "keys.json")
    monkeypatch.setattr(settings, "audit_log", tmp_path / "audit.log")
    monkeypatch.setattr(settings, "users_file", tmp_path / "users.json")
    monkeypatch.setattr(settings, "orgs_file", tmp_path / "orgs.json")
    monkeypatch.setattr(settings, "annotations_dir", tmp_path / "annotations")
    monkeypatch.setattr(settings, "schedules_file", tmp_path / "schedules.json")
    return tmp_path


def _keys():
    acme, _ = ApiKeyStore().create("ana", "operator", org="acme")
    globex, _ = ApiKeyStore().create("bob", "operator", org="globex")
    return acme, globex


def _headers(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


def test_workspace_endpoint_reports_the_key_org():
    acme, globex = _keys()

    with TestClient(app) as client:
        first = client.get("/workspace", headers=_headers(acme)).json()
        second = client.get("/workspace", headers=_headers(globex)).json()

    assert first["org"] == "acme"
    assert second["org"] == "globex"
    assert first["root"] != second["root"]
    # Every path the API would use lives inside that org's root.
    for kwargs in first["paths"].values():
        for value in kwargs.values():
            assert value.startswith(first["root"])


def test_annotations_are_isolated_per_org():
    acme, globex = _keys()

    with TestClient(app) as client:
        created = client.post(
            "/annotations",
            json={"job_id": "job-1", "path": "index.html", "text": "nota da acme"},
            headers=_headers(acme),
        )
        assert created.status_code == 200

        assert len(client.get("/annotations", headers=_headers(acme)).json()) == 1
        # The other organization must not see it.
        assert client.get("/annotations", headers=_headers(globex)).json() == []


def test_schedules_and_workflows_are_isolated_per_org():
    acme, globex = _keys()

    with TestClient(app) as client:
        assert client.post(
            "/schedules",
            json={"cron": "0 2 * * *", "url": "https://example.com"},
            headers=_headers(acme),
        ).status_code == 200
        assert client.post(
            "/workflows",
            json={"name": "fluxo da acme", "steps": [{"type": "search", "params": {}}]},
            headers=_headers(acme),
        ).status_code == 200

        assert len(client.get("/schedules", headers=_headers(acme)).json()) == 1
        assert client.get("/schedules", headers=_headers(globex)).json() == []
        assert len(client.get("/workflows", headers=_headers(acme)).json()) == 1
        assert client.get("/workflows", headers=_headers(globex)).json() == []


def test_data_lands_on_disk_inside_the_org_tree(_isolated_state):
    acme, _ = _keys()
    root = _isolated_state / "output" / "orgs" / "acme"

    with TestClient(app) as client:
        client.post(
            "/annotations",
            json={"job_id": "job-1", "path": "index.html", "text": "x"},
            headers=_headers(acme),
        )

    assert (root / "annotations" / "job-1.json").is_file()


def test_key_without_org_uses_the_shared_area(_isolated_state):
    shared, _ = ApiKeyStore().create("sem org", "operator")

    with TestClient(app) as client:
        info = client.get("/workspace", headers=_headers(shared)).json()

    assert info["org"] is None
    assert info["shared"] is True
    assert info["output_dir"] == str(settings.output_dir)


def test_org_membership_updates_both_sides(tmp_path, monkeypatch):
    """Adding a member must show up on the user AND on the organization.

    Regression: `OrgStore.add_member` only recorded it on the organization, so
    the users list showed no organization for a member the org clearly had.
    """
    monkeypatch.setattr(settings, "users_file", tmp_path / "users.json")
    monkeypatch.setattr(settings, "orgs_file", tmp_path / "orgs.json")

    from zfrog.users import OrgStore, UserStore, add_member, remove_member

    user, _ = UserStore().create("ana@empresa.com", "Ana", "admin")
    OrgStore().create("Acme", user.id)

    add_member("acme", user.id, "operator")
    assert UserStore().get(user.id).orgs == ["acme"]
    assert OrgStore().get("acme").members[user.id] == "operator"

    remove_member("acme", user.id)
    assert UserStore().get(user.id).orgs == []
    assert OrgStore().get("acme").members == {}


def test_body_cannot_choose_the_organization():
    """A client must not be able to write into someone else's workspace."""
    acme, _ = _keys()

    with TestClient(app) as client:
        info = client.get("/workspace", headers=_headers(acme)).json()

    # Even if a body asks for another org, the key decides.
    with TestClient(app) as client:
        response = client.post(
            "/annotations",
            json={
                "job_id": "job-1",
                "path": "index.html",
                "text": "x",
                "org": "globex",
            },
            headers=_headers(acme),
        )

    assert response.status_code == 200
    assert info["org"] == "acme"
