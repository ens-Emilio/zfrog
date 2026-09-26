"""A small, read-only GraphQL endpoint over what Zfrog already stores.

Zfrog keeps jobs, change-detection snapshots, version-history commits, schedules,
engine metrics, the search index, the multi-site RAG index and chat
conversations. This module exposes all of them through one GraphQL surface
without adding a GraphQL dependency (none is installed, and the subset the
dashboard needs is tiny): a parser (:func:`parse_query`) plus an executor
(:func:`execute`) driven by :data:`SCHEMA`.

Design notes:

* The API is read-only. ``mutation`` and ``subscription`` operations are rejected
  with a :class:`GraphQLError`, and no resolver writes anything.
* The executor never raises for a bad request: parse failures, unknown fields,
  unknown/missing arguments and failing resolvers all become entries in
  :attr:`FieldResult.errors` with ``null`` for the affected field in the data,
  exactly as the GraphQL spec requires. Sibling fields keep their data.
* :data:`SCHEMA` is the single source of truth: it declares each field's type,
  its arguments (type, default, required), the nested selection it yields (so the
  executor can prune the response to what the client asked for) and its resolver.
  :func:`schema_sdl` renders the same schema as SDL for docs/introspection.
* Resolvers read the real stores through module-level imports, so a caller (or a
  test) can monkeypatch any of them.

Root fields:

``jobs(limit: Int = 20, status: String)``
    Extraction jobs, newest first. Fields: ``id, url, mode, status, maxDepth,
    createdAt, outputPath, error``.
``job(id: String!)``
    One job by id, or ``null`` when unknown. Adds ``result { outputPath,
    filesCount, totalBytes, engineUsed, durationSeconds }``.
``snapshots(url: String)``
    Change-detection snapshots, newest first. Fields: ``url, capturedAt, engine,
    pages, path``.
``versions(url: String!, branch: String)``
    Version-history commits. Fields: ``id, url, branch, message, capturedAt,
    pages, parent, snapshot``.
``schedules``
    Recurring jobs. Fields: ``id, cron, url, mode, maxDepth, enabled, lastRun,
    nextRun``.
``engines``
    Registered engines. Fields: ``name, source``.
``analytics(engine: String)``
    Per-engine run metrics. Fields: ``engine, runs, succeeded, failed,
    successRate, avgDurationS, avgBytes, totalBytes, avgFiles, totalCost,
    avgCost``.
``search(query: String!, mode: String = "fulltext", limit: Int = 20)``
    Search hits. Fields: ``path, url, title, snippet, score``.
``sites``
    Sites in the multi-site RAG index. Fields: ``url, pages, chunks``.
``conversations``
    Saved chat threads. Fields: ``id, sites, turns, createdAt``.

Any object selection also accepts ``__typename``.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from zfrog.ai.chat import ChatSession
from zfrog.ai.multisite import MultiSiteIndex
from zfrog.analytics import MetricsStore
from zfrog.diff import list_snapshots
from zfrog.engines import ENGINE_SOURCES, ENGINES
from zfrog.orchestrator import get_job, get_result, list_jobs
from zfrog.scheduler import ScheduleStore
from zfrog.search import SearchIndex
from zfrog.versioning import VersionStore

logger = logging.getLogger(__name__)

#: Name of the root type, reported by a root-level ``__typename`` selection.
QUERY_TYPE = "Query"

#: Kinds of token the lexer produces.
_TOKEN_NAME = "name"
_TOKEN_INT = "int"
_TOKEN_FLOAT = "float"
_TOKEN_STRING = "string"
_TOKEN_PUNCT = "punct"
_TOKEN_EOF = "eof"

_NAME_RE = re.compile(r"[_A-Za-z][_0-9A-Za-z]*")
_NUMBER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_PUNCTUATORS = frozenset("{}()[]:!$=@")

_STRING_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class GraphQLError(Exception):
    """A parse or validation failure, optionally carrying source locations.

    ``locations`` is a list of ``{"line", "column"}`` dicts, in the shape the
    GraphQL spec uses for the ``errors[].locations`` response entry.
    """

    def __init__(self, message: str, locations: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.locations = list(locations or [])

    def as_dict(self, path: list[Any] | None = None) -> dict:
        """Serialize this error the way a GraphQL response reports it."""
        entry: dict[str, Any] = {"message": self.message}
        if self.locations:
            entry["locations"] = list(self.locations)
        if path:
            entry["path"] = list(path)
        return entry


@dataclass(frozen=True)


class Variable:
    """A ``$name`` argument value, resolved when the query is executed."""

    name: str


def _location(line: int, column: int) -> dict:
    """A GraphQL source location."""
    return {"line": line, "column": column}


@dataclass(frozen=True)


class _Token:
    """One lexed token."""

    kind: str
    value: Any
    line: int
    column: int


def _advance(text: str, line: int, column: int) -> tuple[int, int]:
    """Line/column after consuming ``text``."""
    if "\n" not in text:
        return line, column + len(text)
    return line + text.count("\n"), len(text) - text.rfind("\n")


def _read_string(source: str, index: int, line: int, column: int) -> tuple[str, int, int, int]:
    """Read a (block) string literal; returns value, next index, line, column."""
    start = index
    if source.startswith('"""', index):
        end = source.find('"""', index + 3)
        if end == -1:
            raise GraphQLError(
                "Syntax error: unterminated block string.", [_location(line, column)]
            )
        new_index = end + 3
        value = source[index + 3 : end]
        new_line, new_column = _advance(source[start:new_index], line, column)
        return value, new_index, new_line, new_column

    index += 1
    characters: list[str] = []
    while index < len(source):
        character = source[index]
        if character == '"':
            new_index = index + 1
            new_line, new_column = _advance(source[start:new_index], line, column)
            return "".join(characters), new_index, new_line, new_column
        if character == "\n":
            break
        if character == "\\":
            escape = source[index + 1 : index + 2]
            if escape == "u":
                digits = source[index + 2 : index + 6]
                if len(digits) != 4 or any(d not in "0123456789abcdefABCDEF" for d in digits):
                    raise GraphQLError(
                        "Syntax error: invalid unicode escape.", [_location(line, column)]
                    )
                characters.append(chr(int(digits, 16)))
                index += 6
                continue
            if escape in _STRING_ESCAPES:
                characters.append(_STRING_ESCAPES[escape])
                index += 2
                continue
            raise GraphQLError(
                f"Syntax error: invalid escape '\\{escape}'.", [_location(line, column)]
            )
        characters.append(character)
        index += 1
    raise GraphQLError("Syntax error: unterminated string.", [_location(line, column)])


def _tokenize(source: str) -> list[_Token]:
    """Turn a GraphQL document into tokens (commas and comments are ignored)."""
    tokens: list[_Token] = []
    index = 0
    line = 1
    column = 1
    length = len(source)

    while index < length:
        character = source[index]
        if character == "\ufeff" or character in " \t\r\n,":
            line, column = _advance(character, line, column)
            index += 1
            continue
        if character == "#":
            while index < length and source[index] != "\n":
                index += 1
            continue

        start_line, start_column = line, column
        if character == '"':
            value, index, line, column = _read_string(source, index, line, column)
            tokens.append(_Token(_TOKEN_STRING, value, start_line, start_column))
            continue

        match = _NUMBER_RE.match(source, index) if character == "-" or character.isdigit() else None
        if match is not None:
            text = match.group(0)
            kind = _TOKEN_FLOAT if any(mark in text for mark in ".eE") else _TOKEN_INT
            value = float(text) if kind == _TOKEN_FLOAT else int(text)
            tokens.append(_Token(kind, value, start_line, start_column))
            line, column = _advance(text, line, column)
            index = match.end()
            continue

        match = _NAME_RE.match(source, index)
        if match is not None:
            text = match.group(0)
            tokens.append(_Token(_TOKEN_NAME, text, start_line, start_column))
            line, column = _advance(text, line, column)
            index = match.end()
            continue

        if character in _PUNCTUATORS:
            tokens.append(_Token(_TOKEN_PUNCT, character, start_line, start_column))
            line, column = _advance(character, line, column)
            index += 1
            continue

        raise GraphQLError(
            f"Syntax error: unexpected character {character!r}.",
            [_location(start_line, start_column)],
        )

    tokens.append(_Token(_TOKEN_EOF, None, line, column))
    return tokens


class _Parser:
    """Recursive-descent parser for the query subset Zfrog serves."""

    def __init__(self, source: str):
        self.tokens = _tokenize(source)
        self.index = 0

    # ── token plumbing ───────────────────────────────────────────

    @property
    def _current(self) -> _Token:
        return self.tokens[self.index]

    def _at_end(self) -> bool:
        return self._current.kind == _TOKEN_EOF

    def _peek_punct(self, value: str) -> bool:
        token = self._current
        return token.kind == _TOKEN_PUNCT and token.value == value

    def _peek_name(self, value: str | None = None) -> bool:
        token = self._current
        return token.kind == _TOKEN_NAME and (value is None or token.value == value)

    def _advance(self) -> _Token:
        token = self._current
        if token.kind != _TOKEN_EOF:
            self.index += 1
        return token

    def _unexpected(self, expected: str) -> GraphQLError:
        token = self._current
        found = "end of input" if token.kind == _TOKEN_EOF else repr(token.value)
        return GraphQLError(
            f"Syntax error: expected {expected}, found {found}.",
            [_location(token.line, token.column)],
        )

    def _expect_punct(self, value: str) -> _Token:
        if not self._peek_punct(value):
            raise self._unexpected(f"'{value}'")
        return self._advance()

    def _expect_name(self) -> _Token:
        if self._current.kind != _TOKEN_NAME:
            raise self._unexpected("a name")
        return self._advance()

    # ── document ─────────────────────────────────────────────────

    def parse_document(self) -> dict:
        """Parse exactly one query operation."""
        if self._peek_name("mutation") or self._peek_name("subscription"):
            token = self._current
            raise GraphQLError(
                f"Unsupported operation '{token.value}': this API is read-only, "
                "only 'query' operations are allowed.",
                [_location(token.line, token.column)],
            )

        variables: list[dict] = []
        if self._peek_name("query"):
            self._advance()
            if self._peek_name():
                self._advance()  # operation name
            if self._peek_punct("("):
                variables = self._variable_definitions()

        document: dict = {"operation": "query", "fields": self._selection_set()}
        if variables:
            document["variables"] = variables
        if not self._at_end():
            raise self._unexpected("end of input")
        return document

    def _variable_definitions(self) -> list[dict]:
        self._expect_punct("(")
        definitions: list[dict] = []
        while not self._peek_punct(")"):
            if self._at_end():
                raise GraphQLError(
                    "Syntax error: unterminated variable definitions, expected ')'.",
                    [_location(self._current.line, self._current.column)],
                )
            self._expect_punct("$")
            name = self._expect_name().value
            self._expect_punct(":")
            definition: dict = {"name": name, "type": self._type_reference()}
            if self._peek_punct("="):
                self._advance()
                definition["default"] = self._value()
            definitions.append(definition)
        self._advance()
        return definitions

    def _type_reference(self) -> str:
        if self._peek_punct("["):
            self._advance()
            inner = self._type_reference()
            self._expect_punct("]")
            text = f"[{inner}]"
        else:
            text = self._expect_name().value
        if self._peek_punct("!"):
            self._advance()
            text += "!"
        return text

    # ── selections ───────────────────────────────────────────────

    def _selection_set(self) -> list[dict]:
        opening = self._expect_punct("{")
        fields: list[dict] = []
        while not self._peek_punct("}"):
            if self._at_end():
                raise GraphQLError(
                    "Syntax error: unterminated selection set, expected '}'.",
                    [_location(opening.line, opening.column)],
                )
            fields.append(self._field())
        closing = self._advance()
        if not fields:
            raise GraphQLError(
                "Syntax error: empty selection set.",
                [_location(closing.line, closing.column)],
            )
        return fields

    def _field(self) -> dict:
        name = self._expect_name().value
        alias: str | None = None
        if self._peek_punct(":"):
            self._advance()
            alias = name
            name = self._expect_name().value

        node: dict = {"name": name}
        if alias is not None:
            node["alias"] = alias
        node["args"] = self._arguments() if self._peek_punct("(") else {}
        if self._peek_punct("@"):
            raise GraphQLError(
                "Syntax error: directives are not supported.",
                [_location(self._current.line, self._current.column)],
            )
        node["selection"] = self._selection_set() if self._peek_punct("{") else []
        return node

    def _arguments(self) -> dict:
        self._expect_punct("(")
        args: dict[str, Any] = {}
        while not self._peek_punct(")"):
            if self._at_end():
                raise GraphQLError(
                    "Syntax error: unterminated argument list, expected ')'.",
                    [_location(self._current.line, self._current.column)],
                )
            name = self._expect_name()
            if name.value in args:
                raise GraphQLError(
                    f"Syntax error: duplicate argument '{name.value}'.",
                    [_location(name.line, name.column)],
                )
            self._expect_punct(":")
            args[name.value] = self._value()
        self._advance()
        return args

    def _value(self) -> Any:
        token = self._current
        if token.kind in (_TOKEN_INT, _TOKEN_FLOAT, _TOKEN_STRING):
            self._advance()
            return token.value
        if token.kind == _TOKEN_NAME:
            self._advance()
            if token.value == "true":
                return True
            if token.value == "false":
                return False
            if token.value == "null":
                return None
            return token.value  # enum value
        if self._peek_punct("$"):
            self._advance()
            return Variable(self._expect_name().value)
        if self._peek_punct("["):
            opening = self._advance()
            values: list[Any] = []
            while not self._peek_punct("]"):
                if self._at_end():
                    raise GraphQLError(
                        "Syntax error: unterminated list value, expected ']'.",
                        [_location(opening.line, opening.column)],
                    )
                values.append(self._value())
            self._advance()
            return values
        if self._peek_punct("{"):
            opening = self._advance()
            values: dict[str, Any] = {}
            while not self._peek_punct("}"):
                if self._at_end():
                    raise GraphQLError(
                        "Syntax error: unterminated input object, expected '}'.",
                        [_location(opening.line, opening.column)],
                    )
                key = self._expect_name().value
                self._expect_punct(":")
                values[key] = self._value()
            self._advance()
            return values
        raise self._unexpected("a value")


def parse_query(query: str) -> dict:
    """Parse a GraphQL document into ``{"operation", "fields"}``.

    Supports a single operation (``query { ... }`` or a bare ``{ ... }``),
    field aliases, arguments (string, int, float, boolean, null, enum, list and
    ``$variable`` values) and nested selections. Mutations and subscriptions are
    rejected because this API is read-only; every syntax error raises a
    :class:`GraphQLError` carrying ``locations``.
    """
    if not isinstance(query, str) or not query.strip():
        raise GraphQLError("Syntax error: the query is empty.")
    return _Parser(query).parse_document()


@dataclass


class FieldResult:
    """Outcome of one query: the (possibly partial) data plus per-field errors."""

    data: dict
    errors: list[dict]


# ── input coercion ───────────────────────────────────────────────


def _named_type(type_ref: str) -> str:
    """``"[Job!]!"`` -> ``"Job"``."""
    return type_ref.replace("!", "").replace("[", "").replace("]", "")


def _is_list_type(type_ref: str) -> bool:
    return "[" in type_ref


def _int_value(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GraphQLError(f"Argument '{label}' expected an Int, got {value!r}.")
    return value


def _float_value(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GraphQLError(f"Argument '{label}' expected a Float, got {value!r}.")
    return float(value)


def _boolean_value(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise GraphQLError(f"Argument '{label}' expected a Boolean, got {value!r}.")
    return value


def _string_value(value: Any, label: str, type_name: str) -> str:
    if isinstance(value, str):
        return value
    if type_name == "ID" and isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise GraphQLError(f"Argument '{label}' expected a {type_name}, got {value!r}.")


def _coerce_input(type_ref: str, value: Any, label: str) -> Any:
    """Coerce one argument (or list item) to its declared input type."""
    if type_ref.endswith("!"):
        if value is None:
            raise GraphQLError(f"Argument '{label}' must not be null (expected {type_ref}).")
        return _coerce_input(type_ref[:-1], value, label)
    if value is None:
        return None
    if _is_list_type(type_ref):
        inner = type_ref[type_ref.index("[") + 1 : type_ref.rindex("]")]
        items = value if isinstance(value, list) else [value]
        return [_coerce_input(inner, item, label) for item in items]

    name = _named_type(type_ref)
    if name == "Int":
        return _int_value(value, label)
    if name == "Float":
        return _float_value(value, label)
    if name == "Boolean":
        return _boolean_value(value, label)
    if name in ("String", "ID"):
        return _string_value(value, label, name)
    raise GraphQLError(f"Argument '{label}' has unsupported type '{name}'.")


def _resolve_value(value: Any, variables: dict, definitions: dict[str, dict]) -> Any:
    """Replace ``$variables`` (and their defaults) inside an argument value."""
    if isinstance(value, Variable):
        if value.name in variables:
            return variables[value.name]
        definition = definitions.get(value.name)
        if definition is not None and "default" in definition:
            return definition["default"]
        raise GraphQLError(f"Variable '${value.name}' was not provided.")
    if isinstance(value, list):
        return [_resolve_value(item, variables, definitions) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_value(item, variables, definitions) for key, item in value.items()}
    return value


def _coerce_arguments(
    spec: dict,
    field_name: str,
    raw: dict,
    variables: dict,
    definitions: dict[str, dict],
) -> dict:
    """Validate/coerce a field's arguments, applying the declared defaults."""
    declared: dict[str, dict] = spec.get("args") or {}
    for name in raw:
        if name not in declared:
            raise GraphQLError(f"Unknown argument '{name}' on field '{field_name}'.")

    values: dict[str, Any] = {}
    for name, arg_spec in declared.items():
        if name in raw:
            resolved = _resolve_value(raw[name], variables, definitions)
            values[name] = _coerce_input(arg_spec["type"], resolved, name)
        elif "default" in arg_spec:
            values[name] = arg_spec["default"]
        elif arg_spec["type"].endswith("!"):
            raise GraphQLError(
                f"Field '{field_name}' argument '{name}' of type "
                f"'{arg_spec['type']}' is required."
            )
    return values


# ── output projection ────────────────────────────────────────────


def _coerce_scalar(type_ref: str, value: Any, name: str) -> Any:
    """Shape one resolved scalar (or list of scalars) as its type promises."""
    if value is None:
        return None
    if _is_list_type(type_ref):
        inner = type_ref[type_ref.index("[") + 1 : type_ref.rindex("]")]
        items = value if isinstance(value, (list, tuple)) else [value]
        return [_coerce_scalar(inner, item, name) for item in items]
    kind = _named_type(type_ref)
    try:
        if kind == "Int":
            return int(value)
        if kind == "Float":
            return float(value)
        if kind == "Boolean":
            return bool(value)
    except (TypeError, ValueError) as exc:
        raise GraphQLError(f"Field '{name}' could not be coerced to {kind}: {exc}") from exc
    return value if kind == "ID" else str(value)


def _project(
    value: Any,
    fields: dict[str, dict],
    selection: list[dict],
    path: list[Any],
    type_name: str,
) -> Any:
    """Keep only the requested subfields of ``value`` (``None`` stays ``None``)."""
    if not selection:
        raise GraphQLError(
            f"Field '{path[-1]}' of type '{type_name}' must have a selection of subfields."
        )
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [
            _project_object(item, fields, selection, [*path, index], type_name)
            for index, item in enumerate(value)
        ]
    return _project_object(value, fields, selection, path, type_name)


def _project_object(
    item: Any,
    fields: dict[str, dict],
    selection: list[dict],
    path: list[Any],
    type_name: str,
) -> dict:
    """Project one object of ``type_name`` onto the requested selection."""
    if not isinstance(item, dict):
        raise GraphQLError(
            f"Field '{path[-1]}' of type '{type_name}' did not resolve to an object."
        )

    projected: dict[str, Any] = {}
    for node in selection:
        name = node["name"]
        key = node.get("alias") or name
        if name == "__typename":
            projected[key] = type_name
            continue

        spec = fields.get(name)
        if spec is None:
            raise GraphQLError(f"Cannot query field '{name}' on type '{type_name}'.")
        if node.get("args"):
            raise GraphQLError(f"Field '{name}' does not take arguments.")

        child = item.get(name)
        nested = spec.get("fields")
        if nested:
            projected[key] = _project(
                child,
                nested,
                node.get("selection") or [],
                [*path, key],
                _named_type(spec["type"]),
            )
            continue
        if node.get("selection"):
            raise GraphQLError(
                f"Field '{name}' must not have a selection since type '{spec['type']}' "
                "has no subfields."
            )
        projected[key] = _coerce_scalar(spec["type"], child, name)
    return projected


# ── resolvers ────────────────────────────────────────────────────


def _status_value(status: Any) -> str:
    """``JobStatus.COMPLETED`` and ``"completed"`` both become ``"completed"``."""
    return str(getattr(status, "value", status))


def _isoformat(value: Any) -> str:
    """ISO 8601 text for a datetime, ``str()`` for anything else."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value) if value is not None else ""


def _camel(key: str) -> str:
    """``"avg_duration_s"`` -> ``"avgDurationS"``."""
    head, *tail = key.split("_")
    return head + "".join(part.title() for part in tail)


def _record_dict(item: Any) -> dict:
    """A dataclass (or plain mapping) with its keys in camelCase."""
    data = asdict(item) if is_dataclass(item) and not isinstance(item, type) else dict(item)
    return {_camel(key): value for key, value in data.items()}


def _job_dict(job: Any) -> dict:
    """One job, in the shape the ``Job`` type declares."""
    return {
        "id": str(job.id),
        "url": str(job.url),
        "mode": str(job.mode),
        "status": _status_value(job.status),
        "maxDepth": int(job.max_depth),
        "createdAt": _isoformat(job.created_at),
        "outputPath": job.output_path,
        "error": job.error,
    }


def _result_dict(result: Any) -> dict:
    """One job result, in the shape the ``JobResult`` type declares."""
    return {
        "outputPath": result.output_path,
        "filesCount": int(result.files_count),
        "totalBytes": int(result.total_size_bytes),
        "engineUsed": str(result.engine_used),
        "durationSeconds": float(result.duration_seconds),
    }


def _resolve_jobs(limit: int = 20, status: str | None = None) -> list[dict]:
    """Jobs, newest first, optionally filtered by status."""
    jobs = list(list_jobs())
    if status is not None:
        wanted = status.strip().lower()
        jobs = [job for job in jobs if _status_value(job.status).lower() == wanted]
    jobs.sort(key=lambda job: _isoformat(job.created_at), reverse=True)
    return [_job_dict(job) for job in jobs[: max(0, limit)]]


def _resolve_job(id: str) -> dict | None:
    """One job (plus its result) by id, or ``None`` when unknown."""
    job = get_job(id)
    if job is None:
        return None
    payload = _job_dict(job)
    result = get_result(id)
    payload["result"] = _result_dict(result) if result is not None else None
    return payload


def _read_snapshot_json(path: Path) -> dict | None:
    """Read a snapshot file, returning ``None`` (and logging) when unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Snapshot %s ilegível (%s); ignorando", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _resolve_snapshots(url: str | None = None) -> list[dict]:
    """Change-detection snapshots (newest first), optionally for one URL."""
    entries: list[dict] = []
    for path in list_snapshots(url):
        data = _read_snapshot_json(path)
        if data is None:
            continue
        entries.append(
            {
                "url": str(data.get("url") or ""),
                "capturedAt": str(data.get("captured_at") or ""),
                "engine": str(data.get("engine") or ""),
                "pages": len(data.get("pages") or []),
                "path": str(path),
            }
        )
    entries.reverse()
    return entries


def _resolve_versions(url: str, branch: str | None = None) -> list[dict]:
    """Version-history commits of one URL, newest first."""
    return [_record_dict(version) for version in VersionStore().log(url, branch)]


def _resolve_schedules() -> list[dict]:
    """Every stored recurring schedule."""
    return [_record_dict(schedule) for schedule in ScheduleStore().list()]


def _resolve_engines() -> list[dict]:
    """Registered engines and where each one came from."""
    return [
        {"name": name, "source": ENGINE_SOURCES.get(name, "unknown")} for name in sorted(ENGINES)
    ]


def _resolve_analytics(engine: str | None = None) -> list[dict]:
    """Aggregated run metrics per engine."""
    return [_record_dict(stat) for stat in MetricsStore().engine_stats(engine)]


def _resolve_search(query: str, mode: str = "fulltext", limit: int = 20) -> list[dict]:
    """Search hits for a query, full-text or semantic."""
    return [
        {
            "path": hit.path,
            "url": hit.url,
            "title": hit.title,
            "snippet": hit.snippet,
            "score": hit.score,
        }
        for hit in SearchIndex().search(query, mode=mode, limit=limit)
    ]


def _resolve_sites() -> list[dict]:
    """Sites present in the multi-site RAG index."""
    return [
        {"url": entry["url"], "pages": entry["pages"], "chunks": entry["chunks"]}
        for entry in MultiSiteIndex().sites()
    ]


def _resolve_conversations() -> list[dict]:
    """Saved chat conversations, by file name."""
    session = ChatSession()
    directory = session.history_dir
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    entries: list[dict] = []
    for path in files:
        conversation = session.load(path.stem)
        if conversation is None:
            continue
        entries.append(
            {
                "id": conversation.id,
                "sites": list(conversation.sites),
                "turns": len(conversation.turns),
                "createdAt": conversation.created_at,
            }
        )
    return entries


# ── schema ───────────────────────────────────────────────────────

#: Fields shared by every job selection.
JOB_FIELDS: dict[str, dict] = {
    "id": {"type": "ID!", "doc": "Job identifier."},
    "url": {"type": "String!", "doc": "URL the job was created for."},
    "mode": {"type": "String!", "doc": "Extraction mode."},
    "status": {
        "type": "String!",
        "doc": "pending, probing, running, processing, completed, failed or cancelled.",
    },
    "maxDepth": {"type": "Int!", "doc": "Maximum crawl depth."},
    "createdAt": {"type": "String!", "doc": "Creation timestamp (ISO 8601)."},
    "outputPath": {"type": "String", "doc": "Directory holding the extracted data."},
    "error": {"type": "String", "doc": "Failure reason, when the job failed."},
}

#: Fields of a finished job's result.
JOB_RESULT_FIELDS: dict[str, dict] = {
    "outputPath": {"type": "String!", "doc": "Directory holding the result."},
    "filesCount": {"type": "Int!", "doc": "Number of files produced."},
    "totalBytes": {"type": "Int!", "doc": "Total payload size in bytes."},
    "engineUsed": {"type": "String!", "doc": "Engine that ran the job."},
    "durationSeconds": {"type": "Float!", "doc": "Wall-clock duration in seconds."},
}

#: Every resolvable root field: type, arguments, nested selection and resolver.
SCHEMA: dict[str, dict] = {
    "jobs": {
        "type": "[Job!]!",
        "doc": "Extraction jobs, newest first.",
        "args": {"limit": {"type": "Int", "default": 20}, "status": {"type": "String"}},
        "resolve": _resolve_jobs,
        "fields": JOB_FIELDS,
    },
    "job": {
        "type": "Job",
        "doc": "One job by id, or null when it does not exist.",
        "args": {"id": {"type": "String!"}},
        "resolve": _resolve_job,
        "fields": {
            **JOB_FIELDS,
            "result": {
                "type": "JobResult",
                "doc": "Result of the finished job.",
                "fields": JOB_RESULT_FIELDS,
            },
        },
    },
    "snapshots": {
        "type": "[Snapshot!]!",
        "doc": "Change-detection snapshots, newest first.",
        "args": {"url": {"type": "String"}},
        "resolve": _resolve_snapshots,
        "fields": {
            "url": {"type": "String!", "doc": "URL the snapshot belongs to."},
            "capturedAt": {"type": "String!", "doc": "Capture timestamp (ISO 8601)."},
            "engine": {"type": "String!", "doc": "Engine that produced the clone."},
            "pages": {"type": "Int!", "doc": "Number of pages in the snapshot."},
            "path": {"type": "String!", "doc": "Snapshot file on disk."},
        },
    },
    "versions": {
        "type": "[Version!]!",
        "doc": "Version-history commits of one URL, newest first.",
        "args": {"url": {"type": "String!"}, "branch": {"type": "String"}},
        "resolve": _resolve_versions,
        "fields": {
            "id": {"type": "ID!", "doc": "Commit id."},
            "url": {"type": "String!", "doc": "URL the commit belongs to."},
            "branch": {"type": "String!", "doc": "Branch holding the commit."},
            "message": {"type": "String!", "doc": "Commit message."},
            "capturedAt": {"type": "String!", "doc": "Capture timestamp (ISO 8601)."},
            "pages": {"type": "Int!", "doc": "Number of pages committed."},
            "parent": {"type": "ID", "doc": "Parent commit id, when there is one."},
            "snapshot": {"type": "String!", "doc": "Snapshot file the commit came from."},
        },
    },
    "schedules": {
        "type": "[Schedule!]!",
        "doc": "Recurring job definitions.",
        "resolve": _resolve_schedules,
        "fields": {
            "id": {"type": "ID!", "doc": "Schedule identifier."},
            "cron": {"type": "String!", "doc": "Cron expression."},
            "url": {"type": "String!", "doc": "URL to crawl."},
            "mode": {"type": "String!", "doc": "Extraction mode."},
            "maxDepth": {"type": "Int!", "doc": "Maximum crawl depth."},
            "enabled": {"type": "Boolean!", "doc": "Whether the schedule still runs."},
            "lastRun": {"type": "String", "doc": "Last run timestamp (ISO 8601)."},
            "nextRun": {"type": "String", "doc": "Next run timestamp (ISO 8601)."},
        },
    },
    "engines": {
        "type": "[Engine!]!",
        "doc": "Registered extraction engines.",
        "resolve": _resolve_engines,
        "fields": {
            "name": {"type": "String!", "doc": "Engine name, as used by a job's mode."},
            "source": {"type": "String!", "doc": "built-in, entry-point:<x> or local:<file>."},
        },
    },
    "analytics": {
        "type": "[EngineStats!]!",
        "doc": "Aggregated run metrics per engine.",
        "args": {"engine": {"type": "String"}},
        "resolve": _resolve_analytics,
        "fields": {
            "engine": {"type": "String!", "doc": "Engine name."},
            "runs": {"type": "Int!", "doc": "Recorded runs."},
            "succeeded": {"type": "Int!", "doc": "Runs that completed."},
            "failed": {"type": "Int!", "doc": "Runs that did not complete."},
            "successRate": {"type": "Float!", "doc": "succeeded / runs, between 0 and 1."},
            "avgDurationS": {"type": "Float!", "doc": "Mean duration in seconds."},
            "avgBytes": {"type": "Float!", "doc": "Mean payload size in bytes."},
            "totalBytes": {"type": "Int!", "doc": "Sum of every payload size."},
            "avgFiles": {"type": "Float!", "doc": "Mean number of files per run."},
            "totalCost": {"type": "Float!", "doc": "Estimated cost of every run."},
            "avgCost": {"type": "Float!", "doc": "Estimated cost per run."},
        },
    },
    "search": {
        "type": "[SearchHit!]!",
        "doc": "Search hits over the cloned pages.",
        "args": {
            "query": {"type": "String!"},
            "mode": {"type": "String", "default": "fulltext"},
            "limit": {"type": "Int", "default": 20},
        },
        "resolve": _resolve_search,
        "fields": {
            "path": {"type": "String!", "doc": "Page path inside the clone."},
            "url": {"type": "String!", "doc": "Source URL of the page."},
            "title": {"type": "String!", "doc": "Page title."},
            "snippet": {"type": "String!", "doc": "Matching excerpt."},
            "score": {"type": "Float!", "doc": "Relevance score, higher first."},
        },
    },
    "sites": {
        "type": "[Site!]!",
        "doc": "Sites present in the multi-site RAG index.",
        "resolve": _resolve_sites,
        "fields": {
            "url": {"type": "String!", "doc": "Indexed site URL."},
            "pages": {"type": "Int!", "doc": "Pages indexed for the site."},
            "chunks": {"type": "Int!", "doc": "Chunks indexed for the site."},
        },
    },
    "conversations": {
        "type": "[Conversation!]!",
        "doc": "Saved chat conversations.",
        "resolve": _resolve_conversations,
        "fields": {
            "id": {"type": "ID!", "doc": "Conversation identifier."},
            "sites": {"type": "[String!]!", "doc": "Sites the conversation indexed."},
            "turns": {"type": "Int!", "doc": "Number of stored turns."},
            "createdAt": {"type": "String!", "doc": "Creation timestamp (ISO 8601)."},
        },
    },
}


async def execute(query: str, variables: dict | None = None) -> FieldResult:
    """Run ``query`` against the real stores and return data plus errors.

    Parse errors, unknown fields, unknown/missing arguments and failing resolvers
    are reported in :attr:`FieldResult.errors` with ``null`` for the affected
    field; every other field still resolves.
    """
    try:
        document = parse_query(query)
    except GraphQLError as exc:
        return FieldResult(data={}, errors=[exc.as_dict()])

    if variables is not None and not isinstance(variables, dict):
        return FieldResult(
            data={}, errors=[{"message": "Variables must be an object.", "path": []}]
        )

    provided: dict = dict(variables or {})
    definitions = {item["name"]: item for item in document.get("variables") or []}
    data: dict[str, Any] = {}
    errors: list[dict] = []

    for node in document["fields"]:
        name = node["name"]
        key = node.get("alias") or name
        if name == "__typename":
            data[key] = QUERY_TYPE
            continue

        spec = SCHEMA.get(name)
        if spec is None:
            errors.append(
                {"message": f"Cannot query field '{name}' on type '{QUERY_TYPE}'.", "path": [key]}
            )
            data[key] = None
            continue

        try:
            arguments = _coerce_arguments(
                spec, name, node.get("args") or {}, provided, definitions
            )
            resolved = spec["resolve"](**arguments)
            if inspect.isawaitable(resolved):
                resolved = await resolved
            selection = node.get("selection") or []
            fields = spec.get("fields") or {}
            if fields:
                data[key] = _project(
                    resolved, fields, selection, [key], _named_type(spec["type"])
                )
            elif selection:
                raise GraphQLError(
                    f"Field '{name}' must not have a selection since type "
                    f"'{spec['type']}' has no subfields."
                )
            else:
                data[key] = _coerce_scalar(spec["type"], resolved, name)
        except GraphQLError as exc:
            errors.append(exc.as_dict([key]))
            data[key] = None
        except Exception as exc:  # a broken store must never kill the response
            logger.warning("GraphQL resolver '%s' falhou: %s", name, exc)
            errors.append({"message": str(exc) or exc.__class__.__name__, "path": [key]})
            data[key] = None

    return FieldResult(data=data, errors=errors)


# ── SDL ──────────────────────────────────────────────────────────


def _collect_object_types(
    fields: dict[str, dict], into: dict[str, dict], seen: set[int] | None = None
) -> None:
    """Walk the schema collecting every object type by name."""
    visited = set() if seen is None else seen
    for spec in fields.values():
        nested = spec.get("fields")
        if not nested:
            continue
        name = _named_type(spec["type"])
        if name not in into:
            into[name] = nested
        if id(nested) in visited:
            continue
        visited.add(id(nested))
        _collect_object_types(nested, into, visited)


def _object_types() -> dict[str, dict]:
    """Every object type declared by :data:`SCHEMA`, keyed by name."""
    types: dict[str, dict] = {}
    _collect_object_types(SCHEMA, types)
    return types


def _sdl_literal(value: Any) -> str:
    """Render a default value as GraphQL SDL."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, str):
        return json.dumps(value)
    return repr(value)


def _sdl_arguments(args: dict[str, dict]) -> str:
    """``(limit: Int = 20, status: String)``, or ``""`` when there are none."""
    if not args:
        return ""
    parts = []
    for name, spec in args.items():
        text = f"{name}: {spec['type']}"
        if "default" in spec:
            text += f" = {_sdl_literal(spec['default'])}"
        parts.append(text)
    return "(" + ", ".join(parts) + ")"


def _sdl_field_lines(name: str, spec: dict, indent: str) -> list[str]:
    """One field, with its docstring and arguments, as SDL lines."""
    lines: list[str] = []
    doc = spec.get("doc")
    if doc:
        lines.append(f'{indent}"""{doc}"""')
    lines.append(f"{indent}{name}{_sdl_arguments(spec.get('args') or {})}: {spec['type']}")
    return lines


def schema_sdl() -> str:
    """Render :data:`SCHEMA` as SDL, for docs and introspection display."""
    lines = [
        '"""Zfrog read-only GraphQL schema."""',
        "",
        "scalar Boolean",
        "scalar Float",
        "scalar ID",
        "scalar Int",
        "scalar String",
        "",
        "type Query {",
    ]
    for name, spec in SCHEMA.items():
        lines.extend(_sdl_field_lines(name, spec, "  "))
    lines.append("}")

    types = _object_types()
    for type_name in sorted(types):
        lines.append("")
        lines.append(f"type {type_name} {{")
        for name, spec in types[type_name].items():
            lines.extend(_sdl_field_lines(name, spec, "  "))
        lines.append("}")
    return "\n".join(lines) + "\n"
