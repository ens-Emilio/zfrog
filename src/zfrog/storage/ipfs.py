"""Publish the content-addressed store to IPFS through a Kubo node's HTTP API.

The node is addressed over HTTP (`/api/v0/...`), so publishing needs no extra
dependency: plain `httpx` multipart requests are enough. Files keep their path
relative to the published directory, which means the resulting CID addresses the
same tree layout the crawler produced.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from zfrog.config import settings
from zfrog.storage.content_addressed import ContentAddressedStore

logger = logging.getLogger(__name__)

ADD_PATH = "/api/v0/add"
ID_PATH = "/api/v0/id"
PIN_ADD_PATH = "/api/v0/pin/add"
DEFAULT_GATEWAY = "https://ipfs.io"
PART_NAME = "file"
PART_CONTENT_TYPE = "application/octet-stream"

MultipartPart = tuple[str, tuple[str, Any, str]]

@dataclass
class IpfsPublishResult:
    """Outcome of publishing a file or directory to IPFS."""

    cid: str
    name: str
    size: int
    files: int
    gateway_url: str

def gateway_url(cid: str, gateway: str = DEFAULT_GATEWAY) -> str:
    """Build the public gateway URL for a CID."""
    return f"{gateway}/ipfs/{cid}"

def _parse_add_response(text: str) -> list[dict[str, Any]]:
    """Parse the newline-delimited JSON that `/api/v0/add` streams back."""
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("skipping unparsable IPFS add line: %r", line)
            continue
        if isinstance(record, dict):
            records.append(record)
    return records

def _last_hash(records: Sequence[dict[str, Any]]) -> str:
    """Return the top-level CID: the Hash of the last record that carries one.

    With `wrap-with-directory=true` the node emits one record per file (and per
    intermediate directory) followed by the wrapping directory, so the last
    record is the published root.
    """
    for record in reversed(records):
        cid = record.get("Hash")
        if isinstance(cid, str) and cid:
            return cid
    raise RuntimeError("IPFS add response contained no Hash")

def _iter_files(root: Path) -> list[tuple[str, Path]]:
    """Return `(relative POSIX path, absolute path)` for every file under root."""
    found: list[tuple[str, Path]] = []
    for candidate in sorted(root.rglob("*")):
        if candidate.is_file():
            found.append((candidate.relative_to(root).as_posix(), candidate))
    return found

class IpfsClient:
    """Minimal async client for the subset of the Kubo HTTP API we need."""

    def __init__(
        self,
        api_url: str | None = None,
        timeout_s: int | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_url = (api_url or settings.ipfs_api_url).rstrip("/")
        self.timeout_s = settings.ipfs_timeout_s if timeout_s is None else timeout_s
        self._client = client
        self._owns_client = client is None

    def _ensure_client(self) -> httpx.AsyncClient:
        """Return the injected client, or build and cache one."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        """Close the HTTP client, but only when this instance created it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _url(self, path: str) -> str:
        return f"{self.api_url}{path}"

    async def is_available(self) -> bool:
        """Whether an IPFS node answers at `api_url`. Never raises."""
        try:
            response = await self._ensure_client().post(self._url(ID_PATH), content=b"")
        except Exception:
            logger.debug("IPFS node unreachable at %s", self.api_url, exc_info=True)
            return False
        return response.status_code == 200

    async def _add(self, files: list[MultipartPart], params: dict[str, str]) -> httpx.Response:
        """POST a multipart add and raise for any non-2xx node response."""
        response = await self._ensure_client().post(self._url(ADD_PATH), params=params, files=files)
        response.raise_for_status()
        return response

    async def add_bytes(self, data: bytes, name: str = "file") -> str:
        """Add raw bytes, returning the resulting CID."""
        response = await self._add([(PART_NAME, (name, data, PART_CONTENT_TYPE))], {"pin": "true"})
        return _last_hash(_parse_add_response(response.text))

    async def add_path(self, path: Path) -> IpfsPublishResult:
        """Add a file or a directory tree, returning the root CID and totals."""
        path = Path(path)
        if path.is_dir():
            return await self._add_directory(path)
        if not path.is_file():
            raise RuntimeError(f"cannot publish {path}: not a file or directory")
        return await self._add_file(path)

    async def _add_file(self, path: Path) -> IpfsPublishResult:
        """Add a single file; the file itself is the published root."""
        with path.open("rb") as handle:
            response = await self._add(
                [(PART_NAME, (path.name, handle, PART_CONTENT_TYPE))],
                {"pin": "true"},
            )
        cid = _last_hash(_parse_add_response(response.text))
        size = path.stat().st_size
        logger.debug("added %s to IPFS as %s (%d bytes)", path, cid, size)
        return IpfsPublishResult(
            cid=cid,
            name=path.name,
            size=size,
            files=1,
            gateway_url=gateway_url(cid),
        )

    async def _add_directory(self, path: Path) -> IpfsPublishResult:
        """Add every file under `path`, wrapped in a directory that keeps the layout."""
        entries = _iter_files(path)
        if not entries:
            raise RuntimeError(f"cannot publish {path}: no files found")
        with ExitStack() as stack:
            parts = [
                (PART_NAME, (relative, stack.enter_context(file.open("rb")), PART_CONTENT_TYPE))
                for relative, file in entries
            ]
            response = await self._add(
                parts,
                {"pin": "true", "wrap-with-directory": "true", "recursive": "true"},
            )
        cid = _last_hash(_parse_add_response(response.text))
        size = sum(file.stat().st_size for _, file in entries)
        logger.debug("added %s to IPFS as %s (%d files, %d bytes)", path, cid, len(entries), size)
        return IpfsPublishResult(
            cid=cid,
            name=path.name,
            size=size,
            files=len(entries),
            gateway_url=gateway_url(cid),
        )

    async def pin(self, cid: str) -> bool:
        """Pin a CID recursively. Returns False instead of raising."""
        try:
            response = await self._ensure_client().post(
                self._url(PIN_ADD_PATH), params={"arg": cid}
            )
        except Exception:
            logger.warning("could not pin %s: IPFS node unreachable", cid, exc_info=True)
            return False
        if response.status_code != 200:
            logger.warning("could not pin %s: node returned HTTP %s", cid, response.status_code)
            return False
        return True

def _store_stats() -> dict[str, int]:
    """Dedup picture from the content-addressed store, without creating it."""
    if not (settings.output_dir / ".store").exists():
        return {"objects": 0, "bytes": 0}
    try:
        return ContentAddressedStore().stats()
    except Exception:
        logger.debug("content-addressed store stats unavailable", exc_info=True)
        return {"objects": 0, "bytes": 0}

async def publish_output(output_dir: Path, client: IpfsClient | None = None) -> IpfsPublishResult:
    """Publish `output_dir` to IPFS, or explain why that is impossible."""
    if not settings.ipfs_enabled:
        raise RuntimeError(
            "IPFS publishing is disabled: enable it with ZFROG_IPFS_ENABLED=true "
            "(settings.ipfs_enabled)"
        )
    ipfs = client or IpfsClient()
    owns_client = client is None
    try:
        if not await ipfs.is_available():
            raise RuntimeError(
                f"IPFS node unreachable at {ipfs.api_url}: start a Kubo node there "
                "or point ZFROG_IPFS_API_URL at one"
            )
        result = await ipfs.add_path(Path(output_dir))
    finally:
        if owns_client:
            await ipfs.aclose()
    stats = _store_stats()
    logger.info(
        "published %s to IPFS: %s (%d files, %d bytes); store holds %d deduped objects / %d bytes",
        output_dir,
        result.cid,
        result.files,
        result.size,
        stats["objects"],
        stats["bytes"],
    )
    return result
