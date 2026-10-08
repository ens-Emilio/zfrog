"""URL guard: keep server-side fetches away from internal addresses.

The API fetches URLs that a client supplies (jobs, probe, extract, safety scans).
Without a guard, `POST /jobs {"url": "http://169.254.169.254/..."}` makes
the server read its own cloud metadata, and any address on the private network
becomes reachable through Zfrog. That is a server-side request forgery, and on a
machine with a cloud role attached it is the classic way to steal credentials.

Local use legitimately clones `localhost` and LAN sites, so the guard is OFF by
default (`ZFROG_ALLOW_PRIVATE_HOSTS=true`) and a public deployment turns it on.
That keeps the open-source promise (it runs locally, against local things) while
making the production posture explicit instead of accidental.

The check runs on EVERY request the client makes — including each redirect hop,
because httpx re-runs the hook for them. Checking only the initial URL would miss
`https://public.example -> http://169.254.169.254/`.

Limitation, stated plainly: the guard resolves the name and then httpx resolves it
again to connect. A DNS server that answers the first lookup with a public address
and the second with an internal one (DNS rebinding) can still slip through. Closing
that requires pinning the resolved address in the connection itself, which means a
custom transport rather than a hook. The guard raises the cost of the attack from
"one curl" to "control the target's DNS", which is worth having, but it is not a
sandbox.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from zfrog.config import settings

logger = logging.getLogger(__name__)

#: Hostnames that always resolve inside the machine, whatever DNS says.
_LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


class BlockedUrlError(ValueError):
    """Raised when a URL points at an address the server must not fetch."""


def _addresses_for(host: str) -> list[ipaddress._BaseAddress]:
    """Resolve every address a hostname maps to.

    Every address is returned, not just the first: a name that resolves to both a
    public and a private address is a known way to slip past a guard that only
    looks at one.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedUrlError(f"could not resolve {host!r}: {exc}") from exc

    addresses = []
    for info in infos:
        raw = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(raw.split("%")[0]))
        except ValueError:  # pragma: no cover - getaddrinfo returns valid IPs
            continue
    return addresses


def is_blocked_address(address: ipaddress._BaseAddress) -> bool:
    """Whether an address is internal, reserved or otherwise not for us."""
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,  # 169.254.0.0/16 — cloud metadata
            address.is_reserved,
            address.is_multicast,
            address.is_unspecified,
        )
    )


def check_url(url: str) -> None:
    """Raise BlockedUrlError when `url` must not be fetched.

    A no-op when `ZFROG_ALLOW_PRIVATE_HOSTS` is true (the default), so local use
    is unaffected.
    """
    if settings.allow_private_hosts:
        return

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedUrlError(f"disallowed scheme: {parsed.scheme or '(empty)'}")

    host = parsed.hostname
    if not host:
        raise BlockedUrlError("URL without host")

    if host.lower() in _LOCAL_NAMES:
        raise BlockedUrlError(f"internal host blocked: {host}")

    for address in _addresses_for(host):
        if is_blocked_address(address):
            raise BlockedUrlError(f"{host} resolves to an internal address ({address})")


async def guard_request_hook(request) -> None:
    """httpx request hook: check every outgoing request, redirects included."""
    check_url(str(request.url))
