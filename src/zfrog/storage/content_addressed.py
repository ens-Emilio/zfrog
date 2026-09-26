"""Content-addressed storage with SHA-256 deduplication.

Assets are stored by their hash. Jobs reference assets via symlinks,
enabling deduplication across jobs and projects.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from zfrog.config import settings


class ContentAddressedStore:
    """Storage backend where files are addressed by their SHA-256 hash."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or (settings.output_dir / ".store")
        self.objects_dir = self.base_dir / "objects"
        self.objects_dir.mkdir(parents=True, exist_ok=True)

    def _hash_file(self, file_path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _hash_bytes(self, data: bytes) -> str:
        """Compute SHA-256 hash of bytes."""
        return hashlib.sha256(data).hexdigest()

    def _object_path(self, hash_hex: str) -> Path:
        """Get the path for a stored object."""
        # Use first 2 chars as directory for flat structure
        return self.objects_dir / hash_hex[:2] / hash_hex

    def store_file(self, file_path: Path) -> str:
        """Store a file and return its hash.

        If the file already exists (same hash), it's a no-op.

        Returns:
            SHA-256 hex digest.
        """
        file_hash = self._hash_file(file_path)
        dest = self._object_path(file_hash)

        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, dest)

        return file_hash

    def store_bytes(self, data: bytes, suffix: str = "") -> str:
        """Store raw bytes and return its hash.

        Args:
            data: Bytes to store.
            suffix: Optional file suffix (e.g., ".html").

        Returns:
            SHA-256 hex digest.
        """
        file_hash = self._hash_bytes(data)
        dest = self._object_path(file_hash)

        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        return file_hash

    def get(self, hash_hex: str) -> Path | None:
        """Retrieve a stored object by hash.

        Returns:
            Path to the object, or None if not found.
        """
        path = self._object_path(hash_hex)
        return path if path.exists() else None

    def has(self, hash_hex: str) -> bool:
        """Check if an object exists."""
        return self._object_path(hash_hex).exists()

    def link_to_job(self, hash_hex: str, job_dir: Path, relative_path: str) -> Path:
        """Create a symlink from a job directory to a stored object.

        Args:
            hash_hex: Hash of the stored object.
            job_dir: Job's output directory.
            relative_path: Path within the job directory.

        Returns:
            Path to the created symlink.
        """
        source = self._object_path(hash_hex)
        if not source.exists():
            raise FileNotFoundError(f"Object {hash_hex} not found in store")

        link_path = job_dir / relative_path
        link_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing symlink/file if present
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()

        link_path.symlink_to(source.resolve())
        return link_path

    def store_directory(self, dir_path: Path, prefix: str = "") -> dict[str, str]:
        """Store all files in a directory, returning hash→relative_path mapping.

        Args:
            dir_path: Directory to store.
            prefix: Optional prefix for relative paths.

        Returns:
            Dict mapping SHA-256 hash to relative path within dir_path.
        """
        mapping = {}
        for file_path in dir_path.rglob("*"):
            if file_path.is_file():
                file_hash = self.store_file(file_path)
                rel = file_path.relative_to(dir_path)
                if prefix:
                    rel = Path(prefix) / rel
                mapping[file_hash] = str(rel)
        return mapping

    def stats(self) -> dict[str, int]:
        """Return storage statistics."""
        total_files = 0
        total_bytes = 0
        for obj in self.objects_dir.rglob("*"):
            if obj.is_file():
                total_files += 1
                total_bytes += obj.stat().st_size
        return {"objects": total_files, "bytes": total_bytes}
