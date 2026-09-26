"""Comments and annotations on cloned content.

A reviewer points at a page of a clone — optionally at a CSS selector inside that
page — and leaves a note, so a whole team can review the same clone together
instead of trading screenshots. One JSON file per job lives under
``settings.annotations_dir``.

Every mutation rewrites the job file atomically (temp file + ``os.replace``), so a
concurrent reader never observes a half-written document, and the job id is
sanitised before it is ever used as a file name.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from zfrog.config import settings

logger = logging.getLogger(__name__)

_ID_LENGTH = 10
# A job id becomes a file name, so separators and ``..`` must never get through.
_PATH_SEPARATORS = tuple(sep for sep in {"/", "\\", os.sep, os.altsep} if sep)

# ``_now`` hands out strictly increasing stamps: "newest first" is derived from
# ``created_at``, so two annotations made inside the same microsecond must still
# compare as different.
_last_stamp: datetime | None = None


@dataclass
class Reply:
    """A single answer to an annotation."""

    id: str
    author: str
    text: str
    created_at: str


@dataclass
class Annotation:
    """A note pinned to a page (and optionally a selector) of a clone."""

    id: str
    job_id: str
    path: str
    selector: str = ""
    text: str = ""
    author: str = ""
    created_at: str = ""
    updated_at: str = ""
    resolved: bool = False
    tags: list[str] = field(default_factory=list)
    replies: list[dict] = field(default_factory=list)


def _now() -> str:
    """Return the current UTC time as ISO-8601, strictly increasing per process."""
    global _last_stamp
    stamp = datetime.now(timezone.utc)
    if _last_stamp is not None and stamp <= _last_stamp:
        stamp = _last_stamp + timedelta(microseconds=1)
    _last_stamp = stamp
    return stamp.isoformat()


def _new_id() -> str:
    """Return a short random id for an annotation or a reply."""
    return uuid.uuid4().hex[:_ID_LENGTH]


def _normalize_job_id(job_id: str) -> str:
    """Return the job id used as a file name, refusing anything unsafe.

    Raises:
        ValueError: when the id is blank or could escape the store directory.
    """
    value = str(job_id or "").strip()
    if not value:
        raise ValueError("O id do job não pode estar vazio")
    if ".." in value or any(sep in value for sep in _PATH_SEPARATORS):
        raise ValueError(f"Id de job inválido: {job_id!r}")
    return value


def _require_text(text: str, what: str) -> str:
    """Return ``text`` stripped, refusing a blank value.

    Raises:
        ValueError: when ``text`` holds nothing but whitespace.
    """
    value = str(text or "").strip()
    if not value:
        raise ValueError(f"{what} não pode estar vazia")
    return value


def _clean_tags(tags: list[str] | None) -> list[str]:
    """Return tags stripped of blanks and duplicates, keeping the given order."""
    cleaned: list[str] = []
    for tag in tags or []:
        value = str(tag).strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _validate_selector(selector: str) -> None:
    """Raise ``ValueError`` when ``selector`` is not valid CSS.

    ``zfrog.selector`` owns CSS validation for the extractor; when it cannot be
    imported the check falls back to soupsieve directly, and degrades to a log
    line when neither is available.
    """
    try:
        from zfrog.selector import validate_selector as selector_validator
    except ImportError:
        selector_validator = None

    if selector_validator is not None:
        selector_validator(selector)
        return

    try:
        from soupsieve import SelectorSyntaxError
        from soupsieve import compile as compile_selector
    except ImportError:
        logger.warning("Validação de seletor CSS indisponível; aceitando %r", selector)
        return

    try:
        compile_selector(selector)
    except (SelectorSyntaxError, NotImplementedError) as exc:
        raise ValueError(f"Seletor CSS inválido: {selector!r} ({exc})") from exc


def _clean_selector(selector: str) -> str:
    """Return the trimmed selector, validating it when it is not blank."""
    value = str(selector or "").strip()
    if value:
        _validate_selector(value)
    return value


class AnnotationStore:
    """JSON-file store of annotations, one file per job."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path(settings.annotations_dir)

    def add(
        self,
        job_id: str,
        path: str,
        text: str,
        author: str = "",
        selector: str = "",
        tags: list[str] | None = None,
    ) -> Annotation:
        """Create and persist an annotation.

        Raises:
            ValueError: when the job id, the page path or the text is blank, or
                when ``selector`` is not valid CSS.
        """
        clean_job = _normalize_job_id(job_id)
        page = str(path or "").strip()
        if not page:
            raise ValueError("O caminho da página não pode estar vazio")

        annotation = Annotation(
            id=_new_id(),
            job_id=clean_job,
            path=page,
            selector=_clean_selector(selector),
            text=_require_text(text, "A anotação"),
            author=str(author or "").strip(),
            created_at=_now(),
            tags=_clean_tags(tags),
        )
        annotation.updated_at = annotation.created_at

        annotations = self._load(clean_job)
        annotations.append(annotation)
        self._save(clean_job, annotations)
        logger.info("Anotação %s criada no job %s (%s)", annotation.id, clean_job, page)
        return annotation

    def get(self, annotation_id: str) -> Annotation | None:
        """Return the annotation with this id, or None."""
        located = self._locate(annotation_id)
        if located is None:
            return None
        _, annotations, index = located
        return annotations[index]

    def list(
        self,
        job_id: str | None = None,
        resolved: bool | None = None,
        author: str | None = None,
        tag: str | None = None,
    ) -> list[Annotation]:
        """Return annotations newest first, filtered by the given fields.

        ``job_id`` limits the search to one job file; the remaining filters are
        applied to the candidates and combine with AND.
        """
        found = self._load(job_id) if job_id is not None else self._all()

        if resolved is not None:
            found = [annotation for annotation in found if annotation.resolved == bool(resolved)]
        if author is not None:
            found = [annotation for annotation in found if annotation.author == author]
        if tag is not None:
            found = [annotation for annotation in found if tag in annotation.tags]

        return sorted(found, key=lambda annotation: annotation.created_at, reverse=True)

    def update(
        self,
        annotation_id: str,
        text: str | None = None,
        selector: str | None = None,
        tags: list[str] | None = None,
    ) -> Annotation:
        """Change the given fields and refresh ``updated_at``.

        ``created_at`` never moves; a field left as None keeps its value, and a
        blank selector clears the pin.

        Raises:
            ValueError: when the id is unknown, the text is blank or the
                selector is not valid CSS.
        """
        job_id, annotations, annotation = self._require(annotation_id)

        if text is not None:
            annotation.text = _require_text(text, "A anotação")
        if selector is not None:
            annotation.selector = _clean_selector(selector)
        if tags is not None:
            annotation.tags = _clean_tags(tags)
        annotation.updated_at = _now()

        self._save(job_id, annotations)
        return annotation

    def resolve(self, annotation_id: str, resolved: bool = True) -> Annotation:
        """Mark an annotation resolved (or open again), refreshing ``updated_at``.

        Raises:
            ValueError: when the id is unknown.
        """
        job_id, annotations, annotation = self._require(annotation_id)
        annotation.resolved = bool(resolved)
        annotation.updated_at = _now()
        self._save(job_id, annotations)
        return annotation

    def reply(self, annotation_id: str, text: str, author: str = "") -> Annotation:
        """Append a reply to an annotation and refresh its ``updated_at``.

        Raises:
            ValueError: when the id is unknown or the reply text is blank.
        """
        job_id, annotations, annotation = self._require(annotation_id)
        entry = Reply(
            id=_new_id(),
            author=str(author or "").strip(),
            text=_require_text(text, "A resposta"),
            created_at=_now(),
        )
        annotation.replies.append(asdict(entry))
        annotation.updated_at = _now()
        self._save(job_id, annotations)
        return annotation

    def remove(self, annotation_id: str) -> bool:
        """Delete an annotation; return False when the id is unknown."""
        located = self._locate(annotation_id)
        if located is None:
            return False

        job_id, annotations, index = located
        del annotations[index]
        self._save(job_id, annotations)
        return True

    def counts(self, job_id: str) -> dict[str, Any]:
        """Summarise one job: totals, resolution split and author/tag breakdowns.

        Annotations without an author stay out of ``by_author``; a tag counts
        once per annotation that carries it.
        """
        annotations = self._load(job_id)

        by_author: dict[str, int] = {}
        by_tag: dict[str, int] = {}
        resolved = 0
        for annotation in annotations:
            if annotation.author:
                by_author[annotation.author] = by_author.get(annotation.author, 0) + 1
            for tag in annotation.tags:
                by_tag[tag] = by_tag.get(tag, 0) + 1
            resolved += int(annotation.resolved)

        total = len(annotations)
        return {
            "total": total,
            "open": total - resolved,
            "resolved": resolved,
            "by_author": by_author,
            "by_tag": by_tag,
        }

    # ── storage ──

    def _file_path(self, job_id: str) -> Path:
        """Return the JSON file that holds one job's annotations."""
        return self.root / f"{_normalize_job_id(job_id)}.json"

    def _load(self, job_id: str) -> list[Annotation]:
        """Return the annotations of one job; a missing file means an empty list."""
        return self._read(self._file_path(job_id), job_id)

    def _all(self) -> list[Annotation]:
        """Return every stored annotation, from every job file."""
        return [item for path in sorted(self.root.glob("*.json")) for item in self._read(path, path.stem)]

    def _read(self, path: Path, job_id: str) -> list[Annotation]:
        """Read one job file, turning malformed JSON into a ValueError."""
        if not path.exists():
            return []

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Arquivo de anotações inválido ({path}): {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError(f"Arquivo de anotações inválido ({path}): esperado um objeto")

        records = payload.get("annotations", [])
        if not isinstance(records, list):
            raise ValueError(f"Arquivo de anotações inválido ({path}): 'annotations' não é uma lista")

        return [self._from_dict(record, job_id, path) for record in records]

    def _save(self, job_id: str, annotations: list[Annotation]) -> None:
        """Write one job file atomically (temp file + ``os.replace``)."""
        target = self._file_path(job_id)
        payload = {"job_id": job_id, "annotations": [asdict(item) for item in annotations]}
        target.parent.mkdir(parents=True, exist_ok=True)

        handle_fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, text=True
        )
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def _locate(self, annotation_id: str) -> tuple[str, list[Annotation], int] | None:
        """Find an annotation by id across every job file."""
        wanted = str(annotation_id or "")
        for path in sorted(self.root.glob("*.json")):
            annotations = self._read(path, path.stem)
            for index, annotation in enumerate(annotations):
                if annotation.id == wanted:
                    return path.stem, annotations, index
        return None

    def _require(self, annotation_id: str) -> tuple[str, list[Annotation], Annotation]:
        """Return the job id, its annotations and the wanted one.

        Raises:
            ValueError: when the id is unknown.
        """
        located = self._locate(annotation_id)
        if located is None:
            raise ValueError(f"Anotação desconhecida: {annotation_id!r}")

        job_id, annotations, index = located
        return job_id, annotations, annotations[index]

    def _from_dict(self, record: object, job_id: str, path: Path) -> Annotation:
        """Build an Annotation from one JSON record."""
        if not isinstance(record, dict):
            raise ValueError(f"Arquivo de anotações inválido ({path}): registro não é objeto")

        return Annotation(
            id=str(record.get("id") or ""),
            job_id=str(record.get("job_id") or job_id),
            path=str(record.get("path") or ""),
            selector=str(record.get("selector") or ""),
            text=str(record.get("text") or ""),
            author=str(record.get("author") or ""),
            created_at=str(record.get("created_at") or ""),
            updated_at=str(record.get("updated_at") or ""),
            resolved=bool(record.get("resolved", False)),
            tags=[str(tag) for tag in record.get("tags") or []],
            replies=[dict(reply) for reply in record.get("replies") or [] if isinstance(reply, dict)],
        )


def _annotation_markdown(annotation: Annotation) -> list[str]:
    """Markdown block for one annotation, replies included."""
    check = "x" if annotation.resolved else " "
    lines = [
        f"## [{check}] {annotation.path}",
        "",
        f"- **Autor:** {annotation.author or 'anônimo'}",
        f"- **Criada em:** {annotation.created_at}",
        f"- **Atualizada em:** {annotation.updated_at}",
    ]
    if annotation.selector:
        lines.append(f"- **Seletor:** `{annotation.selector}`")
    if annotation.tags:
        lines.append(f"- **Tags:** {', '.join(annotation.tags)}")

    lines += ["", annotation.text, ""]
    if annotation.replies:
        lines += ["**Respostas:**", ""]
        for reply in annotation.replies:
            author = str(reply.get("author") or "anônimo")
            lines.append(f"- **{author}** ({reply.get('created_at', '')}): {reply.get('text', '')}")
        lines.append("")
    return lines


def export_markdown(annotations: list[Annotation], job_id: str = "") -> str:
    """Render ``annotations`` as a readable review document, newest first."""
    lines = [f"# Anotações do job `{job_id}`" if job_id else "# Anotações", ""]

    ordered = sorted(annotations, key=lambda annotation: annotation.created_at, reverse=True)
    if not ordered:
        lines.append("_Nenhuma anotação._")
    for annotation in ordered:
        lines.extend(_annotation_markdown(annotation))

    return "\n".join(lines).rstrip("\n") + "\n"


def filter_by_page(annotations: list[Annotation], path: str) -> list[Annotation]:
    """Return the annotations whose page path matches ``path`` exactly."""
    wanted = str(path or "")
    return [annotation for annotation in annotations if annotation.path == wanted]
