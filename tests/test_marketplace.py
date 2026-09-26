"""Tests for the local asset marketplace (publish, install, rate, remote index)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
import respx

from zfrog.config import settings
from zfrog.engines.base import EngineAdapter
from zfrog.marketplace import Marketplace
from zfrog.workflows import WorkflowStore

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

WORKFLOW_PAYLOAD = {
    "steps": [
        {"type": "probe", "params": {"url": "https://example.test"}},
        {"type": "commit", "params": {}},
    ]
}
TEMPLATE_PAYLOAD = {"selectors": {"title": "h1", "price": ".price"}}

INDEX_URL = "https://market.test/index.json"

@pytest.fixture
def market(tmp_path, monkeypatch):
    """A marketplace plus the plugin/output directories it installs into."""
    monkeypatch.setattr(settings, "marketplace_dir", tmp_path / "market")
    monkeypatch.setattr(settings, "plugins_dir", tmp_path / "plugins")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    return Marketplace()

def _publish_three(market: Marketplace) -> tuple:
    """Publish one asset of each kind and return them in order."""
    workflow = market.publish(
        "workflow",
        "Sitemap Crawler",
        WORKFLOW_PAYLOAD,
        description="Rastreia sitemaps",
        author="ana",
        tags=["seo", "crawl"],
    )
    plugin = market.publish(
        "plugin",
        "Marker Engine",
        {"source": PLUGIN_SOURCE},
        description="Motor de teste",
        author="bruno",
        tags=["engine"],
    )
    template = market.publish(
        "template",
        "Loja",
        TEMPLATE_PAYLOAD,
        description="Preços de loja",
        author="carla",
        tags=["seo"],
    )
    return workflow, plugin, template

def _import_file(path: Path, module_name: str):
    """Import ``path`` as ``module_name`` and return the module."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module

# ── publish + list ──────────────────────────────────────────────────

def test_publish_writes_one_file_per_kind(market, tmp_path):
    workflow, plugin, template = _publish_three(market)

    assert workflow.id == "workflow-sitemap-crawler"
    assert plugin.id == "plugin-marker-engine"
    assert template.id == "template-loja"
    assert (tmp_path / "market" / "workflows" / f"{workflow.id}.json").is_file()
    assert (tmp_path / "market" / "plugins" / f"{plugin.id}.json").is_file()
    assert (tmp_path / "market" / "templates" / f"{template.id}.json").is_file()

    stored = json.loads(
        (tmp_path / "market" / "workflows" / f"{workflow.id}.json").read_text(encoding="utf-8")
    )
    assert stored["payload"] == WORKFLOW_PAYLOAD
    assert stored["installs"] == 0
    assert stored["rating_count"] == 0

def test_list_returns_every_asset_and_filters(market):
    _publish_three(market)

    assert len(market.list()) == 3
    assert [a.id for a in market.list(kind="plugin")] == ["plugin-marker-engine"]
    assert {a.id for a in market.list(tag="seo")} == {
        "workflow-sitemap-crawler",
        "template-loja",
    }
    assert {a.id for a in market.list(tag="SEO")} == {
        "workflow-sitemap-crawler",
        "template-loja",
    }
    assert [a.id for a in market.list(query="sitemap")] == ["workflow-sitemap-crawler"]
    assert [a.id for a in market.list(query="motor de teste")] == ["plugin-marker-engine"]
    assert market.list(query="nada-a-ver") == []
    assert market.list(kind="template", tag="seo", query="loja")[0].name == "Loja"

def test_list_sorts_by_rating(market):
    low = market.publish("template", "Um", TEMPLATE_PAYLOAD)
    high = market.publish("template", "Dois", TEMPLATE_PAYLOAD)
    market.rate(low.id, 2)
    market.rate(high.id, 5)

    assert [a.id for a in market.list()] == [high.id, low.id]

def test_list_sorts_by_installs_when_ratings_match(market):
    first = market.publish("template", "Um", TEMPLATE_PAYLOAD)
    second = market.publish("template", "Dois", TEMPLATE_PAYLOAD)
    market.rate(first.id, 4)
    market.rate(second.id, 4)
    market.install(first.id)
    market.install(first.id)
    market.install(second.id)

    assert market.get(first.id).rating == market.get(second.id).rating
    assert [a.id for a in market.list()] == [first.id, second.id]

def test_get_unknown_returns_none(market):
    _publish_three(market)
    assert market.get("template-inexistente") is None
    assert market.get("") is None

def test_publish_unknown_kind_raises(market):
    with pytest.raises(ValueError):
        market.publish("extension", "Coisa", {"source": "x = 1"})

def test_publish_without_name_raises(market):
    with pytest.raises(ValueError):
        market.publish("template", "   ", TEMPLATE_PAYLOAD)

@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("workflow", {"steps": []}),
        ("workflow", {"name": "sem passos"}),
        ("workflow", {"steps": [{"type": "teleport", "params": {}}]}),
        ("plugin", {"source": ""}),
        ("plugin", {"source": "valor = 1\n"}),
        ("template", {"selectors": {}}),
        ("template", {"nome": "sem selectors"}),
        ("template", {"selectors": {"titulo": "   "}}),
    ],
)
def test_publish_rejects_invalid_payloads(market, kind, payload):
    with pytest.raises(ValueError):
        market.publish(kind, "Quebrado", payload)

    assert market.list() == []

def test_publish_rejects_plugin_that_raises_on_import(market):
    with pytest.raises(ValueError):
        market.publish("plugin", "Explosivo", {"source": 'raise RuntimeError("boom")\n'})

def test_publish_rejects_plugin_with_syntax_error(market):
    with pytest.raises(ValueError):
        market.publish("plugin", "Torto", {"source": "def broken(:\n"})

def test_publish_rejects_payload_that_is_not_json(market):
    with pytest.raises(ValueError):
        market.publish("template", "Binário", {"selectors": {"a": "b"}, "raw": object()})

def test_republish_same_payload_keeps_id_and_stats(market):
    first = market.publish("template", "Loja", TEMPLATE_PAYLOAD)
    market.rate(first.id, 5)
    market.install(first.id)

    again = market.publish("template", "Loja", TEMPLATE_PAYLOAD)

    assert again.id == first.id
    assert again.installs == 1
    assert again.rating == 5.0
    assert again.rating_count == 1
    assert len(market.list()) == 1

def test_republish_different_payload_needs_new_version(market):
    first = market.publish("template", "Loja", TEMPLATE_PAYLOAD)

    with pytest.raises(ValueError):
        market.publish("template", "Loja", {"selectors": {"title": "h2"}})

    replaced = market.publish(
        "template", "Loja", {"selectors": {"title": "h2"}}, version="2.0.0"
    )
    assert replaced.id == first.id
    assert replaced.version == "2.0.0"
    assert market.get(first.id).payload == {"selectors": {"title": "h2"}}

# ── install / uninstall ─────────────────────────────────────────────

def test_install_workflow_creates_it_in_the_store(market):
    asset = market.publish("workflow", "Sitemap Crawler", WORKFLOW_PAYLOAD)

    first = market.install(asset.id)

    assert first["kind"] == "workflow"
    assert first["name"] == "Sitemap Crawler"
    assert first["installed"] is True
    assert first["detail"]
    stored = WorkflowStore().get(first["target"])
    assert stored is not None
    assert stored.name == "Sitemap Crawler"
    assert [step.type for step in stored.steps] == ["probe", "commit"]

    second = market.install(asset.id)
    assert second["installed"] is True
    assert second["target"] == first["target"]

def test_install_plugin_writes_an_importable_module(market, tmp_path):
    asset = market.publish("plugin", "Marker Engine", {"source": PLUGIN_SOURCE})

    result = market.install(asset.id)

    path = tmp_path / "plugins" / f"{asset.id}.py"
    assert result["installed"] is True
    assert result["target"] == str(path)
    assert path.read_text(encoding="utf-8") == PLUGIN_SOURCE

    module = _import_file(path, "test_marketplace_plugin_under_test")
    assert issubclass(module.MarkerEngine, EngineAdapter)
    assert module.MarkerEngine.name == "marker"

def test_install_template_writes_json_under_output(market, tmp_path):
    asset = market.publish("template", "Loja", TEMPLATE_PAYLOAD)

    result = market.install(asset.id)

    path = tmp_path / "output" / "templates" / f"{asset.id}.json"
    assert result["installed"] is True
    assert path.is_file()
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["selectors"] == TEMPLATE_PAYLOAD["selectors"]
    assert document["name"] == "Loja"
    assert document["id"] == asset.id

def test_install_increments_installs_on_disk(market):
    asset = market.publish("template", "Loja", TEMPLATE_PAYLOAD)

    market.install(asset.id)
    market.install(asset.id)

    assert market.get(asset.id).installs == 2
    assert Marketplace().get(asset.id).installs == 2

def test_install_unknown_asset_raises(market):
    with pytest.raises(ValueError):
        market.install("template-fantasma")

def test_uninstall_plugin_removes_file_but_keeps_asset(market, tmp_path):
    asset = market.publish("plugin", "Marker Engine", {"source": PLUGIN_SOURCE})
    market.install(asset.id)
    path = tmp_path / "plugins" / f"{asset.id}.py"
    assert path.is_file()

    assert market.uninstall(asset.id) is True

    assert not path.exists()
    assert market.get(asset.id) is not None
    assert market.uninstall(asset.id) is False

def test_uninstall_workflow_removes_it_from_the_store(market):
    asset = market.publish("workflow", "Sitemap Crawler", WORKFLOW_PAYLOAD)
    workflow_id = market.install(asset.id)["target"]

    assert market.uninstall(asset.id) is True

    assert WorkflowStore().get(workflow_id) is None
    assert market.get(asset.id) is not None

def test_uninstall_template_removes_file_but_keeps_asset(market, tmp_path):
    asset = market.publish("template", "Loja", TEMPLATE_PAYLOAD)
    market.install(asset.id)
    path = tmp_path / "output" / "templates" / f"{asset.id}.json"

    assert market.uninstall(asset.id) is True

    assert not path.exists()
    assert market.get(asset.id) is not None

# ── rate / remove ───────────────────────────────────────────────────

def test_rate_keeps_a_running_average(market):
    asset = market.publish("template", "Loja", TEMPLATE_PAYLOAD)

    market.rate(asset.id, 5)
    market.rate(asset.id, 4)
    rated = market.rate(asset.id, 3)

    assert rated.rating_count == 3
    assert rated.rating == pytest.approx(4.0)
    assert Marketplace().get(asset.id).rating_count == 3
    assert Marketplace().get(asset.id).rating == pytest.approx(4.0)

@pytest.mark.parametrize("score", [-0.5, 5.5, 100, "dez", None])
def test_rate_rejects_invalid_scores(market, score):
    asset = market.publish("template", "Loja", TEMPLATE_PAYLOAD)

    with pytest.raises(ValueError):
        market.rate(asset.id, score)

    assert market.get(asset.id).rating_count == 0
    assert market.get(asset.id).rating == 0.0

def test_rate_unknown_asset_raises(market):
    with pytest.raises(ValueError):
        market.rate("template-fantasma", 4)

def test_remove_deletes_the_published_asset(market):
    asset = market.publish("template", "Loja", TEMPLATE_PAYLOAD)

    assert market.remove(asset.id) is True

    assert market.get(asset.id) is None
    assert market.list() == []
    assert market.remove(asset.id) is False

# ── remote index ────────────────────────────────────────────────────

def test_search_remote_parses_index():
    index = {
        "assets": [
            {
                "id": "workflow-sitemap",
                "kind": "workflow",
                "name": "Sitemap",
                "version": "1.2.0",
                "tags": ["seo"],
                "payload": WORKFLOW_PAYLOAD,
                "rating": 4.5,
                "rating_count": 2,
                "installs": 7,
            },
            {"kind": "template", "name": "Loja", "payload": TEMPLATE_PAYLOAD},
            {"kind": "template", "name": ""},
            {"kind": "", "name": "sem tipo"},
            "não é um item",
        ]
    }
    with respx.mock(assert_all_called=True) as mock:
        mock.get(INDEX_URL).mock(return_value=httpx.Response(200, json=index))
        assets = Marketplace().search_remote(INDEX_URL)

    assert [a.id for a in assets] == ["workflow-sitemap", "template-loja"]
    assert assets[0].rating == 4.5
    assert assets[0].installs == 7
    assert assets[0].payload == WORKFLOW_PAYLOAD
    assert assets[1].payload == TEMPLATE_PAYLOAD

def test_search_remote_accepts_a_bare_list():
    index = [{"kind": "plugin", "name": "Marker Engine", "payload": {"source": PLUGIN_SOURCE}}]
    with respx.mock(assert_all_called=True) as mock:
        mock.get(INDEX_URL).mock(return_value=httpx.Response(200, json=index))
        assets = Marketplace().search_remote(INDEX_URL)

    assert [a.id for a in assets] == ["plugin-marker-engine"]
    assert assets[0].kind == "plugin"

def test_search_remote_unreachable_index_returns_empty():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(INDEX_URL).mock(side_effect=httpx.ConnectError("sem rede"))
        assert Marketplace().search_remote(INDEX_URL) == []

def test_search_remote_broken_json_returns_empty():
    with respx.mock(assert_all_called=True) as mock:
        mock.get(INDEX_URL).mock(return_value=httpx.Response(200, text="<html>nada</html>"))
        assert Marketplace().search_remote(INDEX_URL) == []

def test_search_remote_requires_url(market):
    with pytest.raises(ValueError):
        market.search_remote("   ")
