"""Tests for OpenID Connect SSO: discovery, the code exchange and real token verification.

The ID tokens here are signed with keys generated in the test itself, so the
signature checks are exercised against real RS256/ES256 cryptography — an
unverified or tampered token must never be accepted.
"""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from zfrog.auth import ROLES
from zfrog.config import settings
from zfrog.sso import (
    OidcDiscovery,
    authorization_url,
    clear_discovery_cache,
    complete_login,
    config_from_settings,
    decode_unverified,
    discover,
    exchange_code,
    is_configured,
    new_nonce,
    new_state,
    role_from_groups,
    verify_id_token,
)

ISSUER = "https://idp.test"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
AUTHORIZE_URL = f"{ISSUER}/authorize"
TOKEN_URL = f"{ISSUER}/token"
JWKS_URL = f"{ISSUER}/jwks"
REDIRECT_URI = "http://localhost:8000/auth/callback"
CLIENT_ID = "zfrog-client"
CLIENT_SECRET = "s3cret-do-not-log"
KID = "key-1"


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    """Point the settings at a fake provider and keep the discovery cache clean."""
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "oidc_client_secret", CLIENT_SECRET)
    monkeypatch.setattr(settings, "oidc_redirect_uri", REDIRECT_URI)
    monkeypatch.setattr(settings, "oidc_scopes", "openid email profile")
    monkeypatch.setattr(settings, "oidc_username_claim", "email")
    monkeypatch.setattr(settings, "oidc_groups_claim", "groups")
    monkeypatch.setattr(settings, "oidc_group_role_map", "admins=admin,devs=operator")
    clear_discovery_cache()
    yield
    clear_discovery_cache()


def _discovery_document(**overrides) -> dict:
    """A realistic ``openid-configuration`` document."""
    document = {
        "issuer": ISSUER,
        "authorization_endpoint": AUTHORIZE_URL,
        "token_endpoint": TOKEN_URL,
        "jwks_uri": JWKS_URL,
        "userinfo_endpoint": f"{ISSUER}/userinfo",
        "end_session_endpoint": f"{ISSUER}/logout",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256", "ES256"],
        "scopes_supported": ["openid", "email", "profile"],
        "claims_supported": ["sub", "iss", "aud", "exp", "email", "name", "groups"],
    }
    document.update(overrides)
    return document


def _discovery() -> OidcDiscovery:
    """The discovery object the tests hand to the functions under test."""
    return OidcDiscovery(
        issuer=ISSUER,
        authorization_endpoint=AUTHORIZE_URL,
        token_endpoint=TOKEN_URL,
        jwks_uri=JWKS_URL,
        userinfo_endpoint=f"{ISSUER}/userinfo",
        end_session_endpoint=f"{ISSUER}/logout",
    )


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _segment(document: dict) -> str:
    return _b64url(json.dumps(document, separators=(",", ":")).encode("utf-8"))


def _rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _rsa_jwk(key: rsa.RSAPrivateKey, kid: str = KID) -> dict:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64url(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
        "e": _b64url(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
    }


def _ec_jwk(key: ec.EllipticCurvePrivateKey, kid: str = KID) -> dict:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "EC",
        "kid": kid,
        "use": "sig",
        "alg": "ES256",
        "crv": "P-256",
        "x": _b64url(numbers.x.to_bytes(32, "big")),
        "y": _b64url(numbers.y.to_bytes(32, "big")),
    }


def _sign(key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey, header: dict, claims: dict) -> str:
    """Sign ``header.claims`` the way a provider would.

    RS256 keeps the raw PKCS#1 v1.5 signature; ES256 emits the JWS form of the
    ECDSA signature — the fixed-width ``R‖S`` concatenation of RFC 7518, not
    the DER encoding ``cryptography`` hands back — so the tests exercise the
    same bytes a real provider puts on the wire.
    """
    signing_input = f"{_segment(header)}.{_segment(claims)}"
    data = signing_input.encode("ascii")
    if isinstance(key, rsa.RSAPrivateKey):
        signature = key.sign(data, padding.PKCS1v15(), hashes.SHA256())
    else:
        r, s = decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{signing_input}.{_b64url(signature)}"


def _sign_ec_der(key: ec.EllipticCurvePrivateKey, header: dict, claims: dict) -> str:
    """Sign with a DER-encoded ECDSA signature, the non-JWS encoding."""
    signing_input = f"{_segment(header)}.{_segment(claims)}"
    signature = key.sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    return f"{signing_input}.{_b64url(signature)}"


def _claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "user-1",
        "exp": now + 300,
        "iat": now,
        "email": "ana@example.com",
        "name": "Ana Silva",
        "groups": ["admins"],
        "nonce": "nonce-1",
    }
    claims.update(overrides)
    return claims


def _rs256_token(key: rsa.RSAPrivateKey, claims: dict | None = None, kid: str = KID) -> str:
    return _sign(key, {"alg": "RS256", "kid": kid, "typ": "JWT"}, claims or _claims())


async def _verify_with(token: str, keys: list[dict], nonce: str = "nonce-1"):
    """Run verification against a JWKS holding ``keys``.

    ``assert_all_called`` stays off: checks that run before the JWKS fetch
    (algorithm, ``kid``) must not need the route to be hit.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json={"keys": keys}))
        return await verify_id_token(token, config_from_settings(), _discovery(), nonce=nonce)


# ── Configuration ────────────────────────────────────────────────────────────


def test_config_from_settings_reads_every_field():
    config = config_from_settings()

    assert config.issuer == ISSUER
    assert config.client_id == CLIENT_ID
    assert config.client_secret == CLIENT_SECRET
    assert config.redirect_uri == REDIRECT_URI
    assert config.scopes == ["openid", "email", "profile"]
    assert config.username_claim == "email"
    assert config.groups_claim == "groups"
    assert config.group_role_map == {"admins": "admin", "devs": "operator"}
    assert is_configured() is True


def test_config_from_settings_strips_a_trailing_slash(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", f"{ISSUER}/")

    assert config_from_settings().issuer == ISSUER


def test_config_from_settings_requires_issuer_and_client_id(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "")
    monkeypatch.setattr(settings, "oidc_client_id", "")

    assert is_configured() is False
    with pytest.raises(ValueError) as excinfo:
        config_from_settings()
    message = str(excinfo.value)
    assert "ZFROG_OIDC_ISSUER" in message
    assert "ZFROG_OIDC_CLIENT_ID" in message


def test_is_configured_is_false_without_a_client_id(monkeypatch):
    monkeypatch.setattr(settings, "oidc_client_id", "  ")

    assert is_configured() is False
    with pytest.raises(ValueError):
        config_from_settings()


def test_config_from_settings_rejects_a_broken_group_map(monkeypatch):
    monkeypatch.setattr(settings, "oidc_group_role_map", "admins")

    with pytest.raises(ValueError, match="group_role_map"):
        config_from_settings()


# ── Discovery ────────────────────────────────────────────────────────────────


async def test_discover_parses_the_document_and_caches_it():
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(DISCOVERY_URL).mock(
            return_value=httpx.Response(200, json=_discovery_document())
        )

        first = await discover()
        second = await discover()

        assert route.call_count == 1

    assert first == _discovery()
    assert second is first

    clear_discovery_cache()

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(DISCOVERY_URL).mock(
            return_value=httpx.Response(200, json=_discovery_document())
        )
        await discover()

    assert route.call_count == 1  # fetched again after the cache was cleared


async def test_discover_uses_the_issuer_argument_for_the_cache_key():
    other = "https://other-idp.test"
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{other}/.well-known/openid-configuration").mock(
            return_value=httpx.Response(200, json=_discovery_document(issuer=other))
        )
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=_discovery_document()))

        from_other = await discover(other)
        from_settings = await discover()

    assert from_other.issuer == other
    assert from_settings.issuer == ISSUER


async def test_discover_requires_the_configured_issuer(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "")

    with pytest.raises(ValueError, match="ZFROG_OIDC_ISSUER"):
        await discover()


async def test_discover_without_jwks_uri_raises():
    with respx.mock(assert_all_called=True) as mock:
        mock.get(DISCOVERY_URL).mock(
            return_value=httpx.Response(200, json=_discovery_document(jwks_uri=""))
        )

        with pytest.raises(ValueError, match="jwks_uri"):
            await discover()


async def test_discover_reports_a_provider_error():
    with respx.mock(assert_all_called=True) as mock:
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(503, text="unavailable"))

        with pytest.raises(ValueError, match="503"):
            await discover()


# ── Authorization redirect ───────────────────────────────────────────────────


def test_authorization_url_carries_every_parameter():
    url = authorization_url(config_from_settings(), _discovery(), "state-123", "nonce-456")

    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZE_URL
    assert parse_qs(parsed.query) == {
        "response_type": ["code"],
        "client_id": [CLIENT_ID],
        "redirect_uri": [REDIRECT_URI],
        "scope": ["openid email profile"],
        "state": ["state-123"],
        "nonce": ["nonce-456"],
    }


def test_authorization_url_keeps_an_existing_query_string():
    discovery = _discovery()
    discovery.authorization_endpoint = f"{AUTHORIZE_URL}?tenant=acme"

    url = authorization_url(config_from_settings(), discovery, "s", "n")

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert params["tenant"] == ["acme"]
    assert params["state"] == ["s"]


def test_new_state_and_nonce_are_unique_and_url_safe():
    state, other_state = new_state(), new_state()
    nonce = new_nonce()

    assert state != other_state
    assert len(state) >= 32 and len(nonce) >= 32
    assert all(character.isalnum() or character in "-_" for character in state + nonce)


# ── Code exchange ────────────────────────────────────────────────────────────


async def test_exchange_code_posts_the_documented_body_with_basic_auth():
    token_payload = {"access_token": "at-1", "id_token": "it-1", "token_type": "Bearer"}

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=token_payload))

        payload = await exchange_code(config_from_settings(), _discovery(), "code-1")

    request = route.calls.last.request
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qs(request.content.decode()) == {
        "grant_type": ["authorization_code"],
        "code": ["code-1"],
        "redirect_uri": [REDIRECT_URI],
    }
    scheme, _, credentials = request.headers["authorization"].partition(" ")
    assert scheme == "Basic"
    assert base64.b64decode(credentials).decode() == f"{CLIENT_ID}:{CLIENT_SECRET}"
    assert payload == token_payload


async def test_exchange_code_sends_the_client_id_in_the_body_for_public_clients(monkeypatch):
    monkeypatch.setattr(settings, "oidc_client_secret", "")

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": "it"}))

        await exchange_code(config_from_settings(), _discovery(), "code-2")

    request = route.calls.last.request
    assert "authorization" not in request.headers
    assert parse_qs(request.content.decode())["client_id"] == [CLIENT_ID]


async def test_exchange_code_reports_the_provider_error():
    with respx.mock(assert_all_called=True) as mock:
        mock.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                400, json={"error": "invalid_grant", "error_description": "code expired"}
            )
        )

        with pytest.raises(ValueError) as excinfo:
            await exchange_code(config_from_settings(), _discovery(), "stale-code")

    message = str(excinfo.value)
    assert "invalid_grant" in message
    assert "code expired" in message
    assert CLIENT_SECRET not in message


async def test_exchange_code_rejects_an_empty_code():
    with pytest.raises(ValueError, match="código"):
        await exchange_code(config_from_settings(), _discovery(), "")


# ── Unverified decoding ──────────────────────────────────────────────────────


def test_decode_unverified_reads_the_header_and_claims():
    token = _rs256_token(_rsa_key(), _claims(sub="user-9"))

    header, claims = decode_unverified(token)

    assert header == {"alg": "RS256", "kid": KID, "typ": "JWT"}
    assert claims["sub"] == "user-9"


@pytest.mark.parametrize(
    "token",
    ["", "not-a-token", "only.two", "a.b.c.d", "!!!.@@@.###", ".."],
)
def test_decode_unverified_rejects_malformed_tokens(token):
    with pytest.raises(ValueError):
        decode_unverified(token)


def test_decode_unverified_rejects_segments_that_are_not_json():
    token = f"{_b64url(b'not json')}.{_b64url(b'{}')}.{_b64url(b'sig')}"

    with pytest.raises(ValueError):
        decode_unverified(token)


# ── Signature verification with real keys ────────────────────────────────────


async def test_verify_accepts_a_token_signed_with_the_jwks_key():
    key = _rsa_key()
    claims = _claims()
    token = _rs256_token(key, claims)

    verified = await _verify_with(token, [_rsa_jwk(key)])

    assert verified.subject == "user-1"
    assert verified.email == "ana@example.com"
    assert verified.name == "Ana Silva"
    assert verified.groups == ["admins"]
    assert verified.issuer == ISSUER
    assert verified.audience == [CLIENT_ID]
    assert verified.expires_at == claims["exp"]
    assert verified.raw["nonce"] == "nonce-1"


async def test_verify_accepts_an_es256_token():
    key = _ec_key()
    token = _sign(key, {"alg": "ES256", "kid": KID, "typ": "JWT"}, _claims())

    verified = await _verify_with(token, [_ec_jwk(key)])

    assert verified.subject == "user-1"


async def test_verify_accepts_an_es256_token_with_a_der_signature():
    key = _ec_key()
    token = _sign_ec_der(key, {"alg": "ES256", "kid": KID, "typ": "JWT"}, _claims())

    verified = await _verify_with(token, [_ec_jwk(key)])

    assert verified.subject == "user-1"


async def test_verify_rejects_an_es256_signature_of_the_wrong_length():
    key = _ec_key()
    header, payload = _segment({"alg": "ES256", "kid": KID}), _segment(_claims())
    # Hoisted out of the f-string: a backslash inside an f-string expression is a
    # SyntaxError before Python 3.12, and this project supports 3.11.
    bad_signature = _b64url(b"\x01\x02\x03")
    token = f"{header}.{payload}.{bad_signature}"

    with pytest.raises(ValueError, match="assinatura"):
        await _verify_with(token, [_ec_jwk(key)])


async def test_verify_accepts_an_audience_list():
    key = _rsa_key()
    token = _rs256_token(key, _claims(aud=["other-client", CLIENT_ID]))

    verified = await _verify_with(token, [_rsa_jwk(key)])

    assert verified.audience == ["other-client", CLIENT_ID]


async def test_verify_rejects_a_token_signed_by_another_key():
    key, attacker = _rsa_key(), _rsa_key()
    token = _rs256_token(attacker)

    with pytest.raises(ValueError, match="assinatura"):
        await _verify_with(token, [_rsa_jwk(key)])


async def test_verify_rejects_a_tampered_payload():
    key = _rsa_key()
    token = _rs256_token(key)
    header, payload, signature = token.split(".")
    tampered = f"{header}.{_segment(_claims(sub='admin-1', groups=['admins']))}.{signature}"

    with pytest.raises(ValueError, match="assinatura"):
        await _verify_with(tampered, [_rsa_jwk(key)])


async def test_verify_rejects_an_audience_list_without_the_client_id():
    key = _rsa_key()
    token = _rs256_token(key, _claims(aud=["other-client", "another"]))

    with pytest.raises(ValueError, match="aud"):
        await _verify_with(token, [_rsa_jwk(key)])


async def test_verify_rejects_an_es256_token_signed_by_another_key():
    key, attacker = _ec_key(), _ec_key()
    token = _sign(attacker, {"alg": "ES256", "kid": KID, "typ": "JWT"}, _claims())

    with pytest.raises(ValueError, match="assinatura"):
        await _verify_with(token, [_ec_jwk(key)])


async def test_verify_rejects_an_rsa_signature_checked_against_an_ec_key():
    key, other = _rsa_key(), _ec_key()
    token = _rs256_token(key)

    with pytest.raises(ValueError, match="assinatura"):
        await _verify_with(token, [_ec_jwk(other)])


async def test_verify_rejects_a_wrong_issuer():
    key = _rsa_key()
    token = _rs256_token(key, _claims(iss="https://evil.test"))

    with pytest.raises(ValueError, match="iss"):
        await _verify_with(token, [_rsa_jwk(key)])


async def test_verify_rejects_a_wrong_audience():
    key = _rsa_key()
    token = _rs256_token(key, _claims(aud="another-client"))

    with pytest.raises(ValueError, match="aud"):
        await _verify_with(token, [_rsa_jwk(key)])


async def test_verify_rejects_an_expired_token():
    key = _rsa_key()
    token = _rs256_token(key, _claims(exp=int(time.time()) - 3600))

    with pytest.raises(ValueError, match="exp"):
        await _verify_with(token, [_rsa_jwk(key)])


async def test_verify_tolerates_small_clock_skew():
    key = _rsa_key()
    token = _rs256_token(key, _claims(exp=int(time.time()) - 5))

    verified = await _verify_with(token, [_rsa_jwk(key)])

    assert verified.subject == "user-1"


async def test_verify_rejects_a_mismatched_nonce():
    key = _rsa_key()
    token = _rs256_token(key, _claims(nonce="nonce-from-another-login"))

    with pytest.raises(ValueError, match="nonce"):
        await _verify_with(token, [_rsa_jwk(key)], nonce="nonce-1")


async def test_verify_rejects_an_unknown_kid():
    key = _rsa_key()
    token = _rs256_token(key, kid="rotated-key")

    with pytest.raises(ValueError, match="kid"):
        await _verify_with(token, [_rsa_jwk(key)])


@pytest.mark.parametrize("alg", ["none", "HS256", ""])
async def test_verify_rejects_unsupported_algorithms(alg):
    key = _rsa_key()
    token = _sign(key, {"alg": alg, "kid": KID}, _claims())

    with pytest.raises(ValueError, match="algoritmo"):
        await _verify_with(token, [_rsa_jwk(key)])


async def test_verify_rejects_a_token_without_a_kid():
    key = _rsa_key()
    token = _sign(key, {"alg": "RS256", "typ": "JWT"}, _claims())

    with pytest.raises(ValueError, match="kid"):
        await _verify_with(token, [_rsa_jwk(key)])


async def test_verify_reports_a_jwks_that_cannot_be_fetched():
    key = _rsa_key()

    with respx.mock(assert_all_called=True) as mock:
        mock.get(JWKS_URL).mock(return_value=httpx.Response(500, text="boom"))

        with pytest.raises(ValueError, match="500"):
            await verify_id_token(_rs256_token(key), config_from_settings(), _discovery())


# ── Group to role mapping ────────────────────────────────────────────────────


def test_role_from_groups_picks_the_highest_privilege():
    mapping = {"admins": "admin", "devs": "operator", "readers": "viewer"}

    assert role_from_groups(["readers", "devs"], mapping) == "operator"
    assert role_from_groups(["devs", "admins", "readers"], mapping) == "admin"
    assert role_from_groups(["readers"], mapping) == "viewer"


def test_role_from_groups_ignores_the_mapping_order():
    mapping = {"readers": "viewer", "admins": "admin"}

    assert role_from_groups(["admins", "readers"], mapping) == "admin"


def test_role_from_groups_falls_back_to_the_default():
    assert role_from_groups([], {"admins": "admin"}) == "viewer"
    assert role_from_groups(["outsiders"], {"admins": "admin"}) == "viewer"
    assert role_from_groups(["outsiders"], {"admins": "admin"}, default="operator") == "operator"


# ── End to end ───────────────────────────────────────────────────────────────


async def test_complete_login_returns_the_user_and_role():
    key = _rsa_key()
    token = _rs256_token(key, _claims(groups=["devs"], nonce="nonce-xyz"))

    with respx.mock(assert_all_called=True) as mock:
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=_discovery_document()))
        mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json={"keys": [_rsa_jwk(key)]}))
        token_route = mock.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "at-1", "id_token": token, "token_type": "Bearer"}
            )
        )

        discovery = await discover()
        result = await complete_login(
            config_from_settings(), discovery, "code-xyz", nonce="nonce-xyz"
        )

    assert parse_qs(token_route.calls.last.request.content.decode())["code"] == ["code-xyz"]
    assert result.user == {
        "subject": "user-1",
        "email": "ana@example.com",
        "name": "Ana Silva",
    }
    assert result.role == "operator"
    assert result.role in ROLES  # a role the API can actually enforce
    assert result.claims.groups == ["devs"]


async def test_complete_login_rejects_a_token_for_another_nonce():
    key = _rsa_key()
    token = _rs256_token(key, _claims(nonce="nonce-from-another-login"))

    with respx.mock(assert_all_called=True) as mock:
        mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json={"keys": [_rsa_jwk(key)]}))
        mock.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"id_token": token, "token_type": "Bearer"})
        )

        with pytest.raises(ValueError, match="nonce"):
            await complete_login(
                config_from_settings(), _discovery(), "code-xyz", nonce="nonce-xyz"
            )


async def test_complete_login_requires_an_id_token():
    with respx.mock(assert_all_called=True) as mock:
        mock.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "at-1"})
        )

        with pytest.raises(ValueError, match="id_token"):
            await complete_login(config_from_settings(), _discovery(), "code-xyz")


async def test_complete_login_never_leaks_the_client_secret():
    with respx.mock(assert_all_called=True) as mock:
        mock.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                401,
                json={
                    "error": "invalid_client",
                    "error_description": f"client {CLIENT_ID} rejected secret {CLIENT_SECRET}",
                },
            )
        )

        with pytest.raises(ValueError) as excinfo:
            await complete_login(config_from_settings(), _discovery(), "code-xyz")

    assert CLIENT_SECRET not in str(excinfo.value)
