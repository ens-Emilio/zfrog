"""API authentication and role-based access control.

Keys are stored as SHA-256 digests in a JSON file owned by the process
(``settings.api_keys_file``). The plaintext secret is shown once, at creation
time, and cannot be recovered afterwards — losing it means creating a new key.

Role matrix (``ROLES``), where ``*`` grants every action and ``read:*`` grants
every action in the ``read`` namespace:

    ===========  ==========================================================
    role         permitted actions
    ===========  ==========================================================
    ``viewer``   ``read:*``
    ``operator`` ``read:*``, ``job:create``, ``job:cancel``
    ``admin``    everything, including ``key:manage``, ``schedule:manage``
                 and ``version:manage``
    ===========  ==========================================================

Authorisation is open while ``settings.auth_enabled`` is false, so deployments
that predate this module keep working; set it to true to enforce the matrix.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping

from zfrog.config import settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import Request

logger = logging.getLogger(__name__)

#: Key files hold credential digests: keep them owner-only.
KEY_FILE_MODE = 0o600

#: Every generated secret carries this prefix, so leaked strings are greppable.
KEY_PREFIX = "zk_"

#: Role -> granted actions. ``"*"`` matches anything, ``"<ns>:*"`` a namespace.
ROLES: dict[str, set[str]] = {
    "viewer": {"read:*"},
    "operator": {"read:*", "job:create", "job:cancel"},
    "admin": {"*"},
}

#: Actor used when a request carries no usable credential.
ANONYMOUS = "anonymous"


def hash_key(secret: str) -> str:
    """Return the SHA-256 hex digest of ``secret``.

    Only this digest is ever stored: the plaintext key is shown once at
    creation time and cannot be recovered from the key file.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_key() -> tuple[str, str]:
    """Return a fresh ``(secret, hash)`` pair, the secret prefixed with ``zk_``."""
    secret = KEY_PREFIX + secrets.token_urlsafe(32)
    return secret, hash_key(secret)


def role_allows(role: str, action: str) -> bool:
    """Return True when ``role`` may perform ``action`` according to :data:`ROLES`."""
    for granted in ROLES.get(role, set()):
        if granted == "*" or granted == action:
            return True
        if granted.endswith(":*") and action.startswith(granted[:-1]):
            return True
    return False


@dataclass
class ApiKey:
    """One stored credential. ``hash`` is the digest of the secret, never the secret."""

    id: str
    name: str
    role: str
    hash: str
    created_at: str
    last_used_at: str | None = None
    enabled: bool = True
    # Organization this key belongs to; "" means the shared/default area.
    org: str = ""


@dataclass
class AuthDecision:
    """Outcome of an authorisation check, ready for logging or an HTTP error."""

    allowed: bool
    actor: str
    role: str
    reason: str
    #: Organization whose workspace the data belongs to ("" = the shared area).
    org: str = ""
    #: Which credential was used: "key", "session", or "" when unidentified.
    via: str = ""


@dataclass(frozen=True)
class Identity:
    """A resolved caller: who it is, what it may do, and where its data lives.

    Two credential kinds reach this shape — an API key (``via="key"``) and a
    dashboard session cookie (``via="session"``) — so the rest of the code has a
    single notion of "the caller" instead of re-deriving one per endpoint.
    """

    actor: str
    role: str
    org: str
    via: str


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def extract_credential(headers: Mapping[str, str] | None) -> str | None:
    """Return the secret carried by ``headers``.

    ``Authorization: Bearer <secret>`` wins, then ``X-API-Key: <secret>``; the
    header names are matched case-insensitively. Returns None when neither
    header carries a non-empty value.
    """
    if not headers:
        return None

    lowered = {str(name).lower(): value for name, value in headers.items()}

    authorization = str(lowered.get("authorization") or "").strip()
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()

    api_key = str(lowered.get("x-api-key") or "").strip()
    return api_key or None


class ApiKeyStore:
    """JSON-file store of API keys (digests only), written atomically with mode 0600."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else Path(settings.api_keys_file)

    # ── writing ──

    def create(self, name: str, role: str = "viewer", org: str = "") -> tuple[str, ApiKey]:
        """Store a new key and return ``(secret, key)``.

        The secret is returned exactly once; only its hash is persisted. An
        unknown role raises ValueError. ``org`` ties the key to an organization,
        which is what decides where its data is written.
        """
        if role not in ROLES:
            raise ValueError(
                f"papel desconhecido: {role!r} (válidos: {', '.join(sorted(ROLES))})"
            )

        secret, digest = generate_key()
        key = ApiKey(
            id=secrets.token_hex(8),
            name=str(name).strip() or "sem nome",
            role=role,
            hash=digest,
            created_at=_now(),
            last_used_at=None,
            enabled=True,
            org=str(org or "").strip(),
        )
        keys = self._load()
        keys.append(key)
        self._save(keys)
        return secret, key

    def revoke(self, key_id: str) -> bool:
        """Delete ``key_id``; return False when it does not exist."""
        keys = self._load()
        remaining = [key for key in keys if key.id != key_id]
        if len(remaining) == len(keys):
            return False
        self._save(remaining)
        return True

    def set_enabled(self, key_id: str, enabled: bool) -> bool:
        """Enable or disable ``key_id``; return False when it does not exist."""
        keys = self._load()
        for key in keys:
            if key.id == key_id:
                key.enabled = bool(enabled)
                self._save(keys)
                return True
        return False

    # ── reading ──

    def list(self) -> list[ApiKey]:
        """Return every stored key, oldest first."""
        return self._load()

    def get(self, key_id: str) -> ApiKey | None:
        """Return the key with ``key_id``, or None."""
        for key in self._load():
            if key.id == key_id:
                return key
        return None

    def verify(self, secret: str) -> ApiKey | None:
        """Return the enabled key matching ``secret``, else None.

        The digest comparison is constant-time. A successful match stamps
        ``last_used_at``; a disabled key never matches.
        """
        if not secret:
            return None

        digest = hash_key(secret)
        keys = self._load()
        for key in keys:
            if not hmac.compare_digest(key.hash, digest):
                continue
            if not key.enabled:
                logger.warning("Chave %s está desativada", key.id)
                return None
            key.last_used_at = _now()
            self._save(keys)
            return key
        return None

    # ── file handling ──

    def _load(self) -> list[ApiKey]:
        """Read the key file; a missing or empty file means "no keys"."""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []

        if not raw.strip():
            return []

        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise ValueError(f"arquivo de chaves inválido ({self.path}): {exc}") from exc

        if not isinstance(data, list):
            raise ValueError(f"arquivo de chaves inválido ({self.path}): esperado uma lista")
        return [self._from_dict(item) for item in data]

    def _from_dict(self, item: object) -> ApiKey:
        """Build an ApiKey from one JSON record."""
        if not isinstance(item, dict):
            raise ValueError(f"arquivo de chaves inválido ({self.path}): registro não é objeto")

        required = ("id", "name", "role", "hash", "created_at")
        missing = [field for field in required if not item.get(field)]
        if missing:
            raise ValueError(
                f"arquivo de chaves inválido ({self.path}): faltam campos {', '.join(missing)}"
            )

        return ApiKey(
            id=str(item["id"]),
            name=str(item["name"]),
            role=str(item["role"]),
            hash=str(item["hash"]),
            created_at=str(item["created_at"]),
            last_used_at=item.get("last_used_at") or None,
            enabled=bool(item.get("enabled", True)),
            org=str(item.get("org") or ""),
        )

    def _save(self, keys: list[ApiKey]) -> None:
        """Write the whole list atomically (temp file + os.replace) as mode 0600."""
        payload = json.dumps([asdict(key) for key in keys], indent=2, ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        handle_fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, KEY_FILE_MODE)
            os.replace(temp_name, self.path)
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise


def authorize(secret: str | None, action: str, store: ApiKeyStore | None = None) -> AuthDecision:
    """Decide whether ``secret`` may perform ``action``.

    While ``settings.auth_enabled`` is false every request is allowed as actor
    ``"anonymous"`` (the default keeps existing deployments open). When it is
    true, a missing secret, an unknown/disabled key or a role that lacks the
    action is denied; a valid key is allowed with its name as actor. Denials are
    logged at warning level.
    """
    if not settings.auth_enabled:
        return AuthDecision(True, ANONYMOUS, ANONYMOUS, "autenticação desativada")

    key_store = store if store is not None else ApiKeyStore()

    if not secret:
        decision = AuthDecision(False, ANONYMOUS, "", "credencial ausente")
    else:
        key = key_store.verify(secret)
        if key is None:
            decision = AuthDecision(False, ANONYMOUS, "", "chave desconhecida ou desativada")
        elif not role_allows(key.role, action):
            decision = AuthDecision(
                False, key.name, key.role, f"papel '{key.role}' não permite a ação '{action}'"
            )
        else:
            decision = AuthDecision(
                True, key.name, key.role, f"papel '{key.role}' permite a ação '{action}'"
            )

    if not decision.allowed:
        logger.warning(
            "Acesso negado a %s (papel %s) para %s: %s",
            decision.actor,
            decision.role or "nenhum",
            action,
            decision.reason,
        )
    return decision


def identify(
    headers: Mapping[str, str] | None,
    cookies: Mapping[str, str] | None = None,
) -> Identity | None:
    """Resolve the caller from an API key or a dashboard session cookie.

    The API key is tried first: it is what machine clients send, and a browser
    that somehow carries both should be treated as the more explicit credential.

    Never raises. A store that cannot be read means "not identified", which the
    callers turn into a denial — the one direction that is safe to fail in.
    """
    secret = extract_credential(headers)
    if secret:
        try:
            key = ApiKeyStore().verify(secret)
        except Exception as exc:
            logger.warning("Falha ao verificar chave de API: %s", exc)
            return None
        if key is not None:
            return Identity(actor=key.name, role=key.role, org=key.org, via="key")

    # Imported here: `zfrog.users` imports ROLES from this module, so a
    # module-level import would be a cycle.
    from zfrog.users import UserStore
    from zfrog.websession import SESSION_COOKIE, verify

    token = (cookies or {}).get(SESSION_COOKIE)
    if token:
        try:
            user_id = verify(token)
            user = UserStore().get(user_id) if user_id else None
        except Exception as exc:
            logger.warning("Falha ao verificar sessão do painel: %s", exc)
            return None
        if user is not None and user.enabled:
            # Role and org come from the store, not the cookie, so a change or a
            # revocation applies on the next request.
            return Identity(
                actor=user.email or user.id,
                role=user.role,
                org=user.orgs[0] if user.orgs else "",
                via="session",
            )

    return None


def authorize_request(
    headers: Mapping[str, str] | None,
    cookies: Mapping[str, str] | None,
    action: str,
) -> AuthDecision:
    """Decide whether the caller behind ``headers``/``cookies`` may perform ``action``.

    The counterpart of :func:`authorize` for a real request, where the credential
    may arrive as a header (API key) or as the dashboard's session cookie.
    """
    if not settings.auth_enabled:
        return AuthDecision(True, ANONYMOUS, ANONYMOUS, "autenticação desativada")

    identity = identify(headers, cookies)

    if identity is None:
        decision = AuthDecision(False, ANONYMOUS, "", "credencial ausente")
    elif not role_allows(identity.role, action):
        decision = AuthDecision(
            False,
            identity.actor,
            identity.role,
            f"papel '{identity.role}' não permite a ação '{action}'",
            org=identity.org,
            via=identity.via,
        )
    else:
        decision = AuthDecision(
            True,
            identity.actor,
            identity.role,
            f"papel '{identity.role}' permite a ação '{action}'",
            org=identity.org,
            via=identity.via,
        )

    if not decision.allowed:
        logger.warning(
            "Acesso negado a %s (papel %s) para %s: %s",
            decision.actor,
            decision.role or "nenhum",
            action,
            decision.reason,
        )
    return decision


def require(action: str) -> Callable[[Request], AuthDecision]:
    """Return a FastAPI dependency that enforces ``action``.

    The dependency reads the credential from the request headers *or* the
    dashboard session cookie and raises ``HTTPException(401)`` when no usable
    credential was supplied, ``HTTPException(403)`` when a resolved caller lacks
    the action. FastAPI is imported lazily so this module works without it
    installed.
    """
    from fastapi import HTTPException, Request as FastAPIRequest

    def dependency(request: Request) -> AuthDecision:
        decision = authorize_request(request.headers, request.cookies, action)
        if decision.allowed:
            return decision
        # An empty role means nothing usable reached the check: that is 401,
        # whereas a resolved caller that lacks the action is 403.
        status = 403 if decision.role else 401
        raise HTTPException(status_code=status, detail=decision.reason)

    # ``from __future__ import annotations`` keeps the hint as the string
    # "Request", which FastAPI resolves against this module's globals — where the
    # lazy import does not live. Pin the real class so the request object is
    # injected instead of being read as a query parameter.
    dependency.__annotations__["request"] = FastAPIRequest
    return dependency


__all__ = [
    "ANONYMOUS",
    "ROLES",
    "ApiKey",
    "ApiKeyStore",
    "AuthDecision",
    "Identity",
    "authorize",
    "authorize_request",
    "extract_credential",
    "generate_key",
    "hash_key",
    "identify",
    "require",
    "role_allows",
]
