"""Local marketplace of reusable assets: workflows, engine plugins and templates.

A marketplace is just a directory (``settings.marketplace_dir`` by default):
publishing an asset writes one JSON file per item under
``<root>/<kind>s/<id>.json`` — ``workflows``, ``plugins`` or ``templates`` — so a
shared folder or a git repository works as a marketplace without any server. An
index published over HTTP can be read with :meth:`Marketplace.search_remote`.

Every payload is validated against its kind *before* it is written: a workflow is
checked with :func:`zfrog.workflows.validate_steps`, a plugin is compiled and
executed in a throwaway namespace to prove it defines an
:class:`~zfrog.engines.base.EngineAdapter` subclass with a name, and a template
must carry a non-empty ``selectors`` mapping. A broken asset therefore never
reaches the directory, and it is validated again on install.

Installing puts the asset where the rest of Zfrog looks for it: workflows go to
the :class:`~zfrog.workflows.WorkflowStore`, plugins to ``settings.plugins_dir``
and templates to ``settings.output_dir/templates``. Each successful install
increments the install counter stored in the asset file, so popularity and
ratings survive a restart, and :meth:`Marketplace.uninstall` removes exactly what
:meth:`Marketplace.install` wrote (the published asset itself stays).
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from zfrog.config import settings
from zfrog.engines.base import EngineAdapter
from zfrog.utils.http import CHROME_HEADERS
from zfrog.workflows import WorkflowStore, validate_steps

logger = logging.getLogger(__name__)

#: Asset kinds a marketplace accepts, each with its own directory and rules.
KINDS: tuple[str, ...] = ("workflow", "plugin", "template")

#: Highest score :meth:`Marketplace.rate` accepts.
MAX_RATING = 5.0

#: How long :meth:`Marketplace.search_remote` waits for the index.
INDEX_TIMEOUT_S = 15.0

#: Everything that is not a letter or a digit collapses into a single dash.
_SLUG_SEPARATOR = re.compile(r"[^a-z0-9]+")


@dataclass
class Asset:
    """One published asset: metadata plus the payload of its kind."""

    id: str
    kind: str
    name: str
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    payload: dict = field(default_factory=dict)
    installs: int = 0
    rating: float = 0.0
    rating_count: int = 0


class Marketplace:
    """Read and write the assets published under ``root``."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else Path(settings.marketplace_dir)

    # ── publishing ──────────────────────────────────────────────────

    def publish(
        self,
        kind: str,
        name: str,
        payload: dict,
        description: str = "",
        author: str = "",
        version: str = "1.0.0",
        tags: list[str] | None = None,
    ) -> Asset:
        """Validate ``payload`` and store it under ``kind``/``name``.

        The id is a slug of the kind and the name, so republishing the same name
        keeps the same id. Replacing an asset with a *different* payload is
        refused unless ``version`` changes; installs and ratings are kept when
        it does. Raises :class:`ValueError` for an unknown kind, an empty name or
        a payload that breaks the rules of its kind (nothing is written then).
        """
        clean_kind = str(kind or "").strip().lower()
        if clean_kind not in KINDS:
            raise ValueError(
                f"tipo de item desconhecido: {kind!r} (use workflow, plugin ou template)"
            )
        clean_name = name.strip() if isinstance(name, str) else ""
        if not clean_name:
            raise ValueError("o item precisa de um nome")
        if not isinstance(payload, dict) or not payload:
            raise ValueError("o item precisa de um payload com conteúdo")

        data = _json_copy(payload)
        _validate_payload(clean_kind, data)

        asset_id = _asset_id(clean_kind, clean_name)
        path = self._path(clean_kind, asset_id)
        previous = self._read(path)
        clean_version = str(version or "").strip() or "1.0.0"
        if previous is not None and previous.payload != data and previous.version == clean_version:
            raise ValueError(
                f"{asset_id} já existe com outro payload na versão {clean_version}; "
                "publique uma versão nova"
            )

        asset = Asset(
            id=asset_id,
            kind=clean_kind,
            name=clean_name,
            description=str(description or ""),
            author=str(author or ""),
            version=clean_version,
            tags=_clean_tags(tags),
            payload=data,
            installs=previous.installs if previous else 0,
            rating=previous.rating if previous else 0.0,
            rating_count=previous.rating_count if previous else 0,
        )
        self._write(path, _asset_to_payload(asset))
        logger.info("Item %s publicado (%s)", asset.id, clean_kind)
        return asset

    # ── browsing ────────────────────────────────────────────────────

    def list(
        self,
        kind: str | None = None,
        query: str | None = None,
        tag: str | None = None,
    ) -> list[Asset]:
        """Return the published assets, best rated first and most installed next."""
        wanted_kind = str(kind).strip().lower() if kind else None
        wanted_tag = str(tag).strip().casefold() if tag else None
        needle = str(query).strip().casefold() if query else None

        assets: list[Asset] = []
        for path in self._paths():
            asset = self._read(path)
            if asset is None:
                continue
            if wanted_kind and asset.kind != wanted_kind:
                continue
            if wanted_tag and wanted_tag not in {item.casefold() for item in asset.tags}:
                continue
            if needle and not _matches(asset, needle):
                continue
            assets.append(asset)

        return sorted(assets, key=lambda asset: (-asset.rating, -asset.installs, asset.name))

    def get(self, asset_id: str) -> Asset | None:
        """Return the asset with ``asset_id``, or None when it is not published."""
        found = self._find(asset_id)
        return found[0] if found is not None else None

    # ── installing ──────────────────────────────────────────────────

    def install(self, asset_id: str) -> dict:
        """Install ``asset_id`` and report what was installed and where.

        Returns ``{"kind", "name", "target", "installed", "detail"}``; ``target``
        is the workflow id for a workflow and the written path otherwise. The
        asset's install counter is incremented and saved. Raises
        :class:`ValueError` when the asset is unknown or its payload is invalid.
        """
        found = self._find(asset_id)
        if found is None:
            raise ValueError(f"item não encontrado: {asset_id}")
        asset, path = found

        installer = _INSTALLERS.get(asset.kind)
        if installer is None:
            raise ValueError(f"tipo de item desconhecido: {asset.kind!r}")
        _validate_payload(asset.kind, asset.payload)

        try:
            target, detail = installer(self, asset)
        except OSError as exc:
            logger.warning("Falha ao instalar %s: %s", asset.id, exc)
            return {
                "kind": asset.kind,
                "name": asset.name,
                "target": "",
                "installed": False,
                "detail": f"falha ao instalar: {exc}",
            }

        asset.installs += 1
        self._write(path, _asset_to_payload(asset))
        logger.info("Item %s instalado em %s", asset.id, target)
        return {
            "kind": asset.kind,
            "name": asset.name,
            "target": target,
            "installed": True,
            "detail": detail,
        }

    def uninstall(self, asset_id: str) -> bool:
        """Remove what :meth:`install` wrote, returning whether anything went away.

        The published asset itself is never deleted here.
        """
        found = self._find(asset_id)
        if found is None:
            return False
        asset, _ = found

        if asset.kind == "plugin":
            removed = _remove_file(Path(settings.plugins_dir) / f"{asset.id}.py")
        elif asset.kind == "template":
            removed = _remove_file(
                Path(settings.output_dir) / "templates" / f"{asset.id}.json"
            )
        elif asset.kind == "workflow":
            removed = self._uninstall_workflow(asset)
        else:
            logger.warning("Não sei desinstalar o tipo %s", asset.kind)
            return False

        if removed:
            logger.info("Instalação de %s removida", asset.id)
        return removed

    def rate(self, asset_id: str, score: float) -> Asset:
        """Add ``score`` (0-5) to the asset's average and save the result."""
        found = self._find(asset_id)
        if found is None:
            raise ValueError(f"item não encontrado: {asset_id}")
        asset, path = found

        value = _score(score)
        total = asset.rating * asset.rating_count + value
        asset.rating_count += 1
        asset.rating = round(total / asset.rating_count, 6)
        self._write(path, _asset_to_payload(asset))
        logger.info("Item %s avaliado com %.1f (média %.2f)", asset.id, value, asset.rating)
        return asset

    def remove(self, asset_id: str) -> bool:
        """Delete the published asset, returning whether a file was removed."""
        found = self._find(asset_id)
        if found is None:
            return False
        asset, path = found
        path.unlink()
        logger.info("Item %s removido do marketplace", asset.id)
        return True

    # ── remote index ────────────────────────────────────────────────

    def search_remote(self, index_url: str) -> list[Asset]:
        """Read an index of assets published at ``index_url``.

        The index is JSON: either a list of assets or an object with an
        ``assets`` list. An unreachable or malformed index is logged and
        reported as an empty list instead of raising.
        """
        url = str(index_url or "").strip()
        if not url:
            raise ValueError("o índice precisa de uma URL")

        try:
            with httpx.Client(
                timeout=INDEX_TIMEOUT_S, follow_redirects=True, headers=CHROME_HEADERS
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Índice remoto indisponível em %s: %s", url, exc)
            return []

        return _assets_from_index(document, url)

    # ── internals ───────────────────────────────────────────────────

    def _path(self, kind: str, asset_id: str) -> Path:
        return self.root / f"{kind}s" / f"{asset_id}.json"

    def _paths(self) -> list[Path]:
        """Return every file that may hold an asset, in a stable order."""
        if not self.root.is_dir():
            return []
        found = set(self.root.glob("*/*.json")) | set(self.root.glob("*.json"))
        return sorted(found)

    def _find(self, asset_id: str) -> tuple[Asset, Path] | None:
        """Return the asset with ``asset_id`` together with the file holding it."""
        wanted = str(asset_id or "").strip()
        if not wanted:
            return None
        for path in self._paths():
            if path.stem != wanted:
                continue
            asset = self._read(path)
            if asset is not None:
                return asset, path
        return None

    def _read(self, path: Path) -> Asset | None:
        """Read one asset file, returning None (and logging) when it is unusable."""
        if not path.is_file():
            return None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Item ilegível %s: %s", path, exc)
            return None
        asset = _asset_from_payload(document)
        if asset is None:
            logger.warning("Item inválido em %s", path)
        return asset

    def _write(self, path: Path, payload: dict) -> None:
        """Write ``payload`` as JSON through a temporary file plus ``os.replace``."""
        _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))

    def _uninstall_workflow(self, asset: Asset) -> bool:
        """Remove the workflow :meth:`install` saved under the asset's name."""
        store = WorkflowStore()
        for workflow in store.list():
            if workflow.name == asset.name:
                return store.remove(workflow.id)
        return False

    def _install_workflow(self, asset: Asset) -> tuple[str, str]:
        """Save the asset's steps in the workflow store; return its id and path."""
        store = WorkflowStore()
        workflow = store.save(asset.name, list(asset.payload.get("steps") or []))
        return workflow.id, f"fluxo salvo como {workflow.id} em {store.root}"

    def _install_plugin(self, asset: Asset) -> tuple[str, str]:
        """Write the plugin source as a loadable module in ``plugins_dir``."""
        path = Path(settings.plugins_dir) / f"{asset.id}.py"
        _write_text(path, str(asset.payload.get("source") or ""))
        return str(path), f"plugin gravado em {path}"

    def _install_template(self, asset: Asset) -> tuple[str, str]:
        """Write the template JSON under ``output_dir/templates``."""
        path = Path(settings.output_dir) / "templates" / f"{asset.id}.json"
        document = {
            "id": asset.id,
            "kind": asset.kind,
            "name": asset.name,
            "version": asset.version,
            "description": asset.description,
            **asset.payload,
        }
        self._write(path, document)
        return str(path), f"template gravado em {path}"


#: Installers per kind, so an unknown kind can be refused in one place.
_INSTALLERS: dict[str, Callable[[Marketplace, Asset], tuple[str, str]]] = {
    "workflow": Marketplace._install_workflow,
    "plugin": Marketplace._install_plugin,
    "template": Marketplace._install_template,
}


def _slugify(text: str) -> str:
    """Reduce ``text`` to lowercase ASCII words joined by dashes."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return _SLUG_SEPARATOR.sub("-", ascii_text).strip("-")


def _asset_id(kind: str, name: str) -> str:
    """Return the stable id of an asset: the kind plus the slug of its name."""
    slug = _slugify(name)
    if not slug:
        raise ValueError(f"nome inválido para um item: {name!r}")
    return f"{kind}-{slug}"


def _clean_tags(tags: Any) -> list[str]:
    """Return ``tags`` as non-empty, de-duplicated strings, in order."""
    if tags is None:
        return []
    if isinstance(tags, str):
        candidates: list[Any] = [tags]
    else:
        try:
            candidates = list(tags)
        except TypeError as exc:
            raise ValueError(f"tags inválidas: {tags!r}") from exc

    cleaned: list[str] = []
    for tag in candidates:
        text = str(tag).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _json_copy(payload: dict) -> dict:
    """Return a JSON round-trip of ``payload``, refusing what cannot be stored."""
    try:
        return json.loads(json.dumps(payload, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"o payload precisa ser serializável em JSON: {exc}") from exc


def _matches(asset: Asset, needle: str) -> bool:
    """Return whether ``needle`` (already folded) appears in the asset's text."""
    haystack = " ".join([asset.id, asset.name, asset.description, asset.author, *asset.tags])
    return needle in haystack.casefold()


def _score(score: Any) -> float:
    """Return ``score`` as a number between 0 and 5, refusing anything else."""
    try:
        value = float(score)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"nota inválida: {score!r}") from exc
    if not 0.0 <= value <= MAX_RATING:
        raise ValueError(f"a nota precisa estar entre 0 e {MAX_RATING:.0f}: {score!r}")
    return value


def _validate_payload(kind: str, payload: Any) -> None:
    """Check ``payload`` against the rules of ``kind`` (``ValueError`` when not)."""
    validator = _VALIDATORS.get(kind)
    if validator is None:
        raise ValueError(
            f"tipo de item desconhecido: {kind!r} (use workflow, plugin ou template)"
        )
    if not isinstance(payload, dict) or not payload:
        raise ValueError("o item precisa de um payload com conteúdo")
    validator(payload)


def _validate_workflow(payload: dict) -> None:
    """Refuse a workflow payload whose ``steps`` are missing or invalid."""
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("o fluxo precisa de uma lista 'steps' com pelo menos um passo")
    validate_steps(steps)


def _validate_plugin(payload: dict) -> None:
    """Refuse a plugin payload that does not define a usable engine.

    The source is executed in a throwaway namespace: a plugin that cannot even
    be imported is never published, and the class it declares must be an
    :class:`~zfrog.engines.base.EngineAdapter` subclass with a non-empty name.
    """
    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("o plugin precisa de 'source' com o código do motor")

    namespace: dict[str, Any] = {"__name__": "zfrog_marketplace_plugin"}
    try:
        exec(compile(source, "<plugin>", "exec"), namespace)  # noqa: S102
    except Exception as exc:
        raise ValueError(f"o plugin não pode ser carregado: {exc}") from exc

    for value in namespace.values():
        if not isinstance(value, type) or value is EngineAdapter:
            continue
        if issubclass(value, EngineAdapter) and str(getattr(value, "name", "") or "").strip():
            return
    raise ValueError("o plugin precisa definir um motor (subclasse de EngineAdapter) com 'name'")


def _validate_template(payload: dict) -> None:
    """Refuse a template payload without a mapping of non-empty selectors."""
    selectors = payload.get("selectors")
    if not isinstance(selectors, dict) or not selectors:
        raise ValueError("o template precisa de 'selectors' como objeto não vazio")
    for key, value in selectors.items():
        if not str(key).strip():
            raise ValueError("o template tem um seletor sem nome")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"o seletor {key!r} precisa de um valor de texto não vazio")


#: Validators per kind, used both when publishing and when installing.
_VALIDATORS: dict[str, Callable[[dict], None]] = {
    "workflow": _validate_workflow,
    "plugin": _validate_plugin,
    "template": _validate_template,
}


def _asset_to_payload(asset: Asset) -> dict:
    """Serialise an asset into its on-disk JSON shape."""
    return {
        "id": asset.id,
        "kind": asset.kind,
        "name": asset.name,
        "description": asset.description,
        "author": asset.author,
        "version": asset.version,
        "tags": list(asset.tags),
        "payload": asset.payload,
        "installs": asset.installs,
        "rating": asset.rating,
        "rating_count": asset.rating_count,
    }


def _asset_from_payload(payload: Any) -> Asset | None:
    """Build an :class:`Asset` from stored or remote JSON, or None when unusable."""
    if not isinstance(payload, dict):
        return None
    kind = str(payload.get("kind") or "").strip().lower()
    name = str(payload.get("name") or "").strip()
    if not kind or not name:
        return None

    stored_id = str(payload.get("id") or "").strip()
    if not stored_id:
        try:
            stored_id = _asset_id(kind, name)
        except ValueError:
            return None

    raw_payload = payload.get("payload")
    try:
        tags = _clean_tags(payload.get("tags"))
    except ValueError as exc:
        logger.warning("Tags inválidas em %s: %s", name, exc)
        return None
    return Asset(
        id=stored_id,
        kind=kind,
        name=name,
        description=str(payload.get("description") or ""),
        author=str(payload.get("author") or ""),
        version=str(payload.get("version") or "1.0.0"),
        tags=tags,
        payload=dict(raw_payload) if isinstance(raw_payload, dict) else {},
        installs=_as_int(payload.get("installs")),
        rating=_as_float(payload.get("rating")),
        rating_count=_as_int(payload.get("rating_count")),
    )


def _assets_from_index(document: Any, source: str) -> list[Asset]:
    """Read the assets of a remote index, skipping the entries that make no sense."""
    entries = document.get("assets") if isinstance(document, dict) else document
    if not isinstance(entries, list):
        logger.warning("Índice remoto sem lista de itens: %s", source)
        return []

    assets: list[Asset] = []
    for entry in entries:
        asset = _asset_from_payload(entry)
        if asset is None:
            logger.warning("Item inválido no índice %s: %r", source, entry)
            continue
        assets.append(asset)
    return assets


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


def _write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically, creating its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _remove_file(path: Path) -> bool:
    """Delete ``path`` when it exists, returning whether it was there."""
    if not path.is_file():
        return False
    path.unlink()
    return True
