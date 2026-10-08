"""Hosted half of the marketplace: serve a published index over HTTP.

The app exposes the read side of :mod:`zfrog.marketplace_index`: it turns the
assets published under a marketplace root into the index a client fetches with
:meth:`~zfrog.marketplace.Marketplace.search_remote`, plus the payload of each
item so a client can install it from a URL instead of a shared folder. Publishing
and deleting go through :class:`~zfrog.marketplace.Marketplace`, so the rules that
protect a local marketplace protect the server as well.

The index the server advertises is built when it is first needed and rebuilt after
every change made through the API. Editing the marketplace directory behind the
server's back therefore does not change what it advertises, and
``GET /verify/{id}`` reports exactly that drift: it compares the checksum the
index advertises with the bytes currently on disk.

Writes need no token unless ``require_token`` is set, in which case they need
``Authorization: Bearer <token>``; reads never need one.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Mapping

from fastapi import Body, FastAPI, Header, HTTPException, Query

from zfrog.config import settings
from zfrog.marketplace import Marketplace
from zfrog.marketplace_index import INDEX_VERSION, index_from_marketplace, verify_entry

logger = logging.getLogger(__name__)

#: Name the root route reports, so a client can recognise the service.
SERVICE_NAME = "zfrog-marketplace"


def create_app(
    marketplace: Marketplace | None = None,
    source: str = "",
    require_token: str = "",
) -> FastAPI:
    """Build the ASGI app that serves ``marketplace`` over HTTP.

    ``marketplace`` defaults to one over :data:`zfrog.config.settings.marketplace_dir`,
    ``source`` is reported as the index origin and ``require_token``, when set,
    is the bearer token every write must present.
    """
    store = marketplace if marketplace is not None else Marketplace()
    origin = str(source or "")
    token = str(require_token or "")

    app = FastAPI(title="Zfrog Marketplace", version=str(INDEX_VERSION))
    advertised: dict[str, Any] = {"index": None}

    # ── the advertised index ────────────────────────────────────────

    def index() -> dict:
        """Return the advertised index, building it on first use."""
        current = advertised["index"]
        if current is None:
            current = index_from_marketplace(store, source=origin)
            advertised["index"] = current
        return current

    def refresh() -> dict:
        """Rebuild the advertised index after a change made through the API."""
        current = index_from_marketplace(store, source=origin)
        advertised["index"] = current
        return current

    def entry_of(asset_id: str) -> dict:
        """Return the advertised entry of ``asset_id``, or raise a 404."""
        entry = _entry_by_id(index(), asset_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"item not found: {asset_id}")
        return entry

    def guard(authorization: str | None) -> None:
        """Refuse a write that does not present the configured bearer token."""
        if not token:
            return
        scheme, _, value = str(authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(value.strip(), token):
            raise HTTPException(
                status_code=401,
                detail="missing or invalid publish token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # ── reading ─────────────────────────────────────────────────────

    @app.get("/")
    def root() -> dict:
        """Report what this server is and how many items it advertises."""
        current = index()
        return {
            "service": SERVICE_NAME,
            "version": INDEX_VERSION,
            "count": current["count"],
            "source": origin,
        }

    @app.get("/index.json")
    def index_route() -> dict:
        """Serve the whole index, the document clients fetch and merge."""
        return index()

    @app.get("/assets")
    def assets(
        kind: str | None = Query(default=None, description="Only items of this kind."),
        query: str | None = Query(default=None, description="Search in name, description and tags."),
    ) -> list[dict]:
        """Serve the index's items, optionally filtered by kind and by text."""
        wanted_kind = str(kind).strip().lower() if kind else ""
        needle = str(query).strip().casefold() if query else ""

        found: list[dict] = []
        for entry in index()["assets"]:
            if wanted_kind and str(entry.get("kind") or "").lower() != wanted_kind:
                continue
            if needle and not _matches(entry, needle):
                continue
            found.append(entry)
        return found

    @app.get("/assets/{asset_id}")
    def asset(asset_id: str) -> dict:
        """Serve one advertised item, 404 when the server does not have it."""
        return entry_of(asset_id)

    @app.get("/assets/{asset_id}/payload")
    def asset_payload(asset_id: str) -> dict:
        """Serve just the payload of one item: what a client installs."""
        payload = entry_of(asset_id).get("payload")
        return payload if isinstance(payload, dict) else {}

    @app.get("/verify/{asset_id}")
    def verify(asset_id: str) -> dict:
        """Check the local item against the checksum the index advertises.

        ``valid`` is false when the item was changed behind the server's back,
        and also when the advertised item is not on disk at all any more.
        """
        entry = entry_of(asset_id)
        asset = store.get(asset_id)
        return {
            "id": str(entry.get("id") or ""),
            "checksum": str(entry.get("checksum") or ""),
            "valid": asset is not None and verify_entry(entry, asset),
        }

    @app.get("/health")
    def health() -> dict:
        """Report that the server is up."""
        return {"status": "ok"}

    # ── writing ─────────────────────────────────────────────────────

    @app.post("/assets")
    def publish(
        body: dict[str, Any] = Body(...),
        authorization: str | None = Header(default=None),
    ) -> dict:
        """Publish an item and return the entry the index now advertises."""
        guard(authorization)
        try:
            stored = store.publish(
                kind=body.get("kind"),
                name=body.get("name"),
                payload=body.get("payload"),
                description=body.get("description") or "",
                author=body.get("author") or "",
                version=body.get("version") or "1.0.0",
                tags=body.get("tags"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        entry = _entry_by_id(refresh(), stored.id)
        if entry is None:
            raise HTTPException(
                status_code=500,
                detail=f"the item {stored.id} was published but did not enter the index",
            )
        logger.info("Item %s published via HTTP", stored.id)
        return entry

    @app.delete("/assets/{asset_id}")
    def remove(
        asset_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        """Delete an item, 404 when it is not published."""
        guard(authorization)
        if not store.remove(asset_id):
            raise HTTPException(status_code=404, detail=f"item not found: {asset_id}")
        refresh()
        logger.info("Item %s removed via HTTP", asset_id)
        return {"id": asset_id, "removed": True}

    return app


def serve(
    host: str = "",
    port: int = 0,
    marketplace: Marketplace | None = None,
    source: str = "",
    require_token: str = "",
) -> None:
    """Run the marketplace server until it is stopped.

    ``host`` and ``port`` default to :data:`zfrog.config.settings.marketplace_host`
    and :data:`zfrog.config.settings.marketplace_port`. Uvicorn is imported here,
    so importing the app never needs the server runner.
    """
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - the dependency is installed
        raise RuntimeError("marketplace server requires uvicorn installed") from exc

    bind_host = str(host or "").strip() or str(settings.marketplace_host)
    try:
        bind_port = int(port) or int(settings.marketplace_port)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid marketplace port: {port!r}") from exc

    app = create_app(marketplace=marketplace, source=source, require_token=require_token)
    logger.info(
        "Marketplace at http://%s:%d (%s)",
        bind_host,
        bind_port,
        source or "local marketplace",
    )
    uvicorn.run(app, host=bind_host, port=bind_port)


def _entry_by_id(document: Mapping[str, Any], asset_id: str) -> dict | None:
    """Return the entry of ``asset_id`` in an index document, or None."""
    entries = document.get("assets")
    if not isinstance(entries, list):
        return None
    wanted = str(asset_id or "").strip()
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("id") or "") == wanted:
            return entry
    return None


def _matches(entry: Mapping[str, Any], needle: str) -> bool:
    """Return whether the folded ``needle`` appears in the entry's text.

    The text searched is the name, the description and the tags; ``needle`` must
    already be folded to lower case.
    """
    parts = [str(entry.get("name") or ""), str(entry.get("description") or "")]
    tags = entry.get("tags")
    if isinstance(tags, str):
        parts.append(tags)
    elif isinstance(tags, (list, tuple, set)):
        parts.extend(str(tag) for tag in tags)
    return needle in " ".join(parts).casefold()
