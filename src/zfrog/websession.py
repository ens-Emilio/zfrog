"""Dashboard sessions: a logged-in browser, as a signed cookie.

Distinct from :mod:`zfrog.session`, which stores cookies for the *target* sites a
scrape logs into. This module answers a different question — "which of our own
users is making this request" — so the dashboard can work without an API key
sitting in the browser.

Design:

* The cookie holds only the user id and an expiry, signed with HMAC-SHA256 under
  a key file (mode ``0600``) created on first use. It is signed, not encrypted,
  and does not need to be: nothing secret is in it.
* Role and organization are deliberately **not** in the cookie. They are read
  from the user store on every request, so disabling a user or changing a role
  takes effect immediately instead of whenever the cookie happens to expire.
* ``HttpOnly`` keeps it away from scripts, ``SameSite=Lax`` blocks cross-site
  POSTs, and ``Secure`` is set when the login arrived over https.

The key file is per installation, not per organization: it signs every session,
and :func:`load_or_create_key` never falls back to accepting an unsigned token
when it cannot be read.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path

from zfrog.config import settings

logger = logging.getLogger(__name__)

#: Name of the cookie the dashboard carries.
SESSION_COOKIE = "zfrog_session"

#: Token format version, so a future change is rejected instead of misread.
_TOKEN_VERSION = "v1"

#: The signing key is a secret, so the file is owner-only.
KEY_FILE_MODE = 0o600
KEY_BYTES = 32


def _b64url(raw: bytes) -> str:
    """Encode ``raw`` as unpadded base64url."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64url(text: str) -> bytes:
    """Decode unpadded base64url; raises ``ValueError`` on malformed input."""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _key_path(path: Path | None = None) -> Path:
    """Return the key file to use, defaulting to ``settings.websession_key_file``."""
    return Path(path) if path is not None else Path(settings.websession_key_file)


def read_key(path: Path | None = None) -> bytes | None:
    """Return the signing key, or None when there is no usable one.

    Never creates anything: verification must not write to disk, and a missing
    key means no token can be valid anyway.
    """
    key_file = _key_path(path)
    try:
        key = key_file.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("Unreadable session key %s: %s", key_file, exc)
        return None

    if len(key) != KEY_BYTES:
        logger.warning(
            "Session key %s has %d bytes (expected %d): ignored",
            key_file,
            len(key),
            KEY_BYTES,
        )
        return None
    return key


def load_or_create_key(path: Path | None = None) -> bytes | None:
    """Return the signing key, creating it (mode ``0600``) on first use.

    Returns None — never raising — when the key cannot be read or written. The
    caller must treat that as "sessions are unavailable" and fall back to API
    keys; it must never mean "accept an unsigned cookie".
    """
    existing = read_key(path)
    if existing is not None:
        return existing

    key_file = _key_path(path)
    if key_file.exists():
        # It exists but is unusable (wrong size, unreadable). Overwriting would
        # silently invalidate every live session, so leave it alone.
        return None

    key = os.urandom(KEY_BYTES)
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        handle_fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, KEY_FILE_MODE)
        with os.fdopen(handle_fd, "wb") as handle:
            handle.write(key)
        # An already existing file keeps its old mode, so enforce it again.
        os.chmod(key_file, KEY_FILE_MODE)
    except OSError as exc:
        logger.warning("Could not write the session key %s: %s", key_file, exc)
        return None

    logger.info("Session key created at %s", key_file)
    return key


def _sign(key: bytes, payload: str) -> str:
    """Return the base64url HMAC-SHA256 of ``payload`` under ``key``."""
    return _b64url(hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest())


def issue(
    user_id: str,
    *,
    ttl_s: int | None = None,
    now: float | None = None,
    path: Path | None = None,
) -> str | None:
    """Return a signed session token for ``user_id``, or None when unavailable.

    ``ttl_s`` defaults to ``settings.websession_ttl_s``. Returning None is the
    signal that the cookie could not be issued (no writable key file), so the
    caller can report it instead of handing out a token that will not verify.
    """
    key = load_or_create_key(path)
    if key is None:
        return None

    subject = str(user_id or "").strip()
    if not subject:
        raise ValueError("user_id is required")

    issued = time.time() if now is None else now
    lifetime = settings.websession_ttl_s if ttl_s is None else ttl_s
    payload = json.dumps(
        {"sub": subject, "iat": int(issued), "exp": int(issued + lifetime)},
        separators=(",", ":"),
        sort_keys=True,
    )
    encoded = _b64url(payload.encode("utf-8"))
    return f"{_TOKEN_VERSION}.{encoded}.{_sign(key, encoded)}"


def verify(token: str, *, now: float | None = None, path: Path | None = None) -> str | None:
    """Return the user id carried by ``token``, or None when it is not valid.

    None covers every failure — malformed, wrong version, bad signature, expired
    — because the caller must not distinguish them.
    """
    key = read_key(path)
    if key is None or not token:
        return None

    parts = str(token).split(".")
    if len(parts) != 3 or parts[0] != _TOKEN_VERSION:
        return None

    _, encoded, signature = parts
    # Constant time: a comparison that leaks how far it matched would let a
    # signature be forged byte by byte.
    if not hmac.compare_digest(_sign(key, encoded), signature):
        return None

    try:
        payload = json.loads(_unb64url(encoded))
        subject = str(payload["sub"]).strip()
        expires = int(payload["exp"])
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        return None

    if not subject:
        return None
    if expires <= (time.time() if now is None else now):
        return None
    return subject


def set_session_cookie(response, token: str, *, secure: bool) -> None:
    """Attach the session cookie to an outgoing response.

    ``HttpOnly`` (scripts cannot read it), ``SameSite=Lax`` (no cross-site POST),
    ``Secure`` when the login came over https, and ``Path=/`` so every route
    receives it.
    """
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.websession_ttl_s,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response) -> None:
    """Expire the session cookie on an outgoing response."""
    response.delete_cookie(SESSION_COOKIE, path="/")


__all__ = [
    "KEY_FILE_MODE",
    "SESSION_COOKIE",
    "clear_session_cookie",
    "issue",
    "load_or_create_key",
    "read_key",
    "set_session_cookie",
    "verify",
]
