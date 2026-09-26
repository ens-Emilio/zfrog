"""Two-factor codes (RFC 6238 TOTP / RFC 4226 HOTP) for logging into *your own* accounts.

Many sites behind a login ask for a 6-digit code on top of the password. That code is
derived from a shared secret the user already possesses — the base32 string an
authenticator app was given — and the algorithm is fully specified (RFC 4226 for the
HMAC-based one-time password, RFC 6238 for the time-based variant), so it can be
computed locally with nothing but :mod:`hmac` and :mod:`hashlib`. That is what this
module does: it turns the secret the user already has into the code a site expects.

**Scope, in plain words:** this only generates codes from a secret the user already
holds. It does NOT solve CAPTCHAs, bypass credentials, or attempt to defeat any
anti-automation control — that is deliberately out of scope and stays that way.

The account store keeps live 2FA secrets in one JSON file (``settings.output_dir /
"totp.json"``), so the file is written atomically with mode **0600**, no secret is ever
logged, and display helpers (:func:`redact`, :meth:`TotpStore.list`, ``repr``) mask the
secret instead of returning it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit, unquote

from zfrog.config import settings

logger = logging.getLogger(__name__)

# The file holds 2FA secrets: nobody but the owner may read it.
STORE_FILE_MODE = 0o600
MIN_DIGITS = 6
MAX_DIGITS = 8
_BASE32_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
# A fixed mask, never a partial secret: even a prefix would leak key material.
_SECRET_MASK = "********"
_STORE_VERSION = 1

def _check_digits(digits: int) -> int:
    """Return ``digits`` when it is a usable code length, else raise ``ValueError``."""
    try:
        value = int(digits)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"digits must be an integer, got {digits!r}") from exc
    if not MIN_DIGITS <= value <= MAX_DIGITS:
        raise ValueError(f"digits must be between {MIN_DIGITS} and {MAX_DIGITS}, got {value}")
    return value

def _check_period(period: int) -> int:
    """Return ``period`` when it is a positive number of seconds, else raise."""
    try:
        value = int(period)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"period must be an integer, got {period!r}") from exc
    if value <= 0:
        raise ValueError(f"period must be a positive number of seconds, got {value}")
    return value

def _key(secret: str | bytes) -> bytes:
    """Return the raw HMAC key for ``secret`` (base32 text or already-decoded bytes)."""
    if isinstance(secret, bytes):
        if not secret:
            raise ValueError("secret is empty")
        return secret
    return normalize_secret(secret)

def normalize_secret(secret: str) -> bytes:
    """Decode a base32 shared secret exactly as users paste it.

    Uppercases, drops spaces, dashes and existing padding, then pads back to a
    multiple of 8 before decoding. Raises ``ValueError`` with a clear message for an
    empty secret, a character outside the base32 alphabet, or a bad length.
    """
    if not isinstance(secret, str):
        raise ValueError(f"secret must be a string, got {type(secret).__name__}")
    cleaned = secret.replace(" ", "").replace("-", "").replace("=", "").upper()
    if not cleaned:
        raise ValueError("secret is empty")
    invalid = sorted(set(cleaned) - _BASE32_ALPHABET)
    if invalid:
        raise ValueError(
            "secret is not base32: unexpected character(s) " + ", ".join(repr(c) for c in invalid)
        )
    padding = (-len(cleaned)) % 8
    try:
        return base64.b32decode(cleaned + "=" * padding, casefold=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"secret is not valid base32: {exc}") from exc

def _encode_secret(key: bytes) -> str:
    """Return the canonical (upper-case, unpadded) base32 spelling of ``key``."""
    return base64.b32encode(key).decode("ascii").rstrip("=")

def hotp(secret: str | bytes, counter: int, digits: int = 6) -> str:
    """RFC 4226 HOTP: HMAC-SHA1 of the 8-byte big-endian ``counter``, truncated.

    ``secret`` is a base32 string (as pasted by a user) or raw key bytes.
    ``digits`` must be 6, 7 or 8.
    """
    digits = _check_digits(digits)
    try:
        step = int(counter)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"counter must be an integer, got {counter!r}") from exc
    if step < 0:
        raise ValueError(f"counter must not be negative, got {step}")
    if step >= 1 << 64:
        raise ValueError("counter does not fit in 8 bytes")
    digest = hmac.new(_key(secret), step.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(truncated % (10**digits)).zfill(digits)

def _counter_for(when: float | int | None, period: int) -> int:
    """Return the TOTP step number for ``when`` (``None`` means now)."""
    period = _check_period(period)
    stamp = time.time() if when is None else float(when)
    return int(stamp // period)

def totp(
    secret: str | bytes,
    when: float | int | None = None,
    period: int = 30,
    digits: int = 6,
) -> str:
    """RFC 6238 TOTP with HMAC-SHA1 — the variant virtually every site uses.

    ``when`` is a unix timestamp in seconds; ``None`` means "right now".
    """
    return hotp(secret, _counter_for(when, period), digits)

def totp_at(
    secret: str | bytes,
    when: float | int | None = None,
    period: int = 30,
    digits: int = 6,
) -> str:
    """The code valid at ``when`` — alias of :func:`totp` for callers that read better."""
    return totp(secret, when, period=period, digits=digits)

def seconds_remaining(when: float | int | None = None, period: int = 30) -> int:
    """How long the current code stays valid, from 1 to ``period`` seconds."""
    period = _check_period(period)
    stamp = time.time() if when is None else float(when)
    return period - int(stamp % period)

def verify(
    secret: str | bytes,
    code: str,
    when: float | int | None = None,
    period: int = 30,
    digits: int = 6,
    window: int = 1,
) -> bool:
    """Check ``code`` for the step at ``when``, allowing ``window`` steps of clock drift.

    Comparison is constant-time. A code that is not a string of exactly ``digits``
    decimal digits returns ``False`` instead of raising.
    """
    digits = _check_digits(digits)
    period = _check_period(period)
    try:
        steps = int(window)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"window must be an integer, got {window!r}") from exc
    if steps < 0:
        raise ValueError(f"window must not be negative, got {steps}")
    if not isinstance(code, str):
        return False
    candidate_input = code.strip()
    if len(candidate_input) != digits or not candidate_input.isascii() or not candidate_input.isdigit():
        return False

    key = _key(secret)
    counter = _counter_for(when, period)
    matched = False
    for offset in range(-steps, steps + 1):
        if counter + offset < 0:
            continue
        expected = hotp(key, counter + offset, digits)
        # No early exit: the result must not depend on which step matched.
        matched |= hmac.compare_digest(candidate_input, expected)
    return matched

def provisioning_uri(
    secret: str,
    account: str,
    issuer: str = "Zfrog",
    digits: int = 6,
    period: int = 30,
) -> str:
    """Build the ``otpauth://totp/...`` URI an authenticator app scans.

    The label is ``issuer:account`` with both halves percent-encoded, so an account
    containing ``@`` or a space survives :func:`parse_provisioning_uri` unchanged.
    """
    digits = _check_digits(digits)
    period = _check_period(period)
    cleaned_account = (account or "").strip()
    if not cleaned_account:
        raise ValueError("account is required to build a provisioning URI")
    cleaned_issuer = (issuer or "").strip()

    label = quote(cleaned_account, safe="")
    params: dict[str, str] = {"secret": _encode_secret(normalize_secret(secret))}
    if cleaned_issuer:
        label = f"{quote(cleaned_issuer, safe='')}:{label}"
        params["issuer"] = cleaned_issuer
    params["digits"] = str(digits)
    params["period"] = str(period)
    return f"otpauth://totp/{label}?{urlencode(params)}"

def _int_param(query: dict[str, list[str]], name: str, default: int) -> int:
    """Read an integer query parameter of a provisioning URI."""
    raw = (query.get(name) or [""])[0].strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"provisioning URI has a non-numeric {name}: {raw!r}") from exc

def parse_provisioning_uri(uri: str) -> dict:
    """Read a stored provisioning URI back into its parts.

    Returns ``{"secret", "account", "issuer", "digits", "period"}``. A malformed URI,
    a non-``otpauth`` scheme, a non-``totp`` type, a missing/undecodable secret or an
    empty account raises ``ValueError``.
    """
    if not isinstance(uri, str) or not uri.strip():
        raise ValueError("provisioning URI is empty")
    parts = urlsplit(uri.strip())
    if parts.scheme.lower() != "otpauth":
        raise ValueError(f"not an otpauth:// URI (scheme {parts.scheme!r})")
    if parts.netloc.lower() != "totp":
        raise ValueError(f"unsupported otpauth type {parts.netloc!r}: only 'totp' is supported")

    # Split the label while it is still quoted, so a %3A inside a name is not
    # mistaken for the issuer/account separator.
    raw_label = parts.path.lstrip("/")
    label_issuer = ""
    if ":" in raw_label:
        issuer_part, _, account_part = raw_label.partition(":")
        label_issuer = unquote(issuer_part).strip()
        account = unquote(account_part).strip()
    else:
        account = unquote(raw_label).strip()
    if not account:
        raise ValueError("provisioning URI has no account label")

    query = parse_qs(parts.query, keep_blank_values=True)
    secret = (query.get("secret") or [""])[0].strip()
    if not secret:
        raise ValueError("provisioning URI has no secret")
    normalize_secret(secret)

    issuer = (query.get("issuer") or [""])[0].strip() or label_issuer
    return {
        "secret": secret,
        "account": account,
        "issuer": issuer,
        "digits": _check_digits(_int_param(query, "digits", 6)),
        "period": _check_period(_int_param(query, "period", 30)),
    }

@dataclass(repr=False)
class TotpAccount:
    """One of your own accounts protected by a shared TOTP secret."""

    name: str
    secret: str
    issuer: str = ""
    created_at: str = ""

    def __repr__(self) -> str:
        """Never let a secret reach a log line or a traceback."""
        return (
            f"TotpAccount(name={self.name!r}, issuer={self.issuer!r}, "
            f"secret={_SECRET_MASK!r}, created_at={self.created_at!r})"
        )

def redact(account: TotpAccount) -> dict:
    """Return a display copy of ``account`` with the secret replaced by a mask."""
    return {
        "name": account.name,
        "issuer": account.issuer,
        "created_at": account.created_at,
        "secret": _SECRET_MASK,
    }

class TotpStore:
    """Your 2FA accounts, in one JSON file (default ``settings.output_dir/totp.json``).

    The file holds live TOTP secrets, so it is written atomically (temp file +
    ``os.replace``) with mode **0600**, and no secret value is ever logged or returned
    by :meth:`list`, :func:`redact` or ``repr``.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else Path(settings.output_dir) / "totp.json"

    def __repr__(self) -> str:
        return f"TotpStore(path={self.path!r})"

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> list[TotpAccount]:
        """Read the store; a missing, empty or corrupt file means "nothing stored"."""
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("totp.json ilegível (%s): começando vazio (%s)", self.path, exc)
            return []

        items = payload.get("accounts") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            logger.warning("totp.json sem lista de contas (%s): começando vazio", self.path)
            return []

        accounts: list[TotpAccount] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("name") or not item.get("secret"):
                logger.warning("registro inválido em %s ignorado", self.path)
                continue
            accounts.append(
                TotpAccount(
                    name=str(item["name"]),
                    secret=str(item["secret"]),
                    issuer=str(item.get("issuer") or ""),
                    created_at=str(item.get("created_at") or ""),
                )
            )
        return accounts

    def _save(self, accounts: list[TotpAccount]) -> None:
        """Write every account atomically, as mode 0600, without ever logging a secret."""
        payload = {"version": _STORE_VERSION, "accounts": [asdict(a) for a in accounts]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle_fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, STORE_FILE_MODE)
            os.replace(temp_name, self.path)
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise

    # ── accounts ─────────────────────────────────────────────────────────────

    def add(self, name: str, secret: str, issuer: str = "") -> TotpAccount:
        """Register ``name`` with ``secret``; a duplicate name or a bad secret raises."""
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("name is required")
        key = normalize_secret(secret)
        accounts = self._load()
        if any(account.name == clean_name for account in accounts):
            raise ValueError(f"account already registered: {clean_name}")

        account = TotpAccount(
            name=clean_name,
            secret=_encode_secret(key),
            issuer=(issuer or "").strip(),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        accounts.append(account)
        self._save(accounts)
        logger.info("Conta TOTP registrada: %s", clean_name)
        return account

    def get(self, name: str) -> TotpAccount | None:
        """Return the account named ``name`` (secret included) or ``None``."""
        target = (name or "").strip()
        for account in self._load():
            if account.name == target:
                return account
        return None

    def list(self) -> list[dict]:
        """Every account as a redacted display dict — never with the secret."""
        return [redact(account) for account in sorted(self._load(), key=lambda a: a.name)]

    def remove(self, name: str) -> bool:
        """Delete ``name``; ``False`` when there was nothing to delete."""
        target = (name or "").strip()
        accounts = self._load()
        remaining = [account for account in accounts if account.name != target]
        if len(remaining) == len(accounts):
            return False
        self._save(remaining)
        logger.info("Conta TOTP removida: %s", target)
        return True

    def code(self, name: str, when: float | int | None = None) -> str:
        """The current code for ``name``; an unknown name raises ``ValueError``."""
        account = self.get(name)
        if account is None:
            raise ValueError(f"unknown account: {name}")
        return totp(account.secret, when, period=settings.totp_period_s, digits=settings.totp_digits)

    def uri(self, name: str) -> str:
        """The provisioning URI of ``name``; an unknown name raises ``ValueError``."""
        account = self.get(name)
        if account is None:
            raise ValueError(f"unknown account: {name}")
        return provisioning_uri(
            account.secret,
            account.name,
            issuer=account.issuer or "Zfrog",
            digits=settings.totp_digits,
            period=settings.totp_period_s,
        )
