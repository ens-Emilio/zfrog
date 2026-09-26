"""Per-organization data isolation ("workspaces").

Every store in Zfrog already accepts an explicit path or root (``VersionStore(root=...)``,
``SearchIndex(db_path=...)``, ``AuditLog(path=...)`` and so on), so isolating one organization
from another is a matter of *computing* the right paths and handing them over. This module
computes them; it modifies no store and mutates no global state.

Layout — ``root`` is ``settings.output_dir / "orgs" / <slug>``::

    output/orgs/<slug>/
        output/          clones and jobs of this org
        versions/        git-like history
        schedules.json
        workflows/
        marketplace/
        integrations/
        search.db
        metrics.db
        audit.log
        .rag-multi/
        chats/
        sessions/
        annotations/
        domains/

Identity is global, data is per-org: ``users_file`` and ``orgs_file`` stay at
``settings.users_file`` / ``settings.orgs_file``, shared by every workspace. A user belongs to
organizations, so their account cannot live inside one of them; deleting a workspace therefore
never touches those two files.
"""

from __future__ import annotations

import logging
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from zfrog.config import settings

logger = logging.getLogger(__name__)

#: Directory holding one sub-directory per organization, under ``settings.output_dir``.
ORGS_DIRNAME = "orgs"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SLUG_ONLY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
#: Path separators, NUL and ``..`` — never normalised away, always refused.
_UNSAFE_RE = re.compile(r"[\\/\x00]|\.\.")

#: The directories ``for_org`` creates up front. Files (``search.db``, ``audit.log``, ...)
#: are created by the store that owns them, on first write.
DIRECTORY_NAMES: tuple[str, ...] = (
    "output",
    "versions",
    "workflows",
    "marketplace",
    "integrations",
    ".rag-multi",
    "chats",
    "sessions",
    "annotations",
    "domains",
    "analysis",
    "finetune",
)

#: ``Workspace`` properties whose value lives inside the org root (never the shared identity files).
_DATA_PROPERTIES: tuple[str, ...] = (
    "output_dir",
    "versions_dir",
    "schedules_file",
    "workflows_dir",
    "marketplace_dir",
    "integrations_dir",
    "search_db",
    "metrics_db",
    "audit_log",
    "multisite_dir",
    "chats_dir",
    "sessions_dir",
    "annotations_dir",
    "domains_dir",
    "analysis_dir",
    "finetune_dir",
    "totp_file",
    "arweave_wallet_file",
)

#: ``settings`` attribute -> ``Workspace`` property that replaces it under :func:`scoped`.
#: ``workflows_dir`` has no settings field yet and is skipped when absent.
_SCOPED_FIELDS: tuple[tuple[str, str], ...] = (
    ("output_dir", "output_dir"),
    ("versions_dir", "versions_dir"),
    ("schedules_file", "schedules_file"),
    ("workflows_dir", "workflows_dir"),
    ("marketplace_dir", "marketplace_dir"),
    ("integrations_dir", "integrations_dir"),
    ("search_db", "search_db"),
    ("metrics_db", "metrics_db"),
    ("audit_log", "audit_log"),
    ("sessions_dir", "sessions_dir"),
    ("annotations_dir", "annotations_dir"),
    ("domain_profiles_dir", "domains_dir"),
)


def _slug(value: str) -> str:
    """Lowercase ``value`` and collapse every run of non-alphanumerics into ``-``."""
    return _SLUG_RE.sub("-", str(value or "").strip().lower()).strip("-")


def slug_org(org: str) -> str:
    """Return the directory-safe slug used for ``org``.

    Lowercased, with every run of non-alphanumeric characters collapsed into a single ``-``;
    an empty name falls back to ``settings.default_org``.

    A name carrying a path separator or a ``..`` sequence is refused with :class:`ValueError`
    rather than normalised: ``../../etc/passwd`` would otherwise become ``etc-passwd``, silently
    pointing at a different organization than the caller asked for.
    """
    raw = str(org or "").strip()
    if not raw:
        return _slug(settings.default_org) or "default"

    if _UNSAFE_RE.search(raw):
        raise ValueError(f"nome de organização inválido: {org!r}")

    slug = _slug(raw)
    if not slug:
        raise ValueError(f"nome de organização inválido: {org!r}")
    return slug


def _inside(path: Path, root: Path) -> bool:
    """Return True when ``path`` resolves to something inside ``root``."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
    return True


@dataclass
class Workspace:
    """The paths of one organization's data.

    Build these through :class:`WorkspaceManager` (or :func:`get_workspace`), which validates
    ``org`` and creates the tree.
    """

    org: str
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    # ── identity ──

    @property
    def slug(self) -> str:
        """Directory name of this workspace, i.e. ``root.name``."""
        return self.root.name

    # ── per-org data ──

    @property
    def output_dir(self) -> Path:
        """Clones, jobs and pipeline artefacts of this organization."""
        return self.root / "output"

    @property
    def versions_dir(self) -> Path:
        """Content-addressed history of this organization's clones."""
        return self.root / "versions"

    @property
    def schedules_file(self) -> Path:
        """JSON file with this organization's schedules."""
        return self.root / "schedules.json"

    @property
    def workflows_dir(self) -> Path:
        """One JSON file per workflow, private to this organization."""
        return self.root / "workflows"

    @property
    def marketplace_dir(self) -> Path:
        """Workflows and plugins this organization published."""
        return self.root / "marketplace"

    @property
    def integrations_dir(self) -> Path:
        """Outbound destinations (Notion/Airtable/Sheets) of this organization."""
        return self.root / "integrations"

    @property
    def search_db(self) -> Path:
        """SQLite full-text/semantic index of this organization."""
        return self.root / "search.db"

    @property
    def metrics_db(self) -> Path:
        """SQLite analytics store of this organization."""
        return self.root / "metrics.db"

    @property
    def audit_log(self) -> Path:
        """JSONL audit trail of this organization."""
        return self.root / "audit.log"

    @property
    def multisite_dir(self) -> Path:
        """RAG index (``MultiSiteIndex``) of this organization."""
        return self.root / ".rag-multi"

    @property
    def chats_dir(self) -> Path:
        """Conversation history (``ChatSession``) of this organization."""
        return self.root / "chats"

    @property
    def sessions_dir(self) -> Path:
        """Authenticated browser sessions (cookies/localStorage) of this organization."""
        return self.root / "sessions"

    @property
    def annotations_dir(self) -> Path:
        """Comments on this organization's clones."""
        return self.root / "annotations"

    @property
    def domains_dir(self) -> Path:
        """Domain profiles (vocabulary/instructions) of this organization."""
        return self.root / "domains"

    @property
    def analysis_dir(self) -> Path:
        """Price history, competitive analysis and trend data of this organization."""
        return self.root / "analysis"

    @property
    def finetune_dir(self) -> Path:
        """Fine-tuning datasets built from this organization's clones."""
        return self.root / "finetune"

    @property
    def totp_file(self) -> Path:
        """Two-factor secrets of this organization (mode 0600)."""
        return self.root / "totp.json"

    @property
    def arweave_wallet_file(self) -> Path:
        """Arweave wallet used to publish this organization's archives."""
        return self.root / "arweave-wallet.json"

    # ── shared identity (deliberately NOT under ``root``) ──

    @property
    def users_file(self) -> Path:
        """Accounts. Global: a user belongs to many organizations, so it stays shared."""
        return Path(settings.users_file)

    @property
    def orgs_file(self) -> Path:
        """Organizations and their membership. Global, shared by every workspace."""
        return Path(settings.orgs_file)

    # ── helpers ──

    def directories(self) -> tuple[Path, ...]:
        """Every directory of the layout, whether or not it exists yet."""
        return tuple(self.root / name for name in DIRECTORY_NAMES)

    def data_paths(self) -> dict[str, Path]:
        """The paths that belong to this organization (never the shared identity files)."""
        return {name: getattr(self, name) for name in _DATA_PROPERTIES}


class WorkspaceManager:
    """Create, list and delete the per-organization data trees.

    ``base`` is the parent of the ``orgs/`` directory and defaults to
    ``settings.output_dir``, so the layout follows the configured output root.
    """

    def __init__(self, base: Path | None = None) -> None:
        self.base = Path(base) if base is not None else Path(settings.output_dir)

    # ── paths ──

    @property
    def orgs_dir(self) -> Path:
        """Directory holding one sub-directory per organization."""
        return self.base / ORGS_DIRNAME

    def _root_for(self, org: str) -> Path:
        """Return the root of ``org``'s tree. Raises ``ValueError`` for an unsafe name."""
        # ``slug_org`` rejects separators and ``..``, and its result cannot contain a ``.``,
        # so the join below always stays a single component under ``orgs/``.
        return self.orgs_dir / slug_org(org)

    # ── lifecycle ──

    def for_org(self, org: str) -> Workspace:
        """Return ``org``'s workspace, creating every directory on demand."""
        slug = slug_org(org)
        workspace = Workspace(
            org=str(org or "").strip() or settings.default_org,
            root=self.orgs_dir / slug,
        )
        for directory in workspace.directories():
            directory.mkdir(parents=True, exist_ok=True)
        logger.debug("Workspace %s pronto em %s", slug, workspace.root)
        return workspace

    def exists(self, org: str) -> bool:
        """Return True when ``org`` already has a data tree."""
        return self._root_for(org).is_dir()

    def list(self) -> list[str]:
        """Return the slugs of the organizations that have a directory, sorted."""
        try:
            entries = list(self.orgs_dir.iterdir())
        except FileNotFoundError:
            return []
        except OSError as exc:
            logger.warning("Não foi possível listar %s: %s", self.orgs_dir, exc)
            return []

        return sorted(
            entry.name
            for entry in entries
            if entry.is_dir() and _SLUG_ONLY_RE.match(entry.name)
        )

    def remove(self, org: str) -> bool:
        """Delete ``org``'s data tree and return True when there was one.

        The shared identity files (``users_file``, ``orgs_file``) are never touched; a
        configuration that places them *inside* the org tree is refused instead of obeyed.
        """
        root = self._root_for(org)
        if not root.is_dir():
            return False

        for shared in (settings.users_file, settings.orgs_file):
            if _inside(shared, root):
                raise ValueError(
                    f"identidade compartilhada ({shared}) está dentro de {root}: "
                    "recusando apagar"
                )

        shutil.rmtree(root)
        logger.info("Workspace %s removido (%s)", slug_org(org), root)
        return True


def get_workspace(org: str | None = None) -> Workspace:
    """Return (creating on demand) the workspace for ``org``, or for the default org."""
    return WorkspaceManager().for_org(org or settings.default_org)


def store_paths(workspace: Workspace) -> dict[str, dict[str, Path]]:
    """Return the constructor argument each store needs, keyed by class name.

    Built from paths only — this module never imports the stores, so it stays free of the
    heavy or optional dependencies they pull in::

        paths = store_paths(ws)
        history = VersionStore(**paths["VersionStore"])
        audit = AuditLog(**paths["AuditLog"])
    """
    return {
        "VersionStore": {"root": workspace.versions_dir},
        "ScheduleStore": {"path": workspace.schedules_file},
        "WorkflowStore": {"root": workspace.workflows_dir},
        "Marketplace": {"root": workspace.marketplace_dir},
        "DestinationStore": {"root": workspace.integrations_dir},
        "SearchIndex": {"db_path": workspace.search_db},
        "MetricsStore": {"db_path": workspace.metrics_db},
        "AuditLog": {"path": workspace.audit_log},
        "MultiSiteIndex": {"root": workspace.multisite_dir},
        "ChatSession": {"history_dir": workspace.chats_dir},
        "SessionStore": {"root": workspace.sessions_dir},
        "AnnotationStore": {"root": workspace.annotations_dir},
        "DomainProfileStore": {"root": workspace.domains_dir},
    }


def _scoped_values(workspace: Workspace) -> dict[str, object]:
    """Map ``settings`` attribute -> value for :func:`scoped`."""
    values: dict[str, object] = {}
    for attribute, prop in _SCOPED_FIELDS:
        if hasattr(settings, attribute):
            values[attribute] = getattr(workspace, prop)

    # The session key follows the session directory; otherwise it would stay at the shared
    # ``sessions/.key`` and be recreated outside the workspace.
    if hasattr(settings, "sessions_key_file"):
        values["sessions_key_file"] = workspace.sessions_dir / ".key"
    return values


@contextmanager
def scoped(workspace: Workspace) -> Iterator[Workspace]:
    """Point the ``settings`` defaults at ``workspace`` for the duration of the block.

    Every attribute is restored on exit, including when the block raises.

    .. warning::
        This mutates the process-wide ``settings`` object, so it is **not safe under
        concurrency** — two threads or requests entering different workspaces would fight
        over the same globals. It exists for the CLI, where one process handles one
        organization at a time. The API and the workers must pass explicit paths instead
        (:func:`store_paths`).
    """
    values = _scoped_values(workspace)
    previous: dict[str, object] = {}
    try:
        for attribute, value in values.items():
            previous[attribute] = getattr(settings, attribute)
            setattr(settings, attribute, value)
        logger.debug("settings apontando para o workspace %s", workspace.root)
        yield workspace
    finally:
        for attribute, value in previous.items():
            setattr(settings, attribute, value)
