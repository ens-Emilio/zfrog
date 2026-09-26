"""WebSocket support for real-time job progress updates."""

import asyncio
import json
import time
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect
from redis import asyncio as aioredis

from zfrog.config import settings


#: Application close code for a rejected handshake (4401: unauthorised).
_WS_UNAUTHORISED = 4401
#: Application close code for a handshake from an origin we do not serve, or for a
#: job that belongs to someone else's workspace.
_WS_FORBIDDEN = 4403

#: The subprotocol a script client offers, and the one the server echoes back.
#: RFC 6455 lets the server select only a subprotocol the client proposed, so the
#: client must offer exactly this value.
WS_SUBPROTOCOL = "zfrog.v1"
#: Prefix a script client uses to carry its API key as a second subprotocol.
WS_KEY_PREFIX = "zfrog.key."


def _origin_allowed(websocket: WebSocket) -> bool:
    """Whether the handshake's ``Origin`` may open a socket.

    A browser always sends ``Origin`` on a WebSocket handshake, and it attaches
    the session cookie to that same handshake — so without this check any site a
    logged-in user visits could open a socket as them and read their job events.
    That is Cross-Site WebSocket Hijacking.

    Non-browser clients send no ``Origin``; they are not exempt, they just have to
    present a credential (see :func:`_may_watch`).
    """
    origin = websocket.headers.get("origin")
    if not origin:
        return True

    from zfrog.api import allowed_origins

    allowed = allowed_origins()
    if "*" in allowed:
        # The default local setup accepts any origin, matching the API's CORS
        # posture. Tightening one without the other would be theatre.
        return True
    return origin.rstrip("/") in allowed


async def _may_watch(websocket: WebSocket, job_id: str) -> bool:
    """Whether this caller may receive the events of this job.

    Closing before ``accept()`` turns the handshake into an HTTP 403, so a
    rejected caller never receives a single event.

    Three things are checked: the origin (browsers only), that the credential may
    read at all, and that the job sits in the caller's own workspace — otherwise a
    valid credential for one organization could watch another's jobs by guessing
    an id.

    Credentials, in order: the ``Authorization``/``X-API-Key`` header, the session
    cookie, or an API key carried as the ``zfrog.key.<secret>`` subprotocol. A
    browser cannot set headers on a WebSocket, which is exactly why it uses the
    cookie; a script has no cookie, and a subprotocol is a header, so its key is
    never written to a reverse proxy's access log.
    """
    from zfrog.api import ACTION_READ
    from zfrog.auth import authorize_request
    from zfrog.orchestrator import get_job

    if not _origin_allowed(websocket):
        await websocket.close(code=_WS_FORBIDDEN)
        return False

    offered = websocket.scope.get("subprotocols") or []
    subprotocol_key = next(
        (value[len(WS_KEY_PREFIX) :] for value in offered if value.startswith(WS_KEY_PREFIX)),
        "",
    )

    credentials = dict(websocket.headers)
    if subprotocol_key:
        credentials["x-api-key"] = subprotocol_key

    decision = authorize_request(credentials, websocket.cookies, ACTION_READ)
    if not decision.allowed:
        await websocket.close(code=_WS_UNAUTHORISED)
        return False

    # With a credential in play, the job must be visible AND in the caller's own
    # workspace. An unknown job id is denied rather than streamed: we cannot
    # verify who owns it, and failing open on an authorisation check would also
    # mean that a Redis outage — which makes `get_job` fall back to per-process
    # memory — silently turns into "any job id is allowed".
    job = get_job(job_id)
    if decision.via and (job is None or (job.org or "") != decision.org):
        await websocket.close(code=_WS_FORBIDDEN)
        return False

    return True


async def job_progress_ws(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for streaming job progress events.
    
    Listens to Redis pub/sub channel `job:{job_id}:events` and forwards
    messages to the connected WebSocket client. Sends a ping every 30s
    to keep the connection alive.
    
    Args:
        websocket: The FastAPI WebSocket connection.
        job_id: The job ID to subscribe to.
    """
    if not await _may_watch(websocket, job_id):
        return

    # A client that offered the subprotocol requires the server to select one of
    # the values it proposed; answering without one makes the browser fail the
    # connection. Clients that offered none are accepted as before.
    offered = websocket.scope.get("subprotocols") or []
    await websocket.accept(subprotocol=WS_SUBPROTOCOL if WS_SUBPROTOCOL in offered else None)
    
    redis_client = None
    pubsub = None
    
    try:
        redis_client = aioredis.from_url(settings.redis_url)
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"job:{job_id}:events")
        
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "job_id": job_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        
        last_ping = time.monotonic()
        ping_interval = 30  # seconds
        
        while True:
            # Calculate timeout for next heartbeat
            elapsed = time.monotonic() - last_ping
            remaining = ping_interval - elapsed
            
            if remaining <= 0:
                # Send heartbeat ping
                try:
                    await websocket.send_json({
                        "type": "ping",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    break
                last_ping = time.monotonic()
                remaining = ping_interval
            
            # Wait for Redis message or timeout (for heartbeat)
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=min(remaining, 0.5),  # Short poll for responsiveness
                    ),
                    timeout=min(remaining, 0.5),
                )
            except asyncio.TimeoutError:
                # No message within timeout, check heartbeat
                elapsed = time.monotonic() - last_ping
                if elapsed >= ping_interval:
                    try:
                        await websocket.send_json({
                            "type": "ping",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        last_ping = time.monotonic()
                    except Exception:
                        break
                continue
            
            if message is None:
                # No message received, continue loop
                elapsed = time.monotonic() - last_ping
                if elapsed >= ping_interval:
                    try:
                        await websocket.send_json({
                            "type": "ping",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        last_ping = time.monotonic()
                    except Exception:
                        break
                continue
            
            # Process Redis message
            try:
                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()
                
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                
                event = json.loads(data)
                
                # Ensure required fields
                if "type" not in event:
                    event["type"] = "unknown"
                if "timestamp" not in event:
                    event["timestamp"] = datetime.now(timezone.utc).isoformat()
                
                # Send to WebSocket client
                await websocket.send_json(event)
                
                # If job completed/failed/cancelled, send final message and close
                if event["type"] in ("completed", "failed", "cancelled", "error"):
                    break
                    
            except json.JSONDecodeError:
                # Invalid JSON, skip
                continue
            except Exception:
                # Connection might be closed
                break
                
    except WebSocketDisconnect:
        # Client disconnected normally
        pass
    except Exception:
        # Unexpected error
        try:
            await websocket.close()
        except Exception:
            pass
    finally:
        # Cleanup Redis resources
        if pubsub:
            try:
                await pubsub.unsubscribe(f"job:{job_id}:events")
                await pubsub.close()
            except Exception:
                pass
        if redis_client:
            try:
                await redis_client.close()
            except Exception:
                pass