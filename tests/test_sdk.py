"""Contract tests for the published Zfrog client SDKs.

The Python suite cannot run `bun test` or `go test`, so it guards the one thing
that rots silently: whether the SDKs still speak to the endpoints the API
serves. Each SDK builds its request paths from string literals, so the paths are
extracted from the real sources and compared with the documented endpoint list
and with each other — an SDK that drops or renames an endpoint fails here long
before anyone installs a toolchain to notice.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
JS_DIR = REPO_ROOT / "sdk" / "js"
GO_DIR = REPO_ROOT / "sdk" / "go"

JS_SOURCES = (JS_DIR / "src" / "index.ts", JS_DIR / "src" / "types.ts")
GO_SOURCES = (GO_DIR / "zfrog.go",)
SDK_FILES = (
    JS_DIR / "package.json",
    JS_DIR / "src" / "index.ts",
    JS_DIR / "src" / "types.ts",
    JS_DIR / "test" / "client.test.ts",
    GO_DIR / "go.mod",
    GO_DIR / "zfrog.go",
    GO_DIR / "zfrog_test.go",
)

# Every endpoint the API serves, with path parameters normalised to `{}` so the
# same template matches the JS `${...}` interpolation and the Go concatenation.
DOCUMENTED_ENDPOINTS = (
    "/health",
    "/jobs",
    "/jobs/{}/cancel",
    "/jobs/{}/download",
    "/jobs/{}/pdf",
    "/jobs/{}/result",
    "/jobs/{}",
    "/probe/{}",
    "/snapshots",
    "/diff",
    "/versions",
    "/versions/rollback",
    "/search",
    "/schedules",
    "/schedules/{}/run",
    "/schedules/{}",
    "/workflows",
    "/workflows/{}/run",
    "/analytics/engines",
    "/analytics/totals",
    "/audit",
    "/stats",
    "/safety/scan",
    "/ipfs/publish",
)

_INTERPOLATION = re.compile(r"\$\{(?:[^{}]|\{[^{}]*\})*\}")
_PARAM = re.compile(r"\{[^{}]*\}")
# `"/audit" + queryString(...)` glues a query onto the path, not a path segment.
_QUERY_SUFFIX = re.compile(r"(?<=[a-z0-9])\{\}$")
_LETTER = re.compile(r"[a-z]")
# The operand a Go source glues onto a path to interpolate a parameter.
_GO_OPERAND = re.compile(r"\s*\+\s*(?:url\.PathEscape\(|fmt\.Sprint\()")

# A JS/TS token that can hide a path: comments, string literals and template
# literals. Scanned left to right so a `//` inside a string is not a comment.
_JS_TOKEN = re.compile(
    r"/\*.*?\*/"  # block comment
    r"|//[^\n]*"  # line comment
    r'|"(?:\\.|[^"\\])*"'  # double-quoted string
    r"|'(?:\\.|[^'\\])*'"  # single-quoted string
    r"|`(?:\\.|[^`\\])*`",  # template literal
    re.DOTALL,
)

# The same idea for Go: block/line comments and interpreted or raw strings.
_GO_TOKEN = re.compile(
    r"/\*.*?\*/"
    r"|//[^\n]*"
    r'|"(?:\\.|[^"\\])*"'
    r"|`[^`]*`",
    re.DOTALL,
)


def _normalise(path: str) -> str:
    """Collapse every path parameter to `{}`, dropping a query-string suffix."""
    collapsed = _PARAM.sub("{}", _INTERPOLATION.sub("{}", path))
    return _QUERY_SUFFIX.sub("", collapsed)


def _starts_path(candidate: str) -> bool:
    """True for a literal that opens a request path, e.g. `/jobs/`."""
    return candidate.startswith("/") and bool(_LETTER.search(candidate))


def _looks_like_path(candidate: str) -> bool:
    """True for a complete absolute request path such as `/jobs/{}`."""
    return (
        candidate.startswith("/")
        and not candidate.endswith("/")
        and " " not in candidate
        and bool(_LETTER.search(candidate))
    )


def _js_paths(source: str) -> set[str]:
    """Every request path literal in a JS/TS source file."""
    found: set[str] = set()
    for token in _JS_TOKEN.finditer(source):
        text = token.group(0)
        if text[0] not in "\"'`":
            continue
        candidate = _normalise(text[1:-1])
        if _looks_like_path(candidate):
            found.add(candidate)
    return found


def _go_paths(source: str) -> set[str]:
    """Every request path a Go source file builds, `+` concatenations included."""
    found: set[str] = set()
    chain: list[str] = []
    previous_end = 0

    def flush(trailing: str) -> None:
        if not chain:
            return
        if _GO_OPERAND.match(trailing):
            chain.append("{}")
        candidate = _normalise("".join(chain))
        if _looks_like_path(candidate):
            found.add(candidate)
        chain.clear()

    for token in _GO_TOKEN.finditer(source):
        text = token.group(0)
        between = source[previous_end:token.start()]
        previous_end = token.end()

        if text.startswith("/*") or text.startswith("//"):
            flush(between)
            continue

        literal = text[1:-1]
        if not chain:
            if _starts_path(literal):
                chain.append(literal)
            continue
        if "url.PathEscape(" in between or "fmt.Sprint(" in between:
            chain.append("{}")
            chain.append(literal)
        elif between.strip() == "+":
            chain.append(literal)
        else:
            flush(between)
            if _starts_path(literal):
                chain.append(literal)

    flush(source[previous_end:])
    return found


def _read_sources(sources: tuple[Path, ...]) -> str:
    """Concatenate the sources, failing the test when one is missing."""
    chunks: list[str] = []
    for source in sources:
        assert source.is_file(), f"missing SDK source: {source}"
        chunks.append(source.read_text(encoding="utf-8"))
    return "\n".join(chunks)


@pytest.fixture(scope="module")
def js_paths() -> set[str]:
    """Request paths found in the JavaScript SDK."""
    return _js_paths(_read_sources(JS_SOURCES))


@pytest.fixture(scope="module")
def go_paths() -> set[str]:
    """Request paths found in the Go SDK."""
    return _go_paths(_read_sources(GO_SOURCES))


def test_sdk_sources_exist_and_are_not_empty():
    for path in SDK_FILES:
        assert path.is_file(), f"missing SDK file: {path.relative_to(REPO_ROOT)}"
        assert path.stat().st_size > 0, f"empty SDK file: {path.relative_to(REPO_ROOT)}"


def test_js_client_covers_every_documented_endpoint(js_paths: set[str]):
    missing = sorted(set(DOCUMENTED_ENDPOINTS) - js_paths)
    assert not missing, f"the JS SDK does not call: {missing}"


def test_go_client_covers_every_documented_endpoint(go_paths: set[str]):
    missing = sorted(set(DOCUMENTED_ENDPOINTS) - go_paths)
    assert not missing, f"the Go SDK does not call: {missing}"


def test_both_sdks_expose_the_same_endpoints(js_paths: set[str], go_paths: set[str]):
    assert sorted(js_paths) == sorted(go_paths)
    assert js_paths == set(DOCUMENTED_ENDPOINTS), (
        f"the SDKs call undocumented endpoints: {sorted(js_paths - set(DOCUMENTED_ENDPOINTS))}"
    )
