"""Outbound destinations: push extracted records to Sheets, Airtable or Notion.

Every destination is one JSON file under :data:`settings.integrations_dir` holding
the API token plus the ids the remote service needs. Those files are credentials,
so they are created with mode ``0o600`` and replaced atomically: a crash in the
middle of a save never leaves a truncated destination behind.

:meth:`DestinationStore.list` and :meth:`DestinationStore.get` hand out the tokens
in clear text, because the clients need them to authenticate; :func:`redact` is the
form to use for anything printed or logged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from zfrog.config import settings

logger = logging.getLogger(__name__)

#: Mode destination files are created with: they hold API tokens.
FILE_MODE = 0o600

#: Config keys whose value :func:`redact` masks (case-insensitive substring match,
#: so ``access_token`` and ``api_key`` are covered as well).
SECRET_MARKERS = ("token", "secret", "password", "key")

#: What :func:`redact` puts in place of a credential.
MASK = "***"

#: Longest response body kept inside a :class:`PushResult` error message.
ERROR_BODY_MAX = 300

_UNSAFE_IN_SLUG = re.compile(r"[^a-z0-9._-]+")


@dataclass
class Destination:
    """One remote place records can be pushed to.

    ``config`` carries the credentials and ids the service needs (``token``,
    ``spreadsheet_id``, ``base_id``, ``table``, ``database_id``, ...).
    """

    kind: str
    name: str
    config: dict = field(default_factory=dict)


@dataclass
class PushResult:
    """Outcome of one push, with failures collected instead of raised."""

    destination: str
    rows: int = 0
    created: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)


class DestinationStore:
    """One JSON file per destination under ``root`` (default ``settings.integrations_dir``).

    The files hold API tokens, so they are written with mode ``0o600`` and are
    readable only by the account running the push.
    """

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else Path(settings.integrations_dir)

    # ── CRUD ────────────────────────────────────────────────────────

    def save(self, destination: Destination) -> Destination:
        """Store ``destination`` under its name, replacing a destination of that name.

        Raises :class:`ValueError` for an empty name or kind, and writes nothing
        in that case. The returned destination is the normalised copy that was
        written (name and kind stripped).
        """
        name = str(destination.name or "").strip()
        kind = str(destination.kind or "").strip().lower()
        if not name:
            raise ValueError("o destino precisa de um nome")
        if not kind:
            raise ValueError(f"o destino {name} precisa de um tipo")

        stored = Destination(kind=kind, name=name, config=dict(destination.config or {}))
        self._write_atomic(self._path(name), asdict(stored))
        logger.info("Destino %s (%s) salvo", name, kind)
        return stored

    def list(self) -> list[Destination]:
        """Every stored destination, sorted by name (unreadable files are skipped).

        The tokens come back in clear text: the clients authenticate with them.
        """
        if not self.root.is_dir():
            return []
        destinations = [
            destination
            for destination in (self._read(path) for path in sorted(self.root.glob("*.json")))
            if destination is not None
        ]
        return sorted(destinations, key=lambda destination: destination.name)

    def get(self, name: str) -> Destination | None:
        """Return the destination stored under ``name``, or None when there is none."""
        wanted = str(name or "").strip()
        if not wanted:
            return None
        for destination in self.list():
            if destination.name == wanted:
                return destination
        return None

    def remove(self, name: str) -> bool:
        """Delete the destination stored under ``name``; True when a file was removed."""
        wanted = str(name or "").strip()
        if not wanted:
            return False
        path = self._path(wanted)
        if not path.is_file():
            return False
        stored = self._read(path)
        if stored is None or stored.name != wanted:
            return False
        path.unlink()
        logger.info("Destino %s removido", wanted)
        return True

    # ── internals ───────────────────────────────────────────────────

    def _path(self, name: str) -> Path:
        """File holding ``name``, falling back to a digest when two names share a slug."""
        slug = _slug(name)
        for path in (self.root / f"{slug}.json", self.root / f"{slug}-{_digest(name)}.json"):
            if not path.is_file():
                return path
            stored = self._read(path)
            if stored is None or stored.name == name:
                return path
        return self.root / f"{slug}-{_digest(name)}.json"

    def _write_atomic(self, path: Path, payload: dict) -> None:
        """Write ``payload`` to ``path`` through a mode-0600 temp file plus ``os.replace``."""
        self.root.mkdir(parents=True, exist_ok=True)
        handle_fd, temp_name = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        temp_path = Path(temp_name)
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, FILE_MODE)
            os.replace(temp_path, path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

    def _read(self, path: Path) -> Destination | None:
        """Read one destination file, returning None (and logging) when it is unusable."""
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            name = str(payload["name"])
            kind = str(payload["kind"])
            config = payload.get("config") or {}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Destino ilegível em %s: %s", path, exc)
            return None
        if not isinstance(config, dict):
            logger.warning("Destino %s ignorado: config não é um objeto JSON", path)
            return None
        return Destination(kind=kind, name=name, config=dict(config))


class DestinationClient(ABC):
    """A remote service records can be pushed to."""

    #: Value of :attr:`Destination.kind` this client handles.
    kind: str = ""

    @abstractmethod
    async def push(self, destination: Destination, rows: list[dict]) -> PushResult:
        """Send ``rows`` to ``destination``.

        Failures (unreachable host, 4xx, 5xx, rejected records) are collected in
        :attr:`PushResult.errors` instead of raised, so one bad batch does not
        abort the push.
        """


def client_for(destination: Destination) -> DestinationClient:
    """Return the client that speaks ``destination.kind``.

    Raises :class:`ValueError` for a kind no client handles.
    """
    from zfrog.integrations.airtable import AirtableClient
    from zfrog.integrations.notion import NotionClient
    from zfrog.integrations.sheets import SheetsClient

    kind = str(destination.kind or "").strip().lower()
    for client_class in (SheetsClient, AirtableClient, NotionClient):
        if client_class.kind == kind:
            return client_class()
    raise ValueError(f"tipo de destino desconhecido: {destination.kind!r}")


def redact(destination: Destination) -> dict:
    """Return ``destination`` as a plain dict with the credentials masked.

    The store deliberately returns real tokens (the clients need them); use this
    for CLI output, logs and anything else a human reads.
    """
    config = {
        str(key): (MASK if _is_secret(str(key)) else value)
        for key, value in (destination.config or {}).items()
    }
    return {"name": destination.name, "kind": destination.kind, "config": config}


def rows_from_records(
    records: list[dict], fields: list[str] | None = None
) -> tuple[list[str], list[list]]:
    """Turn ``records`` into a ``(header, rows)`` matrix.

    Without ``fields`` the header is the union of the record keys in first-seen
    order. Every row follows the header, and a record missing a field contributes
    ``""`` for it. Raises :class:`TypeError` when a record is not a JSON object.
    """
    for record in records:
        if not isinstance(record, dict):
            raise TypeError(f"registro não é um objeto JSON: {type(record).__name__}")

    header: list[str] = []
    if fields is None:
        for record in records:
            for key in record:
                name = str(key)
                if name not in header:
                    header.append(name)
    else:
        header = [str(name) for name in fields]

    return header, [[record.get(name, "") for name in header] for record in records]


def column_fields(config: dict) -> list[str] | None:
    """Column order named by a destination config (``fields``), or None for the union.

    Accepts a list or a comma-separated string, so a destination written by hand
    can pin the order of the columns it sends.
    """
    raw = config.get("fields")
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple)):
        names = [str(item) for item in raw]
        return names or None
    return None


def config_text(config: dict, key: str) -> str:
    """Return ``config[key]`` as a stripped string, or "" when it is absent."""
    value = config.get(key)
    return str(value).strip() if value is not None else ""


def error_detail(response: httpx.Response) -> str:
    """One-line, length-capped body of a response, for :attr:`PushResult.errors`."""
    return " ".join(response.text.split())[:ERROR_BODY_MAX]


def response_error(response: httpx.Response, service: str) -> str:
    """Return "" for a success response, else ``"<service> respondeu <status>: <body>"``."""
    if response.status_code < 400:
        return ""
    detail = error_detail(response)
    return f"{service} respondeu {response.status_code}" + (f": {detail}" if detail else "")


def _is_secret(key: str) -> bool:
    """Whether a config key holds a credential."""
    lowered = key.lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def _slug(name: str) -> str:
    """Filesystem-safe stem for ``name``."""
    slug = _UNSAFE_IN_SLUG.sub("-", name.strip().lower()).strip("-._")
    return slug or "destino"


def _digest(name: str) -> str:
    """Short stable suffix separating two names that share a slug."""
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
