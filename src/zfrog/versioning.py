"""Git-style version history for site clones.

Each commit stores the files of a clone in content-addressed storage
(deduplicated by SHA-256) and references the corresponding change snapshot.
Branches are pointers to the last commit, kept in
``<root>/<slug>/refs.json``; os commits ficam serializados em
``<root>/<slug>/objects/<id>.json``.

The layout is intentionally simple: the history is a chain linked by
``parent``, so operations like ``rollback`` only need the blobs and the
commit record.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from zfrog.config import settings
from zfrog.diff import DiffReport, diff_snapshots, snapshots_dir, url_slug
from zfrog.storage.content_addressed import ContentAddressedStore

logger = logging.getLogger(__name__)

# 12 hex characters are enough for human use; collisions are checked
# against the already-recorded commits before accepting a new id.
ID_LENGTH = 12
# Minimum prefix accepted by `resolve`: below this the ambiguity risk is high.
MIN_PREFIX_LENGTH = 4
HEAD_REF = "HEAD"
DEFAULT_BRANCH = "main"
# The blob store is never part of a clone's content.
STORE_DIRNAME = ".store"
# Ids are hex; anything else in `resolve` is not an id prefix.
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


@dataclass
class Version:
    """One commit: the files of a clone plus the snapshot metadata."""

    id: str
    url: str
    snapshot: str
    captured_at: str
    message: str
    parent: str | None
    branch: str
    pages: int
    files: dict[str, str]


def _read_snapshot_meta(path: Path) -> dict:
    """Read a JSON snapshot; missing or unreadable becomes ``{}`` (with a warning)."""
    if not path.is_file():
        logger.warning("missing snapshot: %s", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("unreadable snapshot %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _is_safe_relative(rel: str) -> bool:
    """Reject absolute paths or ``..`` before writing to the destination."""
    parts = Path(rel).parts
    return bool(parts) and not Path(rel).is_absolute() and ".." not in parts


class VersionStore:
    """Commit history per URL, backed by the content-addressed store."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path(settings.versions_dir)
        self.store = ContentAddressedStore(self.root / "store")

    # ------------------------------------------------------------------ paths

    def _site_dir(self, url: str) -> Path:
        return self.root / url_slug(url)

    def _refs_path(self, url: str) -> Path:
        return self._site_dir(url) / "refs.json"

    def _objects_dir(self, url: str) -> Path:
        return self._site_dir(url) / "objects"

    def _read_refs(self, url: str) -> dict[str, str]:
        """Read the branch pointers; unknown site becomes ``{}``."""
        path = self._refs_path(url)
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("unreadable refs at %s: %s", path, exc)
            return {}
        branches = data.get("branches") if isinstance(data, dict) else None
        if not isinstance(branches, dict):
            return {}
        return {str(name): str(commit) for name, commit in branches.items()}

    def _write_refs(self, url: str, branches: dict[str, str]) -> None:
        path = self._refs_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"branches": {name: branches[name] for name in sorted(branches)}}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # --------------------------------------------------------------- versions

    def _new_id(self, url: str) -> str:
        objects_dir = self._objects_dir(url)
        while True:
            candidate = uuid.uuid4().hex[:ID_LENGTH]
            if not (objects_dir / f"{candidate}.json").exists():
                return candidate

    def _version_path(self, url: str, version_id: str) -> Path:
        return self._objects_dir(url) / f"{version_id}.json"

    def _write_version(self, version: Version) -> None:
        path = self._version_path(version.url, version.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(version), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_version(self, url: str, version_id: str) -> Version | None:
        path = self._version_path(url, version_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("unreadable commit %s: %s", path, exc)
            return None
        if not isinstance(data, dict):
            return None
        known = {f.name for f in fields(Version)}
        try:
            return Version(**{key: value for key, value in data.items() if key in known})
        except TypeError as exc:
            logger.warning("invalid commit %s: %s", path, exc)
            return None

    def _walk(self, url: str, version_id: str | None) -> list[Version]:
        """Follow the ``parent`` chain from a commit (newest first)."""
        chain: list[Version] = []
        seen: set[str] = set()
        current = version_id
        while current and current not in seen:
            seen.add(current)
            version = self._load_version(url, current)
            if version is None:
                logger.warning("missing commit %s for %s", current, url)
                break
            chain.append(version)
            current = version.parent
        return chain

    # -------------------------------------------------------------- blobs

    def _store_output(self, output_dir: Path) -> dict[str, str]:
        """Store each file of the clone and return ``path -> sha256``.

        ``store_directory`` returns ``hash -> path``, which collapses files of
        identical content into a single pair; because the commit needs all
        paths, storage is done file by file (the store still deduplicates by
        hash).
        """
        files: dict[str, str] = {}
        if not output_dir.is_dir():
            logger.warning("missing output directory: %s", output_dir)
            return files
        for path in sorted(output_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(output_dir)
            if rel.parts[0] == STORE_DIRNAME:
                continue
            files[str(rel)] = self.store.store_file(path)
        return files

    # -------------------------------------------------------------- public API

    def commit(
        self,
        url: str,
        snapshot_path: Path,
        output_dir: Path | None = None,
        message: str = "",
        branch: str = DEFAULT_BRANCH,
    ) -> Version:
        """Record a commit with the files of ``output_dir`` and advance the branch.

        Args:
            url: URL of the versioned site.
            snapshot_path: Corresponding change snapshot (only the name is stored).
            output_dir: Clone directory; ``None`` records a commit without files.
            message: Commit message.
            branch: Branch to advance (created implicitly if it does not exist).

        Returns:
            The recorded ``Version``.
        """
        snapshot_path = Path(snapshot_path)
        branches = self._read_refs(url)
        parent = branches.get(branch)
        snapshot = _read_snapshot_meta(snapshot_path)
        pages = snapshot.get("pages")
        files = self._store_output(Path(output_dir)) if output_dir is not None else {}

        version = Version(
            id=self._new_id(url),
            url=url,
            snapshot=snapshot_path.name,
            captured_at=str(snapshot.get("captured_at") or ""),
            message=message,
            parent=parent,
            branch=branch,
            pages=len(pages) if isinstance(pages, list) else 0,
            files=files,
        )
        self._write_version(version)

        branches[branch] = version.id
        self._write_refs(url, branches)
        logger.info("version %s recorded for %s (%d file(s))", version.id, url, len(files))
        return version

    def log(self, url: str, branch: str | None = None) -> list[Version]:
        """List commits from newest to oldest.

        Without ``branch``, returns the history of all branches. An unknown
        URL or branch yields an empty list (listings never fail).
        """
        branches = self._read_refs(url)
        if branch is not None:
            tip = branches.get(branch)
            return self._walk(url, tip) if tip else []

        versions: list[Version] = []
        seen: set[str] = set()
        for name in sorted(branches):
            for version in self._walk(url, branches[name]):
                if version.id not in seen:
                    seen.add(version.id)
                    versions.append(version)
        versions.sort(key=lambda version: version.captured_at, reverse=True)
        return versions

    def head(self, url: str, branch: str = DEFAULT_BRANCH) -> Version | None:
        """Commit pointed to by the branch, or ``None`` when the branch does not exist."""
        version_id = self._read_refs(url).get(branch)
        if version_id is None:
            return None
        return self._load_version(url, version_id)

    def branches(self, url: str) -> list[str]:
        """Existing branch names (sorted); unknown URL becomes ``[]``."""
        return sorted(self._read_refs(url))

    def create_branch(self, url: str, name: str, from_branch: str = DEFAULT_BRANCH) -> None:
        """Create ``name`` pointing at the current commit of ``from_branch``."""
        branches = self._read_refs(url)
        if from_branch not in branches:
            raise ValueError(f"unknown source branch: '{from_branch}' at {url}")
        target = branches[from_branch]
        if name in branches:
            if branches[name] == target:
                return
            raise ValueError(f"branch already exists: '{name}' at {url}")
        branches[name] = target
        self._write_refs(url, branches)
        logger.info("branch %s created from %s at %s", name, from_branch, url)
    def resolve(self, url: str, ref: str) -> Version | None:
        """Resolve ``ref`` (``HEAD``, a branch or an id prefix) to a ``Version``.

        Raises:
            ValueError: URL without history, unknown branch/ref, or ambiguous prefix.
        """
        text = str(ref or "").strip()
        if not text:
            raise ValueError("empty version reference")

        branches = self._read_refs(url)
        if not branches:
            raise ValueError(f"no saved versions for {url}")

        if text == HEAD_REF:
            tip = branches.get(DEFAULT_BRANCH)
            if tip is None:
                raise ValueError(f"no version on branch '{DEFAULT_BRANCH}' for {url}")
            version = self._load_version(url, tip)
            if version is None:
                raise ValueError(f"commit {tip} of '{DEFAULT_BRANCH}' not found for {url}")
            return version

        if text in branches:
            version = self._load_version(url, branches[text])
            if version is None:
                raise ValueError(f"commit {branches[text]} of branch '{text}' not found for {url}")
            return version

        return self._resolve_prefix(url, text)

    def _require(self, url: str, ref: str) -> Version:
        """Like ``resolve``, but guarantees a version instead of ``None``."""
        version = self.resolve(url, ref)
        if version is None:
            raise ValueError(f"unknown version: '{ref}' at {url}")
        return version

    def _resolve_prefix(self, url: str, prefix: str) -> Version:
        if len(prefix) < MIN_PREFIX_LENGTH:
            raise ValueError(f"reference too short: '{prefix}' (minimum {MIN_PREFIX_LENGTH} characters)")
        if not _HEX_DIGITS.issuperset(prefix):
            raise ValueError(f"unknown version: '{prefix}' at {url}")
        objects_dir = self._objects_dir(url)
        matches = sorted(p.stem for p in objects_dir.glob(f"{prefix}*.json")) if objects_dir.is_dir() else []
        if not matches:
            raise ValueError(f"unknown version: '{prefix}' at {url}")
        if len(matches) > 1:
            raise ValueError(f"ambiguous prefix: '{prefix}' matches {len(matches)} versions at {url}")
        version = self._load_version(url, matches[0])
        if version is None:
            raise ValueError(f"unreadable commit {matches[0]} at {url}")
        return version

    def rollback(self, url: str, ref: str, dest: Path | None = None) -> Path:
        """Restore the files of a version into ``dest`` and return the path.

        Missing blobs are skipped with a warning; the rest is restored.
        """
        version = self._require(url, ref)
        destination = Path(dest) if dest is not None else self._site_dir(url) / f"checkout-{version.id}"
        destination.mkdir(parents=True, exist_ok=True)

        restored = 0
        for rel, digest in sorted(version.files.items()):
            if not _is_safe_relative(rel):
                logger.warning("invalid path in commit %s: %s", version.id, rel)
                continue
            blob = self.store.get(digest)
            if blob is None:
                logger.warning("missing blob %s; %s not restored", digest, rel)
                continue
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(blob, target)
            restored += 1
        logger.info("version %s restored at %s (%d file(s))", version.id, destination, restored)
        return destination

    def diff_versions(self, url: str, ref_a: str, ref_b: str) -> DiffReport:
        """Compare the snapshots of two versions (order fixed by timestamp)."""
        version_a = self._require(url, ref_a)
        version_b = self._require(url, ref_b)

        site_snapshots = snapshots_dir() / url_slug(url)
        path_a = site_snapshots / version_a.snapshot
        path_b = site_snapshots / version_b.snapshot
        for version, path in ((version_a, path_a), (version_b, path_b)):
            if not path.is_file():
                raise ValueError(
                    f"snapshot '{version.snapshot}' of version {version.id} not found at {site_snapshots}"
                )
        return diff_snapshots(path_a, path_b)
