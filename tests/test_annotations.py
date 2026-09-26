"""Tests for the clone annotation store."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from zfrog.annotations import AnnotationStore, export_markdown, filter_by_page
from zfrog.config import settings


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Point the default store at a temporary annotations directory."""
    target = tmp_path / "annotations"
    monkeypatch.setattr(settings, "annotations_dir", target)
    return target


@pytest.fixture
def store(root):
    return AnnotationStore()


def _stored_ids(root) -> list[str]:
    """Every annotation id currently on disk, whatever the file."""
    ids: list[str] = []
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        ids.extend(record["id"] for record in payload["annotations"])
    return ids


def test_add_round_trips_and_lists_newest_first(store):
    first = store.add("job-1", "/index.html", "primeira nota", author="ana")
    second = store.add("job-1", "/about.html", "segunda nota")
    third = store.add("job-1", "/contact.html", "terceira nota")

    fetched = store.get(second.id)
    assert fetched is not None
    assert fetched.id == second.id
    assert fetched.job_id == "job-1"
    assert fetched.path == "/about.html"
    assert fetched.text == "segunda nota"
    assert fetched.author == ""
    assert fetched.selector == ""
    assert fetched.resolved is False
    assert fetched.tags == []
    assert fetched.replies == []
    assert fetched.created_at == fetched.updated_at

    assert len(first.id) == 10
    assert int(first.id, 16) >= 0

    assert [item.id for item in store.list()] == [third.id, second.id, first.id]


def test_add_validates_inputs_and_writes_nothing(store, root):
    with pytest.raises(ValueError):
        store.add("job-1", "/index.html", "   ")
    with pytest.raises(ValueError):
        store.add("job-1", "", "nota")
    with pytest.raises(ValueError):
        store.add("job-1", "   ", "nota")
    with pytest.raises(ValueError):
        store.add("", "/index.html", "nota")
    with pytest.raises(ValueError):
        store.add("job-1", "/index.html", "nota", selector="a[")

    assert store.list() == []
    assert _stored_ids(root) == []


def test_add_accepts_a_valid_selector(store):
    annotation = store.add("job-1", "/produto.html", "preço errado", selector="#main > p.price")

    assert annotation.selector == "#main > p.price"
    assert store.get(annotation.id).selector == "#main > p.price"


def test_unsafe_job_id_is_rejected(store, root):
    for bad in ("a/b", "../job", "job\\x", "..", "/etc/passwd"):
        with pytest.raises(ValueError):
            store.add(bad, "/index.html", "nota")

    assert not root.exists() or list(root.iterdir()) == []


def test_update_changes_text_and_bumps_updated_at(store):
    annotation = store.add("job-1", "/index.html", "nota", author="ana")

    updated = store.update(annotation.id, text="  nota revisada  ", tags=["preco", "preco", " "])

    assert updated.text == "nota revisada"
    assert updated.tags == ["preco"]
    assert updated.created_at == annotation.created_at
    assert datetime.fromisoformat(updated.updated_at) > datetime.fromisoformat(annotation.created_at)

    stored = store.get(annotation.id)
    assert stored is not None
    assert stored.text == "nota revisada"
    assert stored.created_at == annotation.created_at

    with pytest.raises(ValueError):
        store.update("0000000000", text="x")
    with pytest.raises(ValueError):
        store.update(annotation.id, text="   ")
    assert store.get(annotation.id).text == "nota revisada"


def test_resolve_flips_the_flag(store):
    annotation = store.add("job-1", "/index.html", "nota")

    assert store.resolve(annotation.id).resolved is True
    assert store.get(annotation.id).resolved is True

    assert store.resolve(annotation.id, False).resolved is False
    assert store.get(annotation.id).resolved is False

    with pytest.raises(ValueError):
        store.resolve("0000000000")


def test_reply_appends_and_is_visible(store):
    annotation = store.add("job-1", "/index.html", "nota")

    replied = store.reply(annotation.id, "  confirmado  ", author="bob")

    assert len(replied.replies) == 1
    entry = replied.replies[0]
    assert entry["author"] == "bob"
    assert entry["text"] == "confirmado"
    assert len(entry["id"]) == 10
    assert entry["created_at"]

    stored = store.get(annotation.id)
    assert [reply["text"] for reply in stored.replies] == ["confirmado"]

    store.reply(annotation.id, "de novo")
    assert [reply["text"] for reply in store.get(annotation.id).replies] == ["confirmado", "de novo"]

    with pytest.raises(ValueError):
        store.reply(annotation.id, "  ")
    with pytest.raises(ValueError):
        store.reply("0000000000", "texto")
    assert len(store.get(annotation.id).replies) == 2


def test_list_filters(store):
    ana = store.add("job-1", "/a.html", "preço errado", author="ana", tags=["preco"])
    bob = store.add("job-1", "/b.html", "falta imagem", author="bob", tags=["imagem", "preco"])
    elsewhere = store.add("job-2", "/a.html", "outro job", author="ana", tags=["preco"])
    store.resolve(bob.id)

    assert {item.id for item in store.list(job_id="job-1")} == {ana.id, bob.id}
    assert [item.id for item in store.list(resolved=True)] == [bob.id]
    assert {item.id for item in store.list(resolved=False)} == {ana.id, elsewhere.id}
    assert {item.id for item in store.list(author="ana")} == {ana.id, elsewhere.id}
    assert {item.id for item in store.list(tag="imagem")} == {bob.id}
    assert {item.id for item in store.list(tag="preco")} == {ana.id, bob.id, elsewhere.id}

    assert [item.id for item in store.list(job_id="job-1", author="ana", resolved=False)] == [ana.id]
    assert store.list(job_id="job-1", author="bob", resolved=False) == []
    assert store.list(job_id="job-3") == []
    assert {item.id for item in store.list()} == {ana.id, bob.id, elsewhere.id}


def test_counts_reports_totals_and_breakdowns(store):
    store.add("job-1", "/a.html", "um", author="ana", tags=["preco", "layout"])
    store.add("job-1", "/b.html", "dois", author="ana", tags=["preco"])
    third = store.add("job-1", "/c.html", "tres", author="bob")
    store.add("job-1", "/d.html", "quatro")
    store.resolve(third.id)

    counts = store.counts("job-1")
    assert counts["total"] == 4
    assert counts["open"] == 3
    assert counts["resolved"] == 1
    assert counts["by_author"] == {"ana": 2, "bob": 1}
    assert counts["by_tag"] == {"preco": 2, "layout": 1}

    assert store.counts("job-2") == {
        "total": 0,
        "open": 0,
        "resolved": 0,
        "by_author": {},
        "by_tag": {},
    }


def test_remove_deletes_and_leaves_a_valid_empty_file(store, root):
    first = store.add("job-1", "/a.html", "um")
    second = store.add("job-1", "/b.html", "dois")

    assert store.remove(first.id) is True
    assert store.get(first.id) is None
    assert [item.id for item in store.list()] == [second.id]
    assert store.remove(first.id) is False

    assert store.remove(second.id) is True
    assert store.get(second.id) is None
    assert store.list() == []

    payload = json.loads((root / "job-1.json").read_text(encoding="utf-8"))
    assert payload == {"job_id": "job-1", "annotations": []}


def test_two_jobs_use_two_files(store, root):
    one = store.add("job-1", "/a.html", "um")
    two = store.add("job-2", "/a.html", "dois")

    assert sorted(path.name for path in root.glob("*.json")) == ["job-1.json", "job-2.json"]
    assert [item.id for item in store.list(job_id="job-1")] == [one.id]
    assert [item.id for item in store.list(job_id="job-2")] == [two.id]
    assert store.counts("job-1")["total"] == 1
    assert store.counts("job-2")["total"] == 1
    assert store.get(one.id).text == "um"


def test_explicit_root_overrides_settings(tmp_path, store, root):
    other = AnnotationStore(root=tmp_path / "elsewhere")
    annotation = other.add("job-9", "/a.html", "noutro lugar")

    assert (tmp_path / "elsewhere" / "job-9.json").is_file()
    assert store.get(annotation.id) is None
    assert store.list() == []
    assert list(root.glob("*.json")) == []


def test_export_markdown_covers_the_review_doc(store):
    first = store.add(
        "job-1",
        "/index.html",
        "preço desatualizado",
        author="ana",
        selector="#main > p.price",
        tags=["preco"],
    )
    store.reply(first.id, "confirmado no site", author="bob")
    second = store.add("job-1", "/about.html", "texto cortado", author="bob")
    store.resolve(second.id)

    document = export_markdown(store.list(job_id="job-1"), job_id="job-1")

    assert "job-1" in document
    assert "/index.html" in document
    assert "/about.html" in document
    assert "#main > p.price" in document
    assert "preço desatualizado" in document
    assert "texto cortado" in document
    assert "confirmado no site" in document
    assert "ana" in document and "bob" in document
    assert "preco" in document
    assert "[x]" in document and "[ ]" in document
    assert document.index("/about.html") < document.index("/index.html")

    empty = export_markdown([], job_id="job-1")
    assert "Nenhuma anotação" in empty


def test_filter_by_page_matches_exactly(store):
    index = store.add("job-1", "/index.html", "um")
    nested = store.add("job-1", "/index.html/other", "dois")
    store.add("job-1", "/about.html", "tres")

    annotations = store.list()

    assert [item.id for item in filter_by_page(annotations, "/index.html")] == [index.id]
    assert [item.id for item in filter_by_page(annotations, "/index.html/other")] == [nested.id]
    assert filter_by_page(annotations, "/index") == []
    assert filter_by_page(annotations, "/index.html?x=1") == []
    assert filter_by_page(annotations, "") == []


def test_stored_file_is_valid_json_after_every_mutation(store, root):
    path = root / "job-1.json"
    annotation = store.add("job-1", "/a.html", "um", author="ana", tags=["t"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["job_id"] == "job-1"
    assert payload["annotations"][0]["id"] == annotation.id

    store.update(annotation.id, text="dois", selector="p.price")
    store.reply(annotation.id, "resposta", author="bob")
    store.resolve(annotation.id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    record = payload["annotations"][0]
    assert record["text"] == "dois"
    assert record["selector"] == "p.price"
    assert record["resolved"] is True
    assert record["replies"][0]["text"] == "resposta"

    store.remove(annotation.id)
    assert json.loads(path.read_text(encoding="utf-8")) == {"job_id": "job-1", "annotations": []}
    assert not list(root.glob("*.tmp")) and not list(root.glob(".*.tmp"))
