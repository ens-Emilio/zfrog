"""Tests for git-like version history (VersionStore)."""

import json
from pathlib import Path

import pytest

from zfrog.config import settings
from zfrog.diff import snapshots_dir, url_slug
from zfrog.storage.content_addressed import ContentAddressedStore
from zfrog.versioning import VersionStore

URL = "https://example.com"
OTHER_URL = "https://nunca.example"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Nenhum teste toca o output/versions real do repositório."""
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(settings, "versions_dir", tmp_path / "versions")
    return tmp_path


def _job_dir(tmp_path: Path, name: str = "job") -> Path:
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _page(path: str, sha: str, text: str = "", title: str = "") -> dict:
    return {"path": path, "sha256": sha, "size_bytes": len(text), "title": title, "text": text}


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


def _store_stats() -> dict:
    return ContentAddressedStore(settings.versions_dir / "store").stats()


def test_commit_twice_links_parent_and_logs_newest_first(tmp_path):
    job = _job_dir(tmp_path)
    (job / "index.html").write_text("<html>v1</html>", encoding="utf-8")
    first_snap = _write_snapshot(URL, "2026-09-24T03:10:27Z", [_page("index.html", "a" * 64, "v1")])

    store = VersionStore()
    first = store.commit(URL, first_snap, job, message="primeiro")

    assert first.parent is None
    assert first.branch == "main"
    assert len(first.id) == 12 and all(c in "0123456789abcdef" for c in first.id)
    assert first.snapshot == first_snap.name
    assert first.captured_at == "2026-09-24T03:10:27Z"
    assert first.pages == 1
    assert set(first.files) == {"index.html"}

    (job / "index.html").write_text("<html>v2</html>", encoding="utf-8")
    second_snap = _write_snapshot(URL, "2026-09-24T04:10:27Z", [_page("index.html", "b" * 64, "v2")])
    second = store.commit(URL, second_snap, job, message="segundo")

    assert second.parent == first.id
    assert second.id != first.id
    assert second.snapshot == second_snap.name
    assert second.files["index.html"] != first.files["index.html"]

    entries = store.log(URL)
    assert [v.id for v in entries] == [second.id, first.id]
    assert [v.message for v in entries] == ["segundo", "primeiro"]
    assert [v.id for v in store.log(URL, "main")] == [second.id, first.id]
    assert store.head(URL).id == second.id
    assert store.head(URL, "main").id == second.id
    assert store.branches(URL) == ["main"]

    # Os commits ficam gravados no layout documentado.
    site_dir = settings.versions_dir / url_slug(URL)
    refs = json.loads((site_dir / "refs.json").read_text(encoding="utf-8"))
    assert refs == {"branches": {"main": second.id}}
    assert (site_dir / "objects" / f"{first.id}.json").is_file()
    assert (site_dir / "objects" / f"{second.id}.json").is_file()


def test_commit_without_output_dir_records_no_files(tmp_path):
    snapshot = _write_snapshot(URL, "2026-09-24T03:10:27Z", [])
    version = VersionStore().commit(URL, snapshot, None, message="vazio")

    assert version.files == {}
    assert version.pages == 0


def test_identical_content_is_deduplicated_across_commits(tmp_path):
    job = _job_dir(tmp_path)
    (job / "a.html").write_text("<html>a</html>", encoding="utf-8")
    (job / "b.html").write_text("<html>b</html>", encoding="utf-8")

    store = VersionStore()
    store.commit(URL, _write_snapshot(URL, "2026-09-24T03:00:00Z", []), job)
    assert _store_stats()["objects"] == 2

    # Terceiro arquivo novo; os dois anteriores são reenviados sem duplicar blobs.
    (job / "c.html").write_text("<html>c</html>", encoding="utf-8")
    head = store.commit(URL, _write_snapshot(URL, "2026-09-24T04:00:00Z", []), job)

    assert set(head.files) == {"a.html", "b.html", "c.html"}
    assert _store_stats()["objects"] == 3


def test_commit_skips_content_store_directory(tmp_path):
    job = _job_dir(tmp_path)
    (job / "index.html").write_text("<html>x</html>", encoding="utf-8")
    nested = job / ".store" / "objects" / "ab"
    nested.mkdir(parents=True)
    (nested / "deadbeef").write_text("blob", encoding="utf-8")

    version = VersionStore().commit(URL, _write_snapshot(URL, "2026-09-24T03:00:00Z", []), job)

    assert set(version.files) == {"index.html"}


def test_create_branch_leaves_main_head_untouched(tmp_path):
    job = _job_dir(tmp_path)
    (job / "index.html").write_text("<html>base</html>", encoding="utf-8")
    store = VersionStore()
    base = store.commit(URL, _write_snapshot(URL, "2026-09-24T03:00:00Z", []), job, message="base")

    store.create_branch(URL, "dev")
    assert store.branches(URL) == ["dev", "main"]
    assert store.head(URL, "dev").id == base.id

    (job / "index.html").write_text("<html>dev</html>", encoding="utf-8")
    dev_commit = store.commit(
        URL, _write_snapshot(URL, "2026-09-24T04:00:00Z", []), job, message="dev", branch="dev"
    )

    assert dev_commit.parent == base.id
    assert dev_commit.branch == "dev"
    assert store.head(URL, "dev").id == dev_commit.id
    assert store.head(URL, "main").id == base.id
    assert [v.id for v in store.log(URL, "dev")] == [dev_commit.id, base.id]
    assert [v.id for v in store.log(URL, "main")] == [base.id]
    assert [v.id for v in store.log(URL)] == [dev_commit.id, base.id]

    with pytest.raises(ValueError, match="ramo de origem desconhecido"):
        store.create_branch(URL, "outro", from_branch="inexistente")


def test_resolve_head_id_prefix_and_branch(tmp_path):
    job = _job_dir(tmp_path)
    (job / "index.html").write_text("<html>base</html>", encoding="utf-8")
    store = VersionStore()
    base = store.commit(URL, _write_snapshot(URL, "2026-09-24T03:00:00Z", []), job)
    store.create_branch(URL, "dev")

    (job / "index.html").write_text("<html>main 2</html>", encoding="utf-8")
    main_tip = store.commit(URL, _write_snapshot(URL, "2026-09-24T04:00:00Z", []), job)
    (job / "index.html").write_text("<html>dev</html>", encoding="utf-8")
    dev_tip = store.commit(
        URL, _write_snapshot(URL, "2026-09-24T05:00:00Z", []), job, branch="dev"
    )

    assert store.resolve(URL, "HEAD").id == main_tip.id
    assert store.resolve(URL, "main").id == main_tip.id
    assert store.resolve(URL, "dev").id == dev_tip.id
    assert store.resolve(URL, base.id).id == base.id
    assert store.resolve(URL, f" {base.id[:8]} ").id == base.id
    assert store.resolve(URL, dev_tip.id[:6]).id == dev_tip.id


def test_rollback_restores_files_byte_for_byte(tmp_path):
    job = _job_dir(tmp_path)
    png_bytes = b"\x89PNG\r\n\x1a\n\x00binary\xff\xfe"
    (job / "index.html").write_text("<html>v1</html>", encoding="utf-8")
    (job / "assets").mkdir()
    (job / "assets" / "logo.png").write_bytes(png_bytes)

    store = VersionStore()
    first = store.commit(URL, _write_snapshot(URL, "2026-09-24T03:00:00Z", []), job, message="v1")

    # O clone muda: arquivo editado e arquivo removido.
    (job / "index.html").write_text("<html>v2</html>", encoding="utf-8")
    (job / "assets" / "logo.png").unlink()
    second = store.commit(URL, _write_snapshot(URL, "2026-09-24T04:00:00Z", []), job, message="v2")

    dest = tmp_path / "restore"
    restored = store.rollback(URL, first.id, dest)

    assert restored == dest
    assert (dest / "index.html").read_bytes() == b"<html>v1</html>"
    assert (dest / "assets" / "logo.png").read_bytes() == png_bytes

    default_dest = store.rollback(URL, "HEAD")
    assert default_dest == settings.versions_dir / url_slug(URL) / f"checkout-{second.id}"
    assert (default_dest / "index.html").read_text(encoding="utf-8") == "<html>v2</html>"
    assert not (default_dest / "assets" / "logo.png").exists()


def test_rollback_skips_missing_blobs(tmp_path):
    job = _job_dir(tmp_path)
    (job / "index.html").write_text("<html>v1</html>", encoding="utf-8")
    (job / "about.html").write_text("<html>sobre</html>", encoding="utf-8")

    store = VersionStore()
    version = store.commit(URL, _write_snapshot(URL, "2026-09-24T03:00:00Z", []), job)

    blob = ContentAddressedStore(settings.versions_dir / "store").get(version.files["index.html"])
    assert blob is not None
    blob.unlink()

    dest = tmp_path / "partial"
    assert store.rollback(URL, version.id, dest) == dest
    assert not (dest / "index.html").exists()
    assert (dest / "about.html").read_text(encoding="utf-8") == "<html>sobre</html>"


def test_diff_versions_reports_added_removed_and_changed(tmp_path):
    job = _job_dir(tmp_path)
    store = VersionStore()

    pages_a = [_page("index.html", "1" * 64, "um"), _page("gone.html", "2" * 64, "dois")]
    first = store.commit(
        URL, _write_snapshot(URL, "2026-09-24T03:00:00Z", pages_a), job, message="antes"
    )
    pages_b = [_page("index.html", "3" * 64, "um novo"), _page("novo.html", "4" * 64, "quatro")]
    second = store.commit(
        URL, _write_snapshot(URL, "2026-09-24T04:00:00Z", pages_b), job, message="depois"
    )

    report = store.diff_versions(URL, first.id, second.id)

    assert report.added == ["novo.html"]
    assert report.removed == ["gone.html"]
    assert report.changed == ["index.html"]
    assert report.unchanged == []
    assert report.url == URL

    # Refs simbólicas também funcionam; a mesma versão não tem mudanças.
    same = store.diff_versions(URL, "main", "HEAD")
    assert same.changed == []
    assert sorted(same.unchanged) == ["index.html", "novo.html"]


def test_unknown_url_branch_and_ref(tmp_path):
    job = _job_dir(tmp_path)
    (job / "index.html").write_text("<html>v1</html>", encoding="utf-8")
    store = VersionStore()
    version = store.commit(URL, _write_snapshot(URL, "2026-09-24T03:00:00Z", []), job)

    with pytest.raises(ValueError, match="versão desconhecida"):
        store.resolve(URL, "deadbeefdead")
    with pytest.raises(ValueError, match="versão desconhecida"):
        store.resolve(URL, "no-such-branch")
    with pytest.raises(ValueError, match="curta demais"):
        store.resolve(URL, "abc")
    with pytest.raises(ValueError, match="versão desconhecida"):
        store.rollback(URL, "deadbeefdead")
    with pytest.raises(ValueError, match="versão desconhecida"):
        store.diff_versions(URL, version.id, "nope")
    with pytest.raises(ValueError, match="nenhuma versão salva"):
        VersionStore().resolve(OTHER_URL, "HEAD")

    # Listagens degradam para vazio em vez de explodir (CLI/API dependem disso).
    empty = VersionStore()
    assert empty.log(OTHER_URL) == []
    assert empty.log(URL, "inexistente") == []
    assert empty.branches(OTHER_URL) == []
    assert empty.head(OTHER_URL) is None
    assert empty.head(URL, "inexistente") is None


def test_diff_versions_requires_the_snapshot_file(tmp_path):
    job = _job_dir(tmp_path)
    (job / "index.html").write_text("<html>v1</html>", encoding="utf-8")
    store = VersionStore()
    first_snap = _write_snapshot(URL, "2026-09-24T03:00:00Z", [])
    first = store.commit(URL, first_snap, job)
    second = store.commit(URL, _write_snapshot(URL, "2026-09-24T04:00:00Z", []), job)

    first_snap.unlink()

    with pytest.raises(ValueError, match="não encontrado"):
        store.diff_versions(URL, first.id, second.id)
