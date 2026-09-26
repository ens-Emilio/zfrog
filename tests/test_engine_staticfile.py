"""Smoke test: StaticFileEngine against locally created HTML files."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from zfrog.config import settings
from zfrog.engines.static_file import StaticFileEngine
from zfrog.models import JobCreate


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


async def test_staticfile_inlines_local_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path / "state")
    marker = "STATICFILE_SMOKE_MARKER_abc123"
    (tmp_path / "index.html").write_text(
        f"<html><head><title>Smoke</title></head>"
        f"<body><p>{marker}</p></body></html>",
        encoding="utf-8",
    )

    handler = partial(_QuietHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        engine = StaticFileEngine()
        result = await engine.execute(
            JobCreate(url=f"http://127.0.0.1:{port}/index.html"),
            tmp_path / "out",
        )
    finally:
        server.shutdown()
        server.server_close()

    assert engine.name == "static_file"
    assert result.total_bytes > 0
    assert len(result.files) == 1
    assert result.files[0].is_file()
    assert marker in result.files[0].read_text(encoding="utf-8")
