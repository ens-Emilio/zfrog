"""Tests for the time machine (browsing a site as it was on a past date)."""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from zfrog.config import settings
from zfrog.diff import capture_snapshot, snapshots_dir, url_slug
from zfrog.timemachine import (
    ArchivedPage,
    TimelineEntry,
    TimeMachine,
    parse_when,
    resolve_date,
    timeline_summary,
)
from zfrog.utils.text import extract_text
from zfrog.versioning import VersionStore

URL = "https://loja.example"

V1_INDEX = (
    "<html><head><title>Loja v1</title></head>"
    "<body><h1>Bem-vindo</h1><script>var track=1;</script></body></html>"
)
V2_INDEX = (
    "<html><head><title>Loja v2</title></head>"
    "<body><h1>Bem-vindo</h1><p>Promoção</p><script>var track=2;</script></body></html>"
)
ABOUT = "<html><head><title>Sobre</title></head><body><p>Somos a loja</p></body></html>"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Nenhum teste toca o output/versions real do repositório."""
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(settings, "versions_dir", tmp_path / "versions")
    return tmp_path


def _write_snapshot(url: str, captured_at: str, pages: list[dict]) -> Path:
    """Gravar um snapshot no mesmo formato/lugar que `capture_snapshot`."""
    target = snapshots_dir() / url_slug(url)
    target.mkdir(parents=True, exist_ok=True)
    stamp = captured_at.replace("-", "").replace(":", "")
    path = target / f"{stamp}.json"
    path.write_text(
        json.dumps({"url": url, "captured_at": captured_at, "engine": "wget", "pages": pages}),
        encoding="utf-8",
    )
    return path


def _title(html: str) -> str:
    tag = BeautifulSoup(html, "lxml").title
    return tag.string.strip() if tag and tag.string else ""


def _page(rel: str, html: str) -> dict:
    raw = html.encode("utf-8")
    return {
        "path": rel,
        "url": f"{URL}/{rel}",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "title": _title(html),
        "text": extract_text(html),
    }


def _commit(job: Path, captured_at: str, message: str, files: dict[str, str | bytes], branch: str = "main"):
    """Escrever os arquivos no job, capturar um snapshot e commitar."""
    for rel, content in files.items():
        target = job / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    html_pages = [
        _page(rel, content)
        for rel, content in files.items()
        if isinstance(content, str) and rel.endswith(".html")
    ]
    snapshot = _write_snapshot(URL, captured_at, sorted(html_pages, key=lambda page: page["path"]))
    return VersionStore().commit(URL, snapshot, job, message=message, branch=branch)


def test_timeline_lists_every_version_oldest_first(tmp_path):
    job = tmp_path / "job"
    first = _commit(job, "2026-09-01T10:00:00Z", "primeiro", {"index.html": V1_INDEX})
    second = _commit(job, "2026-09-03T10:00:00Z", "segundo", {"index.html": V2_INDEX, "about.html": ABOUT})

    entries = TimeMachine(URL).timeline()

    assert [entry.ref for entry in entries] == [first.id, second.id]
    assert all(isinstance(entry, TimelineEntry) for entry in entries)
    assert [entry.captured_at for entry in entries] == ["2026-09-01T10:00:00Z", "2026-09-03T10:00:00Z"]
    assert entries[0].captured_at < entries[1].captured_at
    assert [entry.message for entry in entries] == ["primeiro", "segundo"]
    assert [entry.branch for entry in entries] == ["main", "main"]

    # pages/size_bytes vêm do snapshot de cada versão.
    assert [entry.pages for entry in entries] == [1, 2]
    assert entries[0].size_bytes == len(V1_INDEX.encode("utf-8"))
    assert entries[1].size_bytes == len(V2_INDEX.encode("utf-8")) + len(ABOUT.encode("utf-8"))


def test_timeline_filters_by_branch(tmp_path):
    job = tmp_path / "job"
    store = VersionStore()
    base = store.commit(
        URL, _write_snapshot(URL, "2026-09-01T10:00:00Z", [_page("index.html", V1_INDEX)]), job, message="base"
    )
    store.create_branch(URL, "dev")
    _commit(job, "2026-09-02T10:00:00Z", "dev", {"index.html": V2_INDEX}, branch="dev")

    machine = TimeMachine(URL)

    assert [entry.ref for entry in machine.timeline("main")] == [base.id]
    assert len(machine.timeline()) == 2


def test_at_reads_the_version_not_the_current_disk(tmp_path):
    job = tmp_path / "job"
    first = _commit(job, "2026-09-01T10:00:00Z", "primeiro", {"index.html": V1_INDEX})
    second = _commit(job, "2026-09-03T10:00:00Z", "segundo", {"index.html": V2_INDEX, "about.html": ABOUT})

    machine = TimeMachine(URL)
    pages_v1 = machine.at(first.id)
    pages_v2 = machine.at(second.id)

    assert [page.path for page in pages_v1] == ["index.html"]
    assert [page.path for page in pages_v2] == ["about.html", "index.html"]

    # A página nova existe no diretório atual do job, mas não na versão 1.
    assert (job / "about.html").is_file()
    assert machine.page(first.id, "about.html") is None
    assert "Somos a loja" in machine.page(second.id, "about.html").text
    assert "Promoção" in machine.page(second.id, "index.html").text
    assert "Promoção" not in pages_v1[0].text

    assert pages_v1[0].url == f"{URL}/index.html"
    assert pages_v2[1].title == "Loja v2"
    assert asdict(pages_v2[1])["sha256"] == _page("index.html", V2_INDEX)["sha256"]


def test_at_lists_archived_files_when_the_snapshot_is_gone(tmp_path):
    job = tmp_path / "job"
    version = _commit(job, "2026-09-01T10:00:00Z", "primeiro", {"index.html": V1_INDEX})

    (snapshots_dir() / url_slug(URL) / version.snapshot).unlink()
    machine = TimeMachine(URL)

    pages = machine.at(version.id)

    assert [page.path for page in pages] == ["index.html"]
    assert pages[0].sha256 == version.files["index.html"]
    assert pages[0].size_bytes == len(V1_INDEX.encode("utf-8"))

    entry = machine.timeline()[0]
    assert (entry.pages, entry.size_bytes) == (0, 0)


def test_timeline_reports_zero_pages_without_a_snapshot(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "index.html").write_text(V1_INDEX, encoding="utf-8")
    VersionStore().commit(URL, tmp_path / "sem-snapshot.json", job, message="sem snapshot")

    entry = TimeMachine(URL).timeline()[0]

    assert (entry.pages, entry.size_bytes) == (0, 0)


def test_content_returns_the_original_html(tmp_path):
    job = tmp_path / "job"
    version = _commit(job, "2026-09-01T10:00:00Z", "primeiro", {"index.html": V1_INDEX})

    html = TimeMachine(URL).content(version.id, "index.html")

    assert html == V1_INDEX
    assert "<script>" in html and "var track=1;" in html
    # O texto guardado no snapshot é o extraído: a tag não sobrevive a ele.
    assert "var track" not in extract_text(html)


def test_content_for_a_missing_blob_returns_none(tmp_path):
    job = tmp_path / "job"
    version = _commit(job, "2026-09-01T10:00:00Z", "primeiro", {"index.html": V1_INDEX})
    digest = version.files["index.html"]
    (settings.versions_dir / "store" / "objects" / digest[:2] / digest).unlink()

    machine = TimeMachine(URL)

    assert machine.content(version.id, "index.html") is None
    assert machine.content(version.id, "nao-existe.html") is None


def test_page_and_at_reject_what_is_not_there(tmp_path):
    job = tmp_path / "job"
    version = _commit(job, "2026-09-01T10:00:00Z", "primeiro", {"index.html": V1_INDEX})
    machine = TimeMachine(URL)

    assert machine.page(version.id, "nao-existe.html") is None
    assert machine.page(version.id, "") is None
    assert isinstance(machine.page(version.id, "index.html"), ArchivedPage)

    with pytest.raises(ValueError):
        machine.at("0" * 12)
    with pytest.raises(ValueError):
        machine.at("nao-e-versao")

    # Um ref inválido no visualizador degrada para "não encontrado".
    assert machine.page("0" * 12, "index.html") is None
    assert machine.content("0" * 12, "index.html") is None


def test_restore_writes_the_version_with_relative_paths(tmp_path):
    job = tmp_path / "job"
    png = b"\x89PNG\r\n\x1a\n\x00binary\xff\xfe"
    version = _commit(
        job,
        "2026-09-01T10:00:00Z",
        "primeiro",
        {"index.html": V1_INDEX, "assets/logo.png": png},
    )

    dest = tmp_path / "restore"
    machine = TimeMachine(URL)
    assert machine.restore(version.id, dest) == dest

    assert (dest / "index.html").read_text(encoding="utf-8") == V1_INDEX
    assert (dest / "assets" / "logo.png").read_bytes() == png

    default_dest = machine.restore(version.id)
    assert default_dest == settings.versions_dir / url_slug(URL) / f"restore-{version.id}"
    assert (default_dest / "index.html").read_bytes() == V1_INDEX.encode("utf-8")


def test_parse_when_accepts_the_documented_formats():
    end_of_day = datetime(2026, 9, 1, 23, 59, 59, tzinfo=timezone.utc)

    assert parse_when("2026-09-01") == end_of_day
    assert parse_when(" 2026-09-01 ") == end_of_day
    assert parse_when("2026-09-01T12:00") == datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    assert parse_when("2026-09-01 12:00") == datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    assert parse_when("2026-09-01T12:00:30Z") == datetime(2026, 9, 1, 12, 0, 30, tzinfo=timezone.utc)

    parsed = parse_when("2026-09-01")
    assert parsed.tzinfo is not None and parsed.hour == 23 and parsed.minute == 59
    # O fim do dia é maior que qualquer captura daquele dia.
    assert parsed > datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def test_parse_when_rejects_unaccepted_formats():
    for bad in ("31/12/2026", "2026-13-45", "", "ontem"):
        with pytest.raises(ValueError) as excinfo:
            parse_when(bad)
        message = str(excinfo.value)
        assert "YYYY-MM-DD" in message and "YYYY-MM-DDTHH:MM" in message and "YYYY-MM-DD HH:MM" in message


def test_resolve_date_picks_the_last_version_at_or_before(tmp_path):
    job = tmp_path / "job"
    day1 = _commit(job, "2026-09-01T10:00:00Z", "dia 1", {"index.html": V1_INDEX})
    day3 = _commit(job, "2026-09-03T10:00:00Z", "dia 3", {"index.html": V2_INDEX})

    assert resolve_date(URL, "2026-09-02") == day1.id
    assert resolve_date(URL, "2026-09-03") == day3.id
    assert resolve_date(URL, "2026-09-03T09:00") == day1.id
    assert resolve_date(URL, "2026-09-01 10:00") == day1.id
    assert resolve_date(URL, "2026-08-31") is None
    assert resolve_date(URL, "2026-09-02", root=tmp_path / "versions") == day1.id

    # A mesma porta pela classe, usada pela API.
    assert TimeMachine(URL).resolve_date("2026-09-02") == day1.id
    with pytest.raises(ValueError):
        TimeMachine(URL).resolve_date("02/09/2026")


def test_dates_are_oldest_first_and_match_the_timeline(tmp_path):
    job = tmp_path / "job"
    _commit(job, "2026-09-01T10:00:00Z", "primeiro", {"index.html": V1_INDEX})
    _commit(job, "2026-09-03T10:00:00Z", "segundo", {"index.html": V2_INDEX})
    machine = TimeMachine(URL)

    assert machine.dates() == [entry.captured_at for entry in machine.timeline()]
    assert machine.dates() == ["2026-09-01T10:00:00Z", "2026-09-03T10:00:00Z"]


def test_between_reports_a_page_added_between_two_versions(tmp_path):
    job = tmp_path / "job"
    first = _commit(job, "2026-09-01T10:00:00Z", "primeiro", {"index.html": V1_INDEX})
    second = _commit(job, "2026-09-03T10:00:00Z", "segundo", {"index.html": V2_INDEX, "about.html": ABOUT})

    report = TimeMachine(URL).between(first.id, second.id)

    assert report.added == ["about.html"]
    assert report.changed == ["index.html"]
    assert report.removed == []


def test_timeline_summary_mentions_the_count(tmp_path):
    job = tmp_path / "job"
    _commit(job, "2026-09-01T10:00:00Z", "primeiro", {"index.html": V1_INDEX})
    _commit(job, "2026-09-03T10:00:00Z", "segundo", {"index.html": V2_INDEX})
    machine = TimeMachine(URL)

    summary = timeline_summary(machine.timeline())

    assert "2" in summary
    assert "2026-09-01T10:00:00Z" in summary and "2026-09-03T10:00:00Z" in summary
    assert "1" in timeline_summary(machine.timeline()[:1])
    assert timeline_summary([])


def test_works_with_snapshots_written_by_capture_snapshot(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "index.html").write_text(V1_INDEX, encoding="utf-8")
    snapshot, _ = capture_snapshot(job, URL, "wget")
    version = VersionStore().commit(URL, snapshot, job, message="via capture_snapshot")

    machine = TimeMachine(URL)

    assert machine.dates() == [version.captured_at]
    assert [page.path for page in machine.at(version.id)] == ["index.html"]
    assert machine.page(version.id, "index.html").title == "Loja v1"
    assert "var track=1;" in machine.content(version.id, "index.html")
    assert resolve_date(URL, version.captured_at) == version.id
