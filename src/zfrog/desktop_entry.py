"""Sidecar entrypoint for Tauri desktop.

Spawned by ``src-tauri/src/lib.rs`` as an ``externalBin``.  Receives an
ephemeral port, auth token and data dir from Rust, binds only on loopback,
and enforces the token on every request except ``/health``.

Usage (called by Tauri, not by humans)::

    zfrog-api --port 54321 --auth-token <hex> --data-dir ~/.local/share/zfrog
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _resolve_data_dir(cli_value: str | None) -> Path:
    if cli_value:
        return Path(cli_value)
    if env := os.environ.get("ZFROG_DATA_DIR"):
        if env.strip():
            return Path(env)
    if sys.platform == "win32":
        if appdata := os.environ.get("APPDATA"):
            return Path(appdata) / "zfrog"
    if xdg := os.environ.get("XDG_DATA_HOME"):
        if xdg.strip():
            return Path(xdg) / "zfrog"
    home = os.environ.get("HOME") or str(Path.home())
    return Path(home) / ".local" / "share" / "zfrog"


def main() -> None:
    parser = argparse.ArgumentParser(description="zfrog desktop sidecar")
    parser.add_argument("--port", type=int, required=True, help="Loopback port chosen by Tauri")
    parser.add_argument("--auth-token", required=True, help="Ephemeral bearer token (64 hex chars)")
    parser.add_argument("--data-dir", default=None, help="State directory (XDG/APPDATA)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (must be loopback)")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost"):
        parser.error("--host must be 127.0.0.1 or localhost (sidecar is loopback-only)")
    data_dir = _resolve_data_dir(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    # Isolate Playwright's browser cache to the XDG cache dir so a fresh
    # install doesn't pollute the user's default ``~/.cache/ms-playwright``
    # (and a later ``playwright install`` outside zfrog can't break desktop).
    # This is the ``~/.cache/zfrog/browsers`` of PLANO-TAURI.md §4.1.
    if sys.platform == "win32":
        browsers_path = data_dir / "browsers"
    else:
        _cache_base = os.environ.get("XDG_CACHE_HOME")
        if _cache_base and _cache_base.strip():
            browsers_path = Path(_cache_base) / "zfrog" / "browsers"
        else:
            browsers_path = Path.home() / ".cache" / "zfrog" / "browsers"
    browsers_path.mkdir(parents=True, exist_ok=True)
    # Only set if the caller didn't already pin it.
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers_path))
    os.environ["ZFROG_DATA_DIR"] = str(data_dir)
    os.environ["ZFROG_DESKTOP_TOKEN"] = args.auth_token
    import uvicorn
    from fastapi import Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    from zfrog.api import app

    @app.middleware("http")
    async def _desktop_auth(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path in ("/health", "/openapi.json", "/docs", "/redoc"):
            return await call_next(request)
        if request.url.path.startswith("/ws/"):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        presented = auth.removeprefix("Bearer ").strip() if auth else ""
        if not presented:
            presented = request.headers.get("x-zfrog-desktop-token", "").strip()
        if presented != args.auth_token:
            return JSONResponse(status_code=401, content={"detail": "Invalid desktop token"})
        return await call_next(request)

    # Patch ws.py so the desktop token carried as a WebSocket subprotocol
    # (zfrog.key.<token>) is accepted even when auth_enabled is off.
    try:
        import zfrog.ws as _ws

        _orig_may_watch = _ws._may_watch  # type: ignore[attr-defined]

        async def _desktop_may_watch(websocket, job_id: str) -> bool:  # type: ignore[no-untyped-def]
            offered = websocket.scope.get("subprotocols") or []
            subprotocol_key = next(
                (v[len(_ws.WS_KEY_PREFIX) :] for v in offered if v.startswith(_ws.WS_KEY_PREFIX)),
                "",
            )
            if subprotocol_key and subprotocol_key == args.auth_token:
                if not _ws._origin_allowed(websocket):  # type: ignore[attr-defined]
                    await websocket.close(code=_ws._WS_FORBIDDEN)  # type: ignore[attr-defined]
                    return False
                return True
            return await _orig_may_watch(websocket, job_id)

        _ws._may_watch = _desktop_may_watch  # type: ignore[attr-defined]

        _orig_origin_allowed = _ws._origin_allowed  # type: ignore[attr-defined]

        def _desktop_origin_allowed(websocket) -> bool:  # type: ignore[no-untyped-def]
            origin = websocket.headers.get("origin") or ""
            if origin.startswith("tauri://") or origin.startswith("https://tauri.localhost"):
                return True
            return _orig_origin_allowed(websocket)

        _ws._origin_allowed = _desktop_origin_allowed  # type: ignore[attr-defined]
    except Exception:
        pass

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "tauri://localhost",
            "https://tauri.localhost",
            "http://tauri.localhost",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
