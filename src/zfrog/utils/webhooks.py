"""Webhook notification utilities."""

import logging
import asyncio
import uuid
from typing import Callable, Any
from pydantic import BaseModel, Field, HttpUrl

from zfrog.models import JobResult
logger = logging.getLogger(__name__)


class WebhookConfig(BaseModel):
    """Webhook configuration."""
    url: HttpUrl
    events: list[str] = ["job.completed", "job.failed"]
    secret: str | None = None
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])


# Registered webhooks, kept in a process-wide list AND mirrored to Redis.
#
# A deployment runs more than one process (API workers, Celery workers). A webhook
# registered in one must be visible to the process that finishes the job, or
# `job.completed` fires for nobody. Redis is the shared store; when it is
# unreachable the local list still works, which is what local use relies on.
_webhooks: list[WebhookConfig] = []

_REDIS_KEY = "zfrog:webhooks"

def _redis():  # type: ignore[no-untyped-def]
    """A Redis client for the shared registry, or None when unavailable."""
    try:
        from zfrog.storage.redis_client import get_sync_client
        client = get_sync_client()
        client.ping()
        return client
    except Exception:
        return None

def _persist() -> None:
    """Mirror the in-process list to Redis; a failure is not fatal."""
    client = _redis()
    if client is None:
        return

    try:
        import json

        client.set(_REDIS_KEY, json.dumps([hook.model_dump(mode="json") for hook in _webhooks]))
    except Exception:
        pass

def _shared_webhooks() -> list[WebhookConfig]:
    """The webhooks every process can see: Redis when available, else local."""
    client = _redis()
    if client is None:
        return list(_webhooks)

    try:
        import json

        raw = client.get(_REDIS_KEY)
        if not raw:
            # First reader after a deploy seeds Redis with the local registrations.
            _persist()
            return list(_webhooks)
        return [WebhookConfig(**item) for item in json.loads(raw)]
    except Exception:
        return list(_webhooks)

def register_webhook(config: WebhookConfig):
    """Register a webhook for notifications."""
    _webhooks.append(config)
    _persist()

def list_webhooks() -> list[WebhookConfig]:
    """Return the registered webhooks, shared across processes when Redis is up."""
    return _shared_webhooks()

def remove_webhook(webhook_id: str) -> bool:
    """Remove a webhook by id; returns whether anything was removed."""
    current = _shared_webhooks()
    remaining = [hook for hook in current if hook.id != webhook_id]
    if len(remaining) == len(current):
        return False

    _webhooks[:] = remaining
    _persist()
    return True

def clear_webhooks():
    """Clear all registered webhooks."""
    _webhooks.clear()
    _persist()


async def notify_webhooks(event: str, data: dict[str, Any]):
    """Send webhook notifications for an event.
    
    Args:
        event: Event type (e.g., "job.completed").
        data: Event data.
    """
    import httpx
    import hmac
    import hashlib
    import json
    
    for webhook in _webhooks:
        if event not in webhook.events:
            continue
        
        try:
            payload = {
                "event": event,
                "data": data,
                "timestamp": asyncio.get_event_loop().time(),
            }
            
            # Sign payload if secret is set
            headers = {"Content-Type": "application/json"}
            body = json.dumps(payload)
            
            if webhook.secret:
                signature = hmac.new(
                    webhook.secret.encode(),
                    body.encode(),
                    hashlib.sha256
                ).hexdigest()
                headers["X-Webhook-Signature"] = f"sha256={signature}"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    str(webhook.url),
                    content=body,
                    headers=headers,
                    timeout=10,
                )
            _record_delivery(webhook, event, "ok", f"HTTP {response.status_code}")
        except Exception as e:
            _record_delivery(webhook, event, "error", str(e))
            logger.warning("Webhook notification failed: %s", e)

def _record_delivery(webhook: WebhookConfig, event: str, outcome: str, detail: str) -> None:
    """Note a delivery attempt in the audit log.

    Best effort: the audit module already swallows its own failures, and a
    missing audit log must never affect the notification itself.
    """
    try:
        from zfrog.utils.audit import AuditLog

        AuditLog().write(
            action="webhook.deliver",
            actor="zfrog",
            target=str(webhook.url),
            outcome=outcome,
            detail=detail,
            metadata={"event": event, "webhook_id": webhook.id},
        )
    except Exception:
        pass


async def notify_job_completed(result: JobResult):
    """Send notification for job completion."""
    await notify_webhooks("job.completed", {
        "job_id": result.job_id,
        "output_path": result.output_path,
        "files_count": result.files_count,
        "total_size_bytes": result.total_size_bytes,
        "engine_used": result.engine_used,
        "duration_seconds": result.duration_seconds,
    })


async def notify_job_failed(job_id: str, error: str):
    """Send notification for job failure."""
    await notify_webhooks("job.failed", {
        "job_id": job_id,
        "error": error,
    })