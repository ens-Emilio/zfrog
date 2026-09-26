"""OpenID Connect single sign-on, implemented without a JWT dependency.

The authorization-code flow lives here: build the redirect, exchange the code
at the token endpoint, then verify the ID token for real. ``pyjwt`` and
``python-jose`` are not installed, so RS256/ES256 signature verification is
done by hand with ``cryptography``: the token's ``kid`` selects a key from the
provider's JWKS, and the signature over ``header.payload`` is checked against
that public key before any claim is trusted.

Nothing in this module trusts an unverified token: :func:`decode_unverified`
exists only to read the header (to find the ``kid``) and is named to make that
obvious. Every failure raises :class:`ValueError` — the API turns it into a
400/401 — and the client secret never appears in an error message.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from zfrog.config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "IdTokenClaims",
    "LoginResult",
    "OidcConfig",
    "OidcDiscovery",
    "authorization_url",
    "clear_discovery_cache",
    "complete_login",
    "config_from_settings",
    "decode_unverified",
    "discover",
    "exchange_code",
    "is_configured",
    "new_nonce",
    "new_state",
    "parse_group_role_map",
    "role_from_groups",
    "verify_id_token",
]

#: Where the provider publishes its endpoints, relative to the issuer.
DISCOVERY_PATH = "/.well-known/openid-configuration"

#: Signature algorithms this module can verify by hand.
SUPPORTED_ALGORITHMS = ("RS256", "ES256")

#: Tolerated clock difference when checking ``exp``.
CLOCK_SKEW_S = 60

HTTP_TIMEOUT = 15.0

#: Base64url without padding, the only alphabet a JWT segment may use.
_B64URL_RE = re.compile(r"[A-Za-z0-9_-]*")

#: Roles from most to least privileged, used by :func:`role_from_groups`.
_ROLE_PRIORITY = {"admin": 3, "operator": 2, "viewer": 1}

#: Discovery documents, keyed by normalised issuer, so logins do not re-fetch.
_DISCOVERY_CACHE: dict[str, OidcDiscovery] = {}


@dataclass
class OidcConfig:
    """Everything needed to talk to one OpenID Connect provider."""

    issuer: str
    client_id: str
    client_secret: str = ""
    redirect_uri: str = ""
    scopes: list[str] = field(default_factory=list)
    username_claim: str = "email"
    groups_claim: str = "groups"
    group_role_map: dict[str, str] = field(default_factory=dict)


@dataclass
class OidcDiscovery:
    """The provider endpoints read from its discovery document."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str = ""
    end_session_endpoint: str = ""


@dataclass
class IdTokenClaims:
    """The claims of a *verified* ID token."""

    subject: str
    email: str
    name: str
    groups: list[str]
    issuer: str
    audience: list[str]
    expires_at: int
    raw: dict[str, Any]


@dataclass
class LoginResult:
    """A finished login: the user fields, the mapped role and the raw claims."""

    user: dict[str, Any]
    role: str
    claims: IdTokenClaims


def parse_group_role_map(text: str) -> dict[str, str]:
    """Parse ``"admins=admin,devs=operator"`` into ``{"admins": "admin", ...}``."""
    mapping: dict[str, str] = {}
    for chunk in (text or "").split(","):
        entry = chunk.strip()
        if not entry:
            continue
        group, sep, role = entry.partition("=")
        group, role = group.strip(), role.strip()
        if not sep or not group or not role:
            raise ValueError(
                f"oidc_group_role_map inválido: {entry!r} — use 'grupo=papel,outro=papel'"
            )
        mapping[group] = role
    return mapping


def config_from_settings() -> OidcConfig:
    """Build an :class:`OidcConfig` from the ``oidc_*`` settings.

    Raises:
        ValueError: when the issuer or the client id is not set.
    """
    issuer = (settings.oidc_issuer or "").strip().rstrip("/")
    client_id = (settings.oidc_client_id or "").strip()
    if not issuer or not client_id:
        raise ValueError("configure ZFROG_OIDC_ISSUER and ZFROG_OIDC_CLIENT_ID")

    return OidcConfig(
        issuer=issuer,
        client_id=client_id,
        client_secret=(settings.oidc_client_secret or "").strip(),
        redirect_uri=(settings.oidc_redirect_uri or "").strip(),
        scopes=[scope for scope in (settings.oidc_scopes or "").split() if scope],
        username_claim=(settings.oidc_username_claim or "email").strip() or "email",
        groups_claim=(settings.oidc_groups_claim or "groups").strip() or "groups",
        group_role_map=parse_group_role_map(settings.oidc_group_role_map),
    )


def is_configured() -> bool:
    """Return True when both the issuer and the client id are set. Never raises."""
    return bool((settings.oidc_issuer or "").strip() and (settings.oidc_client_id or "").strip())


def clear_discovery_cache() -> None:
    """Drop the cached discovery documents (used by tests and after reconfiguring)."""
    _DISCOVERY_CACHE.clear()


def new_state() -> str:
    """Return a fresh, unguessable OAuth ``state`` value."""
    return secrets.token_urlsafe(32)


def new_nonce() -> str:
    """Return a fresh, unguessable OpenID Connect ``nonce`` value."""
    return secrets.token_urlsafe(32)


async def discover(
    issuer: str | None = None, client: httpx.AsyncClient | None = None
) -> OidcDiscovery:
    """Read ``<issuer>/.well-known/openid-configuration`` and cache it per issuer.

    Args:
        issuer: the provider issuer; defaults to the configured one.
        client: an optional HTTP client (tests inject one); one is created and
            closed here when omitted.

    Raises:
        ValueError: when no issuer is known, the document cannot be fetched or
            is missing a required endpoint.
    """
    base = (issuer or settings.oidc_issuer or "").strip().rstrip("/")
    if not base:
        raise ValueError("configure ZFROG_OIDC_ISSUER and ZFROG_OIDC_CLIENT_ID")

    cached = _DISCOVERY_CACHE.get(base)
    if cached is not None:
        return cached

    document = await _get_json(base + DISCOVERY_PATH, client)
    discovery = _discovery_from_document(document, base)
    _DISCOVERY_CACHE[base] = discovery
    logger.debug("descoberta OIDC carregada de %s", base)
    return discovery


def authorization_url(config: OidcConfig, discovery: OidcDiscovery, state: str, nonce: str) -> str:
    """Return the provider URL the user's browser must be sent to."""
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": " ".join(config.scopes),
        "state": state,
        "nonce": nonce,
    }
    separator = "&" if "?" in discovery.authorization_endpoint else "?"
    return f"{discovery.authorization_endpoint}{separator}{urlencode(params)}"


async def exchange_code(
    config: OidcConfig,
    discovery: OidcDiscovery,
    code: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Exchange an authorization ``code`` for tokens at the token endpoint.

    The client id and secret go in an HTTP Basic header when a secret is
    configured, otherwise the client id is sent in the form body (public
    clients).

    Raises:
        ValueError: on a missing code, a network failure, a non-2xx response or
            a body that is not a JSON object.
    """
    if not code:
        raise ValueError("código de autorização ausente")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
    }
    auth: httpx.BasicAuth | None = None
    if config.client_secret:
        auth = httpx.BasicAuth(config.client_id, config.client_secret)
    else:
        data["client_id"] = config.client_id

    return await _post_form(discovery.token_endpoint, data, auth, config.client_secret, client)


def decode_unverified(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a JWT and decode its header and payload **without verifying**.

    Used to read the ``alg``/``kid`` needed to pick a key. The result must
    never be trusted on its own — call :func:`verify_id_token` for that.

    Raises:
        ValueError: when the token is not a well-formed three-part JWT.
    """
    parts = token.split(".") if isinstance(token, str) else []
    if len(parts) != 3 or not parts[0] or not parts[1]:
        raise ValueError("ID token malformado: esperado header.payload.signature")
    return _decode_json_segment(parts[0], "cabeçalho"), _decode_json_segment(parts[1], "payload")


async def verify_id_token(
    token: str,
    config: OidcConfig,
    discovery: OidcDiscovery,
    client: httpx.AsyncClient | None = None,
    nonce: str = "",
) -> IdTokenClaims:
    """Verify an ID token and return its claims.

    Checks, in order: the signature (RS256/ES256, key picked by ``kid`` from
    the provider JWKS), ``iss``, ``aud``, ``exp`` (with 60s of skew) and — when
    ``nonce`` is supplied — that the token echoes it.

    Args:
        token: the raw compact JWT from the token endpoint.
        config: the provider configuration (client id, username claim).
        discovery: the provider endpoints (issuer, JWKS URI).
        client: an optional HTTP client; one is created and closed here when
            omitted.
        nonce: the value from the login that started this flow, if any.

    Raises:
        ValueError: naming whichever check failed.
    """
    header, claims = decode_unverified(token)

    alg = str(header.get("alg") or "")
    if alg not in SUPPORTED_ALGORITHMS:
        raise ValueError(f"algoritmo de assinatura não suportado: {alg!r}")

    kid = header.get("kid")
    if not kid:
        raise ValueError("ID token sem 'kid' no cabeçalho")

    jwks = await _get_json(discovery.jwks_uri, client)
    jwk = _find_jwk(jwks, str(kid))
    if jwk is None:
        raise ValueError(f"kid desconhecido no JWKS do provedor: {kid!r}")

    _verify_signature(token, jwk, alg)
    _check_issuer(claims, discovery.issuer)
    _check_audience(claims, config.client_id)
    _check_expiry(claims)
    _check_nonce(claims, nonce)
    return _claims_from(claims, config)


def role_from_groups(
    groups: list[str],
    mapping: dict[str, str],
    default: str = "viewer",
) -> str:
    """Map identity-provider groups to a Zfrog role.

    The **highest-privilege** match wins: ``admin`` beats ``operator`` beats
    ``viewer``, regardless of the order the groups appear in. A mapped role
    with no known privilege is taken only when nothing better matched, and an
    empty match falls back to ``default``.
    """
    best = ""
    best_rank = -1
    for group in groups:
        role = mapping.get(group)
        if not role:
            continue
        rank = _ROLE_PRIORITY.get(role, 0)
        if rank > best_rank:
            best, best_rank = role, rank
    return best or default


async def complete_login(
    config: OidcConfig,
    discovery: OidcDiscovery,
    code: str,
    nonce: str = "",
    client: httpx.AsyncClient | None = None,
) -> LoginResult:
    """Finish a login: exchange the code, verify the ID token, map the role.

    Raises:
        ValueError: whatever :func:`exchange_code` or :func:`verify_id_token`
            rejected.
    """
    payload = await exchange_code(config, discovery, code, client=client)
    token = str(payload.get("id_token") or "")
    if not token:
        raise ValueError("resposta do provedor sem 'id_token'")
    claims = await verify_id_token(token, config, discovery, client=client, nonce=nonce)
    role = role_from_groups(claims.groups, config.group_role_map)
    user = {"subject": claims.subject, "email": claims.email, "name": claims.name}
    logger.info("login SSO concluído para %s (papel %s)", claims.subject or claims.email, role)
    return LoginResult(user=user, role=role, claims=claims)


# ── HTTP helpers ─────────────────────────────────────────────────────────────


async def _get_json(url: str, client: httpx.AsyncClient | None) -> dict[str, Any]:
    """GET ``url`` and return its JSON object body."""
    if client is None:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as owned:
            response = await _request(owned, "GET", url)
    else:
        response = await _request(client, "GET", url)

    if response.status_code // 100 != 2:
        raise ValueError(f"falha ao consultar {url} (HTTP {response.status_code})")
    return _json_object(response, url)


async def _post_form(
    url: str,
    data: dict[str, str],
    auth: httpx.BasicAuth | None,
    secret: str,
    client: httpx.AsyncClient | None,
) -> dict[str, Any]:
    """POST a form body and return the JSON object response."""
    headers = {"Accept": "application/json"}
    if client is None:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as owned:
            response = await _request(owned, "POST", url, data=data, auth=auth, headers=headers)
    else:
        response = await _request(client, "POST", url, data=data, auth=auth, headers=headers)

    if response.status_code // 100 != 2:
        detail = _redact(_error_detail(response), secret)
        raise ValueError(
            f"falha ao trocar o código por tokens (HTTP {response.status_code}): {detail}"
        )
    return _json_object(response, url)


async def _request(
    client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
) -> httpx.Response:
    """Send one request, turning transport errors into :class:`ValueError`."""
    try:
        return await client.request(method, url, **kwargs)
    except httpx.HTTPError as e:
        raise ValueError(f"falha de rede ao consultar {url}: {e}") from e


def _json_object(response: httpx.Response, url: str) -> dict[str, Any]:
    """Return the response body as a JSON object."""
    try:
        document = response.json()
    except ValueError as e:
        raise ValueError(f"resposta não-JSON de {url}: {e}") from e
    if not isinstance(document, dict):
        raise ValueError(f"resposta inesperada de {url}: esperado um objeto JSON")
    return document


def _error_detail(response: httpx.Response) -> str:
    """Render the provider's error text (``error``/``error_description``)."""
    try:
        document = response.json()
    except ValueError:
        document = None
    if isinstance(document, dict):
        error = str(document.get("error") or "").strip()
        description = str(document.get("error_description") or "").strip()
        if error or description:
            return f"{error}: {description}".strip(": ") if description else error
    return (response.text or "").strip()[:400]


def _redact(message: str, secret: str) -> str:
    """Remove ``secret`` from a message; a leaked secret must never be echoed."""
    return message.replace(secret, "***") if secret and secret in message else message


# ── Discovery / JWKS parsing ─────────────────────────────────────────────────


def _discovery_from_document(document: dict[str, Any], base: str) -> OidcDiscovery:
    """Build an :class:`OidcDiscovery`, requiring the endpoints we actually use."""
    values: dict[str, str] = {}
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = str(document.get(key) or "").strip()
        if not value:
            raise ValueError(f"documento de descoberta sem {key!r}")
        values[key] = value

    return OidcDiscovery(
        issuer=str(document.get("issuer") or base).strip().rstrip("/") or base,
        authorization_endpoint=values["authorization_endpoint"],
        token_endpoint=values["token_endpoint"],
        jwks_uri=values["jwks_uri"],
        userinfo_endpoint=str(document.get("userinfo_endpoint") or "").strip(),
        end_session_endpoint=str(document.get("end_session_endpoint") or "").strip(),
    )


def _find_jwk(document: dict[str, Any], kid: str) -> dict[str, Any] | None:
    """Return the JWK with ``kid`` from a JWKS document."""
    keys = document.get("keys")
    if not isinstance(keys, list):
        raise ValueError("JWKS inválido: falta a lista 'keys'")
    for key in keys:
        if isinstance(key, dict) and str(key.get("kid") or "") == kid:
            return key
    return None


def _public_key_from_jwk(jwk: dict[str, Any]) -> rsa.RSAPublicKey | ec.EllipticCurvePublicKey:
    """Turn a JWK into a ``cryptography`` public key."""
    kty = jwk.get("kty")
    try:
        if kty == "RSA":
            return rsa.RSAPublicNumbers(
                _int_from_b64url(jwk.get("e"), "e"),
                _int_from_b64url(jwk.get("n"), "n"),
            ).public_key()
        if kty == "EC":
            curve = jwk.get("crv")
            if curve != "P-256":
                raise ValueError(f"curva EC não suportada: {curve!r}")
            return ec.EllipticCurvePublicNumbers(
                _int_from_b64url(jwk.get("x"), "x"),
                _int_from_b64url(jwk.get("y"), "y"),
                ec.SECP256R1(),
            ).public_key()
    except (TypeError, ValueError) as e:
        raise ValueError(f"chave JWKS inválida: {e}") from e
    raise ValueError(f"tipo de chave JWKS não suportado: {kty!r}")


def _int_from_b64url(value: Any, name: str) -> int:
    """Decode a base64url big-endian integer parameter of a JWK."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"JWK sem {name!r}")
    return int.from_bytes(_b64url_decode(value), "big")


# ── Signature and claim checks ───────────────────────────────────────────────


def _verify_signature(token: str, jwk: dict[str, Any], alg: str) -> None:
    """Verify the token signature with the public key from ``jwk``."""
    parts = token.split(".")
    if len(parts) != 3 or not parts[2]:
        raise ValueError("ID token malformado: assinatura ausente")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    signature = _b64url_decode(parts[2])
    key = _public_key_from_jwk(jwk)

    try:
        if alg == "RS256":
            if not isinstance(key, rsa.RSAPublicKey):
                raise ValueError("assinatura RS256, mas a chave do JWKS não é RSA")
            key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        else:
            if not isinstance(key, ec.EllipticCurvePublicKey):
                raise ValueError("assinatura ES256, mas a chave do JWKS não é EC")
            key.verify(
                _ec_signature_to_der(signature, key), signing_input, ec.ECDSA(hashes.SHA256())
            )
    except InvalidSignature as e:
        raise ValueError("assinatura do ID token inválida") from e
    except (UnsupportedAlgorithm, TypeError, ValueError) as e:
        raise ValueError(f"assinatura do ID token inválida: {e}") from e


def _ec_signature_to_der(signature: bytes, key: ec.EllipticCurvePublicKey) -> bytes:
    """Convert a JWS ECDSA signature to the DER form ``cryptography`` verifies.

    A JWS ``ES256`` signature is the fixed-width concatenation of ``R`` and
    ``S`` (RFC 7518), while ``cryptography`` expects DER-encoded ASN.1. A
    signature that is already DER is passed through, so tokens built by tools
    that skip the JWS encoding still verify.
    """
    size = (key.curve.key_size + 7) // 8
    if len(signature) == 2 * size:
        r = int.from_bytes(signature[:size], "big")
        s = int.from_bytes(signature[size:], "big")
        return encode_dss_signature(r, s)
    if signature[:1] == b"\x30":
        return signature
    raise ValueError(
        f"assinatura ECDSA com tamanho inesperado: {len(signature)} bytes (esperado {2 * size})"
    )


def _check_issuer(claims: dict[str, Any], expected: str) -> None:
    """Require ``iss`` to match the issuer of the discovery document."""
    issuer = claims.get("iss")
    if str(issuer or "").rstrip("/") != expected.rstrip("/"):
        raise ValueError(f"iss do ID token não confere: {issuer!r} != {expected!r}")


def _check_audience(claims: dict[str, Any], client_id: str) -> None:
    """Require ``aud`` (a string or a list) to contain the client id."""
    if client_id not in _audience_list(claims.get("aud")):
        raise ValueError(f"aud do ID token não contém o client id: {claims.get('aud')!r}")


def _audience_list(value: Any) -> list[str]:
    """Normalise the ``aud`` claim: a single string stays one value, never split."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item)]
    return []


def _check_expiry(claims: dict[str, Any]) -> None:
    """Require ``exp`` to be in the future, allowing 60s of clock skew."""
    expires_at = claims.get("exp")
    if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
        raise ValueError("ID token sem 'exp' numérico")
    if float(expires_at) < time.time() - CLOCK_SKEW_S:
        raise ValueError(f"ID token expirado (exp={expires_at})")


def _check_nonce(claims: dict[str, Any], nonce: str) -> None:
    """Require the token to echo ``nonce`` when one was supplied."""
    if not nonce:
        return
    if claims.get("nonce") != nonce:
        raise ValueError("nonce do ID token não confere com o da requisição")


def _claims_from(claims: dict[str, Any], config: OidcConfig) -> IdTokenClaims:
    """Project the raw claims onto :class:`IdTokenClaims`."""
    subject = str(claims.get("sub") or "")
    # Providers put the address in "email"; some use a custom username claim.
    email = str(claims.get("email") or claims.get(config.username_claim) or "")
    name = str(claims.get("name") or claims.get("preferred_username") or email)
    expires_at = claims.get("exp")
    return IdTokenClaims(
        subject=subject,
        email=email,
        name=name,
        groups=_as_list(claims.get(config.groups_claim)),
        issuer=str(claims.get("iss") or ""),
        audience=_audience_list(claims.get("aud")),
        expires_at=int(expires_at) if isinstance(expires_at, (int, float)) else 0,
        raw=dict(claims),
    )


# ── Encoding helpers ─────────────────────────────────────────────────────────


def _as_list(value: Any) -> list[str]:
    """Normalise a claim that may be a string, a list or absent into ``list[str]``."""
    if isinstance(value, str):
        return [item for item in re.split(r"[,\s]+", value.strip()) if item]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item)]
    return []


def _b64url_decode(segment: str) -> bytes:
    """Decode an unpadded base64url segment, rejecting anything malformed."""
    if not _B64URL_RE.fullmatch(segment):
        raise ValueError("segmento base64url inválido")
    padded = segment + "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"segmento base64url inválido: {e}") from e


def _decode_json_segment(segment: str, label: str) -> dict[str, Any]:
    """Decode one base64url JSON object segment of a JWT."""
    try:
        document = json.loads(_b64url_decode(segment))
    except ValueError as e:
        raise ValueError(f"{label} do ID token ilegível: {e}") from e
    if not isinstance(document, dict):
        raise ValueError(f"{label} do ID token não é um objeto JSON")
    return document
