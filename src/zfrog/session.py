"""Authenticated browser sessions (cookies + localStorage) persisted per domain.

A session is captured interactively with :func:`capture_session` — a headed
Chromium window opens, you log in by hand, press Enter, and the resulting
Playwright ``storage_state`` (cookies **and** localStorage origins) is written to
``<settings.sessions_dir>/<domain>.json``. The Playwright-backed engines then
reuse that file for every job on the same domain.

Security
--------
State files hold live cookie values, so they are written with mode ``0o600``
(owner read/write only) and — when the optional ``cryptography`` package is
installed — encrypted at rest with AES-GCM. The 32-byte key lives in
``settings.sessions_key_file`` (mode ``0o600``, created on first save); a state
file written this way carries ``"encrypted": true`` and its ``state`` field is
the base64 of ``nonce || ciphertext``. Without ``cryptography`` the files stay
plaintext (a warning is logged once per process) and ``0o600`` is the only
protection: anyone who can read them — or read a backup/copy of them — can
impersonate the logged-in user. Keep ``sessions/`` out of version control (never
commit it, never paste a state file into an issue), and delete sessions you no
longer need with :meth:`SessionStore.delete`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from zfrog.config import settings

logger = logging.getLogger(__name__)

#: Cookie values are secrets: state files are owner-only.
STATE_FILE_MODE = 0o600

#: The AES key is a secret too.
KEY_FILE_MODE = 0o600

#: AES-256 key length and AES-GCM nonce length, in bytes.
KEY_BYTES = 32
NONCE_BYTES = 12

#: Set the first time a plaintext session is saved, so the warning is not
#: repeated for every domain/job in the same process.
_plaintext_warning_emitted = False

def encryption_available() -> bool:
    """Return True when the optional ``cryptography`` package can be imported."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    except Exception as exc:  # ImportError, or a broken native extension
        logger.debug("Session encryption unavailable: %s", exc)
        return False
    return True

def _key_path(path: Path | None = None) -> Path:
    """Return the key file to use, defaulting to ``settings.sessions_key_file``."""
    return Path(path) if path is not None else Path(settings.sessions_key_file)

def load_or_create_key(path: Path | None = None) -> bytes | None:
    """Return the 32-byte session key, creating it on first use.

    The key is ``os.urandom(32)`` written to ``path`` (default
    ``settings.sessions_key_file``) with mode ``0o600``, creating parent
    directories as needed. An existing key file is reused verbatim.

    Returns ``None`` — never raising — when encryption is unavailable (no key
    file is created in that case) or when an existing key file cannot be read or
    does not hold exactly 32 bytes; a warning is logged and callers fall back to
    plaintext storage.
    """
    if not encryption_available():
        return None

    key_file = _key_path(path)
    if key_file.is_file():
        try:
            key = key_file.read_bytes()
        except OSError as exc:
            logger.warning("Ignoring unreadable session key %s: %s", key_file, exc)
            return None
        if len(key) != KEY_BYTES:
            logger.warning(
                "Ignoring session key %s: expected %d bytes, found %d",
                key_file,
                KEY_BYTES,
                len(key),
            )
            return None
        return key

    key = os.urandom(KEY_BYTES)
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, KEY_FILE_MODE)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        # An already existing file keeps its old mode, so enforce it again.
        os.chmod(key_file, KEY_FILE_MODE)
    except OSError as exc:
        logger.warning("Could not write session key %s: %s", key_file, exc)
        return None

    logger.info("Created session encryption key at %s", key_file)
    return key

def _encrypt_state(state: dict, key: bytes) -> str:
    """Seal ``state`` with AES-GCM; return base64 of ``nonce || ciphertext``."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(NONCE_BYTES)
    plaintext = json.dumps(state, ensure_ascii=False).encode("utf-8")
    sealed = AESGCM(key).encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + sealed).decode("ascii")

def _decrypt_state(encoded: str, key: bytes) -> dict:
    """Open a base64 ``nonce || ciphertext`` blob; raise when it is not authentic."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = base64.b64decode(encoded, validate=True)
    if len(raw) <= NONCE_BYTES:
        raise ValueError("ciphertext is too short")
    try:
        plaintext = AESGCM(key).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], None)
    except Exception as exc:
        # InvalidTag carries no message of its own.
        raise ValueError(
            f"authentication failed (wrong key or tampered file): {exc or type(exc).__name__}"
        ) from exc
    state = json.loads(plaintext.decode("utf-8"))
    if not isinstance(state, dict):
        raise ValueError("decrypted state is not an object")
    return state

def _warn_plaintext_once(domain: str) -> None:
    """Tell the user — once per process — that this session is not encrypted."""
    global _plaintext_warning_emitted
    if _plaintext_warning_emitted:
        return
    _plaintext_warning_emitted = True
    logger.warning(
        "Session for %s is stored in PLAINTEXT (install 'cryptography' to encrypt "
        "session files at rest); the file is only protected by mode 0o600.",
        domain,
    )

def domain_for(url: str) -> str:
    """Return the session domain of ``url``.

    The lowercased host with the port removed and a leading ``www.`` stripped,
    so ``https://WWW.Example.com:8443/a`` and ``https://example.com/b`` share
    one session. Returns ``""`` when no host can be extracted.
    """
    candidate = url if "//" in url else f"//{url}"
    host = (urlparse(candidate).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _normalize_domain(domain: str) -> str:
    """Lowercase/strip a caller-supplied domain (ports are dropped as well)."""
    cleaned = domain.strip()
    if "://" in cleaned or "/" in cleaned or ":" in cleaned:
        return domain_for(cleaned)
    if cleaned.startswith("www."):
        cleaned = cleaned[4:]
    return cleaned.lower()


class SessionStore:
    """One JSON file per domain under ``root`` (default ``settings.sessions_dir``)."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else Path(settings.sessions_dir)

    # ── paths ───────────────────────────────────────────────────────

    def _path(self, domain: str) -> Path:
        return self.root / f"{domain}.json"

    def state_path(self, url: str) -> Path | None:
        """Return the state file for ``url``'s domain, or None when none is saved."""
        domain = domain_for(url)
        if not domain:
            return None
        path = self._path(domain)
        return path if path.is_file() else None

    # ── CRUD ────────────────────────────────────────────────────────

    def save(self, domain: str, state: dict) -> Path:
        """Persist ``state`` for ``domain`` and return the written path.

        Raises ValueError for an empty domain. The state is sealed with AES-GCM
        when a session key is available (``"encrypted": true``); otherwise — no
        key, or an unusable cipher — it is stored verbatim (``"encrypted":
        false``) and a plaintext warning is logged once per process. The root
        directory is created when missing and the file is (re)chmod-ed to
        ``0o600``.
        """
        if not isinstance(domain, str) or not domain.strip():
            raise ValueError("domain must not be empty")

        normalized = _normalize_domain(domain)
        if not normalized:
            raise ValueError("domain must not be empty")

        key = load_or_create_key()
        stored_state: dict | str = state
        encrypted = False
        if key is not None:
            try:
                stored_state = _encrypt_state(state, key)
                encrypted = True
            except Exception as exc:
                # The key is there but the cipher is unusable (broken install):
                # store plaintext rather than losing the session, and say so.
                logger.warning(
                    "Could not encrypt session for %s, storing it in plaintext: %s",
                    normalized,
                    exc,
                )
                stored_state = state
        if not encrypted:
            _warn_plaintext_once(normalized)

        payload = {
            "domain": normalized,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "encrypted": encrypted,
            "state": stored_state,
        }

        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(normalized)

        # Create with restrictive permissions from the start, so cookie values
        # are never briefly world-readable.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, STATE_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        # An already existing file keeps its old mode, so enforce it again.
        os.chmod(path, STATE_FILE_MODE)

        logger.info("Saved session for %s to %s", normalized, path)
        return path

    def _decode_state(self, payload: dict) -> dict:
        """Return the ``state`` object of ``payload``, decrypting it when needed.

        Raises on a tampered ciphertext, a missing key or a misshaped payload;
        :meth:`_read_payload` turns that into a warning plus ``None``.
        """
        raw = payload.get("state")
        if not payload.get("encrypted"):
            if not isinstance(raw, dict):
                raise ValueError("missing 'state' object")
            return raw

        if not isinstance(raw, str):
            raise ValueError("encrypted 'state' is not a string")
        key = load_or_create_key()
        if key is None:
            raise ValueError("session is encrypted but no usable key is available")
        return _decrypt_state(raw, key)

    def _read_payload(self, path: Path) -> dict | None:
        """Read a state file, returning None (with a warning) when unusable.

        The returned mapping carries the *decrypted* ``state`` object, so callers
        never see the ciphertext.
        """
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload is not an object")
            payload["state"] = self._decode_state(payload)
        except Exception as exc:
            logger.warning(
                "Ignoring unreadable session file %s: %s", path, str(exc) or type(exc).__name__
            )
            return None
        return payload

    def load(self, domain: str) -> dict | None:
        """Return the stored state for ``domain``, or None when absent/corrupt.

        A corrupt, unreadable or undecryptable file (wrong key, tampered
        ciphertext) is logged as a warning and treated as "no session" rather
        than raising.
        """
        path = self._path(_normalize_domain(domain))
        if not path.is_file():
            return None

        payload = self._read_payload(path)
        return None if payload is None else payload["state"]

    def has(self, domain: str) -> bool:
        """Return True when a state file exists for ``domain``."""
        normalized = _normalize_domain(domain)
        return bool(normalized) and self._path(normalized).is_file()

    def list(self) -> list[dict]:
        """Return ``[{"domain", "saved_at", "cookies"}]`` sorted by domain.

        ``cookies`` is the number of cookies in the saved state; unreadable
        files are skipped with a warning.
        """
        if not self.root.is_dir():
            return []

        entries: list[dict] = []
        for path in sorted(self.root.glob("*.json")):
            payload = self._read_payload(path)
            if payload is None:
                continue
            cookies = payload["state"].get("cookies") or []

            entries.append(
                {
                    "domain": str(payload.get("domain") or path.stem),
                    "saved_at": str(payload.get("saved_at") or ""),
                    "cookies": len(cookies),
                }
            )

        entries.sort(key=lambda entry: entry["domain"])
        return entries

    def delete(self, domain: str) -> bool:
        """Delete the session of ``domain``; return False when there was none."""
        path = self._path(_normalize_domain(domain))
        if not path.is_file():
            return False
        path.unlink()
        logger.info("Deleted session for %s", domain)
        return True


async def capture_session(
    url: str,
    store: SessionStore | None = None,
    wait_for_enter: bool = True,
) -> dict:
    """Open a headed browser so the user can log in, then save the session.

    Navigates to ``url``, waits for Enter (unless ``wait_for_enter`` is False),
    reads ``context.storage_state()``, saves it under the URL's domain and
    returns it. Context, browser and playwright are always closed.
    """
    domain = domain_for(url)
    if not domain:
        raise ValueError(f"Could not determine the domain of {url!r}")

    store = store or SessionStore()
    playwright = None
    browser = None
    context = None

    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)

        if wait_for_enter:
            await asyncio.to_thread(
                input,
                "Log in to your account and press Enter to save the session... ",
            )

        state = await context.storage_state()
        store.save(domain, state)
        return state
    finally:
        for closable in (context, browser):
            if closable is not None:
                try:
                    await closable.close()
                except Exception as exc:
                    logger.debug("Failed to close session browser: %s", exc)
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception as exc:
                logger.debug("Failed to stop playwright: %s", exc)
