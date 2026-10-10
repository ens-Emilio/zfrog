"""API router: catalog."""

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from zfrog.api._shared import (
    ACTION_ADMIN,
    ACTION_READ,
    ACTION_VERSION_MANAGE,
    ACTION_WORKFLOW_MANAGE,
    CardNoteRequest,
    CardTagsRequest,
    CatalogSearchRequest,
    SelectorPreviewRequest,
    WorkflowCreateRequest,
    _audit,
    _catalog,
    _scoped,
    auth_dependency,
)  # noqa: F401
from zfrog.auth import AuthDecision
from zfrog.config import settings

router = APIRouter()

@router.get("/catalog")
async def list_catalog(
    request: Request,
    tag: str | None = None,
    color: str | None = None,
    site: str | None = None,
    since: float | None = None,
    until: float | None = None,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List captured design references, newest first. All filters combine with AND."""
    catalog = _catalog(request)
    cards = catalog.list(
        tag=tag, color=color, site=site, since=since, until=until,
        query=query, limit=limit, offset=offset,
    )
    return {
        "total": catalog.count(),
        "cards": [card.to_dict() for card in cards],
    }

@router.get("/catalog/tags")
async def catalog_tags(request: Request,
                       auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Every tag in the catalog with how many references use it."""
    return [{"tag": tag, "count": count} for tag, count in _catalog(request).tags()]

@router.get("/catalog/colors")
async def catalog_colors(request: Request, limit: int = 60,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Every colour in the catalog with how many references carry it."""
    return [{"hex": hex_color, "count": count} for hex_color, count in _catalog(request).colors(limit)]

@router.get("/catalog/sites")
async def catalog_sites(request: Request,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Every captured site with its reference count."""
    return [{"site": site, "count": count} for site, count in _catalog(request).sites()]

@router.post("/catalog/search")
async def catalog_search(body: CatalogSearchRequest, request: Request,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Search the catalog by description ("dark layouts with rounded cards")."""
    from zfrog.visual_search import search_descriptive

    hits = await search_descriptive(_catalog(request), body.query, limit=body.limit)
    return {
        "query": body.query,
        "hits": [
            {"score": round(hit.score, 4), **hit.card.to_dict()} for hit in hits
        ],
    }

@router.post("/catalog/reindex")
async def catalog_reindex(request: Request, force: bool = False,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_VERSION_MANAGE))):
    """Build the embeddings of the catalog, so the descriptive search can rank by vector.

    Without a configured embedding model this indexes nothing and says why, rather than
    failing: the search still answers by word overlap, and a deployment should be able
    to tell "nothing to index", "already indexed" and "the model is broken" apart.
    """
    from zfrog.visual_search import embed_catalog

    result = await embed_catalog(_catalog(request), force=force)
    if result.indexed:
        _audit(request, "catalog.reindex", detail=f"{result.indexed} reference(s)")
    return {"indexed": result.indexed, "reason": result.reason}

@router.get("/catalog/{card_id}")
async def get_catalog_card(card_id: str, request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """One reference, by id or by an unambiguous id prefix."""
    catalog = _catalog(request)
    card = catalog.get(card_id)
    if card is None:
        matches = [c for c in catalog.list(limit=1000) if c.id.startswith(card_id)]
        if len(matches) == 1:
            card = matches[0]
        elif len(matches) > 1:
            raise HTTPException(status_code=409, detail=f"ambiguous prefix: {len(matches)} references")
    if card is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    return card.to_dict()

@router.get("/catalog/{card_id}/screenshot")
async def catalog_screenshot(card_id: str, request: Request,
                             auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Serve the screenshot of a reference.

    The stored path is relative to the media root and is resolved against it with the
    result checked to stay inside — a catalog row is data, and data must not be able
    to name a file outside the tree it belongs to.
    """
    card = _catalog(request).get(card_id)
    if card is None or not card.screenshot:
        raise HTTPException(status_code=404, detail="Screenshot not found")

    root = Path(settings.catalog_media_dir).resolve()
    target = (root / card.screenshot).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found")

    return FileResponse(target)

@router.post("/catalog/{card_id}/tags")
async def catalog_set_tags(card_id: str, body: CardTagsRequest, request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_VERSION_MANAGE))):
    """Add tags to a reference, or replace the whole list."""
    catalog = _catalog(request)
    if catalog.get(card_id) is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    tags = catalog.tag(card_id, body.tags, replace=body.replace)
    _audit(request, "catalog.tag", target=card_id, detail=",".join(tags))
    return {"id": card_id, "tags": tags}

@router.post("/catalog/{card_id}/note")
async def catalog_set_note(card_id: str, body: CardNoteRequest, request: Request,
                           auth: AuthDecision = Depends(auth_dependency(ACTION_VERSION_MANAGE))):
    """Set the note of a reference."""
    catalog = _catalog(request)
    if catalog.get(card_id) is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    catalog.note(card_id, body.note)
    return {"id": card_id, "note": body.note}

@router.delete("/catalog/{card_id}")
async def catalog_delete(card_id: str, request: Request,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_VERSION_MANAGE))):
    """Remove a reference from the catalog. The captured files stay on disk."""
    if not _catalog(request).delete(card_id):
        raise HTTPException(status_code=404, detail="Reference not found")
    _audit(request, "catalog.delete", target=card_id)
    return {"id": card_id, "deleted": True}

@router.get("/sessions")
async def list_sessions(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List saved login sessions."""
    from zfrog.session import SessionStore

    return SessionStore(root=_scoped(request, "sessions_dir")).list()

@router.delete("/sessions/{domain}")
async def delete_session(request: Request, domain: str,
                         auth: AuthDecision = Depends(auth_dependency(ACTION_ADMIN))):
    """Delete a saved login session.

    A session file holds live cookies for a site, so removing one is credential
    management: listing them stays on `read:jobs`, deleting needs an admin.
    """
    from zfrog.session import SessionStore

    if not SessionStore(root=_scoped(request, "sessions_dir")).delete(domain):
        raise HTTPException(status_code=404, detail="Session not found")

    return {"removed": domain}

@router.get("/workflows")
async def list_workflows(request: Request, 
    auth: AuthDecision = Depends(auth_dependency(ACTION_READ)),
):
    """List saved workflows."""
    from zfrog.workflows import WorkflowStore

    return [asdict(workflow) for workflow in WorkflowStore(root=_scoped(request, "workflows_dir")).list()]

@router.post("/workflows")
async def save_workflow(request: WorkflowCreateRequest, http_request: Request,
                        auth: AuthDecision = Depends(auth_dependency(ACTION_WORKFLOW_MANAGE))):
    """Create or replace a workflow."""
    from zfrog.workflows import WorkflowStore

    steps = [
        {
            "type": step.type,
            "params": step.params,
            **({"id": step.id} if step.id else {}),
            **({"needs": step.needs} if step.needs is not None else {}),
        }
        for step in request.steps
    ]
    try:
        workflow = WorkflowStore(root=_scoped(http_request, "workflows_dir")).save(request.name, steps)
    except ValueError as e:
        _audit(http_request, "workflow.save", target=request.name, outcome="error", detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    _audit(
        http_request,
        "workflow.save",
        target=request.name,
        workflow=workflow.id,
        steps=len(workflow.steps),
    )
    return asdict(workflow)

@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str, request: Request,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_WORKFLOW_MANAGE))):
    """Delete a workflow."""
    from zfrog.workflows import WorkflowStore

    if not WorkflowStore(root=_scoped(request, "workflows_dir")).remove(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")

    _audit(request, "workflow.delete", target=workflow_id)
    return {"removed": workflow_id}

@router.post("/workflows/{workflow_id}/run")
async def run_saved_workflow(workflow_id: str, request: Request,
                             auth: AuthDecision = Depends(auth_dependency(ACTION_WORKFLOW_MANAGE))):
    """Run a saved workflow."""
    from zfrog.workflows import WorkflowStore, run_workflow

    workflow = WorkflowStore(root=_scoped(request, "workflows_dir")).get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    _audit(request, "workflow.run", target=workflow.name, workflow=workflow_id)
    result = await run_workflow(workflow)
    return asdict(result)

@router.get("/extract/page")
async def extract_page(url: str,
                    auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Fetch a page, sanitised for rendering in the dashboard iframe."""
    from zfrog.selector import fetch_page

    try:
        return await fetch_page(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/extract/preview")
async def extract_preview(request: SelectorPreviewRequest,
                          auth: AuthDecision = Depends(auth_dependency(ACTION_READ))):
    """Preview what a CSS selector matches on a page."""
    from zfrog.selector import build_selector_preview, fetch_page

    try:
        page = await fetch_page(request.url)
        preview = build_selector_preview(page["html"], request.selector)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"url": request.url, "selector": request.selector, **preview}
