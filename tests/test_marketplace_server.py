"""Tests for the hosted marketplace: the HTTP index server over a marketplace root."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from zfrog.config import settings
from zfrog.marketplace import Marketplace
from zfrog.marketplace_index import INDEX_VERSION, read_index, verify_entry
from zfrog.marketplace_server import SERVICE_NAME, create_app

SOURCE = "http://market.test/"

PLUGIN_SOURCE = '''
from zfrog.engines.base import EngineAdapter

class MarkerEngine(EngineAdapter):
    """Engine published by the tests."""

    name = "marker"

    async def execute(self, job, output_dir, on_progress=None):
        raise NotImplementedError

    def can_handle(self, probe) -> bool:
        return False
'''

BROKEN_PLUGIN_SOURCE = "class NotAnEngine:\n    name = 'nope'\n"

WORKFLOW_PAYLOAD = {
    "steps": [
        {"type": "probe", "params": {"url": "https://example.test"}},
        {"type": "commit", "params": {}},
    ]
}
TEMPLATE_PAYLOAD = {"selectors": {"title": "h1", "price": ".price"}}

def _workflow(name: str = "Sitemap Crawler") -> dict:
    """Return the request body publishing a workflow."""
    return {
        "kind": "workflow",
        "name": name,
        "payload": json.loads(json.dumps(WORKFLOW_PAYLOAD)),
        "description": "Rastreia sitemaps e envia as URLs novas",
        "author": "ana",
        "version": "1.0.0",
        "tags": ["seo", "crawl"],
    }

def _template(name: str = "Price Template") -> dict:
    """Return the request body publishing a template."""
    return {
        "kind": "template",
        "name": name,
        "payload": json.loads(json.dumps(TEMPLATE_PAYLOAD)),
        "description": "Seletores de preço",
        "author": "bruno",
        "tags": ["pricing"],
    }

def _plugin(name: str = "Marker Engine", source: str = PLUGIN_SOURCE) -> dict:
    """Return the request body publishing a plugin."""
    return {
        "kind": "plugin",
        "name": name,
        "payload": {"source": source},
        "description": "Motor de marcação",
        "author": "carla",
        "tags": ["engine"],
    }

@pytest.fixture
def store(tmp_path, monkeypatch):
    """A marketplace rooted in ``tmp_path``, with the dirs it installs into."""
    monkeypatch.setattr(settings, "marketplace_dir", tmp_path / "market")
    monkeypatch.setattr(settings, "plugins_dir", tmp_path / "plugins")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    return Marketplace(tmp_path / "market")

@pytest.fixture
def client(store):
    """A test client over the app serving ``store``."""
    with TestClient(create_app(marketplace=store, source=SOURCE)) as client:
        yield client

def test_root_and_health_report_the_service(client):
    """The root route describes the service and the health route answers."""
    empty = client.get("/")
    assert empty.status_code == 200
    assert empty.json() == {
        "service": SERVICE_NAME,
        "version": INDEX_VERSION,
        "count": 0,
        "source": SOURCE,
    }

    client.post("/assets", json=_workflow())
    assert client.get("/").json()["count"] == 1
    assert client.get("/health").json() == {"status": "ok"}

def test_published_assets_are_listed_and_filtered(client):
    """POST stores the item, and /assets filters it by kind and by text."""
    workflow = client.post("/assets", json=_workflow())
    assert workflow.status_code == 200
    entry = workflow.json()
    assert entry["id"] == "workflow-sitemap-crawler"
    assert entry["checksum"]
    assert entry["tags"] == ["seo", "crawl"]

    template = client.post("/assets", json=_template())
    assert template.status_code == 200
    assert template.json()["id"] == "template-price-template"

    listed = client.get("/assets")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [
        "template-price-template",
        "workflow-sitemap-crawler",
    ]

    only_workflows = client.get("/assets", params={"kind": "workflow"}).json()
    assert [item["id"] for item in only_workflows] == ["workflow-sitemap-crawler"]

    by_tag = client.get("/assets", params={"query": "SEo"}).json()
    assert [item["id"] for item in by_tag] == ["workflow-sitemap-crawler"]

    by_description = client.get("/assets", params={"query": "preço"}).json()
    assert [item["id"] for item in by_description] == ["template-price-template"]

    both = client.get("/assets", params={"kind": "workflow", "query": "pricing"}).json()
    assert both == []

    missing = client.get("/assets", params={"kind": "engine"}).json()
    assert missing == []

def test_one_asset_and_its_payload_are_served(client):
    """GET /assets/{id} serves the entry and its payload route the payload."""
    entry = client.post("/assets", json=_workflow()).json()
    asset_id = entry["id"]

    single = client.get(f"/assets/{asset_id}")
    assert single.status_code == 200
    assert single.json() == entry

    payload = client.get(f"/assets/{asset_id}/payload")
    assert payload.status_code == 200
    assert payload.json() == WORKFLOW_PAYLOAD

    assert client.get("/assets/nope").status_code == 404
    assert client.get("/assets/nope/payload").status_code == 404

def test_an_invalid_payload_is_refused_and_not_listed(client):
    """A plugin without an engine is a 400 and never enters the marketplace."""
    refused = client.post("/assets", json=_plugin(source=BROKEN_PLUGIN_SOURCE))
    assert refused.status_code == 400
    assert "EngineAdapter" in refused.json()["detail"]
    assert client.get("/assets").json() == []
    assert client.get("/assets/plugin-marker-engine").status_code == 404

    unknown_kind = client.post("/assets", json=_workflow() | {"kind": "engine"})
    assert unknown_kind.status_code == 400

    no_payload = client.post("/assets", json={"kind": "workflow", "name": "Sem payload"})
    assert no_payload.status_code == 400

def test_delete_removes_the_asset(client):
    """DELETE takes the item out of the index and 404s the second time."""
    entry = client.post("/assets", json=_template()).json()
    asset_id = entry["id"]
    assert client.get(f"/assets/{asset_id}").status_code == 200

    removed = client.delete(f"/assets/{asset_id}")
    assert removed.status_code == 200
    assert removed.json() == {"id": asset_id, "removed": True}
    assert client.get(f"/assets/{asset_id}").status_code == 404
    assert client.get("/assets").json() == []
    assert client.get("/index.json").json()["count"] == 0

    assert client.delete(f"/assets/{asset_id}").status_code == 404

def test_verify_detects_a_payload_changed_behind_the_server(store, client):
    """The advertised checksum stays put, so drift on disk is reported."""
    entry = client.post("/assets", json=_workflow()).json()
    asset_id = entry["id"]

    fresh = client.get(f"/verify/{asset_id}")
    assert fresh.status_code == 200
    assert fresh.json() == {
        "id": asset_id,
        "checksum": entry["checksum"],
        "valid": True,
    }

    path = store.root / "workflows" / f"{asset_id}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["payload"]["steps"].append({"type": "commit", "params": {"note": "injetado"}})
    path.write_text(json.dumps(document), encoding="utf-8")

    tampered = client.get(f"/verify/{asset_id}")
    assert tampered.status_code == 200
    assert tampered.json()["valid"] is False
    assert tampered.json()["checksum"] == entry["checksum"]

    path.unlink()
    assert client.get(f"/verify/{asset_id}").json()["valid"] is False
    assert client.get("/verify/nope").status_code == 404

def test_writes_need_the_token_but_reads_do_not(store):
    """With a token configured, every write must present it as a bearer token."""
    app = create_app(marketplace=store, source=SOURCE, require_token="s3cret")
    with TestClient(app) as client:
        body = _template()
        assert client.get("/assets").status_code == 200
        assert client.get("/index.json").status_code == 200

        assert client.post("/assets", json=body).status_code == 401
        no_scheme = client.post("/assets", json=body, headers={"Authorization": "nope"})
        assert no_scheme.status_code == 401
        wrong = client.post("/assets", json=body, headers={"Authorization": "Bearer outro"})
        assert wrong.status_code == 401
        scheme = client.post("/assets", json=body, headers={"Authorization": "Token s3cret"})
        assert scheme.status_code == 401

        allowed = client.post(
            "/assets", json=body, headers={"Authorization": "Bearer s3cret"}
        )
        assert allowed.status_code == 200
        assert client.get("/assets").status_code == 200

        asset_id = allowed.json()["id"]
        assert client.delete(f"/assets/{asset_id}").status_code == 401
        deleted = client.delete(
            f"/assets/{asset_id}", headers={"Authorization": "Bearer s3cret"}
        )
        assert deleted.status_code == 200

def test_index_json_is_a_valid_index(store, client):
    """The served index parses back with read_index and describes the items."""
    client.post("/assets", json=_template())
    client.post("/assets", json=_workflow())

    document = client.get("/index.json").json()
    path = store.root.parent / "served-index.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    parsed = read_index(path)

    assert parsed["version"] == INDEX_VERSION == 1
    assert parsed["source"] == SOURCE
    assert parsed["count"] == len(parsed["assets"]) == 2
    ids = [entry["id"] for entry in parsed["assets"]]
    assert ids == sorted(ids)
    for entry in parsed["assets"]:
        assert entry["checksum"]
        assert entry["published_at"]
        assert verify_entry(entry, store.get(entry["id"])) is True

    assert client.get("/index.json").json() == document

def test_serve_starts_a_real_server(tmp_path):
    """`serve` really runs an ASGI server that answers over the network."""
    port = _free_port()
    root = tmp_path / "market"
    script = tmp_path / "run_marketplace.py"
    script.write_text(
        "from zfrog.marketplace import Marketplace\n"
        "from zfrog.marketplace_server import serve\n"
        f"serve(host='127.0.0.1', port={port}, marketplace=Marketplace({str(root)!r}),"
        f" source={SOURCE!r})\n",
        encoding="utf-8",
    )

    log = (tmp_path / "server.log").open("w", encoding="utf-8", buffering=1)
    process = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        response = _wait_for_health(port, process, log)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        root_route = httpx.get(f"http://127.0.0.1:{port}/", timeout=5.0).json()
        assert root_route == {
            "service": SERVICE_NAME,
            "version": INDEX_VERSION,
            "count": 0,
            "source": SOURCE,
        }
        assert httpx.get(f"http://127.0.0.1:{port}/assets", timeout=5.0).json() == []
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
        log.close()

def _free_port() -> int:
    """Return a port nothing is listening on right now."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])

def _wait_for_health(port: int, process: subprocess.Popen, log) -> httpx.Response:
    """Poll the health route of a server started in a subprocess."""
    deadline = time.monotonic() + 30.0
    last: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log.flush()
            raise AssertionError(f"o servidor terminou cedo: {log.name}")
        try:
            return httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
        except httpx.HTTPError as exc:
            last = exc
            time.sleep(0.2)
    raise AssertionError(f"o servidor não respondeu a tempo: {last}")
