"""Server half of the marketplace: build, verify, merge and serve a JSON index.

:class:`zfrog.marketplace.Marketplace` can already *read* an index published over
HTTP (:meth:`Marketplace.search_remote`), but nothing produced one. This module
produces it: :func:`index_from_marketplace` turns every published asset of a
marketplace into one document, :func:`write_index` saves that document atomically
so a shared folder, a git repository or any static host can serve it, and
:func:`merge_index` pulls such a document back into a local marketplace.

Every item carries a ``checksum`` over its ``kind``, ``name``, ``version`` and
``payload`` (canonical JSON, sha256), so a client can tell whether an installed
asset is exactly what the index advertises; :func:`verify_entry` answers that
question before installing something from a remote index.

Two rules keep a sync honest:

* a payload is always validated through ``Marketplace.publish`` before anything is
  written, so a broken item coming from an index lands in
  :attr:`SyncResult.skipped` with the reason in :attr:`SyncResult.errors` and
  never touches the local marketplace;
* an item that changed while keeping its version still wins, because the index is
  the source of truth of a sync: the stale local copy is dropped and republished
  from the index. That is the only case where the install and rating counters of
  an item are reset.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import httpx

from zfrog.marketplace import INDEX_TIMEOUT_S, Asset, Marketplace
from zfrog.utils.http import CHROME_HEADERS

logger = logging.getLogger(__name__)

#: Schema version written by :func:`build_index` and the only one accepted back.
INDEX_VERSION = 1

#: Prefix of the throwaway marketplace used to validate items before writing.
_CHECK_ROOT_PREFIX = "zfrog-index-check-"

@dataclass
class IndexEntry:
    """One item of an index: the asset metadata plus its checksum and date."""

    id: str
    kind: str
    name: str
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    installs: int = 0
    rating: float = 0.0
    rating_count: int = 0
    payload: dict = field(default_factory=dict)
    checksum: str = ""
    published_at: str = ""

@dataclass
class SyncResult:
    """What a :func:`merge_index` run did to the local marketplace."""

    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Return how many items the run looked at."""
        return self.added + self.updated + self.unchanged + self.skipped

# ── checksums ───────────────────────────────────────────────────────

def checksum_for(asset: Any) -> str:
    """Return the sha256 of an asset's identity: kind, name, version and payload.

    The JSON is canonical (``sort_keys=True``) and keeps non-ASCII characters, so
    the same asset always hashes the same and any change to the payload, the name,
    the kind or the version produces a different checksum. Accepts an
    :class:`IndexEntry`, a :class:`~zfrog.marketplace.Asset` or a plain mapping.
    Raises :class:`ValueError` when the payload cannot be serialised as JSON.
    """
    document = {
        "kind": _text(_get(asset, "kind")).lower(),
        "name": _text(_get(asset, "name")),
        "version": _text(_get(asset, "version")) or "1.0.0",
        "payload": _get(asset, "payload") or {},
    }
    try:
        canonical = json.dumps(document, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"o item não pode ser resumido em um checksum: {exc}") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def verify_entry(entry: Any, asset: Any) -> bool:
    """Return whether ``asset`` is exactly what ``entry`` advertises.

    The checksum of ``entry`` is compared with the one recomputed from the local
    asset; an entry without a checksum, or an asset that cannot be hashed, is
    reported as not verified.
    """
    expected = _text(_get(entry, "checksum"))
    if not expected:
        return False
    try:
        return checksum_for(asset) == expected
    except ValueError:
        return False

# ── building ────────────────────────────────────────────────────────

def build_index(assets: Iterable[Any], source: str = "") -> dict:
    """Build an index document out of ``assets`` (assets or entries).

    The result is ``{"version", "generated_at", "source", "count", "assets"}``,
    with the entries serialised as plain JSON sorted by id. An item without kind,
    name or payload raises :class:`ValueError`: an index never advertises
    something that could not be published.
    """
    entries = [_entry_from(asset) for asset in assets or []]
    entries.sort(key=lambda entry: entry.id)
    index = {
        "version": INDEX_VERSION,
        "generated_at": _now(),
        "source": _text(source),
        "count": len(entries),
        "assets": [asdict(entry) for entry in entries],
    }
    logger.info("Índice com %d itens gerado a partir de %s", index["count"], source or "local")
    return index

def index_from_marketplace(marketplace: Marketplace | None = None, source: str = "") -> dict:
    """Build an index with every asset published in ``marketplace``.

    ``marketplace`` defaults to one over :data:`zfrog.config.settings.marketplace_dir`,
    which is the marketplace the rest of Zfrog serves.
    """
    store = marketplace if marketplace is not None else Marketplace()
    index = build_index(store.list(), source=source)
    logger.info("Índice lido de %s: %d itens", store.root, index["count"])
    return index

# ── files ───────────────────────────────────────────────────────────

def write_index(path: Path, index: dict) -> Path:
    """Write ``index`` to ``path`` atomically and return the written path.

    The JSON is indented and keeps non-ASCII characters, so the file stays
    reviewable in a diff; the parent directory is created when missing and the
    content is swapped in with :func:`os.replace`, so a reader never sees a
    half-written index.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(index, indent=2, ensure_ascii=False)
    handle_fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-index-")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    logger.info("Índice gravado em %s", target)
    return target

def read_index(path: Path) -> dict:
    """Read and validate the index stored at ``path``.

    Raises :class:`ValueError` (never a traceback) for a missing or unreadable
    file, for text that is not JSON, for a document that is not an object, for an
    unsupported ``version`` and for a missing ``assets`` list.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"não foi possível ler o índice {source}: {exc}") from exc
    try:
        document = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"o índice {source} não é JSON válido: {exc}") from exc
    return _validate_index(document, source=str(source))

def _validate_index(document: Any, source: str = "") -> dict:
    """Return ``document`` when it is a usable index, or raise :class:`ValueError`."""
    where = f" em {source}" if source else ""
    if not isinstance(document, dict):
        raise ValueError(f"o índice{where} precisa ser um objeto JSON com 'version' e 'assets'")
    version = document.get("version")
    if version != INDEX_VERSION:
        raise ValueError(
            f"versão de índice não suportada{where}: {version!r} (esperada {INDEX_VERSION})"
        )
    if not isinstance(document.get("assets"), list):
        raise ValueError(f"o índice{where} precisa de uma lista 'assets'")
    return document

# ── merging a remote index into a local marketplace ─────────────────

def merge_index(
    index: dict,
    marketplace: Marketplace | None = None,
    trust: bool = False,
) -> SyncResult:
    """Publish every item of ``index`` into ``marketplace`` and report what happened.

    Items are compared by content: an id that is not published locally is
    ``added``, one whose checksum differs is ``updated`` and one that matches is
    ``unchanged``. An item that cannot be validated or whose id does not match its
    kind and name is ``skipped``, with the reason kept in ``errors``, and nothing
    is written for it.

    The install and rating counters an index advertises are informational: the
    counters of the local marketplace belong to it, so a new item starts at zero
    and an item that is updated keeps the numbers it already had.

    ``trust`` exists only to make the intent explicit: a caller that passes
    ``trust=True`` is saying it trusts the index, but the payload is *still*
    validated through ``Marketplace.publish`` — the flag never disables a check.
    """
    document = _validate_index(index)
    store = marketplace if marketplace is not None else Marketplace()
    if trust:
        logger.info("trust=True: a intenção é explícita, mas os payloads continuam validados")

    result = SyncResult()
    with tempfile.TemporaryDirectory(prefix=_CHECK_ROOT_PREFIX) as check_root:
        checker = Marketplace(root=Path(check_root))
        for raw in document["assets"]:
            try:
                entry = _entry_from(raw)
            except ValueError as exc:
                result.skipped += 1
                result.errors.append(f"item inválido no índice: {exc}")
                continue

            local = store.get(entry.id)
            if local is not None and checksum_for(local) == entry.checksum:
                result.unchanged += 1
                continue

            try:
                _publish_entry(store, checker, entry)
            except ValueError as exc:
                result.skipped += 1
                result.errors.append(f"{entry.id}: {exc}")
                continue

            if local is None:
                result.added += 1
            else:
                result.updated += 1

    logger.info(
        "Índice sincronizado: %d novos, %d atualizados, %d iguais, %d ignorados",
        result.added,
        result.updated,
        result.unchanged,
        result.skipped,
    )
    return result

def _publish_entry(store: Marketplace, checker: Marketplace, entry: IndexEntry) -> Asset:
    """Publish ``entry`` in ``store``, replacing a local item of the same version.

    ``checker`` is a throwaway marketplace: publishing there proves the item is
    acceptable (valid payload, id matching kind and name) *before* anything is
    touched locally, so a rejected item never disturbs the local marketplace. The
    only case that needs a replacement is an item that changed while keeping its
    version, which :meth:`Marketplace.publish` refuses to overwrite; the stale
    local copy is dropped then, and its install and rating counters with it.
    """
    checked = _publish(checker, entry)
    if checked.id != entry.id:
        raise ValueError(
            f"o id {entry.id!r} não corresponde a {entry.kind}/{entry.name!r} "
            f"(o Marketplace usaria {checked.id!r})"
        )

    local = store.get(entry.id)
    if local is not None and local.version == entry.version and local.payload != entry.payload:
        logger.info("Item %s trocado por outro payload na mesma versão", entry.id)
        store.remove(entry.id)
    return _publish(store, entry)

def _publish(store: Marketplace, entry: IndexEntry) -> Asset:
    """Publish one entry into ``store`` with the metadata the index carries."""
    return store.publish(
        entry.kind,
        entry.name,
        entry.payload,
        description=entry.description,
        author=entry.author,
        version=entry.version,
        tags=list(entry.tags),
    )

# ── serving ─────────────────────────────────────────────────────────

async def fetch_index(index_url: str, client: httpx.AsyncClient | None = None) -> dict:
    """Fetch and validate the index published at ``index_url``.

    ``client`` may be an existing :class:`httpx.AsyncClient` (it is not closed
    then); otherwise a short-lived one is used. Unlike the best-effort
    :meth:`Marketplace.search_remote`, this one raises :class:`ValueError` for an
    unreachable host, a non-2xx answer, a body that is not JSON or a document that
    is not a valid index: the caller here is an explicit sync command that has to
    report the problem.
    """
    url = _text(index_url)
    if not url:
        raise ValueError("o índice precisa de uma URL")

    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=INDEX_TIMEOUT_S, follow_redirects=True, headers=CHROME_HEADERS
    )
    try:
        response = await http.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ValueError(f"índice remoto indisponível em {url}: {exc}") from exc
    finally:
        if owns_client:
            await http.aclose()

    try:
        document = response.json()
    except ValueError as exc:
        raise ValueError(f"o índice em {url} não é JSON válido: {exc}") from exc
    return _validate_index(document, source=url)

def index_summary(index: dict) -> str:
    """Return one Portuguese sentence about ``index``: how many items, which kinds, from where."""
    document = _validate_index(index)
    source = _text(document.get("source")) or "local"
    assets = document["assets"]
    if not assets:
        return f"O índice de {source} não tem nenhum item publicado."

    kinds = Counter(_text(_get(asset, "kind")).lower() or "desconhecido" for asset in assets)
    detail = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))
    return f"O índice de {source} tem {len(assets)} itens ({detail})."

# ── helpers ─────────────────────────────────────────────────────────

def _entry_from(asset: Any) -> IndexEntry:
    """Build an :class:`IndexEntry` from an asset or from an index item.

    Accepts a :class:`~zfrog.marketplace.Asset`, an :class:`IndexEntry` or the
    plain dict of an index, and raises :class:`ValueError` when the item could not
    be published (no id, kind, name or payload).
    """
    kind = _text(_get(asset, "kind")).lower()
    name = _text(_get(asset, "name"))
    asset_id = _text(_get(asset, "id"))
    if not kind:
        raise ValueError(f"item sem tipo: {name!r}")
    if not name:
        raise ValueError(f"item {asset_id or kind} sem nome")
    if not asset_id:
        raise ValueError(f"item {kind}/{name!r} sem id")
    payload = _get(asset, "payload")
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"item {asset_id} sem payload utilizável")

    entry = IndexEntry(
        id=asset_id,
        kind=kind,
        name=name,
        description=_text(_get(asset, "description")),
        author=_text(_get(asset, "author")),
        version=_text(_get(asset, "version")) or "1.0.0",
        tags=_tags(_get(asset, "tags")),
        installs=_as_int(_get(asset, "installs")),
        rating=_as_float(_get(asset, "rating")),
        rating_count=_as_int(_get(asset, "rating_count")),
        payload=payload,
        checksum="",
        published_at=_text(_get(asset, "published_at")) or _now(),
    )
    entry.checksum = checksum_for(entry)
    return entry

def _now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()

def _get(source: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a mapping, a dataclass or any object, else ``default``."""
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)

def _text(value: Any) -> str:
    """Return ``value`` as a trimmed string, and ``''`` for None."""
    return str(value).strip() if value is not None else ""

def _tags(value: Any) -> list[str]:
    """Return ``value`` as non-empty, de-duplicated tag strings."""
    if isinstance(value, str):
        candidates: list[Any] = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        return []

    tags: list[str] = []
    for tag in candidates:
        text = str(tag).strip()
        if text and text not in tags:
            tags.append(text)
    return tags

def _as_int(value: Any) -> int:
    """Return ``value`` as a non-negative int, defaulting to 0."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0

def _as_float(value: Any) -> float:
    """Return ``value`` as a non-negative float, defaulting to 0.0."""
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0
