"""Tests for permanent Arweave archiving.

RSA keys are generated in-process and written as the JWK files Arweave wallets
use, so wallet loading and signing are exercised for real, and every HTTP call
is served by `respx`.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import logging
import tarfile
from functools import lru_cache
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from zfrog.config import settings
from zfrog.storage.arweave import (
    OWNER_SIZE,
    SIGNATURE_SIZE,
    SIGNATURE_TYPE_RSA_PSS,
    ArweaveClient,
    DataItem,
    Wallet,
    decode_varint,
    deep_hash,
    encode_tags,
    encode_varint,
    gateway_url,
    item_id,
    load_wallet,
    publish_clone,
    sign_data_item,
    wallet_configured,
)

GATEWAY = "http://arweave.test:1984"
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


@pytest.fixture(autouse=True)
def _arweave_settings(tmp_path, monkeypatch):
    """Point the client at a fake gateway and the wallet at tmp_path."""
    monkeypatch.setattr(settings, "arweave_enabled", False)
    monkeypatch.setattr(settings, "arweave_gateway", GATEWAY)
    monkeypatch.setattr(settings, "arweave_timeout_s", 5)
    monkeypatch.setattr(settings, "arweave_wallet_file", tmp_path / "arweave-wallet.json")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _int_b64(value: int) -> str:
    return _b64url(value.to_bytes((value.bit_length() + 7) // 8, "big"))


@lru_cache(maxsize=4)
def _jwk(index: int = 0) -> tuple[dict, rsa.RSAPrivateKey]:
    """Generate (once) an RSA key pair and the JWK Arweave wallets store it as."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.private_numbers()
    public = numbers.public_numbers
    jwk = {
        "kty": "RSA",
        "n": _int_b64(public.n),
        "e": _int_b64(public.e),
        "d": _int_b64(numbers.d),
        "p": _int_b64(numbers.p),
        "q": _int_b64(numbers.q),
    }
    return jwk, key


def _write_wallet(tmp_path: Path, index: int = 0) -> Path:
    jwk, _ = _jwk(index)
    path = tmp_path / f"arweave-wallet-{index}.json"
    path.write_text(json.dumps(jwk), encoding="utf-8")
    return path


def _wallet(tmp_path: Path, index: int = 0) -> Wallet:
    return load_wallet(_write_wallet(tmp_path, index))


def _read_item(body: bytes, owner_size: int) -> tuple[list[tuple[str, str]], bytes]:
    """Walk a signed data item: return its tags and the payload after them."""
    offset = 2 + SIGNATURE_SIZE + owner_size + 32 + 32
    count, offset = decode_varint(body, offset)
    tags: list[tuple[str, str]] = []
    for _ in range(count):
        name_len, offset = decode_varint(body, offset)
        name = body[offset : offset + name_len].decode("utf-8")
        offset += name_len
        value_len, offset = decode_varint(body, offset)
        value = body[offset : offset + value_len].decode("utf-8")
        offset += value_len
        tags.append((name, value))
    return tags, body[offset:]


def _verify_item(body: bytes, wallet: Wallet) -> tuple[list[tuple[str, str]], bytes]:
    """Verify a signed item's RSA-PSS signature; return its `(tags, payload)`.

    RSA-PSS signatures are big-endian integers, so the zero padding that brings a
    2048-bit key's signature up to the fixed field width is stripped again before
    the verifier (which expects a modulus-wide integer) sees it.
    """
    owner_size = len(wallet.public_key)
    tags, payload = _read_item(body, owner_size)
    head = 2 + SIGNATURE_SIZE
    owner = body[head : head + owner_size]
    target = body[head + owner_size : head + owner_size + 32]
    anchor = body[head + owner_size + 32 : head + owner_size + 64]
    digest = deep_hash([owner, target, anchor, encode_tags(tags), payload])
    wallet.private_key.public_key().verify(
        body[2 : 2 + SIGNATURE_SIZE].lstrip(b"\x00"), digest, PSS, hashes.SHA256()
    )
    return tags, payload


# ── load_wallet ──


def test_load_wallet_derives_stable_address_from_the_modulus(tmp_path):
    path = _write_wallet(tmp_path)
    first = load_wallet(path)
    second = load_wallet(path)

    assert isinstance(first, Wallet)
    assert first.address == second.address
    modulus = first.public_key
    assert len(modulus) == 256
    assert first.address == _b64url(hashlib.sha256(modulus).digest())


def test_load_wallet_repr_hides_the_private_key(tmp_path):
    jwk, _ = _jwk(0)
    wallet = load_wallet(_write_wallet(tmp_path))

    rendered = repr(wallet)
    assert rendered == f"Wallet(address='{wallet.address}')"
    assert jwk["d"] not in rendered
    assert jwk["p"] not in rendered
    assert jwk["q"] not in rendered


def test_load_wallet_uses_the_configured_path_and_signs(tmp_path, monkeypatch):
    path = tmp_path / "configured.json"
    path.write_text(json.dumps(_jwk(0)[0]), encoding="utf-8")
    monkeypatch.setattr(settings, "arweave_wallet_file", path)

    wallet = load_wallet()
    assert wallet.address == load_wallet(path).address
    # The loaded key is a working RSA key: it can actually sign.
    signature = wallet.private_key.sign(b"payload", PSS, hashes.SHA256())
    wallet.private_key.public_key().verify(signature, b"payload", PSS, hashes.SHA256())


def test_load_wallet_missing_file_names_the_setting(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(ValueError, match="arweave_wallet_file"):
        load_wallet(missing)


def test_load_wallet_rejects_malformed_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json at all", encoding="utf-8")
    with pytest.raises(ValueError, match="could not read Arweave wallet"):
        load_wallet(path)


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps(["not", "an", "object"]),
        json.dumps({"kty": "EC", "n": "AQAB"}),
        json.dumps({"kty": "RSA", "e": "AQAB", "d": "AQAB", "p": "AQAB", "q": "AQAB"}),
        json.dumps({"kty": "RSA", "n": "AQAB", "e": "AQAB", "d": "AQAB", "p": "AQAB"}),
        json.dumps({"kty": "RSA", "n": "!!not-base64!!", "e": "AQAB", "d": "AQAB", "p": "AQAB", "q": "AQAB"}),
    ],
)
def test_load_wallet_rejects_invalid_jwks(tmp_path, payload):
    path = tmp_path / "invalid.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="Arweave wallet"):
        load_wallet(path)


# ── wallet_configured ──


def test_wallet_configured_tracks_the_configured_file(tmp_path, monkeypatch):
    assert wallet_configured() is False
    path = _write_wallet(tmp_path)
    monkeypatch.setattr(settings, "arweave_wallet_file", path)
    assert wallet_configured() is True
    assert wallet_configured(path) is True
    assert wallet_configured(tmp_path / "absent.json") is False


def test_wallet_configured_is_false_for_a_broken_wallet(tmp_path, monkeypatch, caplog):
    path = tmp_path / "broken.json"
    path.write_text("{oops", encoding="utf-8")
    monkeypatch.setattr(settings, "arweave_wallet_file", path)

    with caplog.at_level(logging.WARNING, logger="zfrog.storage.arweave"):
        assert wallet_configured() is False
    assert "not usable" in caplog.text


# ── varints ──


@pytest.mark.parametrize("value", [0, 1, 127, 128, 300, 2**40 + 12345])
def test_varint_round_trips(value):
    encoded = encode_varint(value)
    decoded, offset = decode_varint(encoded)
    assert decoded == value
    assert offset == len(encoded)


def test_varint_uses_the_base128_layout():
    assert encode_varint(0) == b"\x00"
    assert encode_varint(127) == b"\x7f"
    assert encode_varint(128) == b"\x80\x01"
    assert encode_varint(300) == b"\xac\x02"


def test_decode_varint_honours_the_offset():
    data = b"\xff" + encode_varint(300)
    assert decode_varint(data, 1) == (300, 3)


def test_decode_varint_rejects_truncated_input():
    with pytest.raises(ValueError, match="truncated varint"):
        decode_varint(b"\x80")


def test_encode_varint_rejects_negative_values():
    with pytest.raises(ValueError, match="negative"):
        encode_varint(-1)


# ── tags ──


def test_encode_tags_round_trips_through_decode_varint():
    tags = [("App-Name", "zfrog"), ("Content-Type", "application/gzip")]
    encoded = encode_tags(tags)

    count, offset = decode_varint(encoded)
    assert count == 2
    pairs: list[tuple[str, str]] = []
    for _ in range(count):
        name_len, offset = decode_varint(encoded, offset)
        name = encoded[offset : offset + name_len].decode("utf-8")
        offset += name_len
        value_len, offset = decode_varint(encoded, offset)
        value = encoded[offset : offset + value_len].decode("utf-8")
        offset += value_len
        pairs.append((name, value))

    assert pairs == tags
    assert offset == len(encoded)


def test_encode_tags_empty_is_a_single_zero_byte():
    assert encode_tags([]) == b"\x00"
    assert decode_varint(encode_tags([])) == (0, 1)


def test_encode_tags_measures_lengths_in_utf8_bytes():
    encoded = encode_tags([("hé", "ção")])
    assert encoded == b"\x01\x03h\xc3\xa9\x05\xc3\xa7\xc3\xa3o"


# ── deep hash ──


def test_deep_hash_is_deterministic_and_chunk_sensitive():
    chunks = [b"owner", b"target", b"anchor", b"tags", b"data"]
    assert deep_hash(chunks) == deep_hash(list(chunks))
    assert len(deep_hash(chunks)) == 48
    assert deep_hash(chunks) != deep_hash([b"owner", b"target", b"anchor", b"tags", b"datA"])


def test_deep_hash_length_prefixes_every_chunk():
    assert deep_hash([b"ab", b"c"]) != deep_hash([b"a", b"bc"])


def test_deep_hash_recurses_into_nested_lists():
    nested = deep_hash([b"a", [b"b", b"c"]])
    flat = deep_hash([b"a", b"b", b"c"])
    assert nested != flat
    assert nested == deep_hash([b"a", [b"b", b"c"]])


# ── signing ──


def test_sign_data_item_layout_matches_ans104(tmp_path):
    wallet = _wallet(tmp_path)
    item = DataItem(data=b"hello world", tags=[("App-Name", "zfrog")])
    body = sign_data_item(item, wallet)
    tags_bytes = encode_tags(item.tags)

    assert body[:2] == SIGNATURE_TYPE_RSA_PSS.to_bytes(2, "big")
    assert len(body) == 2 + SIGNATURE_SIZE + OWNER_SIZE + 32 + 32 + len(tags_bytes) + len(item.data)

    owner = body[2 + SIGNATURE_SIZE : 2 + SIGNATURE_SIZE + OWNER_SIZE]
    target = body[2 + SIGNATURE_SIZE + OWNER_SIZE : 2 + SIGNATURE_SIZE + OWNER_SIZE + 32]
    anchor = body[-len(tags_bytes) - len(item.data) - 32 : -len(tags_bytes) - len(item.data)]
    assert owner == wallet.public_key
    assert target == b"\x00" * 32
    assert anchor == b"\x00" * 32
    assert body[-len(item.data) :] == item.data


def test_sign_data_item_signature_verifies_over_the_deep_hash(tmp_path):
    wallet = _wallet(tmp_path)
    item = DataItem(data=b"page", tags=[("App-Name", "zfrog")])
    body = sign_data_item(item, wallet)

    tags, payload = _verify_item(body, wallet)
    assert tags == item.tags
    assert payload == item.data

    # The same signature must not verify a different payload.
    head = 2 + SIGNATURE_SIZE
    owner = body[head : head + len(wallet.public_key)]
    wrong = deep_hash([owner, b"\x00" * 32, b"\x00" * 32, encode_tags(item.tags), b"tampered"])
    with pytest.raises(InvalidSignature):
        wallet.private_key.public_key().verify(
            body[2 : 2 + SIGNATURE_SIZE].lstrip(b"\x00"), wrong, PSS, hashes.SHA256()
        )


def test_sign_data_item_keeps_a_4096_bit_wallet_whole(tmp_path):
    """Arweave wallets are RSA-4096: signature and owner already fill their fields."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    numbers = key.private_numbers()
    public = numbers.public_numbers
    path = tmp_path / "rsa4096.json"
    path.write_text(
        json.dumps(
            {
                "kty": "RSA",
                "n": _int_b64(public.n),
                "e": _int_b64(public.e),
                "d": _int_b64(numbers.d),
                "p": _int_b64(numbers.p),
                "q": _int_b64(numbers.q),
            }
        ),
        encoding="utf-8",
    )
    wallet = load_wallet(path)
    item = DataItem(data=b"big key payload", tags=[("App-Name", "zfrog")])
    body = sign_data_item(item, wallet)

    assert len(wallet.public_key) == 512  # never truncated to OWNER_SIZE
    assert len(body[2 : 2 + SIGNATURE_SIZE]) == SIGNATURE_SIZE
    head = 2 + SIGNATURE_SIZE
    assert body[head : head + 512] == wallet.public_key
    tags, payload = _verify_item(body, wallet)
    assert tags == item.tags
    assert payload == item.data


def test_sign_data_item_is_keyed_by_the_wallet(tmp_path):
    first = _wallet(tmp_path, 0)
    second = _wallet(tmp_path, 1)
    item = DataItem(data=b"same payload", tags=[("App-Name", "zfrog")])

    assert first.address != second.address
    assert sign_data_item(item, first) != sign_data_item(item, second)


def test_sign_data_item_encodes_target_and_anchor(tmp_path):
    wallet = _wallet(tmp_path)
    target = _b64url(bytes(range(32)))
    anchor = _b64url(bytes(reversed(range(32))))
    body = sign_data_item(DataItem(data=b"x", target=target, anchor=anchor), wallet)

    head = 2 + SIGNATURE_SIZE + OWNER_SIZE
    assert body[head : head + 32] == bytes(range(32))
    assert body[head + 32 : head + 64] == bytes(reversed(range(32)))


def test_sign_data_item_rejects_a_wrong_length_target(tmp_path):
    wallet = _wallet(tmp_path)
    with pytest.raises(ValueError, match="target must be a 32-byte"):
        sign_data_item(DataItem(data=b"x", target=_b64url(b"short")), wallet)


# ── item_id ──


def test_item_id_is_stable_and_content_addressed():
    body = b"item-bytes"
    assert item_id(body) == item_id(bytes(body))
    assert item_id(body) == _b64url(hashlib.sha256(body).digest())
    assert item_id(body) != item_id(body + b"x")
    assert "=" not in item_id(body)


# ── gateway_url ──


def test_gateway_url_composes_explicit_and_configured_gateways():
    assert gateway_url("abc", "https://gw.test") == "https://gw.test/abc"
    assert gateway_url("abc", "https://gw.test/") == "https://gw.test/abc"
    assert gateway_url("abc") == f"{GATEWAY}/abc"


# ── info / price / status ──


async def test_info_returns_the_gateway_payload():
    payload = {"height": 1_500_000, "network": "arweave.N.1"}
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.get(f"{GATEWAY}/info").mock(return_value=httpx.Response(200, json=payload))
            assert await ArweaveClient(client=http).info() == payload
        assert route.calls[0].request.method == "GET"


async def test_info_returns_empty_dict_on_server_error(caplog):
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{GATEWAY}/info").mock(return_value=httpx.Response(500, text="boom"))
            with caplog.at_level(logging.WARNING, logger="zfrog.storage.arweave"):
                assert await ArweaveClient(client=http).info() == {}
    assert "500" in caplog.text


async def test_info_returns_empty_dict_when_the_gateway_is_unreachable():
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{GATEWAY}/info").mock(side_effect=httpx.ConnectError("refused"))
            assert await ArweaveClient(client=http).info() == {}


async def test_price_returns_the_gateway_winston_cost():
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.get(f"{GATEWAY}/price/2048").mock(
                return_value=httpx.Response(200, text="987654321\n")
            )
            assert await ArweaveClient(client=http).price(2048) == 987654321
        assert route.calls[0].request.url.path == "/price/2048"


async def test_status_returns_the_gateway_payload():
    payload = {"block_height": 42, "number_of_confirmations": 3}
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{GATEWAY}/tx/abc123/status").mock(
                return_value=httpx.Response(200, json=payload)
            )
            assert await ArweaveClient(client=http).status("abc123") == payload


async def test_status_returns_empty_dict_when_the_item_is_unknown():
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{GATEWAY}/tx/missing/status").mock(
                return_value=httpx.Response(404, text="Not Found")
            )
            assert await ArweaveClient(client=http).status("missing") == {}


# ── upload ──


async def test_upload_posts_signed_bytes_and_returns_the_item_id(tmp_path):
    wallet = _wallet(tmp_path)
    item = DataItem(data=b"page bytes", tags=[("App-Name", "zfrog")])
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post(f"{GATEWAY}/tx").mock(return_value=httpx.Response(200, text="OK"))
            ident = await ArweaveClient(client=http, wallet=wallet).upload(item)

    request = route.calls[0].request
    assert request.headers["content-type"] == "application/octet-stream"
    # RSA-PSS salts are random, so the posted item is verified, not compared byte
    # for byte against a second signature.
    tags, payload = _verify_item(request.content, wallet)
    assert tags == item.tags
    assert payload == item.data
    assert ident == item_id(request.content)


async def test_upload_accepts_a_202_accepted_response(tmp_path):
    wallet = _wallet(tmp_path)
    item = DataItem(data=b"payload")
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post(f"{GATEWAY}/tx").mock(return_value=httpx.Response(202, text="Accepted"))
            ident = await ArweaveClient(client=http, wallet=wallet).upload(item)

    assert ident == item_id(route.calls[0].request.content)
    assert _verify_item(route.calls[0].request.content, wallet)[1] == item.data


async def test_upload_error_carries_the_gateway_message(tmp_path):
    wallet = _wallet(tmp_path)
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.post(f"{GATEWAY}/tx").mock(
                return_value=httpx.Response(400, json={"error": "Invalid signature"})
            )
            with pytest.raises(RuntimeError, match="Invalid signature"):
                await ArweaveClient(client=http, wallet=wallet).upload(DataItem(data=b"x"))


async def test_upload_error_carries_a_plain_text_body(tmp_path):
    wallet = _wallet(tmp_path)
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            mock.post(f"{GATEWAY}/tx").mock(
                return_value=httpx.Response(500, text="gateway is overloaded")
            )
            with pytest.raises(RuntimeError, match="gateway is overloaded"):
                await ArweaveClient(client=http, wallet=wallet).upload(DataItem(data=b"x"))


async def test_upload_without_a_wallet_names_the_setting():
    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=False) as mock:
            mock.post(f"{GATEWAY}/tx").mock(return_value=httpx.Response(200, text="OK"))
            with pytest.raises(RuntimeError, match="arweave_wallet_file"):
                await ArweaveClient(client=http).upload(DataItem(data=b"x"))
        assert not mock.calls


# ── aclose ──


async def test_aclose_leaves_an_injected_client_usable():
    async with httpx.AsyncClient() as http:
        arweave = ArweaveClient(client=http)
        await arweave.aclose()
        assert http.is_closed is False
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{GATEWAY}/info").mock(return_value=httpx.Response(200, json={"height": 1}))
            assert await arweave.info() == {"height": 1}


async def test_aclose_closes_a_client_it_created():
    arweave = ArweaveClient()
    http = arweave._ensure_client()
    await arweave.aclose()
    assert http.is_closed is True
    assert arweave._client is None


# ── publish_clone ──


async def test_publish_clone_raises_when_disabled(tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "index.html").write_bytes(b"<h1>hi</h1>")

    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=False) as mock:
            with pytest.raises(RuntimeError, match="arweave_enabled"):
                await publish_clone(clone, ArweaveClient(client=http))
        assert not mock.calls


async def test_publish_clone_raises_when_the_wallet_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "arweave_enabled", True)
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "index.html").write_bytes(b"<h1>hi</h1>")

    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=False) as mock:
            with pytest.raises(RuntimeError, match="Arweave wallet unavailable"):
                await publish_clone(clone, ArweaveClient(client=http))
        assert not mock.calls


async def test_publish_clone_raises_for_a_missing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "arweave_enabled", True)
    monkeypatch.setattr(settings, "arweave_wallet_file", _write_wallet(tmp_path))

    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=False) as mock:
            with pytest.raises(RuntimeError, match="not a directory"):
                await publish_clone(tmp_path / "absent", ArweaveClient(client=http))
        assert not mock.calls


async def test_publish_clone_uploads_a_tagged_gzip_tar(tmp_path, monkeypatch):
    wallet_path = _write_wallet(tmp_path)
    monkeypatch.setattr(settings, "arweave_enabled", True)
    monkeypatch.setattr(settings, "arweave_wallet_file", wallet_path)
    wallet = load_wallet(wallet_path)

    clone = tmp_path / "clone"
    (clone / "sub").mkdir(parents=True)
    (clone / "index.html").write_bytes(b"<h1>archived</h1>")
    (clone / "sub" / "a.txt").write_bytes(b"nested content")

    async with httpx.AsyncClient() as http:
        with respx.mock(assert_all_called=True) as mock:
            price_route = mock.get(url__regex=rf"{GATEWAY}/price/[0-9]+").mock(
                return_value=httpx.Response(200, text="12345")
            )
            tx_route = mock.post(f"{GATEWAY}/tx").mock(
                return_value=httpx.Response(200, text="OK")
            )
            result = await publish_clone(clone, ArweaveClient(client=http))

    body = tx_route.calls[0].request.content
    assert tx_route.calls[0].request.headers["content-type"] == "application/octet-stream"
    tags, payload = _verify_item(body, wallet)
    tag_map = dict(tags)
    assert tag_map["App-Name"] == "zfrog"
    assert tag_map["Content-Type"] == "application/gzip"
    assert tag_map["Source-Path"] == str(clone.resolve())

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        names = archive.getnames()
        assert f"{clone.name}/index.html" in names
        assert f"{clone.name}/sub/a.txt" in names
        assert archive.extractfile(f"{clone.name}/index.html").read() == b"<h1>archived</h1>"
    assert gzip.decompress(payload)  # the payload really is gzip, not plain tar

    assert result["item_id"] == item_id(body)
    assert result["size_bytes"] == len(payload)
    assert result["winston"] == 12345
    assert result["gateway_url"] == f"{GATEWAY}/{result['item_id']}"
    priced = int(price_route.calls[0].request.url.path.rsplit("/", 1)[-1])
    assert priced == len(payload)


async def test_publish_clone_creates_and_closes_its_own_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "arweave_enabled", True)
    monkeypatch.setattr(settings, "arweave_wallet_file", _write_wallet(tmp_path))
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "index.html").write_bytes(b"<h1>hi</h1>")

    with respx.mock(assert_all_called=True) as mock:
        mock.get(url__regex=rf"{GATEWAY}/price/[0-9]+").mock(
            return_value=httpx.Response(200, text="7")
        )
        mock.post(f"{GATEWAY}/tx").mock(return_value=httpx.Response(200, text="OK"))
        result = await publish_clone(clone)

    assert result["winston"] == 7
    assert result["gateway_url"].startswith(f"{GATEWAY}/")
    assert result["size_bytes"] > 0
