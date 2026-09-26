"""Tests for delta crawling: the revalidation plan, the summary and the engine."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
import respx

from zfrog.config import settings
from zfrog.delta import plan_delta, summarize_delta
from zfrog.diff import capture_snapshot, snapshots_dir, url_slug
from zfrog.engines.delta import DeltaEngine
from zfrog.models import JobCreate

SITE = "https://site.test"
ROOT = f"{SITE}/b.html"
PAGE_A = f"{SITE}/a.html"

OLD_A = "<html><body><p>pagina a estavel</p></body></html>"
OLD_B = "<html><body><p>versao antiga de b</p></body></html>"
NEW_B = '<html><body><p>versao nova de b</p><a href="/a.html">A</a></body></html>'

@pytest.fixture(autouse=True)
def _isolated_output(tmp_path, monkeypatch):
    """Keep snapshots and job output inside the test's tmp dir."""
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _page(
    url: str,
    text: str,
    path: str,
    etag: str = "",
    last_modified: str = "",
) -> dict:
    return {
        "path": path,
        "url": url,
        "sha256": _sha(text),
        "size_bytes": len(text.encode("utf-8")),
        "title": "",
        "text": text,
        "etag": etag,
        "last_modified": last_modified,
    }

def _write_snapshot(url: str, pages: list[dict]) -> Path:
    directory = snapshots_dir() / url_slug(url)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "20000101T000000Z.json"
    path.write_text(
        json.dumps(
            {"url": url, "captured_at": "2000-01-01T00:00:00Z", "engine": "delta", "pages": pages}
        ),
        encoding="utf-8",
    )
    return path

def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def _page_files(output_dir: Path) -> set[str]:
    """Files written by the crawl, excluding the two sidecar files."""
    sidecars = {".http_meta.json", "delta_report.json"}
    return {
        str(f.relative_to(output_dir))
        for f in output_dir.rglob("*")
        if f.is_file() and f.name not in sidecars
    }

def test_plan_delta_without_snapshot_is_empty():
    plan = plan_delta(f"{SITE}/")

    assert plan.url == f"{SITE}/"
    assert plan.known == {}
    assert plan.etags == {}

def test_plan_delta_reads_latest_snapshot():
    _write_snapshot(
        f"{SITE}/",
        [
            _page(PAGE_A, OLD_A, "site.test/a.html", etag='"a-v1"'),
            _page(ROOT, OLD_B, "site.test/b.html", last_modified="Wed, 21 Oct 2026 07:28:00 GMT"),
            {"path": "site.test/orphan.html", "url": "", "sha256": "x"},
        ],
    )

    plan = plan_delta(f"{SITE}/")

    assert set(plan.known) == {PAGE_A, ROOT}
    assert plan.etags == {PAGE_A: '"a-v1"'}
    assert plan.known[ROOT]["last_modified"] == "Wed, 21 Oct 2026 07:28:00 GMT"

def test_plan_delta_matches_directory_and_index_spellings():
    _write_snapshot(f"{SITE}/", [_page(f"{SITE}/index.html", OLD_A, "site.test/index.html")])

    plan = plan_delta(f"{SITE}/")

    assert plan.previous_for(f"{SITE}/") is not None

def test_summarize_delta_classifies_pages():
    previous = {
        f"{SITE}/keep": {"sha256": "keep"},
        f"{SITE}/edit": {"sha256": "before"},
        f"{SITE}/gone": {"sha256": "gone"},
    }
    current = {
        f"{SITE}/keep": {"sha256": "keep"},
        f"{SITE}/edit": {"sha256": "after"},
        f"{SITE}/new": {"sha256": "new"},
    }

    result = summarize_delta(previous, current, unchanged_bytes=4321)

    assert result.added == [f"{SITE}/new"]
    assert result.changed == [f"{SITE}/edit"]
    assert result.unchanged == [f"{SITE}/keep"]
    assert result.removed == [f"{SITE}/gone"]
    assert result.bytes_saved == 4321
    assert result.pages_written == 2

@pytest.mark.asyncio
async def test_delta_engine_downloads_only_the_changed_page(tmp_path):
    _write_snapshot(
        ROOT,
        [
            _page(PAGE_A, OLD_A, "site.test/a.html", etag='"a-v1"'),
            _page(ROOT, OLD_B, "site.test/b.html", etag='"b-v1"'),
        ],
    )
    output_dir = tmp_path / "job"
    requests: dict[str, str | None] = {}

    def revalidate_a(request: httpx.Request) -> httpx.Response:
        requests["a"] = request.headers.get("if-none-match")
        return httpx.Response(304, headers={"etag": '"a-v1"'})

    def changed_b(request: httpx.Request) -> httpx.Response:
        requests["b"] = request.headers.get("if-none-match")
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8", "etag": '"b-v2"'},
            text=NEW_B,
        )

    job = JobCreate(url=ROOT, mode="delta", max_depth=1, max_pages=10)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(PAGE_A).mock(side_effect=revalidate_a)
        mock.get(ROOT).mock(side_effect=changed_b)
        result = await DeltaEngine().execute(job, output_dir)

    # Both requests were conditional, carrying the validators from the snapshot.
    assert requests == {"a": '"a-v1"', "b": '"b-v1"'}

    report = _read_json(output_dir / "delta_report.json")
    assert report["unchanged"] == [PAGE_A]
    assert report["changed"] == [ROOT]
    assert report["added"] == []
    assert report["removed"] == []
    assert report["pages_written"] == 1
    assert report["bytes_saved"] == len(OLD_A.encode("utf-8"))

    # The 304 page is reused, never rewritten; only the changed page lands on disk.
    assert _page_files(output_dir) == {"site.test/b.html"}
    assert not (output_dir / "site.test" / "a.html").exists()
    assert (output_dir / "site.test" / "b.html").read_text(encoding="utf-8").startswith("<html>")

    meta = _read_json(output_dir / ".http_meta.json")
    assert meta[ROOT]["etag"] == '"b-v2"'
    assert meta[PAGE_A]["etag"] == '"a-v1"'

    assert result.files == [output_dir / "site.test" / "b.html"]
    assert result.total_bytes == (output_dir / "site.test" / "b.html").stat().st_size
    assert result.logs[0] == "Revalidando 2 páginas conhecidas..."
    assert result.logs[-1] == "Delta concluído: 0 novas, 1 alteradas"

@pytest.mark.asyncio
async def test_delta_engine_first_run_without_snapshot_writes_everything(tmp_path):
    output_dir = tmp_path / "job"
    root_html = '<html><body><a href="/child.html">child</a></body></html>'
    child_html = "<html><body><p>filho</p></body></html>"
    requests: list[str | None] = []

    def root(request: httpx.Request) -> httpx.Response:
        requests.append(request.headers.get("if-none-match"))
        return httpx.Response(
            200, headers={"content-type": "text/html", "etag": '"root-1"'}, text=root_html
        )

    def child(request: httpx.Request) -> httpx.Response:
        requests.append(request.headers.get("if-none-match"))
        return httpx.Response(200, headers={"content-type": "text/html"}, text=child_html)

    job = JobCreate(url=f"{SITE}/", mode="delta", max_depth=1, max_pages=10)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{SITE}/").mock(side_effect=root)
        mock.get(f"{SITE}/child.html").mock(side_effect=child)
        result = await DeltaEngine().execute(job, output_dir)

    # Nothing was known, so nothing was conditional.
    assert requests == [None, None]

    report = _read_json(output_dir / "delta_report.json")
    assert report["added"] == [f"{SITE}/", f"{SITE}/child.html"]
    assert report["changed"] == []
    assert report["unchanged"] == []
    assert report["pages_written"] == 2

    assert _page_files(output_dir) == {"site.test/index.html", "site.test/child.html"}
    assert (output_dir / "site.test" / "index.html").read_text(encoding="utf-8") == root_html
    assert _read_json(output_dir / ".http_meta.json")[f"{SITE}/"]["etag"] == '"root-1"'
    assert result.total_bytes == len(root_html.encode()) + len(child_html.encode())

@pytest.mark.asyncio
async def test_delta_engine_max_depth_zero_does_not_follow_links(tmp_path):
    output_dir = tmp_path / "job"
    root_html = '<html><body><a href="/child.html">child</a></body></html>'

    job = JobCreate(url=f"{SITE}/", mode="delta", max_depth=0, max_pages=10)
    with respx.mock(assert_all_called=False) as mock:
        root_route = mock.get(f"{SITE}/").mock(
            return_value=httpx.Response(
                200, headers={"content-type": "text/html"}, text=root_html
            )
        )
        child_route = mock.get(f"{SITE}/child.html").mock(
            return_value=httpx.Response(
                200, headers={"content-type": "text/html"}, text="<html></html>"
            )
        )
        await DeltaEngine().execute(job, output_dir)

    assert root_route.called
    assert not child_route.called
    assert _page_files(output_dir) == {"site.test/index.html"}

@pytest.mark.asyncio
async def test_delta_engine_follow_up_run_downloads_nothing(tmp_path):
    """Second run over an unchanged site revalidates instead of re-downloading."""
    _write_snapshot(
        ROOT,
        [
            _page(PAGE_A, OLD_A, "site.test/a.html", etag='"a-v1"'),
            _page(ROOT, OLD_B, "site.test/b.html", etag='"b-v1"'),
        ],
    )
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"

    def revalidate_a(request: httpx.Request) -> httpx.Response:
        return httpx.Response(304, headers={"etag": '"a-v1"'})

    def changed_b(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "etag": '"b-v2"'},
            text='<html><body><a href="/a.html">A</a></body></html>',
        )

    job = JobCreate(url=ROOT, mode="delta", max_depth=1, max_pages=10)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(PAGE_A).mock(side_effect=revalidate_a)
        mock.get(ROOT).mock(side_effect=changed_b)
        await DeltaEngine().execute(job, first_output)

    # Exactly what the orchestrator does after a delta run.
    snapshot_path, _ = capture_snapshot(first_output, ROOT, "delta")
    snapshot = _read_json(snapshot_path)
    # Page a was revalidated (304, no file) and page b was re-downloaded; both
    # belong to the snapshot, each under its real URL, so the next run has a
    # validator for each of them.
    by_url = {page["url"]: page for page in snapshot["pages"]}
    assert sorted(by_url) == [f"{SITE}/a.html", f"{SITE}/b.html"]
    assert by_url[f"{SITE}/b.html"]["etag"] == '"b-v2"'
    assert by_url[f"{SITE}/a.html"]["etag"] == '"a-v1"'

    second_requests: list[str | None] = []

    def unchanged(request: httpx.Request) -> httpx.Response:
        second_requests.append(request.headers.get("if-none-match"))
        return httpx.Response(304, headers={"etag": request.headers.get("if-none-match", "")})

    with respx.mock(assert_all_called=False) as mock:
        # Both pages carry a validator now: the root (b.html, downloaded last
        # time) and a.html (revalidated last time, carried into the snapshot).
        mock.get(ROOT).mock(side_effect=unchanged)
        mock.get(PAGE_A).mock(side_effect=unchanged)
        result = await DeltaEngine().execute(job, second_output)

    assert sorted(second_requests) == ['"a-v1"', '"b-v2"']

    report = _read_json(second_output / "delta_report.json")
    assert report["added"] == []
    assert report["removed"] == []
    assert report["changed"] == []
    assert sorted(report["unchanged"]) == sorted([ROOT, PAGE_A])
    assert report["pages_written"] == 0
    assert _page_files(second_output) == set()
    assert result.files == []

@pytest.mark.asyncio
async def test_delta_engine_revalidates_known_pages_behind_an_unchanged_root(tmp_path):
    """A 304 root yields no links, so known pages must still be revalidated."""
    _write_snapshot(
        f"{SITE}/",
        [
            _page(f"{SITE}/index.html", OLD_B, "site.test/index.html", etag='"root-1"'),
            _page(PAGE_A, OLD_A, "site.test/a.html", etag='"a-v1"'),
        ],
    )
    output_dir = tmp_path / "job"
    requests: dict[str, str | None] = {}

    def revalidate(request: httpx.Request) -> httpx.Response:
        requests[request.url.path] = request.headers.get("if-none-match")
        return httpx.Response(304, headers={"etag": request.headers.get("if-none-match", "")})

    job = JobCreate(url=f"{SITE}/", mode="delta", max_depth=1, max_pages=10)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{SITE}/").mock(side_effect=revalidate)
        mock.get(PAGE_A).mock(side_effect=revalidate)
        result = await DeltaEngine().execute(job, output_dir)

    assert requests == {"/": '"root-1"', "/a.html": '"a-v1"'}

    report = _read_json(output_dir / "delta_report.json")
    assert report["unchanged"] == [f"{SITE}/index.html", PAGE_A]
    assert report["added"] == []
    assert report["changed"] == []
    assert report["removed"] == []
    assert report["bytes_saved"] == len(OLD_B.encode()) + len(OLD_A.encode())
    assert _page_files(output_dir) == set()
    assert result.files == []
