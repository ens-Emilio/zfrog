"""Smoke test: WgetEngine against the local fixture server."""

from zfrog.config import settings
from zfrog.engines.wget import WgetEngine
from zfrog.models import JobCreate


async def test_wget_mirrors_fixture_page(static_page_url, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path / "state")
    engine = WgetEngine()
    assert engine.name == "wget"

    job = JobCreate(
        url=static_page_url,
        max_depth=1,
        max_pages=5,
        delay_ms=0,
        respect_robots=False,
    )
    result = await engine.execute(job, tmp_path / "out")

    assert result.files, "expected wget to download at least one file"
    assert all(p.is_file() for p in result.files)
    sizes = [p.stat().st_size for p in result.files]
    assert all(s > 0 for s in sizes), "downloaded files must be non-empty"
    assert result.total_bytes > 0
    assert result.total_bytes == sum(sizes)
