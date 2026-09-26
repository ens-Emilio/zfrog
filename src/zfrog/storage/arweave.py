"""Permanent archiving of clones on Arweave.

A clone published here keeps existing independently of this machine: the bundle
is uploaded to an Arweave gateway as a signed data item and paid for in AR, so
it survives as long as the network does.

This module implements the protocol pieces needed to do that with `cryptography`
alone (no `arweave-python-client`): wallet loading from the JWK key file Arweave
wallets ship, the ANS-104 data-item layout that Arweave's bundlers accept
(`signature type | signature | owner | target | anchor | tags | data`), Arweave's
deep hash and the `/tx` upload.

Scope: it has been exercised against a mocked gateway, NOT against the live
network. Publishing for real costs AR and needs a funded wallet whose JWK lives
at `settings.arweave_wallet_file`.

Two layout details worth stating, because Arweave's production wallets are
RSA-4096 while the fixed ANS-104 fields below are what bundlers parse:

* the signature is left-padded to `SIGNATURE_SIZE` bytes. An RSA signature is a
  big-endian integer, so padding a shorter key's signature with leading zeros
  preserves the value the network verifies; Arweave's RSA-4096 wallets fill the
  field exactly. Note that OpenSSL itself insists on a modulus-wide integer, so
  a 2048-bit key's padded signature only verifies once the padding is stripped;
* the owner is the public modulus, left-padded to `OWNER_SIZE` bytes but never
  truncated, so an RSA-4096 wallet keeps its natural 512-byte modulus.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import logging
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from zfrog.config import settings

logger = logging.getLogger(__name__)

#: ANS-104 signature type 1 = Arweave RSA-PSS with SHA-256.
SIGNATURE_TYPE_RSA_PSS = 1
SIGNATURE_TYPE_SIZE = 2
#: Fixed signature field width in the ANS-104 header.
SIGNATURE_SIZE = 512
#: Minimum owner field width; the owner is the RSA public modulus.
OWNER_SIZE = 256
#: Target and anchor are 32-byte hashes; zeros stand for "unset".
HASH_SIZE = 32
ZERO_HASH = b"\x00" * HASH_SIZE

ITEM_CONTENT_TYPE = "application/octet-stream"
ARCHIVE_CONTENT_TYPE = "application/gzip"
APP_NAME = "zfrog"

INFO_PATH = "/info"
PRICE_PATH = "/price/{size}"
TX_PATH = "/tx"
STATUS_PATH = "/tx/{item_id}/status"


def encode_varint(value: int) -> bytes:
    """Encode `value` as a base-128 varint (little-endian groups, continuation bit)."""
    if value < 0:
        raise ValueError("varint value must not be negative")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode a base-128 varint at `offset`, returning `(value, new offset)`."""
    value = 0
    shift = 0
    position = offset
    while True:
        if position >= len(data):
            raise ValueError("truncated varint: ran out of bytes")
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
        if shift > 63:
            raise ValueError("varint is too long to be a 64-bit integer")


def encode_tags(tags: list[tuple[str, str]]) -> bytes:
    """Encode ANS-104 tags: a varint count, then length-prefixed name/value pairs."""
    out = bytearray(encode_varint(len(tags)))
    for name, value in tags:
        name_bytes = name.encode("utf-8")
        value_bytes = value.encode("utf-8")
        out += encode_varint(len(name_bytes))
        out += name_bytes
        out += encode_varint(len(value_bytes))
        out += value_bytes
    return bytes(out)


def _deep_hash(data: bytes | list) -> bytes:
    """Recursive core of `deep_hash`: `blob` tag for bytes, `list` tag for lists."""
    if isinstance(data, (bytes, bytearray, memoryview)):
        blob = bytes(data)
        return hashlib.sha384(b"blob" + encode_varint(len(blob)) + blob).digest()
    if isinstance(data, (list, tuple)):
        items = list(data)
        digest = hashlib.sha384()
        digest.update(b"list" + encode_varint(len(items)))
        for item in items:
            digest.update(_deep_hash(item))
        return digest.digest()
    raise TypeError(f"deep hash only accepts bytes or lists, got {type(data).__name__}")


def deep_hash(chunks: list[bytes]) -> bytes:
    """Arweave's deep hash of `chunks`: SHA-384 over length-prefixed, tagged chunks.

    This is the digest a data item's signature covers.
    """
    return _deep_hash(list(chunks))


def _b64url(data: bytes) -> str:
    """Base64url without padding, the encoding Arweave uses for ids and addresses."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_bytes(text: str) -> bytes:
    """Decode a base64url string, with or without padding."""
    if not isinstance(text, str):
        raise ValueError(f"expected a base64url string, got {type(text).__name__}")
    padded = text + "=" * (-len(text) % 4)
    try:
        return base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise ValueError(f"invalid base64url value: {exc}") from exc


def _jwk_int(value: Any, field_name: str) -> int:
    """Decode a JWK base64url big-endian integer field."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"JWK field {field_name!r} must be a non-empty base64url string")
    raw = _b64url_bytes(value)
    if not raw:
        raise ValueError(f"JWK field {field_name!r} decoded to no bytes")
    return int.from_bytes(raw, "big")


def _pad_to_size(value: bytes, size: int) -> bytes:
    """Left-pad `value` to `size` bytes; never truncate a longer value."""
    if len(value) >= size:
        return value
    return value.rjust(size, b"\x00")


def _hash_field(value: str, field_name: str) -> bytes:
    """Decode a 32-byte base64url hash field, defaulting to zeros when empty."""
    if not value:
        return ZERO_HASH
    raw = _b64url_bytes(value)
    if len(raw) != HASH_SIZE:
        raise ValueError(f"{field_name} must be a {HASH_SIZE}-byte base64url hash")
    return raw


@dataclass(repr=False)
class Wallet:
    """An Arweave RSA wallet.

    The private key is deliberately never rendered: `repr` exposes the address
    only, so logging a wallet can not leak key material.
    """

    address: str
    public_key: bytes
    private_key: object

    def __repr__(self) -> str:
        return f"Wallet(address={self.address!r})"


def load_wallet(path: Path | None = None) -> Wallet:
    """Load the JWK key file Arweave wallets use.

    The address is the base64url SHA-256 of the modulus, which is exactly how
    Arweave derives an address from a key.
    """
    wallet_path = Path(path) if path is not None else Path(settings.arweave_wallet_file)
    if not wallet_path.exists():
        raise ValueError(
            f"Arweave wallet not found at {wallet_path}: write a JWK key file there or "
            "point settings.arweave_wallet_file (ZFROG_ARWEAVE_WALLET_FILE) at one"
        )
    try:
        raw = json.loads(wallet_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read Arweave wallet {wallet_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Arweave wallet {wallet_path} is not a JWK object")
    key_type = raw.get("kty")
    if key_type is not None and key_type != "RSA":
        raise ValueError(f"Arweave wallet {wallet_path} is a {key_type!r} JWK, expected RSA")

    try:
        n = _jwk_int(raw.get("n"), "n")
        e = _jwk_int(raw.get("e"), "e")
        d = _jwk_int(raw.get("d"), "d")
        p = _jwk_int(raw.get("p"), "p")
        q = _jwk_int(raw.get("q"), "q")
    except ValueError as exc:
        raise ValueError(f"Arweave wallet {wallet_path} is not a valid RSA JWK: {exc}") from exc

    public_numbers = rsa.RSAPublicNumbers(e, n)
    private_numbers = rsa.RSAPrivateNumbers(
        p,
        q,
        d,
        rsa.rsa_crt_dmp1(d, p),
        rsa.rsa_crt_dmq1(d, q),
        rsa.rsa_crt_iqmp(p, q),
        public_numbers,
    )
    try:
        private_key = private_numbers.private_key()
    except ValueError as exc:
        raise ValueError(
            f"Arweave wallet {wallet_path} holds inconsistent RSA numbers: {exc}"
        ) from exc

    modulus = n.to_bytes((n.bit_length() + 7) // 8, "big")
    address = _b64url(hashlib.sha256(modulus).digest())
    logger.debug("loaded Arweave wallet %s from %s", address, wallet_path)
    return Wallet(address=address, public_key=modulus, private_key=private_key)


def wallet_configured(path: Path | None = None) -> bool:
    """Whether a usable Arweave wallet is configured. Never raises.

    Used by the status endpoint: it must answer even when the key file is
    missing or broken.
    """
    wallet_path = Path(path) if path is not None else Path(settings.arweave_wallet_file)
    if not wallet_path.exists():
        logger.debug("no Arweave wallet at %s", wallet_path)
        return False
    try:
        load_wallet(wallet_path)
    except ValueError:
        logger.warning(
            "Arweave wallet at %s exists but is not usable", wallet_path, exc_info=True
        )
        return False
    return True


@dataclass
class DataItem:
    """An ANS-104 data item: the payload plus its routing metadata."""

    data: bytes
    target: str = ""
    anchor: str = ""
    tags: list[tuple[str, str]] = field(default_factory=list)


def _sign_bytes(private_key: object, message: bytes) -> bytes:
    """RSA-PSS/SHA-256 signature over `message` (salt length = digest length)."""
    signer = getattr(private_key, "sign", None)
    if signer is None:
        raise ValueError("wallet private key is not an RSA private key")
    return signer(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256().digest_size,
        ),
        hashes.SHA256(),
    )


def sign_data_item(item: DataItem, wallet: Wallet) -> bytes:
    """Serialise and sign `item` into the ANS-104 byte layout.

    Layout: signature type (2 bytes, big-endian), signature, owner, target,
    anchor, encoded tags, data. The signature covers the deep hash of
    `[owner, target, anchor, tags, data]`.
    """
    tags_bytes = encode_tags(item.tags)
    target = _hash_field(item.target, "target")
    anchor = _hash_field(item.anchor, "anchor")
    owner = _pad_to_size(wallet.public_key, OWNER_SIZE)
    signature = _sign_bytes(
        wallet.private_key, deep_hash([owner, target, anchor, tags_bytes, item.data])
    )
    if len(signature) < SIGNATURE_SIZE:
        logger.debug(
            "signature is %d bytes, padded to the %d-byte ANS-104 field; Arweave wallets "
            "are RSA-4096 and fill it exactly",
            len(signature),
            SIGNATURE_SIZE,
        )
    return b"".join(
        (
            SIGNATURE_TYPE_RSA_PSS.to_bytes(SIGNATURE_TYPE_SIZE, "big"),
            _pad_to_size(signature, SIGNATURE_SIZE),
            owner,
            target,
            anchor,
            tags_bytes,
            item.data,
        )
    )


def item_id(item_bytes: bytes) -> str:
    """The id a bundler reports: base64url SHA-256 of the item bytes."""
    return _b64url(hashlib.sha256(item_bytes).digest())


def gateway_url(item_id: str, gateway: str = "") -> str:
    """Build the public gateway URL for an item id."""
    base = (gateway or settings.arweave_gateway).rstrip("/")
    return f"{base}/{item_id}"


def _error_message(response: httpx.Response) -> str:
    """Extract the most useful message from a gateway error response."""
    text = response.text.strip()
    if not text:
        return response.reason_phrase or f"HTTP {response.status_code}"
    try:
        payload = json.loads(text)
    except ValueError:
        return text
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return text


class ArweaveClient:
    """Minimal async client for the gateway endpoints we need."""

    def __init__(
        self,
        gateway: str = "",
        wallet: Wallet | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: int | None = None,
    ):
        self.gateway = (gateway or settings.arweave_gateway).rstrip("/")
        self.wallet = wallet
        self.timeout_s = settings.arweave_timeout_s if timeout_s is None else timeout_s
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
        return f"{self.gateway}{path}"

    async def info(self) -> dict:
        """Network height and version from `GET /info`; `{}` when it fails."""
        try:
            response = await self._ensure_client().get(self._url(INFO_PATH))
        except Exception:
            logger.warning("Arweave gateway %s unreachable for /info", self.gateway, exc_info=True)
            return {}
        if response.status_code != 200:
            logger.warning(
                "Arweave gateway %s answered HTTP %s for /info",
                self.gateway,
                response.status_code,
            )
            return {}
        try:
            payload = response.json()
        except ValueError:
            logger.warning("Arweave gateway %s returned a non-JSON /info body", self.gateway)
            return {}
        return payload if isinstance(payload, dict) else {}

    async def price(self, size_bytes: int) -> int:
        """Winston cost of storing `size_bytes`, from `GET /price/{size}`."""
        if size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        response = await self._ensure_client().get(self._url(PRICE_PATH.format(size=int(size_bytes))))
        response.raise_for_status()
        try:
            return int(response.text.strip())
        except ValueError as exc:
            raise RuntimeError(
                f"Arweave gateway returned a non-numeric price: {response.text.strip()!r}"
            ) from exc

    async def upload(self, item: DataItem) -> str:
        """Sign `item` and `POST /tx`, returning its item id."""
        if self.wallet is None:
            raise RuntimeError(
                "no Arweave wallet loaded: set settings.arweave_wallet_file "
                "(ZFROG_ARWEAVE_WALLET_FILE) and pass the loaded wallet to ArweaveClient"
            )
        payload = sign_data_item(item, self.wallet)
        response = await self._ensure_client().post(
            self._url(TX_PATH),
            content=payload,
            headers={"Content-Type": ITEM_CONTENT_TYPE},
        )
        if response.status_code not in (200, 202):
            raise RuntimeError(
                f"Arweave gateway rejected the upload (HTTP {response.status_code}): "
                f"{_error_message(response)}"
            )
        ident = item_id(payload)
        logger.info(
            "uploaded %d bytes to Arweave as %s via %s", len(payload), ident, self.gateway
        )
        return ident

    async def status(self, item_id: str) -> dict:
        """Confirmation status of an item from `GET /tx/{id}/status`; `{}` on failure."""
        try:
            response = await self._ensure_client().get(
                self._url(STATUS_PATH.format(item_id=item_id))
            )
        except Exception:
            logger.warning("Arweave gateway %s unreachable for /tx status", self.gateway, exc_info=True)
            return {}
        if response.status_code != 200:
            logger.warning(
                "Arweave gateway %s answered HTTP %s for /tx/%s/status",
                self.gateway,
                response.status_code,
                item_id,
            )
            return {}
        try:
            payload = response.json()
        except ValueError:
            logger.warning("Arweave gateway %s returned a non-JSON status body", self.gateway)
            return {}
        return payload if isinstance(payload, dict) else {}


def _tar_directory(dir_path: Path) -> bytes:
    """Pack `dir_path` into a single gzipped tar payload."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(dir_path, arcname=dir_path.name, recursive=True)
    return buffer.getvalue()


async def publish_clone(dir_path: Path, client: ArweaveClient | None = None) -> dict:
    """Archive `dir_path` on Arweave as one gzipped tar data item."""
    if not settings.arweave_enabled:
        raise RuntimeError(
            "Arweave publishing is disabled: enable it with ZFROG_ARWEAVE_ENABLED=true "
            "(settings.arweave_enabled)"
        )
    clone = Path(dir_path)
    if not clone.is_dir():
        raise RuntimeError(f"cannot archive {clone}: not a directory")
    try:
        wallet = load_wallet()
    except ValueError as exc:
        raise RuntimeError(f"Arweave wallet unavailable: {exc}") from exc

    payload = _tar_directory(clone)
    item = DataItem(
        data=payload,
        tags=[
            ("App-Name", APP_NAME),
            ("Content-Type", ARCHIVE_CONTENT_TYPE),
            ("Source-Path", str(clone.resolve())),
        ],
    )

    arweave = client or ArweaveClient(wallet=wallet)
    if arweave.wallet is None:
        arweave.wallet = wallet
    owns_client = client is None
    try:
        winston = await arweave.price(len(payload))
        ident = await arweave.upload(item)
    finally:
        if owns_client:
            await arweave.aclose()

    result = {
        "item_id": ident,
        "size_bytes": len(payload),
        "winston": winston,
        "gateway_url": gateway_url(ident, arweave.gateway),
    }
    logger.info(
        "archived %s on Arweave as %s (%d bytes, %d winston)",
        clone,
        ident,
        result["size_bytes"],
        winston,
    )
    return result
