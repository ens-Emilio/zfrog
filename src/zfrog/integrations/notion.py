"""Notion destination: create one database page per record."""

from __future__ import annotations

import logging

import httpx

from zfrog.integrations.base import (
    Destination,
    DestinationClient,
    PushResult,
    column_fields,
    config_text,
    response_error,
    rows_from_records,
)

logger = logging.getLogger(__name__)

#: Endpoint that creates a page.
NOTION_PAGES_API = "https://api.notion.com/v1/pages"

#: API version Notion requires on every request.
NOTION_VERSION = "2022-06-28"

#: Seconds a request may take before it is reported as a failure.
TIMEOUT_S = 30.0

#: Notion rejects rich-text content longer than this many characters.
NOTION_TEXT_MAX = 2000


class NotionClient(DestinationClient):
    """Create one page per record in a Notion database (``kind = "notion"``).

    Config: ``database_id`` and ``token`` (required), ``title_property`` (name of
    the database's title property, default: the first field of the row) and
    ``fields`` (column order, default: the union of the record keys).

    The title field is sent as ``{"title": [...]}`` and every other field as
    ``{"rich_text": [...]}``, the only shapes the Notion API accepts for them;
    blank values are skipped and long values are cut at
    :data:`NOTION_TEXT_MAX` characters, Notion's hard limit. A record whose title
    is blank is recorded in ``errors`` (Notion needs a title) and the remaining
    records are still pushed.
    """

    kind = "notion"

    async def push(self, destination: Destination, rows: list[dict]) -> PushResult:
        result = PushResult(destination=destination.name, rows=len(rows))
        database_id = config_text(destination.config, "database_id")
        token = config_text(destination.config, "token")
        if not database_id or not token:
            result.errors.append("destino notion sem database_id ou token")
            return result
        if not rows:
            return result

        try:
            header, matrix = rows_from_records(rows, column_fields(destination.config))
        except TypeError as exc:
            result.errors.append(str(exc))
            return result

        title_key = config_text(destination.config, "title_property") or (header[0] if header else "")
        headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        parent = {"database_id": database_id}

        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            for row_number, row in enumerate(matrix, start=1):
                properties = _properties(header, row, title_key)
                if properties is None:
                    result.errors.append(f"linha {row_number}: sem valor para o título {title_key!r}")
                    continue
                try:
                    response = await client.post(
                        NOTION_PAGES_API,
                        headers=headers,
                        json={"parent": parent, "properties": properties},
                    )
                except httpx.HTTPError as exc:
                    result.errors.append(f"linha {row_number}: falha de rede no Notion: {exc}")
                    continue

                message = response_error(response, "Notion")
                if message:
                    result.errors.append(f"linha {row_number}: {message}")
                    continue

                if _page_id(response):
                    result.created += 1
                else:
                    result.errors.append(f"linha {row_number}: resposta do Notion sem id de página")
        return result


def _properties(header: list[str], row: list, title_key: str) -> dict | None:
    """Build the ``properties`` payload of one page, or None when the title is blank."""
    values = dict(zip(header, row))
    title = values.get(title_key)
    if title is None or not str(title).strip():
        return None

    properties: dict = {title_key: _title(_trim(str(title)))}
    for name, value in values.items():
        if name == title_key or value is None or not str(value).strip():
            continue
        properties[name] = _rich_text(_trim(str(value)))
    return properties


def _title(value: str) -> dict:
    """A Notion title property."""
    return {"title": [{"text": {"content": value}}]}


def _rich_text(value: str) -> dict:
    """A Notion rich-text property."""
    return {"rich_text": [{"text": {"content": value}}]}


def _trim(value: str) -> str:
    """Cut ``value`` at Notion's rich-text limit."""
    if len(value) <= NOTION_TEXT_MAX:
        return value
    logger.debug("Valor cortado em %d caracteres para o Notion", NOTION_TEXT_MAX)
    return value[:NOTION_TEXT_MAX]


def _page_id(response: httpx.Response) -> str:
    """The id of the page a create response confirmed, or "" when it has none."""
    try:
        payload = response.json()
    except ValueError:
        logger.warning("Resposta do Notion sem JSON legível: %s", response.text[:200])
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("id") or "")
