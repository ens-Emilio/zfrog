"""Tests for the outbound integrations (Sheets, Airtable, Notion)."""

from __future__ import annotations

import json
import stat

import httpx
import pytest
import respx

from zfrog.config import settings
from zfrog.integrations import (
    AirtableClient,
    Destination,
    DestinationStore,
    NotionClient,
    SheetsClient,
    client_for,
    redact,
    rows_from_records,
)

AIRTABLE_URL = "https://api.airtable.com/v0/app-1/Leads"
NOTION_URL = "https://api.notion.com/v1/pages"


def _sheets_url(spreadsheet: str = "sheet-1", target_range: str = "Dados!A1") -> str:
    return f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet}/values/{target_range}:append"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A store rooted in ``tmp_path``, never in the repo's ``integrations/``."""
    monkeypatch.setattr(settings, "integrations_dir", tmp_path / "integrations")
    return DestinationStore()


# ── store ───────────────────────────────────────────────────────────


def test_store_round_trip_keeps_tokens_owner_only(store, tmp_path):
    saved = store.save(
        Destination(
            kind="sheets",
            name="Planilha de Leads",
            config={"spreadsheet_id": "sheet-1", "token": "tok-123"},
        )
    )
    assert saved.name == "Planilha de Leads"

    files = list((tmp_path / "integrations").glob("*.json"))
    assert len(files) == 1
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600

    assert [destination.name for destination in store.list()] == ["Planilha de Leads"]
    fetched = store.get("Planilha de Leads")
    assert fetched is not None
    assert (fetched.kind, fetched.config) == (
        "sheets",
        {"spreadsheet_id": "sheet-1", "token": "tok-123"},
    )
    assert store.get("inexistente") is None

    assert store.remove("Planilha de Leads") is True
    assert store.get("Planilha de Leads") is None
    assert store.remove("Planilha de Leads") is False


def test_store_defaults_to_the_configured_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "integrations_dir", tmp_path / "integracoes")
    DestinationStore().save(Destination(kind="notion", name="Base", config={"token": "t"}))
    assert (tmp_path / "integracoes" / "base.json").is_file()


def test_store_replaces_same_name_and_keeps_similar_names_apart(store, tmp_path):
    store.save(Destination(kind="sheets", name="Planilha", config={"token": "a"}))
    store.save(Destination(kind="sheets", name="Planilha", config={"token": "b"}))
    assert len(list((tmp_path / "integrations").glob("*.json"))) == 1
    assert store.get("Planilha").config["token"] == "b"

    store.save(Destination(kind="sheets", name="Minha Planilha!", config={"token": "c"}))
    store.save(Destination(kind="sheets", name="minha planilha?", config={"token": "d"}))
    assert store.get("Minha Planilha!").config["token"] == "c"
    assert store.get("minha planilha?").config["token"] == "d"
    assert sorted(destination.name for destination in store.list()) == [
        "Minha Planilha!",
        "Planilha",
        "minha planilha?",
    ]

    with pytest.raises(ValueError):
        store.save(Destination(kind="sheets", name="   "))


def test_redact_hides_the_token_and_keeps_the_rest(store):
    destination = store.save(
        Destination(
            kind="airtable",
            name="Base",
            config={"base_id": "app-1", "table": "Leads", "token": "key-123"},
        )
    )

    shown = redact(destination)

    assert shown["name"] == "Base" and shown["kind"] == "airtable"
    assert shown["config"]["base_id"] == "app-1"
    assert "key-123" not in json.dumps(shown)
    assert "key-123" not in str(shown)


# ── records ─────────────────────────────────────────────────────────


def test_rows_from_records_uses_first_seen_union_and_fills_blanks():
    records = [{"a": 1, "b": 2}, {"b": 3, "c": 4}]

    header, rows = rows_from_records(records)

    assert header == ["a", "b", "c"]
    assert rows == [[1, 2, ""], ["", 3, 4]]
    assert rows_from_records([]) == ([], [])
    assert rows_from_records(records, ["c", "a"]) == (["c", "a"], [["", 1], [4, ""]])


def test_rows_from_records_rejects_non_objects():
    with pytest.raises(TypeError):
        rows_from_records([{"a": 1}, "b"])


# ── dispatch ────────────────────────────────────────────────────────


def test_client_for_dispatches_on_kind():
    assert isinstance(client_for(Destination(kind="sheets", name="s")), SheetsClient)
    assert isinstance(client_for(Destination(kind="airtable", name="a")), AirtableClient)
    assert isinstance(client_for(Destination(kind="notion", name="n")), NotionClient)
    assert isinstance(client_for(Destination(kind=" SHEETS ", name="s")), SheetsClient)

    with pytest.raises(ValueError):
        client_for(Destination(kind="ftp", name="x"))


@pytest.mark.parametrize("client_class", [SheetsClient, AirtableClient, NotionClient])
def test_client_kind_matches_the_dispatch_key(client_class):
    destination = Destination(kind=client_class.kind, name="destino")
    assert client_for(destination).kind == client_class.kind


# ── sheets ──────────────────────────────────────────────────────────


async def test_sheets_push_appends_the_header_then_the_rows():
    destination = Destination(
        kind="sheets",
        name="Planilha",
        config={"spreadsheet_id": "sheet-1", "range": "Dados!A1", "token": "tok-123"},
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(_sheets_url()).mock(
            return_value=httpx.Response(200, json={"updates": {"updatedRows": 3}})
        )
        result = await SheetsClient().push(destination, [{"a": 1, "b": 2}, {"a": 3}])

    assert route.called
    request = route.calls[0].request
    assert request.url.params["valueInputOption"] == "RAW"
    assert request.headers["authorization"] == "Bearer tok-123"
    assert json.loads(request.content) == {"values": [["a", "b"], [1, 2], [3, ""]]}
    assert result.destination == "Planilha"
    assert (result.rows, result.created, result.updated, result.errors) == (2, 3, 0, [])


async def test_sheets_push_reports_a_403_without_raising():
    destination = Destination(
        kind="sheets",
        name="Planilha",
        config={"spreadsheet_id": "sheet-1", "range": "Dados!A1", "token": "expirado"},
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.post(_sheets_url()).mock(
            return_value=httpx.Response(403, json={"error": {"message": "PERMISSION_DENIED"}})
        )
        result = await SheetsClient().push(destination, [{"a": 1}])

    assert result.created == 0
    assert len(result.errors) == 1
    assert "403" in result.errors[0]
    assert "PERMISSION_DENIED" in result.errors[0]


async def test_sheets_push_reports_an_unreachable_host():
    destination = Destination(
        kind="sheets",
        name="Planilha",
        config={"spreadsheet_id": "sheet-1", "range": "Dados!A1", "token": "tok-123"},
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.post(_sheets_url()).mock(side_effect=httpx.ConnectError("sem rota"))
        result = await SheetsClient().push(destination, [{"a": 1}])

    assert result.created == 0
    assert len(result.errors) == 1
    assert "network" in result.errors[0]


async def test_sheets_push_without_credentials_reports_instead_of_calling_out():
    destination = Destination(kind="sheets", name="Planilha", config={"spreadsheet_id": "sheet-1"})

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(_sheets_url()).mock(return_value=httpx.Response(200, json={}))
        result = await SheetsClient().push(destination, [{"a": 1}])

    assert route.call_count == 0
    assert result.errors == ["sheets destination missing spreadsheet_id or token"]


# ── airtable ────────────────────────────────────────────────────────


async def test_airtable_push_batches_records_in_tens():
    destination = Destination(
        kind="airtable",
        name="Base",
        config={"base_id": "app-1", "table": "Leads", "token": "key-123"},
    )
    rows = [{"name": f"n{index}", "valor": index} for index in range(25)]

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)["records"]
        return httpx.Response(200, json={"records": [{"id": f"rec{i}"} for i in range(len(sent))]})

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(AIRTABLE_URL).mock(side_effect=handler)
        result = await AirtableClient().push(destination, rows)

    assert route.called
    batches = [len(json.loads(call.request.content)["records"]) for call in route.calls]
    assert batches == [10, 10, 5]
    assert route.calls[0].request.headers["authorization"] == "Bearer key-123"
    assert json.loads(route.calls[0].request.content)["records"][0] == {
        "fields": {"name": "n0", "valor": 0}
    }
    assert (result.rows, result.created, result.updated, result.errors) == (25, 25, 0, [])


async def test_airtable_keeps_pushing_after_a_failed_batch():
    destination = Destination(
        kind="airtable",
        name="Base",
        config={"base_id": "app-1", "table": "Leads", "token": "key-123"},
    )
    rows = [{"name": f"n{index}"} for index in range(25)]
    batches: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)["records"]
        batches.append(len(sent))
        if len(batches) == 2:
            return httpx.Response(422, json={"error": {"message": "INVALID_VALUE_FOR_COLUMN"}})
        return httpx.Response(200, json={"records": [{"id": f"rec{i}"} for i in range(len(sent))]})

    with respx.mock(assert_all_called=False) as mock:
        mock.post(AIRTABLE_URL).mock(side_effect=handler)
        result = await AirtableClient().push(destination, rows)

    assert batches == [10, 10, 5]
    assert result.created == 15
    assert len(result.errors) == 1
    assert "batch 2" in result.errors[0]
    assert "422" in result.errors[0]


async def test_airtable_leaves_blank_values_out_of_the_fields():
    destination = Destination(
        kind="airtable",
        name="Base",
        config={"base_id": "app-1", "table": "Leads", "token": "key-123"},
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(AIRTABLE_URL).mock(
            return_value=httpx.Response(200, json={"records": [{"id": "rec1"}]})
        )
        result = await AirtableClient().push(destination, [{"name": "Ana", "email": ""}])

    assert json.loads(route.calls[0].request.content) == {
        "records": [{"fields": {"name": "Ana"}}]
    }
    assert result.created == 1


# ── notion ──────────────────────────────────────────────────────────


async def test_notion_creates_one_page_per_row():
    destination = Destination(
        kind="notion",
        name="Base",
        config={"database_id": "db-1", "token": "ntn-123"},
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(NOTION_URL).mock(return_value=httpx.Response(200, json={"id": "page-1"}))
        result = await NotionClient().push(destination, [{"Titulo": "Um", "Notas": "n1"}])

    assert route.called
    request = route.calls[0].request
    assert request.headers["notion-version"] == "2022-06-28"
    assert request.headers["authorization"] == "Bearer ntn-123"
    body = json.loads(request.content)
    assert body["parent"] == {"database_id": "db-1"}
    assert body["properties"]["Titulo"] == {"title": [{"text": {"content": "Um"}}]}
    assert body["properties"]["Notas"] == {"rich_text": [{"text": {"content": "n1"}}]}
    assert (result.rows, result.created, result.updated, result.errors) == (1, 1, 0, [])


async def test_notion_records_a_failing_row_and_keeps_going():
    destination = Destination(
        kind="notion",
        name="Base",
        config={"database_id": "db-1", "token": "ntn-123"},
    )
    rows = [{"Titulo": "Um", "Notas": "n1"}, {"Titulo": "Dois"}, {"Titulo": "Tres"}]
    titles: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        title = json.loads(request.content)["properties"]["Titulo"]["title"][0]["text"]["content"]
        titles.append(title)
        if title == "Dois":
            return httpx.Response(400, json={"message": "propriedade inválida"})
        return httpx.Response(200, json={"id": f"page-{len(titles)}"})

    with respx.mock(assert_all_called=False) as mock:
        mock.post(NOTION_URL).mock(side_effect=handler)
        result = await NotionClient().push(destination, rows)

    assert titles == ["Um", "Dois", "Tres"]
    assert result.created == 2
    assert len(result.errors) == 1
    assert "row 2" in result.errors[0]
    assert "400" in result.errors[0]


async def test_notion_reports_rows_without_a_title_and_pushes_the_rest():
    destination = Destination(
        kind="notion",
        name="Base",
        config={"database_id": "db-1", "token": "ntn-123"},
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(NOTION_URL).mock(return_value=httpx.Response(200, json={"id": "page-1"}))
        result = await NotionClient().push(
            destination, [{"Titulo": "   ", "Notas": "n1"}, {"Titulo": "Dois"}]
        )

    assert route.call_count == 1
    assert result.created == 1
    assert len(result.errors) == 1
    assert "row 1" in result.errors[0]


async def test_notion_honours_a_configured_title_property():
    destination = Destination(
        kind="notion",
        name="Base",
        config={
            "database_id": "db-1",
            "token": "ntn-123",
            "title_property": "Nome",
            "fields": "Codigo,Nome",
        },
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(NOTION_URL).mock(return_value=httpx.Response(200, json={"id": "page-1"}))
        result = await NotionClient().push(destination, [{"Codigo": "7", "Nome": "Ana"}])

    properties = json.loads(route.calls[0].request.content)["properties"]
    assert properties["Nome"] == {"title": [{"text": {"content": "Ana"}}]}
    assert properties["Codigo"] == {"rich_text": [{"text": {"content": "7"}}]}
    assert result.created == 1
