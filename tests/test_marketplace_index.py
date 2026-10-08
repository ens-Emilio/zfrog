"""Tests for the marketplace index server half (build, verify, merge, fetch)."""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest
import respx

from zfrog.config import settings
from zfrog.marketplace import Marketplace
from zfrog.marketplace_index import (
    INDEX_VERSION,
    build_index,
    checksum_for,
    fetch_index,
    index_from_marketplace,
    index_summary,
    merge_index,
    read_index,
    verify_entry,
    write_index,
)

INDEX_URL = "https://market.test/index.json"

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

@pytest.fixture
def market(tmp_path, monkeypatch):
    """A marketplace rooted in ``tmp_path``, with the dirs it installs into."""
    monkeypatch.setattr(settings, "marketplace_dir", tmp_path / "market")
    monkeypatch.setattr(settings, "plugins_dir", tmp_path / "plugins")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    return Marketplace()

def _publish_three(store: Marketplace) -> list:
    """Publish one asset of each kind and return them in order."""
    workflow = store.publish(
        "workflow",
        "Sitemap Crawler",
        WORKFLOW_PAYLOAD,
        description="Rastreia sitemaps",
        author="ana",
        tags=["seo", "crawl"],
    )
    plugin = store.publish(
        "plugin",
        "Marker Engine",
        {"source": PLUGIN_SOURCE},
        description="Motor de teste",
        author="bruno",
        tags=["engine"],
    )
    template = store.publish(
        "template",
        "Loja",
        TEMPLATE_PAYLOAD,
        description="Preços de loja",
        author="carla",
        tags=["seo"],
    )
    return [workflow, plugin, template]

def _entry(**overrides) -> dict:
    """Return one index item with sensible defaults."""
    entry = {
        "id": "template-loja",
        "kind": "template",
        "name": "Loja",
        "version": "1.0.0",
        "payload": TEMPLATE_PAYLOAD,
    }
    entry.update(overrides)
    return entry

# ── checksums ───────────────────────────────────────────────────────

def test_checksum_is_deterministic_and_follows_the_payload(market):
    asset = market.publish("template", "Loja", TEMPLATE_PAYLOAD)

    first = checksum_for(asset)

    assert first == checksum_for(asset) == checksum_for(market.get(asset.id))
    assert len(first) == 64
    # canonical: the key order of the payload does not matter
    assert checksum_for(_entry(payload={"selectors": {"price": ".price", "title": "h1"}})) == first

    replaced = market.publish(
        "template", "Loja", {"selectors": {"title": "h2"}}, version="2.0.0"
    )
    assert checksum_for(replaced) != first
    assert checksum_for(_entry(version="2.0.0")) != first

def test_verify_entry_matches_and_detects_tampering(market):
    asset = market.publish("template", "Loja", TEMPLATE_PAYLOAD)
    entry = build_index([asset])["assets"][0]

    assert verify_entry(entry, asset) is True
    assert verify_entry(entry, market.get(asset.id)) is True

    # the index advertises another payload, so the installed asset no longer matches
    advertised = build_index([_entry(payload={"selectors": {"title": "h2"}})])["assets"][0]
    assert verify_entry(advertised, asset) is False

    # the installed asset changed under our feet
    other = market.publish("template", "Outra", {"selectors": {"title": "x"}})
    assert verify_entry(entry, other) is False

    # a wrong or missing checksum is never a match
    assert verify_entry({**entry, "checksum": "0" * 64}, asset) is False
    assert verify_entry({"id": entry["id"], "kind": "template", "name": "Loja"}, asset) is False

# ── building ────────────────────────────────────────────────────────

def test_index_from_marketplace_lists_every_asset_sorted(market):
    workflow, plugin, template = _publish_three(market)

    index = index_from_marketplace(market, source=INDEX_URL)

    assert index["version"] == INDEX_VERSION
    assert index["count"] == 3
    assert index["source"] == INDEX_URL
    assert datetime.fromisoformat(index["generated_at"])
    ids = [entry["id"] for entry in index["assets"]]
    assert ids == sorted([workflow.id, plugin.id, template.id])

    by_id = {entry["id"]: entry for entry in index["assets"]}
    assert by_id[template.id]["payload"] == TEMPLATE_PAYLOAD
    assert by_id[template.id]["checksum"] == checksum_for(template)
    assert by_id[template.id]["author"] == "carla"
    assert by_id[workflow.id]["tags"] == ["seo", "crawl"]
    assert by_id[plugin.id]["kind"] == "plugin"

def test_index_from_marketplace_defaults_to_the_configured_directory(market):
    _publish_three(market)

    index = index_from_marketplace()

    assert index["count"] == 3
    assert index["source"] == ""

def test_build_index_on_an_empty_list_is_valid(tmp_path):
    index = build_index([])

    assert index["version"] == INDEX_VERSION
    assert index["count"] == 0
    assert index["assets"] == []
    assert read_index(write_index(tmp_path / "public" / "index.json", index)) == index

# ── files ───────────────────────────────────────────────────────────

def test_write_and_read_index_round_trip(market, tmp_path):
    market.publish("template", "Loja", TEMPLATE_PAYLOAD, description="Preços e ações")
    index = index_from_marketplace(market, source="índice local")

    path = write_index(tmp_path / "public" / "index.json", index)

    assert path.is_file()
    raw = path.read_text(encoding="utf-8")
    assert "Preços e ações" in raw
    assert json.loads(raw) == index
    assert read_index(path) == index

@pytest.mark.parametrize(
    "document",
    [
        {"version": 2, "assets": []},
        {"version": 1},
        {"version": 1, "assets": {}},
        {"assets": []},
        [{"kind": "template", "name": "Loja"}],
    ],
)
def test_read_index_rejects_bad_documents(tmp_path, document):
    path = tmp_path / "index.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError):
        read_index(path)

def test_read_index_rejects_a_corrupt_file(tmp_path):
    path = tmp_path / "index.json"
    path.write_text('{"version": 1, "assets": [', encoding="utf-8")

    with pytest.raises(ValueError):
        read_index(path)

def test_read_index_rejects_a_missing_file(tmp_path):
    with pytest.raises(ValueError):
        read_index(tmp_path / "nao-existe.json")

# ── merging ─────────────────────────────────────────────────────────

def test_merge_index_adds_everything_then_reports_unchanged(market, tmp_path):
    source = Marketplace(root=tmp_path / "remote")
    _publish_three(source)
    index = index_from_marketplace(source, source=INDEX_URL)

    first = merge_index(index, market)

    assert (first.added, first.updated, first.unchanged, first.skipped) == (3, 0, 0, 0)
    assert first.errors == []
    assert first.total == 3
    assert sorted(asset.id for asset in market.list()) == sorted(
        asset.id for asset in source.list()
    )
    assert {asset.id: asset.payload for asset in market.list()} == {
        asset.id: asset.payload for asset in source.list()
    }

    files = sorted((tmp_path / "market").glob("*/*.json"))
    assert len(files) == 3
    stamps = {path: path.stat().st_mtime_ns for path in files}
    contents = {path: path.read_text(encoding="utf-8") for path in files}

    second = merge_index(index, market)

    assert (second.added, second.updated, second.unchanged, second.skipped) == (0, 0, 3, 0)
    assert second.errors == []
    assert {path: path.stat().st_mtime_ns for path in files} == stamps
    assert {path: path.read_text(encoding="utf-8") for path in files} == contents

def test_merge_index_defaults_to_the_configured_marketplace(market, tmp_path):
    source = Marketplace(root=tmp_path / "remote")
    source.publish("template", "Loja", TEMPLATE_PAYLOAD)

    result = merge_index(index_from_marketplace(source))

    assert (result.added, result.skipped) == (1, 0)
    assert Marketplace().get("template-loja").payload == TEMPLATE_PAYLOAD

def test_merge_index_updates_a_changed_payload(market):
    local = market.publish("template", "Loja", TEMPLATE_PAYLOAD)
    market.install(local.id)
    market.rate(local.id, 5)
    new_payload = {"selectors": {"title": "h2"}}
    index = build_index(
        [_entry(version="2.0.0", payload=new_payload)], source=INDEX_URL
    )

    result = merge_index(index, market)

    assert (result.updated, result.added, result.skipped, result.errors) == (1, 0, 0, [])
    updated = market.get(local.id)
    assert updated.payload == new_payload
    assert updated.version == "2.0.0"
    assert updated.installs == 1
    assert updated.rating == 5.0
    assert verify_entry(index["assets"][0], updated) is True

def test_merge_index_replaces_a_changed_payload_kept_at_the_same_version(market):
    local = market.publish("template", "Loja", TEMPLATE_PAYLOAD)
    new_payload = {"selectors": {"title": "h2"}}
    index = build_index([_entry(payload=new_payload)], source=INDEX_URL)

    result = merge_index(index, market)

    assert (result.updated, result.skipped, result.errors) == (1, 0, [])
    updated = market.get(local.id)
    assert updated.payload == new_payload
    assert updated.version == "1.0.0"
    assert verify_entry(index["assets"][0], updated) is True

def test_merge_index_skips_an_invalid_payload(market, tmp_path):
    index = build_index(
        [
            _entry(
                id="plugin-quebrado",
                kind="plugin",
                name="Quebrado",
                payload={"source": "valor = 1\n"},
            )
        ],
        source=INDEX_URL,
    )

    result = merge_index(index, market)

    assert (result.added, result.updated, result.unchanged, result.skipped) == (0, 0, 0, 1)
    assert len(result.errors) == 1
    assert "plugin-quebrado" in result.errors[0]
    assert "EngineAdapter" in result.errors[0]
    assert market.list() == []
    assert not (tmp_path / "market" / "plugins").exists()

def test_merge_index_never_touches_a_local_item_with_an_invalid_payload(market, tmp_path):
    local = market.publish("plugin", "Marker Engine", {"source": PLUGIN_SOURCE})
    path = tmp_path / "market" / "plugins" / f"{local.id}.json"
    before = path.read_text(encoding="utf-8")
    stamp = path.stat().st_mtime_ns
    index = build_index(
        [
            _entry(
                id=local.id,
                kind="plugin",
                name="Marker Engine",
                version="2.0.0",
                payload={"source": "valor = 1\n"},
            )
        ],
        source=INDEX_URL,
    )

    result = merge_index(index, market)

    assert result.skipped == 1
    assert result.errors and local.id in result.errors[0]
    assert path.read_text(encoding="utf-8") == before
    assert path.stat().st_mtime_ns == stamp
    assert market.get(local.id).payload == {"source": PLUGIN_SOURCE}

def test_merge_index_skips_an_item_whose_id_does_not_match(market, tmp_path):
    index = build_index([_entry(id="template-outro-nome")], source=INDEX_URL)

    result = merge_index(index, market)

    assert (result.added, result.skipped) == (0, 1)
    assert "template-outro-nome" in result.errors[0]
    assert market.list() == []
    assert not (tmp_path / "market" / "templates").exists()

def test_merge_index_skips_a_useless_item(market):
    index = build_index([_entry()], source=INDEX_URL)
    index["assets"].append({"kind": "template", "name": "Sem payload"})
    index["assets"].append("não é um item")
    index["count"] = 3

    result = merge_index(index, market)

    assert (result.added, result.skipped) == (1, 2)
    assert len(result.errors) == 2
    assert market.get("template-loja") is not None

def test_merge_index_trust_still_validates(market):
    index = build_index(
        [
            _entry(
                id="plugin-quebrado",
                kind="plugin",
                name="Quebrado",
                payload={"source": "valor = 1\n"},
            )
        ],
        source=INDEX_URL,
    )

    result = merge_index(index, market, trust=True)

    assert result.skipped == 1
    assert result.errors
    assert market.list() == []

def test_merge_index_rejects_a_bad_document(market):
    with pytest.raises(ValueError):
        merge_index({"version": 2, "assets": []}, market)

# ── fetching ────────────────────────────────────────────────────────

async def test_fetch_index_returns_the_parsed_document(market):
    _publish_three(market)
    index = index_from_marketplace(market, source=INDEX_URL)

    with respx.mock(assert_all_called=True) as mock:
        mock.get(INDEX_URL).mock(return_value=httpx.Response(200, json=index))
        fetched = await fetch_index(INDEX_URL)

    assert fetched == index
    assert fetched["assets"][0]["checksum"] == index["assets"][0]["checksum"]

async def test_fetch_index_uses_the_given_client(market):
    index = index_from_marketplace(market, source=INDEX_URL)

    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(INDEX_URL).mock(return_value=httpx.Response(200, json=index))
            fetched = await fetch_index(INDEX_URL, client=client)

        assert not client.is_closed

    assert fetched["count"] == 0

async def test_fetch_index_raises_for_an_unreachable_host():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(INDEX_URL).mock(side_effect=httpx.ConnectError("sem rede"))

        with pytest.raises(ValueError):
            await fetch_index(INDEX_URL)

async def test_fetch_index_raises_for_a_malformed_body():
    with respx.mock(assert_all_called=True) as mock:
        mock.get(INDEX_URL).mock(return_value=httpx.Response(200, text="<html>nada</html>"))

        with pytest.raises(ValueError):
            await fetch_index(INDEX_URL)

@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(200, json={"version": 2, "assets": []}),
        httpx.Response(200, json={"version": 1}),
    ],
)
async def test_fetch_index_raises_for_a_bad_answer(response):
    with respx.mock(assert_all_called=True) as mock:
        mock.get(INDEX_URL).mock(return_value=response)

        with pytest.raises(ValueError):
            await fetch_index(INDEX_URL)

async def test_fetch_index_requires_a_url():
    with pytest.raises(ValueError):
        await fetch_index("   ")

# ── serving back to search_remote ───────────────────────────────────

def test_index_round_trips_through_the_remote_search(market, tmp_path):
    _publish_three(market)
    path = write_index(tmp_path / "public" / "index.json", index_from_marketplace(market))

    with respx.mock(assert_all_called=True) as mock:
        mock.get(INDEX_URL).mock(return_value=httpx.Response(200, json=read_index(path)))
        assets = Marketplace().search_remote(INDEX_URL)

    assert sorted(asset.id for asset in assets) == sorted(
        asset.id for asset in market.list()
    )
    assert {asset.id: asset.payload for asset in assets} == {
        asset.id: asset.payload for asset in market.list()
    }

def test_index_summary_mentions_count_kinds_and_source(market):
    _publish_three(market)

    summary = index_summary(index_from_marketplace(market, source=INDEX_URL))

    assert "3" in summary
    assert INDEX_URL in summary
    for kind in ("workflow", "plugin", "template"):
        assert kind in summary

def test_index_summary_of_an_empty_index(market):
    summary = index_summary(index_from_marketplace(market, source="https://market.test/vazio.json"))

    assert "https://market.test/vazio.json" in summary
    assert "no published items" in summary
