"""Tests for the IPFS publishing client.

A respx-backed `httpx.AsyncClient` is injected into `IpfsClient`, so every
request is asserted against the real Kubo HTTP API paths and query parameters,
while the multipart bodies are parsed to prove the published layout.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest
import respx

from zfrog.config import settings
from zfrog.storage.content_addressed import ContentAddressedStore
from zfrog.storage.ipfs import IpfsClient, gateway_url, publish_output

API = "http://ipfs.test:5001"
ADD = f"{API}/api/v0/add"
ID = f"{API}/api/v0/id"
PIN_ADD = f"{API}/api/v0/pin/add"

@pytest.fixture(autouse=True)
def _ipfs_settings(tmp_path, monkeypatch):
    """Point the client at a fake node; keep the store out of the real output dir."""
    monkeypatch.setattr(settings, "ipfs_api_url", API)
    monkeypatch.setattr(settings, "ipfs_timeout_s", 5)
    monkeypatch.setattr(settings, "ipfs_enabled", False)
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")

def _ndjson(*records: dict) -> str:
    """Render the newline-delimited JSON the node streams back from /api/v0/add."""
    return "".join(json.dumps(record) + "\n" for record in records)

def _client(http: httpx.AsyncClient) -> IpfsClient:
    return IpfsClient(client=http)

def _tree(tmp_path: Path) -> Path:
    """Two files in two directories: a.txt and sub/b.txt."""
    root = tmp_path / "site"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"aaaa")
    (root / "sub" / "b.txt").write_bytes(b"bbbbbb")
    return root

# ── gateway_url ──

def test_gateway_url_composes_default_and_custom_gateway():
    assert gateway_url("QmXyz") == "https://ipfs.io/ipfs/QmXyz"
    assert gateway_url("QmXyz", gateway="http://127.0.0.1:8080") == (
        "http://127.0.0.1:8080/ipfs/QmXyz"
    )

# ── is_available ──

async def test_is_available_true_when_node_answers_id():
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post(ID).mock(return_value=httpx.Response(200, json={"ID": "12D3KooW"}))
            assert await _client(http).is_available() is True
        assert route.call_count == 1
        assert route.calls[0].request.method == "POST"

async def test_is_available_false_on_connection_error_without_raising():
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ID).mock(side_effect=httpx.ConnectError("connection refused"))
            assert await _client(http).is_available() is False

async def test_is_available_false_on_error_status():
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ID).mock(return_value=httpx.Response(500, text="boom"))
            assert await _client(http).is_available() is False

# ── add_bytes ──

async def test_add_bytes_posts_multipart_and_returns_last_hash():
    body = _ndjson(
        {"Name": "page.html", "Hash": "QmIntermediate", "Size": "11"},
        {"Name": "page.html", "Hash": "QmFinal", "Size": "11"},
    )
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post(ADD).mock(return_value=httpx.Response(200, text=body))
            cid = await _client(http).add_bytes(b"hello world", name="page.html")

    assert cid == "QmFinal"
    request = route.calls[0].request
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert request.url.params["pin"] == "true"
    assert b'filename="page.html"' in request.content
    assert b"hello world" in request.content

async def test_add_bytes_raises_when_node_returns_no_hash():
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ADD).mock(return_value=httpx.Response(200, text="not json\n"))
            with pytest.raises(RuntimeError, match="no Hash"):
                await _client(http).add_bytes(b"data")

# ── add_path: directory ──

async def test_add_path_directory_wraps_tree_and_reports_totals(tmp_path):
    root = _tree(tmp_path)
    body = _ndjson(
        {"Name": "a.txt", "Hash": "QmFileA", "Size": "4"},
        {"Name": "sub/b.txt", "Hash": "QmFileB", "Size": "6"},
        {"Name": "", "Hash": "QmDirectory", "Size": "10"},
    )
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post(ADD).mock(return_value=httpx.Response(200, text=body))
            result = await _client(http).add_path(root)

    # One add entry per file plus the wrapping directory: the wrap is the root CID.
    assert result.cid == "QmDirectory"
    assert result.name == "site"
    assert result.files == 2
    assert result.size == 10
    assert result.gateway_url == "https://ipfs.io/ipfs/QmDirectory"

    request = route.calls[0].request
    params = dict(request.url.params)
    assert params == {"pin": "true", "wrap-with-directory": "true", "recursive": "true"}
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    payload = request.content
    assert payload.count(b"Content-Disposition: form-data") == 2
    # Relative paths are preserved as the multipart filenames.
    assert b'filename="a.txt"' in payload
    assert b'filename="sub/b.txt"' in payload
    assert b"aaaa" in payload
    assert b"bbbbbb" in payload

async def test_add_path_directory_root_cid_is_last_entry(tmp_path):
    """The wrapping directory is emitted last, so a plain last-Hash read is the root."""
    root = tmp_path / "site"
    root.mkdir()
    (root / "only.txt").write_bytes(b"x")
    body = _ndjson(
        {"Name": "only.txt", "Hash": "QmFile", "Size": "1"},
        {"Name": "", "Hash": "QmWrapped", "Size": "1"},
    )
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ADD).mock(return_value=httpx.Response(200, text=body))
            result = await _client(http).add_path(root)
    assert result.cid == "QmWrapped"
    assert result.files == 1
    assert result.size == 1

async def test_add_path_empty_directory_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=False) as mock:
            with pytest.raises(RuntimeError, match="no files"):
                await _client(http).add_path(empty)
        assert not mock.calls

# ── add_path: single file ──

async def test_add_path_single_file_returns_that_file_cid(tmp_path):
    page = tmp_path / "page.html"
    page.write_bytes(b"<html>ok</html>")
    body = _ndjson({"Name": "page.html", "Hash": "QmPage", "Size": "15"})
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post(ADD).mock(return_value=httpx.Response(200, text=body))
            result = await _client(http).add_path(page)

    assert result.cid == "QmPage"
    assert result.name == "page.html"
    assert result.files == 1
    assert result.size == 15
    request = route.calls[0].request
    assert dict(request.url.params) == {"pin": "true"}
    assert b'filename="page.html"' in request.content

# ── pin ──

async def test_pin_returns_true_on_success():
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post(PIN_ADD, params={"arg": "QmPage"}).mock(
                return_value=httpx.Response(200, json={"Pins": ["QmPage"]})
            )
            assert await _client(http).pin("QmPage") is True
        assert route.call_count == 1

async def test_pin_returns_false_on_error_response():
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.post(PIN_ADD).mock(return_value=httpx.Response(500, text="no such cid"))
            assert await _client(http).pin("QmMissing") is False

async def test_pin_returns_false_when_node_unreachable():
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.post(PIN_ADD).mock(side_effect=httpx.ConnectError("down"))
            assert await _client(http).pin("QmPage") is False

# ── aclose ──

async def test_aclose_leaves_injected_client_usable():
    async with httpx.AsyncClient() as http:
        ipfs = _client(http)
        await ipfs.aclose()
        assert http.is_closed is False
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ID).mock(return_value=httpx.Response(200, json={"ID": "12D3KooW"}))
            response = await http.post(ID)
            assert response.status_code == 200
            assert await ipfs.is_available() is True

async def test_aclose_closes_client_it_created():
    ipfs = IpfsClient()
    http = ipfs._ensure_client()
    await ipfs.aclose()
    assert http.is_closed is True
    assert ipfs._client is None

# ── publish_output ──

async def test_publish_output_raises_when_disabled(tmp_path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "a.txt").write_bytes(b"a")
    with respx.mock(assert_all_called=False) as mock:
        with pytest.raises(RuntimeError, match="disabled"):
            await publish_output(tmp_path / "site")
    assert not mock.calls

async def test_publish_output_raises_when_node_unreachable(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    monkeypatch.setattr(settings, "ipfs_enabled", True)
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=False) as mock:
            mock.post(ID).mock(side_effect=httpx.ConnectError("refused"))
            with pytest.raises(RuntimeError, match="unreachable"):
                await publish_output(root, _client(http))

async def test_publish_output_publishes_and_logs_dedup(tmp_path, monkeypatch, caplog):
    root = _tree(tmp_path)
    monkeypatch.setattr(settings, "ipfs_enabled", True)
    # Seed the content-addressed store so the dedup log has something to report.
    store = ContentAddressedStore(settings.output_dir / ".store")
    store.store_bytes(b"aaaa")

    body = _ndjson(
        {"Name": "a.txt", "Hash": "QmFileA", "Size": "4"},
        {"Name": "sub/b.txt", "Hash": "QmFileB", "Size": "6"},
        {"Name": "", "Hash": "QmDirectory", "Size": "10"},
    )
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            id_route = mock.post(ID).mock(return_value=httpx.Response(200, json={"ID": "12D3KooW"}))
            add_route = mock.post(ADD).mock(return_value=httpx.Response(200, text=body))
            with caplog.at_level(logging.INFO, logger="zfrog.storage.ipfs"):
                result = await publish_output(root, _client(http))

    assert id_route.call_count == 1
    assert add_route.call_count == 1
    assert result.cid == "QmDirectory"
    assert result.files == 2
    assert result.size == 10
    assert "1 deduped objects" in caplog.text
    assert "QmDirectory" in caplog.text

async def test_publish_output_creates_and_closes_its_own_client(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    monkeypatch.setattr(settings, "ipfs_enabled", True)
    body = _ndjson(
        {"Name": "a.txt", "Hash": "QmFileA", "Size": "4"},
        {"Name": "sub/b.txt", "Hash": "QmFileB", "Size": "6"},
        {"Name": "", "Hash": "QmDirectory", "Size": "10"},
    )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(ID).mock(return_value=httpx.Response(200, json={"ID": "12D3KooW"}))
        mock.post(ADD).mock(return_value=httpx.Response(200, text=body))
        result = await publish_output(root)
    assert result.cid == "QmDirectory"
