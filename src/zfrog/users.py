"""Identity: who is calling the API and which organization owns the data.

``zfrog.auth`` answers "can this key do that"; this module answers
"who is this person and where does their data live". These are two separate
layers of purpose: an API key can belong to a user without the user
needing a password (SSO), and a user can exist without any key.

Two JSON files, both written atomically (temporary file +
``os.replace``) with mode **0600**, because they hold password hashes and
organization membership:

* ``settings.users_file`` — local accounts (``UserStore``).
* ``settings.orgs_file`` — organizations and their members (``OrgStore``).

A corrupted file never takes the process down: it is logged and treated
as empty.

Passwords: ``hash_password`` uses PBKDF2-HMAC-SHA256 (200 000 iterations,
random 16-byte salt). This serves **local accounts only**; users who
sign in via SSO have no password (empty ``password_hash``) and cannot be
authenticated by ``UserStore.authenticate``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from zfrog.auth import ROLES
from zfrog.config import settings

logger = logging.getLogger(__name__)

#: Both files hold password hashes / membership: owner-only.
STORE_FILE_MODE = 0o600

#: PBKDF2 parameters. Changing the iteration count invalidates old hashes,
#: because the count is stored inside the hash string itself.
PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 200_000
PBKDF2_SALT_BYTES = 16
PBKDF2_PREFIX = "pbkdf2"

_SLUG_RE = re.compile(r"[^a-z0-9]+")

def _now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()

def normalize_email(email: str) -> str:
    """Return ``email`` lowercased and stripped, the canonical comparison form."""
    return str(email or "").strip().lower()

def hash_password(password: str, salt: str = "") -> str:
    """Hash a local-account password with PBKDF2-HMAC-SHA256.

    Returns ``"pbkdf2$<iterations>$<salt_hex>$<hash_hex>"``. A fresh random
    16-byte salt is generated per call, so hashing the same password twice
    yields different strings. ``salt`` may carry a hex salt to reproduce an
    existing hash (used by tests); anything that is not valid hex is encoded as
    UTF-8.

    Only local accounts have a password: SSO users are created with an empty
    ``password_hash`` and authenticate at the identity provider, not here.
    """
    if salt:
        try:
            raw_salt = bytes.fromhex(salt)
        except ValueError:
            raw_salt = salt.encode("utf-8")
    else:
        raw_salt = secrets.token_bytes(PBKDF2_SALT_BYTES)

    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM, str(password).encode("utf-8"), raw_salt, PBKDF2_ITERATIONS
    )
    return (
        f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${raw_salt.hex()}${digest.hex()}"
    )

def verify_password(password: str, stored: str) -> bool:
    """Return True when ``password`` matches the stored hash.

    The comparison is constant-time. A malformed or empty ``stored`` value, or
    any unexpected input, yields False — this function never raises.
    """
    try:
        algorithm, iterations, salt_hex, digest_hex = str(stored).split("$")
        if algorithm != PBKDF2_PREFIX:
            return False
        rounds = int(iterations)
        raw_salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (AttributeError, TypeError, ValueError):
        return False

    if not raw_salt or not expected or rounds <= 0:
        return False

    try:
        candidate = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM, str(password).encode("utf-8"), raw_salt, rounds
        )
    except (TypeError, ValueError):
        return False

    return hmac.compare_digest(candidate, expected)

def _slug(value: str) -> str:
    """Return a URL-safe identifier derived from ``value`` (may be empty)."""
    return _SLUG_RE.sub("-", str(value or "").strip().lower()).strip("-")

@dataclass
class User:
    """One account. ``password_hash`` is empty for SSO-only users."""

    id: str
    email: str
    name: str
    role: str
    orgs: list[str] = field(default_factory=list)
    created_at: str = ""
    enabled: bool = True
    password_hash: str = ""
    sso_subject: str = ""

@dataclass
class Organization:
    """One tenant. ``members`` maps user id -> role inside the organization."""

    id: str
    name: str
    created_at: str
    owner: str
    members: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

def redact(user: User) -> dict:
    """Return ``user`` as a dict without the password hash, for API responses."""
    payload = asdict(user)
    payload.pop("password_hash", None)
    return payload

class _JsonStore:
    """Shared JSON persistence: atomic writes, mode 0600, corrupt file -> empty."""

    def __init__(self, path: Path | None, default_path: Path, label: str) -> None:
        self.path = Path(path) if path is not None else Path(default_path)
        self._label = label

    def _load_raw(self) -> list[dict]:
        """Read the file; missing, empty or corrupt means "nothing stored"."""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            logger.warning("Could not read %s (%s): %s", self._label, self.path, exc)
            return []

        if not raw.strip():
            return []

        try:
            data = json.loads(raw)
        except ValueError as exc:
            logger.warning("%s corrupted (%s): %s — starting empty", self._label, self.path, exc)
            return []

        if not isinstance(data, list):
            logger.warning(
                "%s corrupted (%s): expected a list — starting empty", self._label, self.path
            )
            return []

        records = []
        for item in data:
            if not isinstance(item, dict):
                logger.warning(
                    "%s corrupted (%s): record is not an object — starting empty",
                    self._label,
                    self.path,
                )
                return []
            records.append(item)
        return records

    def _save_records(self, records: list[dict]) -> None:
        """Write the whole list atomically (temp file + os.replace) as mode 0600."""
        payload = json.dumps(records, indent=2, ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        handle_fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, STORE_FILE_MODE)
            os.replace(temp_name, self.path)
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise

class UserStore:
    """JSON-file store of accounts, written atomically with mode 0600."""

    def __init__(self, path: Path | None = None) -> None:
        self._file = _JsonStore(path, settings.users_file, "users file")

    @property
    def path(self) -> Path:
        """Location of the JSON file backing this store."""
        return self._file.path

    # ── writing ──

    def create(
        self,
        email: str,
        name: str = "",
        role: str = "viewer",
        password: str = "",
        orgs: list[str] | None = None,
        sso_subject: str = "",
    ) -> tuple[User, str]:
        """Store a new account and return ``(user, plaintext_password)``.

        The plaintext password is returned exactly once and never persisted;
        only its PBKDF2 hash is written. When ``password`` is empty the account
        is SSO-only and the returned password is empty too. An unknown role or
        an e-mail that is already taken raises ValueError.
        """
        if role not in ROLES:
            raise ValueError(
                f"unknown role: {role!r} (valid: {', '.join(sorted(ROLES))})"
            )

        normalized = normalize_email(email)
        if not normalized:
            raise ValueError("email is required")

        users = self._load()
        if any(user.email == normalized for user in users):
            raise ValueError(f"email already registered: {normalized}")

        user = User(
            id=secrets.token_hex(8),
            email=normalized,
            name=str(name or "").strip(),
            role=role,
            orgs=_unique(orgs),
            created_at=_now(),
            enabled=True,
            password_hash=hash_password(password) if password else "",
            sso_subject=str(sso_subject or "").strip(),
        )
        users.append(user)
        self._save(users)
        return user, str(password or "")

    def update(self, user: User) -> User:
        """Persist ``user`` (a mutated copy of a stored record) and return it."""
        users = self._load()
        for index, stored in enumerate(users):
            if stored.id == user.id:
                users[index] = user
                self._save(users)
                return user
        raise ValueError(f"unknown user: {user.id!r}")

    def set_enabled(self, user_id: str, enabled: bool) -> bool:
        """Enable or disable ``user_id``; return False when it does not exist."""
        users = self._load()
        for user in users:
            if user.id == user_id:
                user.enabled = bool(enabled)
                self._save(users)
                return True
        return False

    def delete(self, user_id: str) -> bool:
        """Delete ``user_id``; return False when it does not exist."""
        users = self._load()
        remaining = [user for user in users if user.id != user_id]
        if len(remaining) == len(users):
            return False
        self._save(remaining)
        return True

    # ── reading ──

    def list(self) -> list[User]:
        """Return every account, oldest first."""
        return self._load()

    def get(self, user_id: str) -> User | None:
        """Return the account with ``user_id``, or None."""
        for user in self._load():
            if user.id == user_id:
                return user
        return None

    def by_email(self, email: str) -> User | None:
        """Return the account with ``email`` (case-insensitive), or None."""
        normalized = normalize_email(email)
        if not normalized:
            return None
        for user in self._load():
            if user.email == normalized:
                return user
        return None

    def by_sso_subject(self, subject: str) -> User | None:
        """Return the account linked to an SSO ``subject``, or None."""
        wanted = str(subject or "").strip()
        if not wanted:
            return None
        for user in self._load():
            if user.sso_subject and user.sso_subject == wanted:
                return user
        return None

    def authenticate(self, email: str, password: str) -> User | None:
        """Return the account matching ``email`` and ``password``, else None.

        None covers every failure the caller must not distinguish between:
        unknown e-mail, wrong password, disabled account and SSO-only accounts
        (which carry no password hash).
        """
        user = self.by_email(email)
        if user is None or not user.enabled:
            return None
        if not user.password_hash:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    def upsert_sso_user(
        self,
        subject: str,
        email: str,
        name: str = "",
        role: str = "viewer",
        orgs: list[str] | None = None,
    ) -> User:
        """Return the account for an SSO login, creating or linking as needed.

        Lookup order: by ``subject`` (repeat logins), then by ``email`` (an
        existing local account is *linked* — it keeps its id, role and
        password), then create. Repeated logins therefore never duplicate an
        account. ``role``/``orgs`` apply only to newly created accounts: an
        existing account is never silently promoted by the identity provider.
        """
        wanted = str(subject or "").strip()
        if not wanted:
            raise ValueError("subject is required")

        existing = self.by_sso_subject(wanted)
        if existing is not None:
            return existing

        users = self._load()
        normalized = normalize_email(email)
        for user in users:
            if normalized and user.email == normalized:
                user.sso_subject = wanted
                if not user.name and str(name or "").strip():
                    user.name = str(name).strip()
                self._save(users)
                return user

        user, _ = self.create(
            email, name=name, role=role, password="", orgs=orgs, sso_subject=wanted
        )
        return user

    # ── file handling ──

    def _load(self) -> list[User]:
        """Read the user file, skipping nothing: a bad record means an empty store."""
        users: list[User] = []
        for item in self._file._load_raw():
            try:
                users.append(self._from_dict(item))
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "users file corrupted (%s): %s — starting empty", self.path, exc
                )
                return []
        return users

    def _from_dict(self, item: dict) -> User:
        """Build a User from one JSON record."""
        missing = [name for name in ("id", "email", "role") if not item.get(name)]
        if missing:
            raise ValueError(f"faltam campos {', '.join(missing)}")
        return User(
            id=str(item["id"]),
            email=normalize_email(item["email"]),
            name=str(item.get("name") or ""),
            role=str(item["role"]),
            orgs=[str(org) for org in item.get("orgs") or []],
            created_at=str(item.get("created_at") or ""),
            enabled=bool(item.get("enabled", True)),
            password_hash=str(item.get("password_hash") or ""),
            sso_subject=str(item.get("sso_subject") or ""),
        )

    def _save(self, users: list[User]) -> None:
        """Persist every account."""
        self._file._save_records([asdict(user) for user in users])

class OrgStore:
    """JSON-file store of organizations and their membership (mode 0600).

    The store is deliberately independent from :class:`UserStore`: it never
    imports it and never checks that ``owner`` or a member exists. Validating
    identities is the caller's job (``api.py``/``cli.py`` do it), which keeps
    this file free of a circular dependency.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._file = _JsonStore(path, settings.orgs_file, "organizations file")

    @property
    def path(self) -> Path:
        """Location of the JSON file backing this store."""
        return self._file.path

    # ── writing ──

    def create(self, name: str, owner: str, org_id: str = "") -> Organization:
        """Store a new organization and return it.

        The id is a slug of ``name`` unless ``org_id`` is given explicitly; a
        name without any usable character falls back to a random id. The owner
        is recorded both as ``owner`` and as an ``admin`` member, so the org
        shows up in ``orgs_for(owner)``. A duplicate id raises ValueError.
        """
        identifier = _slug(org_id) if org_id else _slug(name)
        if not identifier:
            identifier = f"org-{secrets.token_hex(4)}"

        orgs = self._load()
        if any(org.id == identifier for org in orgs):
            raise ValueError(f"organization already exists: {identifier}")

        owner_id = str(owner or "").strip()
        if not owner_id:
            raise ValueError("owner is required")

        org = Organization(
            id=identifier,
            name=str(name or "").strip() or identifier,
            created_at=_now(),
            owner=owner_id,
            members={owner_id: "admin"},
            enabled=True,
        )
        orgs.append(org)
        self._save(orgs)
        return org

    def add_member(self, org_id: str, user_id: str, role: str = "viewer") -> Organization:
        """Add or re-role ``user_id`` inside ``org_id`` and return the org.

        An unknown organization raises ValueError; adding an existing member
        simply updates the role.
        """
        member_id = str(user_id or "").strip()
        if not member_id:
            raise ValueError("user is required")

        orgs = self._load()
        for org in orgs:
            if org.id == org_id:
                org.members[member_id] = str(role or "viewer")
                self._save(orgs)
                return org
        raise ValueError(f"unknown organization: {org_id!r}")

    def remove_member(self, org_id: str, user_id: str) -> Organization:
        """Drop ``user_id`` from ``org_id`` and return the org.

        An unknown organization raises ValueError; removing somebody who is not
        a member is a no-op.
        """
        orgs = self._load()
        for org in orgs:
            if org.id == org_id:
                org.members.pop(str(user_id), None)
                self._save(orgs)
                return org
        raise ValueError(f"unknown organization: {org_id!r}")

    def set_enabled(self, org_id: str, enabled: bool) -> bool:
        """Enable or disable ``org_id``; return False when it does not exist."""
        orgs = self._load()
        for org in orgs:
            if org.id == org_id:
                org.enabled = bool(enabled)
                self._save(orgs)
                return True
        return False

    def delete(self, org_id: str) -> bool:
        """Delete ``org_id``; return False when it does not exist."""
        orgs = self._load()
        remaining = [org for org in orgs if org.id != org_id]
        if len(remaining) == len(orgs):
            return False
        self._save(remaining)
        return True

    # ── reading ──

    def list(self) -> list[Organization]:
        """Return every organization, oldest first."""
        return self._load()

    def get(self, org_id: str) -> Organization | None:
        """Return the organization with ``org_id``, or None."""
        for org in self._load():
            if org.id == org_id:
                return org
        return None

    def role_of(self, org_id: str, user_id: str) -> str | None:
        """Return the role ``user_id`` holds in ``org_id``, or None."""
        org = self.get(org_id)
        if org is None:
            return None
        return org.members.get(str(user_id))

    def orgs_for(self, user_id: str) -> list[str]:
        """Return the ids of the enabled organizations ``user_id`` belongs to."""
        member_id = str(user_id or "").strip()
        if not member_id:
            return []
        return [org.id for org in self._load() if org.enabled and member_id in org.members]

    # ── file handling ──

    def _load(self) -> list[Organization]:
        """Read the org file; a bad record means an empty store."""
        orgs: list[Organization] = []
        for item in self._file._load_raw():
            try:
                orgs.append(self._from_dict(item))
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "organizations file corrupted (%s): %s — starting empty",
                    self.path,
                    exc,
                )
                return []
        return orgs

    def _from_dict(self, item: dict) -> Organization:
        """Build an Organization from one JSON record."""
        missing = [name for name in ("id", "owner") if not item.get(name)]
        if missing:
            raise ValueError(f"missing fields {', '.join(missing)}")
        members = item.get("members") or {}
        if not isinstance(members, dict):
            raise ValueError("invalid members")
        return Organization(
            id=str(item["id"]),
            name=str(item.get("name") or item["id"]),
            created_at=str(item.get("created_at") or ""),
            owner=str(item["owner"]),
            members={str(key): str(value) for key, value in members.items()},
            enabled=bool(item.get("enabled", True)),
        )

    def _save(self, orgs: list[Organization]) -> None:
        """Persist every organization."""
        self._file._save_records([asdict(org) for org in orgs])

def add_member(org_id: str, user_id: str, role: str = "viewer",
               orgs: OrgStore | None = None, users: UserStore | None = None) -> Organization:
    """Add a user to an organization, updating BOTH sides of the link.

    `OrgStore.add_member` only records the membership on the organization, and
    `User.orgs` only records it on the user. Listing users would then show no
    organization for a member that the organization clearly has — so the link is
    made here, where both stores are available.
    """
    org_store = orgs or OrgStore()
    user_store = users or UserStore()

    org = org_store.add_member(org_id, user_id, role)

    user = user_store.get(user_id)
    if user is not None and org.id not in user.orgs:
        user.orgs = [*user.orgs, org.id]
        user_store.update(user)

    return org


def remove_member(org_id: str, user_id: str,
                  orgs: OrgStore | None = None, users: UserStore | None = None) -> Organization:
    """Remove a user from an organization, updating both sides of the link."""
    org_store = orgs or OrgStore()
    user_store = users or UserStore()

    org = org_store.remove_member(org_id, user_id)

    user = user_store.get(user_id)
    if user is not None and org.id in user.orgs:
        user.orgs = [o for o in user.orgs if o != org.id]
        user_store.update(user)

    return org


def ensure_default_org(orgs: OrgStore, owner: str) -> Organization:
    """Return ``settings.default_org``, creating it for ``owner`` when missing.

    Idempotent: calling it twice yields a single organization.
    """
    existing = orgs.get(settings.default_org)
    if existing is not None:
        return existing
    return orgs.create(settings.default_org, owner, org_id=settings.default_org)

def _unique(values: list[str] | None) -> list[str]:
    """Return ``values`` as clean strings with duplicates removed, order kept."""
    seen: list[str] = []
    for value in values or []:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.append(item)
    return seen

__all__ = [
    "OrgStore",
    "Organization",
    "PBKDF2_ITERATIONS",
    "STORE_FILE_MODE",
    "User",
    "UserStore",
    "ensure_default_org",
    "hash_password",
    "normalize_email",
    "redact",
    "verify_password",
]
