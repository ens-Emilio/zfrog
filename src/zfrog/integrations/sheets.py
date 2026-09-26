"""Google Sheets destination: append rows through the Sheets API v4."""

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

#: Root of the Sheets API v4.
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"

#: Seconds a request may take before it is reported as a failure.
TIMEOUT_S = 30.0

#: Range appended to when the destination does not name one.
DEFAULT_RANGE = "Sheet1"


class SheetsClient(DestinationClient):
    """Append rows to a Google Sheets spreadsheet (``kind = "sheets"``).

    Config: ``spreadsheet_id`` and ``token`` (required), ``range`` (the A1 range
    to append to, default ``Sheet1``) and ``fields`` (column order, default: the
    union of the record keys). The header row is appended first, then one row per
    record, with ``valueInputOption=RAW`` so the sheet keeps the values verbatim.
    """

    kind = "sheets"

    async def push(self, destination: Destination, rows: list[dict]) -> PushResult:
        result = PushResult(destination=destination.name, rows=len(rows))
        spreadsheet_id = config_text(destination.config, "spreadsheet_id")
        token = config_text(destination.config, "token")
        target_range = config_text(destination.config, "range") or DEFAULT_RANGE
        if not spreadsheet_id or not token:
            result.errors.append("destino sheets sem spreadsheet_id ou token")
            return result
        if not rows:
            return result

        try:
            header, matrix = rows_from_records(rows, column_fields(destination.config))
        except TypeError as exc:
            result.errors.append(str(exc))
            return result

        url = f"{SHEETS_API}/{spreadsheet_id}/values/{target_range}:append"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                response = await client.post(
                    url,
                    params={"valueInputOption": "RAW"},
                    headers={"Authorization": f"Bearer {token}"},
                    json={"values": [header, *matrix]},
                )
        except httpx.HTTPError as exc:
            result.errors.append(f"falha de rede ao enviar para o Sheets: {exc}")
            return result

        message = response_error(response, "Sheets")
        if message:
            result.errors.append(message)
            return result

        created = _updated_rows(response)
        if created is None:
            result.errors.append("resposta do Sheets sem updates.updatedRows")
        else:
            result.created = created
        return result


def _updated_rows(response: httpx.Response) -> int | None:
    """Read ``updates.updatedRows`` from an append response (None when it is absent)."""
    try:
        payload = response.json()
    except ValueError:
        logger.warning("Resposta do Sheets sem JSON legível: %s", response.text[:200])
        return None
    updates = payload.get("updates") if isinstance(payload, dict) else None
    if not isinstance(updates, dict):
        return None
    try:
        return int(updates.get("updatedRows") or 0)
    except (TypeError, ValueError):
        return None
