"""FastAPI application for Zfrog — package entrypoint."""

from zfrog.api._shared import (
    ACTION_ADMIN,
    ACTION_JOB_CANCEL,
    ACTION_JOB_CREATE,
    ACTION_KEY_MANAGE,
    ACTION_READ,
    ACTION_SCHEDULE_MANAGE,
    ACTION_VERSION_MANAGE,
    ACTION_WORKFLOW_MANAGE,
    UTC,
    JobResponse,
    JobResultResponse,
    Path,
    ProbeResponse,
    WebhookRequest,
    _audit,
    _caller_org,
    _catalog,
    _consume_login,
    _login_redis,
    _pending_logins,
    _purge_expired_logins,
    _reject_traversal,
    _remember_login,
    _scoped,
    _workspace,
    allowed_origins,
    app,
    auth_dependency,
    datetime,
    logger,
    time,
    timezone,
)

# Re-export create_job for tests that import it directly from zfrog.api
try:
    from zfrog.api.routers.jobs import create_job  # noqa: F401
except ImportError:
    pass

from zfrog.api.routers.catalog import router as _catalog_router
from zfrog.api.routers.jobs import router as _jobs_router
from zfrog.api.routers.search import router as _search_router
from zfrog.api.routers.system import router as _system_router
from zfrog.api.routers.workspaces import router as _workspaces_router

for _r in (_jobs_router, _catalog_router, _search_router, _workspaces_router, _system_router):
    for _route in _r.routes:
        app.router.routes.append(_route)
    app.router._mark_routes_changed()

__all__ = [
    "app",
    "create_job",
    "allowed_origins",
    "auth_dependency",
    "logger",
    "ACTION_READ",
    "ACTION_JOB_CREATE",
    "ACTION_JOB_CANCEL",
    "ACTION_KEY_MANAGE",
    "ACTION_SCHEDULE_MANAGE",
    "ACTION_VERSION_MANAGE",
    "ACTION_WORKFLOW_MANAGE",
    "ACTION_ADMIN",
    "JobResponse",
    "ProbeResponse",
    "JobResultResponse",
    "WebhookRequest",
    "_consume_login",
    "_pending_logins",
    "_remember_login",
    "_audit",
    "_caller_org",
    "_catalog",
    "_login_redis",
    "_purge_expired_logins",
    "_reject_traversal",
    "_scoped",
    "_workspace",
    "UTC",
    "datetime",
    "time",
    "timezone",
    "Path",
]
