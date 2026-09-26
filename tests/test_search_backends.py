"""Tests for the pluggable search backends (SQLite, Meilisearch, Elasticsearch)."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest
import respx

import zfrog.search as search_mod
import zfrog.search_backends as backends_mod
from zfrog.config import settings
from zfrog.search_backends import (
    BackendHit,
    ElasticsearchBackend,
    MeilisearchBackend,
    SearchBackend,
    SqliteBackend,
    backend_for,
    index_and_search,
    page_id,
)

MEILI = "http://meili.test:7700"
ES = "http://es.test:9200"

PAGE_A = {
    "path": "docs/a.html",
    "url": "https://site.test/a.html",
    "title": "Alfa",
    "text": "alfa bravo no parque",
    "site": "site.test",
}
PAGE_B = {
    "path": "docs/b.html",
    "url": "https://site.test/b.html",
    "title": "Bravo",
    "text": "charlie delta na cidade",
    "site": "site.test",
}

def _item(doc_id: str, status: int, error: dict | None = None) -> dict:
    """One entry of a ``_bulk`` response body."""
    result: dict = {"_index": "zfrog", "_id": doc_id, "status": status}
    if error is not None:
        result["error"] = error
    return {"index": result}

@pytest.fixture(autouse=True)
def _isolated_backends(tmp_path, monkeypatch):
    """Own database per test, fixed engine urls, and never call a real embedding model."""
    monkeypatch.setattr(settings, "search_db", tmp_path / "search.db")
    monkeypatch.setattr(settings, "search_backend", "sqlite")
    monkeypatch.setattr(settings, "meilisearch_url", MEILI)
    monkeypatch.setattr(settings, "meilisearch_key", "master-key")
    monkeypatch.setattr(settings, "elasticsearch_url", ES)
    monkeypatch.setattr(settings, "elasticsearch_index", "zfrog")
    monkeypatch.setattr(settings, "elasticsearch_user", "")
    monkeypatch.setattr(settings, "elasticsearch_password", "")
    monkeypatch.setattr(search_mod, "is_available", lambda: False)

# ── factory and ids ──

def test_backend_for_builds_the_named_backend():
    sqlite = backend_for("sqlite")
    meili = backend_for("meilisearch")
    elastic = backend_for("elasticsearch")
    assert isinstance(sqlite, SqliteBackend) and sqlite.name == "sqlite"
    assert isinstance(meili, MeilisearchBackend) and meili.name == "meilisearch"
    assert isinstance(elastic, ElasticsearchBackend) and elastic.name == "elasticsearch"
    assert isinstance(backend_for(), SqliteBackend)

def test_backend_for_follows_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "search_backend", "elasticsearch")
    backend = backend_for()
    assert isinstance(backend, ElasticsearchBackend)
    assert backend.name == "elasticsearch"
    assert backend.url == ES

def test_backend_for_rejects_unknown_names():
    with pytest.raises(ValueError) as excinfo:
        backend_for("solr")
    message = str(excinfo.value)
    assert "solr" in message
    assert "sqlite" in message and "meilisearch" in message and "elasticsearch" in message

def test_page_id_is_stable_and_path_specific():
    assert page_id("docs/a.html") == page_id("docs/a.html")
    assert page_id("docs/a.html") != page_id("docs/b.html")
    assert page_id("docs/a.html") == hashlib.sha1(b"docs/a.html").hexdigest()

def test_search_backend_is_abstract():
    with pytest.raises(TypeError):
        SearchBackend()  # type: ignore[abstract]

# ── meilisearch ──

async def test_meilisearch_index_posts_documents_with_primary_key():
    backend = MeilisearchBackend()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{MEILI}/indexes/zfrog/documents", params={"primaryKey": "id"}).mock(
            return_value=httpx.Response(202, json={"taskUid": 4, "status": "enqueued"})
        )
        assert await backend.index([PAGE_A, PAGE_B]) == 2
        await backend.aclose()

    assert route.called
    request = route.calls[0].request
    assert request.url.params["primaryKey"] == "id"
    assert request.headers["authorization"] == "Bearer master-key"
    assert json.loads(request.content) == [
        {
            "id": page_id("docs/a.html"),
            "path": "docs/a.html",
            "url": "https://site.test/a.html",
            "title": "Alfa",
            "text": "alfa bravo no parque",
            "site": "site.test",
        },
        {
            "id": page_id("docs/b.html"),
            "path": "docs/b.html",
            "url": "https://site.test/b.html",
            "title": "Bravo",
            "text": "charlie delta na cidade",
            "site": "site.test",
        },
    ]

async def test_meilisearch_index_ignores_pages_without_path():
    backend = MeilisearchBackend()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{MEILI}/indexes/zfrog/documents").mock(
            return_value=httpx.Response(202, json={"taskUid": 1})
        )
        assert await backend.index([{"url": "https://site.test/orphan.html"}]) == 0
        assert not route.called

async def test_meilisearch_search_maps_hits_and_snippets():
    backend = MeilisearchBackend()
    payload = {
        "hits": [
            {
                "id": page_id("docs/a.html"),
                "path": "docs/a.html",
                "url": "https://site.test/a.html",
                "title": "Alfa",
                "text": "alfa bravo no parque",
                "site": "site.test",
                "_formatted": {"title": "Alfa", "text": "<em>alfa</em> bravo no parque"},
            },
            {
                "id": page_id("docs/b.html"),
                "path": "docs/b.html",
                "url": "https://site.test/b.html",
                "title": "Bravo",
                "text": "charlie delta na cidade",
                "site": "site.test",
                "_rankingScore": 0.25,
            },
        ],
        "query": "alfa",
        "limit": 20,
    }
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{MEILI}/indexes/zfrog/search").mock(
            return_value=httpx.Response(200, json=payload)
        )
        hits = await backend.search("alfa")
        await backend.aclose()

    assert json.loads(route.calls[0].request.content) == {"q": "alfa", "limit": 20}
    assert [hit.path for hit in hits] == ["docs/a.html", "docs/b.html"]
    assert hits[0] == BackendHit(
        path="docs/a.html",
        url="https://site.test/a.html",
        title="Alfa",
        snippet="<em>alfa</em> bravo no parque",
        score=1.0,
    )
    assert hits[1].snippet == "charlie delta na cidade"
    assert hits[1].score == 0.25

async def test_meilisearch_semantic_search_requests_hybrid():
    backend = MeilisearchBackend()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{MEILI}/indexes/zfrog/search").mock(
            return_value=httpx.Response(200, json={"hits": []})
        )
        assert await backend.search("alfa", mode="semantic", limit=5) == []
        await backend.aclose()

    assert json.loads(route.calls[0].request.content) == {
        "q": "alfa",
        "limit": 5,
        "hybrid": {"semanticRatio": 1.0},
    }

async def test_meilisearch_drop_site_posts_filter():
    backend = MeilisearchBackend()
    payload = {
        "taskUid": 9,
        "type": "documentDeletion",
        "details": {"providedIds": 0, "deletedDocuments": 2},
    }
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{MEILI}/indexes/zfrog/documents/delete").mock(
            return_value=httpx.Response(202, json=payload)
        )
        assert await backend.drop_site("site.test") == 2
        await backend.aclose()

    assert json.loads(route.calls[0].request.content) == {"filter": 'site = "site.test"'}

async def test_meilisearch_health_tracks_the_status_code():
    backend = MeilisearchBackend()
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{MEILI}/health").mock(
            return_value=httpx.Response(500, json={"status": "unavailable"})
        )
        assert await backend.healthy() is False
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{MEILI}/health").mock(
            return_value=httpx.Response(200, json={"status": "available"})
        )
        assert await backend.healthy() is True
    await backend.aclose()

# ── elasticsearch ──

async def test_elasticsearch_index_sends_ndjson_bulk_body():
    backend = ElasticsearchBackend()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{ES}/_bulk").mock(
            return_value=httpx.Response(
                200,
                json={
                    "took": 3,
                    "errors": False,
                    "items": [
                        _item(page_id("docs/a.html"), 201),
                        _item(page_id("docs/b.html"), 201),
                    ],
                },
            )
        )
        assert await backend.index([PAGE_A, PAGE_B]) == 2
        await backend.aclose()

    request = route.calls[0].request
    assert request.headers["content-type"] == "application/x-ndjson"
    expected = (
        '{"index": {"_index": "zfrog", "_id": "%s"}}\n'
        '{"path": "docs/a.html", "url": "https://site.test/a.html", "title": "Alfa", '
        '"text": "alfa bravo no parque", "site": "site.test"}\n'
        '{"index": {"_index": "zfrog", "_id": "%s"}}\n'
        '{"path": "docs/b.html", "url": "https://site.test/b.html", "title": "Bravo", '
        '"text": "charlie delta na cidade", "site": "site.test"}\n'
    ) % (page_id("docs/a.html"), page_id("docs/b.html"))
    assert request.content.decode("utf-8") == expected

async def test_elasticsearch_index_reports_rejected_documents(caplog):
    backend = ElasticsearchBackend()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{ES}/_bulk").mock(
            return_value=httpx.Response(
                200,
                json={
                    "took": 1,
                    "errors": True,
                    "items": [
                        _item(page_id("docs/a.html"), 201),
                        _item(
                            page_id("docs/b.html"),
                            400,
                            {"type": "mapper_parsing_exception"},
                        ),
                    ],
                },
            )
        )
        with caplog.at_level("WARNING"):
            assert await backend.index([PAGE_A, PAGE_B]) == 1
        await backend.aclose()

    assert any(page_id("docs/b.html") in record.message for record in caplog.records)

async def test_elasticsearch_search_posts_multi_match_and_maps_hits():
    backend = ElasticsearchBackend()
    payload = {
        "hits": {
            "hits": [
                {
                    "_score": 2.5,
                    "_source": {
                        "path": "docs/a.html",
                        "url": "https://site.test/a.html",
                        "title": "Alfa",
                        "text": "alfa bravo no parque",
                        "site": "site.test",
                    },
                },
                {"_score": None, "_source": {"path": "docs/b.html", "title": "Bravo", "text": ""}},
            ]
        }
    }
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{ES}/zfrog/_search").mock(
            return_value=httpx.Response(200, json=payload)
        )
        hits = await backend.search("alfa")
        await backend.aclose()

    assert json.loads(route.calls[0].request.content) == {
        "query": {"multi_match": {"query": "alfa", "fields": ["title^2", "text"]}},
        "size": 20,
    }
    assert [hit.path for hit in hits] == ["docs/a.html", "docs/b.html"]
    assert hits[0].score == 2.5
    assert hits[0].snippet == "alfa bravo no parque"
    assert hits[0].url == "https://site.test/a.html"
    assert hits[1].score == 0.0

async def test_elasticsearch_semantic_search_uses_knn_query(monkeypatch):
    backend = ElasticsearchBackend()
    embedded: list[list[str]] = []

    async def fake_embed(texts: list[str]) -> list[list[float]]:
        embedded.append(texts)
        return [[0.5, 0.25]]

    monkeypatch.setattr(backends_mod, "embed", fake_embed)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{ES}/zfrog/_search").mock(
            return_value=httpx.Response(200, json={"hits": {"hits": []}})
        )
        assert await backend.search("alfa", mode="semantic", limit=5) == []
        await backend.aclose()

    assert embedded == [["alfa"]]
    assert json.loads(route.calls[0].request.content) == {
        "query": {"knn": {"field": "embedding", "query_vector": [0.5, 0.25], "k": 5}}
    }

async def test_elasticsearch_semantic_search_without_embeddings_returns_nothing(monkeypatch):
    backend = ElasticsearchBackend()

    async def broken_embed(texts: list[str]) -> list[list[float]]:
        raise RuntimeError("modelo fora do ar")

    async def empty_embed(texts: list[str]) -> list[list[float]]:
        return []

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{ES}/zfrog/_search")
        monkeypatch.setattr(backends_mod, "embed", broken_embed)
        assert await backend.search("alfa", mode="semantic") == []
        monkeypatch.setattr(backends_mod, "embed", empty_embed)
        assert await backend.search("alfa", mode="semantic") == []
        assert not route.called

async def test_elasticsearch_drop_site_deletes_by_query():
    backend = ElasticsearchBackend()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{ES}/zfrog/_delete_by_query").mock(
            return_value=httpx.Response(200, json={"deleted": 3, "failures": []})
        )
        assert await backend.drop_site("site.test") == 3
        await backend.aclose()

    assert json.loads(route.calls[0].request.content) == {"query": {"term": {"site": "site.test"}}}

async def test_elasticsearch_health_tracks_the_index_status():
    backend = ElasticsearchBackend()
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{ES}/zfrog").mock(
            return_value=httpx.Response(404, json={"error": "index_not_found_exception"})
        )
        assert await backend.healthy() is False
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{ES}/zfrog").mock(return_value=httpx.Response(200, json={"zfrog": {}}))
        assert await backend.healthy() is True
    await backend.aclose()

async def test_elasticsearch_sends_basic_auth_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "elasticsearch_user", "elastic")
    monkeypatch.setattr(settings, "elasticsearch_password", "s3cret")
    backend = ElasticsearchBackend()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{ES}/zfrog").mock(return_value=httpx.Response(200, json={"zfrog": {}}))
        assert await backend.healthy() is True
        await backend.aclose()

    header = route.calls[0].request.headers["authorization"]
    assert header.startswith("Basic ")
    assert base64.b64decode(header.split(" ", 1)[1]).decode() == "elastic:s3cret"

# ── sqlite ──

async def test_sqlite_backend_indexes_and_finds_the_right_page():
    backend = SqliteBackend()
    assert await backend.healthy() is True
    assert await backend.index([PAGE_A, PAGE_B]) == 2
    # Re-indexing the same pages replaces them instead of duplicating them.
    assert await backend.index([PAGE_A]) == 1

    hits = await backend.search("charlie")
    assert [hit.path for hit in hits] == ["docs/b.html"]
    assert hits[0].url == "https://site.test/b.html"
    assert hits[0].title == "Bravo"
    assert "charlie" in hits[0].snippet
    assert hits[0].score > 0

    assert [hit.path for hit in await backend.search("alfa")] == ["docs/a.html"]
    assert await backend.search("inexistente") == []
    assert Path(settings.search_db).is_file()
    await backend.aclose()

async def test_sqlite_backend_drop_site_removes_pages_and_mirrors():
    backend = SqliteBackend()
    await backend.index([PAGE_A, PAGE_B])

    assert await backend.drop_site("site.test") == 2
    assert await backend.search("charlie") == []
    assert await backend.drop_site("site.test") == 0
    assert [path for path in backend.pages_dir.rglob("*") if path.is_file()] == []

async def test_sqlite_backend_round_trips_awkward_paths():
    pages = [
        {
            "path": "v1.2/docs/relatório final.html",
            "url": "https://site.test/r",
            "title": "Relatório",
            "text": "unicornio no relatorio",
            "site": "site.test",
        },
        {
            "path": "https://site.test/deep/page",
            "url": "",
            "title": "Deep",
            "text": "unicornio na pagina profunda",
            "site": "site.test",
        },
    ]
    backend = SqliteBackend()
    assert await backend.index(pages) == 2

    # A fresh backend has no in-memory state: the page paths come from the mirror file names.
    fresh = SqliteBackend()
    hits = await fresh.search("unicornio")
    assert sorted(hit.path for hit in hits) == sorted(page["path"] for page in pages)
    assert {hit.title for hit in hits} == {"Relatório", "Deep"}

async def test_sqlite_backend_keeps_paths_it_did_not_mirror(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "page.html").write_text(
        "<html><head><title>Fora</title></head><body>unicornio</body></html>", encoding="utf-8"
    )
    backend = SqliteBackend()
    assert backend.indexer.index_directory(root) == 1

    hits = await backend.search("unicornio")
    assert [hit.path for hit in hits] == [(root / "page.html").as_posix()]
    assert hits[0].title == "Fora"

async def test_sqlite_backend_semantic_mode_without_embeddings_is_empty():
    backend = SqliteBackend()
    await backend.index([PAGE_A])
    assert await backend.search("alfa", mode="semantic") == []

async def test_sqlite_backend_never_raises_on_a_broken_database(tmp_path, monkeypatch):
    backend = SqliteBackend()
    db = Path(settings.search_db)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"isto nao e um sqlite")

    assert await backend.healthy() is False
    assert await backend.search("alfa") == []

# ── errors, wiring and ownership ──

async def test_unreachable_backends_never_raise(monkeypatch):
    async def fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2]]

    monkeypatch.setattr(backends_mod, "embed", fake_embed)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.route().mock(side_effect=httpx.ConnectError("sem rede"))
        for factory in (MeilisearchBackend, ElasticsearchBackend):
            backend = factory()
            assert await backend.index([PAGE_A]) == 0
            assert await backend.search("alfa") == []
            assert await backend.search("alfa", mode="semantic") == []
            assert await backend.drop_site("site.test") == 0
            assert await backend.healthy() is False
            await backend.aclose()

    # Five calls each (index, two searches, drop_site, healthy), none of them passed through
    # to the network: respx raised the connection error every time.
    assert route.call_count == 10

async def test_http_backends_reject_an_unknown_mode():
    for factory in (MeilisearchBackend, ElasticsearchBackend, SqliteBackend):
        with pytest.raises(ValueError, match="fulltext"):
            await factory().search("alfa", mode="fuzzy")

async def test_index_and_search_defaults_to_the_sqlite_backend():
    hits = await index_and_search([PAGE_A, PAGE_B], "charlie")
    assert [hit.path for hit in hits] == ["docs/b.html"]
    assert hits[0].title == "Bravo"
    assert hits[0].url == "https://site.test/b.html"

async def test_index_and_search_uses_a_given_backend_and_keeps_it_open():
    backend = MeilisearchBackend()
    client = backend.client()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{MEILI}/indexes/zfrog/documents", params={"primaryKey": "id"}).mock(
            return_value=httpx.Response(202, json={"taskUid": 1})
        )
        mock.post(f"{MEILI}/indexes/zfrog/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "path": "docs/a.html",
                            "url": "https://site.test/a.html",
                            "title": "Alfa",
                            "text": "alfa bravo no parque",
                        }
                    ]
                },
            )
        )
        hits = await index_and_search([PAGE_A], "alfa", backend=backend)
        assert [hit.path for hit in hits] == ["docs/a.html"]
        assert client.is_closed is False
        assert [hit.path for hit in await backend.search("alfa")] == ["docs/a.html"]

    await backend.aclose()
    assert client.is_closed is True

async def test_index_and_search_closes_a_backend_it_created(monkeypatch):
    owned = MeilisearchBackend()
    client = owned.client()
    monkeypatch.setattr(backends_mod, "backend_for", lambda name=None: owned)
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{MEILI}/indexes/zfrog/documents", params={"primaryKey": "id"}).mock(
            return_value=httpx.Response(202, json={"taskUid": 1})
        )
        mock.post(f"{MEILI}/indexes/zfrog/search").mock(
            return_value=httpx.Response(200, json={"hits": []})
        )
        assert await index_and_search([PAGE_A], "alfa") == []

    assert client.is_closed is True
