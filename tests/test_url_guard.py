"""Tests for the URL guard (SSRF protection).

The API fetches URLs a client supplies, so without a guard a request can make the
server read cloud metadata (`169.254.169.254`) or anything on the private network.
The guard is off by default — local use clones localhost and LAN sites — and a
public deployment turns it on.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from zfrog.config import settings
from zfrog.utils.url_guard import BlockedUrlError, check_url, is_blocked_address


@pytest.fixture
def guard_on(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_hosts", False)


@pytest.fixture
def guard_off(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_hosts", True)


def test_local_use_is_unaffected(guard_off):
    """The open-source default must not break cloning your own machine."""
    for url in (
        "http://127.0.0.1:8000/page",
        "http://localhost:3000/",
        "http://192.168.1.5/router",
        "http://169.254.169.254/latest/meta-data/",
    ):
        check_url(url)  # must not raise


def test_public_urls_are_allowed_when_guarding(guard_on, monkeypatch):
    """A public address passes. The resolver is stubbed so the test does not
    depend on the sandbox having DNS."""
    import ipaddress

    from zfrog.utils import url_guard

    monkeypatch.setattr(
        url_guard,
        "_addresses_for",
        lambda host: [ipaddress.ip_address("93.184.216.34")],
    )

    check_url("https://example.com/x")
    check_url("https://sub.example.com/a/b?c=1")


def test_internal_addresses_are_blocked(guard_on, monkeypatch):
    """Literal IPs need no DNS, so these exercise the classification directly."""
    for url in (
        "http://127.0.0.1:8000/x",
        "http://localhost:3000/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.1/",
        "http://192.168.1.5/",
        "http://[::1]/",
        "http://0.0.0.0/",
    ):
        with pytest.raises(BlockedUrlError):
            check_url(url)


def test_non_http_schemes_are_blocked(guard_on):
    for url in ("file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/"):
        with pytest.raises(BlockedUrlError):
            check_url(url)


def test_a_url_without_a_host_is_blocked(guard_on):
    with pytest.raises(BlockedUrlError):
        check_url("http:///no-host")


def test_an_unresolvable_host_is_blocked_rather_than_guessed(guard_on):
    """Fail closed: a name we cannot resolve must not be fetched."""
    with pytest.raises(BlockedUrlError):
        check_url("http://nao-existe-mesmo.invalid/x")


def test_address_classification():
    import ipaddress

    assert is_blocked_address(ipaddress.ip_address("127.0.0.1"))
    assert is_blocked_address(ipaddress.ip_address("169.254.169.254"))
    assert is_blocked_address(ipaddress.ip_address("10.1.2.3"))
    assert is_blocked_address(ipaddress.ip_address("::1"))
    assert not is_blocked_address(ipaddress.ip_address("93.184.216.34"))


def test_the_client_hook_blocks_a_redirect_into_the_private_network(guard_on):
    """The bypass that matters: a public URL redirecting to an internal one.

    Checking only the initial URL would miss this, so the hook runs per hop.
    """
    import asyncio

    from zfrog.utils.http import create_client

    async def run() -> int:
        async with create_client() as client:
            response = await client.get("http://127.0.0.1:1/anything")
            return response.status_code

    # 127.0.0.1 is blocked, so the request never leaves: the hook raises.
    with pytest.raises(BlockedUrlError):
        asyncio.run(run())


def test_a_real_redirect_chain_is_checked_hop_by_hop(guard_on):
    """A server that redirects to a private address must be stopped mid-chain."""

    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Redirector)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        import asyncio

        from zfrog.utils.http import create_client

        async def run() -> None:
            async with create_client() as client:
                await client.get(f"http://127.0.0.1:{port}/start")

        # The FIRST hop is already 127.0.0.1, so it is blocked before the redirect
        # is even followed — which is the correct, stricter behaviour.
        with pytest.raises(BlockedUrlError):
            asyncio.run(run())
    finally:
        server.shutdown()


def test_a_blocked_url_is_a_400_not_a_500(guard_on, tmp_path, monkeypatch):
    """A URL the guard refuses is a bad request, not a server fault.

    Regression: BlockedUrlError propagated out of run_job and the generic handler
    turned it into a 500, which tells the caller the server broke.
    """
    from fastapi.testclient import TestClient

    from zfrog.api import app
    from zfrog.auth import ApiKeyStore

    monkeypatch.setattr(settings, "api_keys_file", tmp_path / "keys.json")
    monkeypatch.setattr(settings, "audit_log", tmp_path / "audit.log")
    secret, _ = ApiKeyStore().create("ana", "operator")

    with TestClient(app) as client:
        response = client.post(
            "/jobs",
            json={"url": "http://169.254.169.254/latest/meta-data/"},
            headers={"Authorization": f"Bearer {secret}"},
        )

    assert response.status_code == 400
    assert "internal address" in response.json()["detail"]


def test_the_guard_does_not_break_a_normal_request(guard_off):
    """With the guard off, a plain request to a local server still works."""

    class Ok(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Ok)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        import asyncio

        from zfrog.utils.http import create_client

        async def run() -> tuple[int, bytes]:
            async with create_client() as client:
                response = await client.get(f"http://127.0.0.1:{port}/x")
                return response.status_code, response.content

        status, body = asyncio.run(run())
        assert status == 200 and body == b"ok"
    finally:
        server.shutdown()
