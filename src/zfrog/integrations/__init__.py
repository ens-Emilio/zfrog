"""Outbound integrations: push extracted records to Sheets, Airtable or Notion."""

from __future__ import annotations

from zfrog.integrations.airtable import AirtableClient
from zfrog.integrations.base import (
    Destination,
    DestinationClient,
    DestinationStore,
    PushResult,
    client_for,
    redact,
    rows_from_records,
)
from zfrog.integrations.notion import NotionClient
from zfrog.integrations.sheets import SheetsClient

__all__ = [
    "AirtableClient",
    "Destination",
    "DestinationClient",
    "DestinationStore",
    "NotionClient",
    "PushResult",
    "SheetsClient",
    "client_for",
    "redact",
    "rows_from_records",
]
