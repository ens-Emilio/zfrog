"""Tests for change detection (snapshots + diff)."""

import json
from pathlib import Path

import pytest

from zfrog import diff as diff_mod
from zfrog.config import settings


def _snapshot(url: str, captured_at: str, pages: list[dict]) -> dict:
    return {"url": url, "captured_at": captured_at, "engine": "wget", "pages": pages}


def _page(path: str, sha: str, text: str = "", title: str = "") -> dict:
    return {"path": path, "sha256": sha, "size_bytes": len(text), "title": title, "text": text}


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _isolated_output(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")


def test_url_slug():
    assert diff_mod.url_slug("https://example.com/a/b?x=1") == "example.com_a_b"
    assert diff_mod.url_slug("https://example.com") == "example.com"


def test_url_slug_never_looks_like_a_content_file():
    """A slug dir ending in .html is read as a page by every crawl in the repo.

    Regression: `output/snapshots/127.0.0.1_8000_static_site.html/` made
    CompareEngine (which scans output_dir.parent) do
    `rglob("*.html")[0].read_text()` on a directory -> IsADirectoryError.
    """
    # Extensions the repo's globs actually search for.
    content_exts = (".html", ".htm", ".css", ".js", ".png", ".jpg", ".json", ".md", ".txt", ".csv", ".zip", ".pdf")
    for url in (
        "http://127.0.0.1:8000/static_site.html",
        "https://example.com/docs/index.html",
        "https://example.com/style.css",
        "https://example.com/pic.png",
        "https://example.com/data.json",
    ):
        slug = diff_mod.url_slug(url)
        assert not slug.endswith(content_exts), f"{url} -> {slug} ends in a file extension"


def test_page_url_from_path_handles_every_engine_layout():
    """The host directory spelling differs per engine; all must map back cleanly.

    Regression: delta writes ``<host with ":" -> "_">/page.html`` and wget writes
    ``mirror/<host with ":" -> "+">/page.html``. Only handling the wget form made
    the snapshot record ``http://host/host_8000/page.html`` — a URL no page has.
    """
    site = "http://127.0.0.1:8000"
    expected = "http://127.0.0.1:8000/sobre.html"

    assert diff_mod.page_url_from_path("mirror/127.0.0.1+8000/sobre.html", site) == expected
    assert diff_mod.page_url_from_path("127.0.0.1_8000/sobre.html", site) == expected
    assert diff_mod.page_url_from_path("sobre.html", site) == expected
    # A page that legitimately lives in a directory named like the host is kept
    assert (
        diff_mod.page_url_from_path("mirror/other.example/x.html", site)
        == "http://127.0.0.1:8000/other.example/x.html"
    )
    # The site root maps to a trailing slash, not a doubled path
    assert diff_mod.page_url_from_path("127.0.0.1_8000", site) == "http://127.0.0.1:8000/"
    # A label instead of a URL (the CLI lets users name an indexed site) must not
    # produce a broken "http:///path".
    assert diff_mod.page_url_from_path("index.html", "loja") == "loja/index.html"
    assert diff_mod.page_url_from_path("index.html", "") == "index.html"


def test_capture_snapshot_records_a_real_page_url(tmp_path):
    """A snapshot's page url must be a URL the site actually serves."""
    output_dir = tmp_path / "job"
    (output_dir / "127.0.0.1_8000").mkdir(parents=True)
    (output_dir / "127.0.0.1_8000" / "sobre.html").write_text(
        "<html><body><p>sobre</p></body></html>", encoding="utf-8"
    )

    new_path, _ = diff_mod.capture_snapshot(output_dir, "http://127.0.0.1:8000", "delta")

    pages = json.loads(new_path.read_text(encoding="utf-8"))["pages"]
    assert pages[0]["url"] == "http://127.0.0.1:8000/sobre.html"


def test_capture_snapshot_keeps_revalidated_pages(tmp_path):
    """Pages revalidated with a 304 write no file but must stay in the snapshot."""
    output_dir = tmp_path / "job"
    output_dir.mkdir()
    (output_dir / "index.html").write_text("<html><body><p>um</p></body></html>", encoding="utf-8")

    # A previous snapshot holding the page that this run only revalidated.
    previous_dir = diff_mod.snapshots_dir() / diff_mod.url_slug("https://example.com")
    previous_dir.mkdir(parents=True, exist_ok=True)
    previous = previous_dir / "20260101T000000000000Z.json"
    previous.write_text(
        json.dumps(
            {
                "url": "https://example.com",
                "captured_at": "2026-01-01T00:00:00Z",
                "engine": "delta",
                "pages": [
                    {
                        "path": "sobre.html",
                        "url": "https://example.com/sobre.html",
                        "sha256": "d" * 64,
                        "size_bytes": 12,
                        "title": "Sobre",
                        "text": "sobre",
                        "etag": '"abc"',
                        "last_modified": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "delta_report.json").write_text(
        json.dumps({"added": [], "changed": [], "unchanged": ["https://example.com/sobre.html"]}),
        encoding="utf-8",
    )

    new_path, _ = diff_mod.capture_snapshot(output_dir, "https://example.com", "delta")

    pages = json.loads(new_path.read_text(encoding="utf-8"))["pages"]
    assert [p["path"] for p in pages] == ["index.html", "sobre.html"]
    assert pages[1]["etag"] == '"abc"'


def test_capture_snapshot_same_second_does_not_overwrite(tmp_path):
    """Two captures in the same second must be two files, not one overwritten.

    Regression: second-resolution names made the second run clobber the first,
    so the version timeline silently lost an entry (and diff_versions between
    two commits reported no changes).
    """
    output_dir = tmp_path / "job"
    output_dir.mkdir()
    (output_dir / "index.html").write_text("<html><body><p>um</p></body></html>", encoding="utf-8")

    first, _ = diff_mod.capture_snapshot(output_dir, "https://example.com", "wget")
    (output_dir / "index.html").write_text("<html><body><p>dois</p></body></html>", encoding="utf-8")
    second, previous = diff_mod.capture_snapshot(output_dir, "https://example.com", "wget")

    assert first != second
    assert previous == first
    assert len(diff_mod.list_snapshots("https://example.com")) == 2

    # Both versions survive with their own content, oldest first.
    titles = [
        json.loads(p.read_text(encoding="utf-8"))["pages"][0]["text"]
        for p in diff_mod.list_snapshots("https://example.com")
    ]
    assert titles == ["um", "dois"]


def test_capture_snapshot_ignores_directories_named_like_pages(tmp_path):
    """A directory whose name ends in .html must not be read as a page."""
    output_dir = tmp_path / "job"
    output_dir.mkdir()
    (output_dir / "real.html").write_text("<html><body><p>ok</p></body></html>", encoding="utf-8")
    # Mimics an old-format snapshot slug directory
    decoy = output_dir / "decoy.html"
    decoy.mkdir()
    (decoy / "20260101T000000Z.json").write_text("{}", encoding="utf-8")

    new_path, _ = diff_mod.capture_snapshot(output_dir, "https://example.com", "wget")

    pages = json.loads(new_path.read_text(encoding="utf-8"))["pages"]
    assert [p["path"] for p in pages] == ["real.html"]


def test_capture_and_list(tmp_path, monkeypatch):
    output_dir = tmp_path / "job"
    output_dir.mkdir()
    (output_dir / "index.html").write_text(
        "<html><head><title>Home</title></head><body><p>Casa</p></body></html>", encoding="utf-8"
    )
    sub = output_dir / "sub"
    sub.mkdir()
    (sub / "page.html").write_text(
        "<html><head><title>Sub</title></head><body><p>Sub page</p></body></html>", encoding="utf-8"
    )

    new_path, previous = diff_mod.capture_snapshot(output_dir, "https://example.com", "wget")

    assert previous is None
    assert new_path.is_file()
    assert new_path.parent.name == "example.com"

    listed = diff_mod.list_snapshots("https://example.com")
    assert listed == [new_path]
    assert diff_mod.latest_snapshot("https://example.com") == new_path

    data = json.loads(new_path.read_text(encoding="utf-8"))
    assert data["engine"] == "wget"
    assert {p["path"] for p in data["pages"]} == {"index.html", "sub/page.html"}
    for page in data["pages"]:
        assert len(page["sha256"]) == 64
        assert page["size_bytes"] > 0
    assert next(p for p in data["pages"] if p["path"] == "index.html")["title"] == "Home"


def test_capture_empty_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    new_path, _ = diff_mod.capture_snapshot(empty, "https://example.com", "wget")

    assert json.loads(new_path.read_text(encoding="utf-8"))["pages"] == []


def test_capture_missing_dir(tmp_path):
    new_path, _ = diff_mod.capture_snapshot(tmp_path / "nope", "https://example.com", "wget")

    assert new_path.is_file()


def test_diff_added_removed_changed(tmp_path):
    a = _write(
        tmp_path / "a.json",
        _snapshot(
            "https://example.com",
            "2026-09-01T10:00:00Z",
            [_page("p1", "X", "antigo"), _page("p2", "Z", "some")],
        ),
    )
    b = _write(
        tmp_path / "b.json",
        _snapshot(
            "https://example.com",
            "2026-09-02T10:00:00Z",
            [_page("p1", "Y", "novo conteudo"), _page("p3", "W", "nova pagina")],
        ),
    )

    report = diff_mod.diff_snapshots(a, b)

    assert report.added == ["p3"]
    assert report.removed == ["p2"]
    assert report.changed == ["p1"]
    assert report.unchanged == []
    assert report.change_ratio == 0.5
    assert report.details[0]["path"] == "p1"
    assert report.details[0]["text_diff_lines"] > 0
    assert report.a == "2026-09-01T10:00:00Z"
    assert report.b == "2026-09-02T10:00:00Z"


def test_diff_identical(tmp_path):
    data = _snapshot("https://example.com", "2026-09-01T10:00:00Z", [_page("p1", "X", "mesmo")])
    a = _write(tmp_path / "a.json", data)
    b = _write(tmp_path / "b.json", data)

    report = diff_mod.diff_snapshots(a, b)

    assert report.changed == []
    assert report.change_ratio == 0.0
    assert report.unchanged == ["p1"]


def test_diff_order_swap(tmp_path):
    a = _write(
        tmp_path / "old.json",
        _snapshot("https://example.com", "2026-09-01T10:00:00Z", [_page("p1", "X", "antigo")]),
    )
    b = _write(
        tmp_path / "new.json",
        _snapshot("https://example.com", "2026-09-02T10:00:00Z", [_page("p2", "Y", "novo")]),
    )

    forward = diff_mod.diff_snapshots(a, b)
    swapped = diff_mod.diff_snapshots(b, a)

    assert swapped.added == forward.added == ["p2"]
    assert swapped.removed == forward.removed == ["p1"]
    assert swapped.a == forward.a == "2026-09-01T10:00:00Z"
    assert swapped.b == forward.b == "2026-09-02T10:00:00Z"


def test_diff_to_markdown(tmp_path):
    a = _write(
        tmp_path / "a.json",
        _snapshot("https://example.com", "2026-09-01T10:00:00Z", [_page("p1", "X", "antigo")]),
    )
    b = _write(
        tmp_path / "b.json",
        _snapshot("https://example.com", "2026-09-02T10:00:00Z", [_page("p1", "Y", "novo")]),
    )

    md = diff_mod.diff_to_markdown(diff_mod.diff_snapshots(a, b))

    assert "p1" in md
    assert "100.0%" in md
    assert "## Alteradas (1)" in md


def test_resolve_snapshot_accepts_path_and_slug_ref(tmp_path):
    output_dir = tmp_path / "job"
    output_dir.mkdir()
    (output_dir / "index.html").write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
    captured, _ = diff_mod.capture_snapshot(output_dir, "https://example.com", "wget")

    # Absolute filesystem path (CLI contract)
    assert diff_mod.resolve_snapshot(captured) == captured
    # <slug>/<filename> reference (what a browser client can build)
    ref = f"{captured.parent.name}/{captured.name}"
    assert diff_mod.resolve_snapshot(ref) == captured


def test_resolve_snapshot_rejects_traversal_and_missing(tmp_path):
    assert diff_mod.resolve_snapshot("example.com/nope.json") is None
    assert diff_mod.resolve_snapshot("../../etc/passwd") is None
    assert diff_mod.resolve_snapshot("../secrets.json") is None
    assert diff_mod.resolve_snapshot("a/b/c.json") is None
    assert diff_mod.resolve_snapshot("") is None
    assert diff_mod.resolve_snapshot("a\\b.json") is None


def test_diff_invalid_snapshot(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        diff_mod.diff_snapshots(bad, bad)

    assert diff_mod.list_snapshots() == []


@pytest.mark.asyncio
async def test_maybe_alert_first_snapshot(tmp_path):
    new = _write(tmp_path / "new.json", _snapshot("https://example.com", "2026-09-02T10:00:00Z", []))

    assert await diff_mod.maybe_alert("https://example.com", new, None) is None


@pytest.mark.asyncio
async def test_maybe_alert_threshold(tmp_path, monkeypatch):
    a = _write(
        tmp_path / "a.json",
        _snapshot("https://example.com", "2026-09-01T10:00:00Z", [_page("p1", "X", "antigo")]),
    )
    b = _write(
        tmp_path / "b.json",
        _snapshot("https://example.com", "2026-09-02T10:00:00Z", [_page("p1", "Y", "novo")]),
    )

    calls: list[tuple[str, dict]] = []

    async def fake_notify(event: str, data: dict):
        calls.append((event, data))

    monkeypatch.setattr(settings, "change_alert_threshold", 0.0)
    monkeypatch.setattr(diff_mod, "notify_webhooks", fake_notify)

    report = await diff_mod.maybe_alert("https://example.com", b, a)

    assert report is not None and report.changed == ["p1"]
    assert len(calls) == 1
    event, data = calls[0]
    assert event == "site.changed"
    assert data["change_ratio"] == 1.0
    assert data["changed"] == ["p1"]
    assert data["snapshot"] == str(b)


@pytest.mark.asyncio
async def test_maybe_alert_below_threshold(tmp_path, monkeypatch):
    a = _write(
        tmp_path / "a.json",
        _snapshot(
            "https://example.com",
            "2026-09-01T10:00:00Z",
            [_page("p1", "X", "antigo"), _page("p2", "Y", "igual")],
        ),
    )
    b = _write(
        tmp_path / "b.json",
        _snapshot(
            "https://example.com",
            "2026-09-02T10:00:00Z",
            [_page("p1", "X2", "novo"), _page("p2", "Y", "igual")],
        ),
    )

    calls: list[str] = []

    async def fake_notify(event: str, data: dict):
        calls.append(event)

    monkeypatch.setattr(settings, "change_alert_threshold", 0.9)
    monkeypatch.setattr(diff_mod, "notify_webhooks", fake_notify)

    report = await diff_mod.maybe_alert("https://example.com", b, a)

    assert report is not None
    assert report.change_ratio == 0.5
    assert calls == []
