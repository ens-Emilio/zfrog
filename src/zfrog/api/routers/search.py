"""API router: search."""

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from zfrog.api._shared import (
    ACTION_ADMIN,
    ACTION_READ,
    ACTION_VERSION_MANAGE,
    ChatRequest,
    DirRequest,
    GraphRequest,
    MarketRateRequest,
    SearchRequest,
    UrlRequest,
    WatermarkRequest,
    WorkflowPreviewRequest,
    _audit,
    _scoped,
    auth_dependency,
)  # noqa: F401
from zfrog.auth import AuthDecision

router = APIRouter()

@router.post("/search")
async def search_content(body: SearchRequest, request: Request,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Search inside cloned content (full-text or semantic)."""
    from zfrog.search import SearchIndex

    if body.mode not in ("fulltext", "semantic"):
        raise HTTPException(status_code=400, detail="mode must be 'fulltext' or 'semantic'")

    index = SearchIndex(db_path=_scoped(request, "search_db"))
    if body.dir:
        target = Path(body.dir)
        if not target.is_dir():
            raise HTTPException(status_code=404, detail=f"directory not found: {body.dir}")
        index.index_directory(target)

    hits = index.search(body.query, mode=body.mode)
    return {
        "query": body.query,
        "mode": body.mode,
        "hits": [asdict(hit) for hit in hits],
    }

@router.get("/analytics/engines")
async def analytics_engines(request: Request, engine: str | None = None,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Per-engine success rate and throughput."""
    from zfrog.analytics import MetricsStore

    return [asdict(stats) for stats in MetricsStore(db_path=_scoped(request, "metrics_db")).engine_stats(engine)]

@router.get("/analytics/totals")
async def analytics_totals(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """Overall run totals."""
    from zfrog.analytics import MetricsStore

    return MetricsStore(db_path=_scoped(request, "metrics_db")).totals()

@router.get("/audit")
async def audit_entries(limit: int = 50, action: str | None = None, actor: str | None = None,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Recent audit entries, newest first."""
    from zfrog.utils.audit import AuditLog

    return [asdict(entry) for entry in AuditLog().read(limit=limit, action=action, actor=actor)]

@router.post("/safety/scan")
async def safety_scan(request: DirRequest,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Scan cloned content for malware and phishing indicators."""
    from zfrog.pipeline.safety import scan_directory

    target = Path(request.dir)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"directory not found: {request.dir}")

    return asdict(scan_directory(target))

@router.post("/ipfs/publish")
async def ipfs_publish(request: DirRequest,
                       auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Publish a clone to IPFS.

    Sends the content to a third party: a clone leaving the machine is an
    admin decision, like the Arweave equivalent.
    """
    from zfrog.storage.ipfs import publish_output

    target = Path(request.dir)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"directory not found: {request.dir}")

    try:
        result = await publish_output(target)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return asdict(result)

@router.post("/graphql")
async def graphql_endpoint(payload: dict,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Execute a read-only GraphQL query."""
    from zfrog.graphql_api import execute

    query = payload.get("query") or ""
    if not query.strip():
        raise HTTPException(status_code=400, detail="missing 'query'")

    result = await execute(query, payload.get("variables"))
    return {"data": result.data, "errors": result.errors}

@router.get("/graphql/schema")
async def graphql_schema(
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """The GraphQL schema as SDL."""
    from zfrog.graphql_api import schema_sdl

    return {"sdl": schema_sdl()}

@router.post("/chat")
async def chat_endpoint(request: ChatRequest, http_request: Request,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Ask a question, keeping conversation context."""
    from zfrog.ai.chat import ChatSession

    session = ChatSession(history_dir=_scoped(http_request, "chats_dir"))
    if request.conversation and session.load(request.conversation) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    for entry in request.sites:
        label, _, raw_path = entry.partition("=")
        if not raw_path:
            label, raw_path = Path(entry).name, entry
        path = Path(raw_path)
        if not path.is_dir():
            candidates = [
                _scoped(http_request, "output_dir") / raw_path,
                Path("output") / raw_path,
                Path("output/snapshots") / raw_path,
                _scoped(http_request, "output_dir") / "snapshots" / raw_path,
                Path("output/snapshots") / label,
            ]
            found = next((c for c in candidates if c.is_dir()), None)
            if found:
                path = found
            else:
                raise HTTPException(status_code=404, detail=f"directory not found: {path}")
        session.add_site(label, path)

    if not session.index.sites():
        raise HTTPException(status_code=400, detail="no sites indexed")

    _audit(http_request, "chat.ask", target=request.conversation or "new")
    result = await session.ask(request.question)
    saved = session.save()
    return {**result, "conversation": saved.stem}

@router.get("/chat")
async def chat_list(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List saved conversations."""
    from zfrog.ai.chat import ChatSession

    session = ChatSession(history_dir=_scoped(request, "chats_dir"))
    directory = session.history_dir
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    conversations = []
    for path in files:
        conversation = session.load(path.stem)
        if conversation is None:
            continue
        conversations.append(
            {
                "id": conversation.id,
                "sites": conversation.sites,
                "turns": len(conversation.turns),
                "created_at": conversation.created_at,
            }
        )
    return conversations

@router.get("/chat/{conversation_id}")
async def chat_get(request: Request, conversation_id: str,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Read a saved conversation."""
    from dataclasses import asdict

    from zfrog.ai.chat import ChatSession

    conversation = ChatSession(history_dir=_scoped(request, "chats_dir")).load(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {
        "id": conversation.id,
        "sites": conversation.sites,
        "created_at": conversation.created_at,
        "turns": [asdict(turn) for turn in conversation.turns],
    }

@router.post("/tos/check")
async def tos_check(request: UrlRequest,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Check a site's robots.txt and Terms for restrictions."""
    from zfrog.ai.tos import check_site

    return asdict(await check_site(request.url))

@router.post("/watermark")
async def watermark_mark(request: WatermarkRequest,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_VERSION_MANAGE))):
    """Mark a clone with provenance metadata.

    Writes into the stored clone, so `version:manage` — verification stays
    readable, marking does not.
    """
    from zfrog.pipeline.watermark import make_mark, watermark_directory

    target = Path(request.dir)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"directory not found: {request.dir}")

    mark = make_mark(request.source or request.dir)
    return await watermark_directory(target, mark, request.source)

@router.post("/watermark/verify")
async def watermark_verify(request: WatermarkRequest,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Report what provenance metadata a directory carries."""
    from zfrog.pipeline.watermark import verify_directory

    target = Path(request.dir)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"directory not found: {request.dir}")

    return await verify_directory(target)

@router.post("/graph")
async def graph_endpoint(request: GraphRequest,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Build a knowledge graph from entity-annotated pages."""
    from zfrog.ai.graph import build_graph, to_json

    return to_json(build_graph(request.pages))

@router.get("/analytics/cost")
async def analytics_cost(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """Estimated cost per engine."""
    from zfrog.analytics import MetricsStore, rates_from_settings

    rates = rates_from_settings()
    return {"currency": rates.currency, "engines": MetricsStore(db_path=_scoped(request, "metrics_db")).cost_by_engine(rates)}

@router.post("/workflows/preview")
async def preview_workflow(request: WorkflowPreviewRequest,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Explain a pipeline and warn about steps that cannot run."""
    from zfrog.workflows import preview_steps

    try:
        return preview_steps([step.model_dump() for step in request.steps])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/marketplace")
async def marketplace_list(request: Request, 
    kind: str | None = None,
    query: str | None = None,
    tag: str | None = None,
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List published marketplace assets."""
    from zfrog.marketplace import Marketplace

    return [asdict(asset) for asset in Marketplace(root=_scoped(request, "marketplace_dir")).list(kind=kind, query=query, tag=tag)]

@router.post("/marketplace/{asset_id}/install")
async def marketplace_install(asset_id: str, request: Request,
                              auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Install a published asset."""
    from zfrog.marketplace import Marketplace

    try:
        result = Marketplace(root=_scoped(request, "marketplace_dir")).install(asset_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(request, "marketplace.install", target=asset_id, kind=result.get("kind", ""))
    return result

@router.delete("/marketplace/{asset_id}/install")
async def marketplace_uninstall(asset_id: str, request: Request,
                                auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Remove an installed asset (the published copy stays)."""
    from zfrog.marketplace import Marketplace

    removed = Marketplace(root=_scoped(request, "marketplace_dir")).uninstall(asset_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Nothing installed for this asset")

    _audit(request, "marketplace.uninstall", target=asset_id)
    return {"removed": True}

@router.post("/marketplace/{asset_id}/rate")
async def marketplace_rate(asset_id: str, request: MarketRateRequest, http_request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Rate a marketplace asset."""
    from zfrog.marketplace import Marketplace

    try:
        asset = Marketplace(root=_scoped(http_request, "marketplace_dir")).rate(asset_id, request.score)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(http_request, "marketplace.rate", target=asset_id, score=request.score)
    return asdict(asset)

@router.post("/marketplace/sync")
async def marketplace_sync(payload: dict, http_request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Import the assets of a remote index."""
    from dataclasses import asdict

    from zfrog.marketplace_index import fetch_index, merge_index

    index_url = payload.get("index_url")
    index = payload.get("index")
    if not index_url and not isinstance(index, dict):
        raise HTTPException(status_code=400, detail="provide 'index_url' or 'index'")

    try:
        remote = index if isinstance(index, dict) else await fetch_index(index_url)
        result = merge_index(remote)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit(http_request, "marketplace.sync", target=index_url or "inline")
    return asdict(result)
