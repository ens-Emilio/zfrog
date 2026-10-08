"""Airtable destination: create records in a table through the Airtable REST API."""

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

#: Root of the Airtable REST API.
AIRTABLE_API = "https://api.airtable.com/v0"

#: Seconds a request may take before it is reported as a failure.
TIMEOUT_S = 30.0

#: Airtable accepts at most ten records per request.
BATCH_SIZE = 10


class AirtableClient(DestinationClient):
    """Create records in an Airtable table (``kind = "airtable"``).

    Config: ``base_id``, ``table`` and ``token`` (required) and ``fields``
    (column order, default: the union of the record keys).

    Records are sent in batches of :data:`BATCH_SIZE`; a batch that fails is
    recorded in ``errors`` while the remaining batches are still sent. Values
    that are missing or blank are left out of ``fields``, because Airtable
    rejects an empty string for a typed column.
    """

    kind = "airtable"

    async def push(self, destination: Destination, rows: list[dict]) -> PushResult:
        result = PushResult(destination=destination.name, rows=len(rows))
        base_id = config_text(destination.config, "base_id")
        table = config_text(destination.config, "table")
        token = config_text(destination.config, "token")
        if not base_id or not table or not token:
            result.errors.append("airtable destination missing base_id, table or token")
            return result
        if not rows:
            return result

        try:
            header, matrix = rows_from_records(rows, column_fields(destination.config))
        except TypeError as exc:
            result.errors.append(str(exc))
            return result

        url = f"{AIRTABLE_API}/{base_id}/{table}"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            for batch_number, start in enumerate(range(0, len(matrix), BATCH_SIZE), start=1):
                batch = matrix[start : start + BATCH_SIZE]
                payload = {"records": [{"fields": _fields(header, row)} for row in batch]}
                try:
                    response = await client.post(url, headers=headers, json=payload)
                except httpx.HTTPError as exc:
                    result.errors.append(f"batch {batch_number}: network failure in Airtable: {exc}")
                    continue

                message = response_error(response, "Airtable")
                if message:
                    result.errors.append(f"batch {batch_number}: {message}")
                    continue

                created = _created_records(response)
                if created is None:
                    result.errors.append(f"batch {batch_number}: Airtable response missing records")
                else:
                    result.created += created
        return result


def _fields(header: list[str], row: list) -> dict:
    """Row values keyed by the header, without the blanks Airtable would reject."""
    return {name: value for name, value in zip(header, row) if value not in ("", None)}


def _created_records(response: httpx.Response) -> int | None:
    """Count the records a create response confirmed (None when it reported none)."""
    try:
        payload = response.json()
    except ValueError:
        logger.warning("Airtable response without readable JSON: %s", response.text[:200])
        return None
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return None
    return len(records)
