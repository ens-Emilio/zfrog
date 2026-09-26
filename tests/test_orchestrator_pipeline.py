"""Tests for the orchestrator's optional post-processing steps."""

from pathlib import Path

import pytest

from zfrog.config import settings
from zfrog.models import JobCreate
from zfrog.orchestrator import run_job

PAGE = (
    "<html><head><title>Contato</title></head><body>"
    "<p>Fale com maria@empresa.com.br. CPF 529.982.247-25.</p>"
    "<script>var interno = 'nao@mexer.com';</script>"
    "</body></html>"
)


@pytest.fixture(autouse=True)
def _isolated_output(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(settings, "safety_enabled", False)


async def _run_singlepage(monkeypatch, page: str) -> str:
    """Run a singlepage job against a stubbed fetch and return the page text."""

    class FakeResponse:
        text = page
        content = page.encode("utf-8")
        headers = {"content-type": "text/html; charset=utf-8"}

        def raise_for_status(self):
            return None

    class FakeClient:
        async def get(self, url):
            return FakeResponse()

        async def aclose(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    def fake_create_client(*args, **kwargs):
        return FakeClient()

    monkeypatch.setattr("zfrog.engines.static_file.create_client", fake_create_client)

    result = await run_job(JobCreate(url="https://example.com", mode="singlepage"))

    output = Path(result.output_path).parent
    pages = [p for p in output.rglob("*.html") if p.is_file()]
    assert pages, "the job should have written a page"
    return "\n".join(p.read_text(encoding="utf-8") for p in pages)


@pytest.mark.asyncio
async def test_pipeline_keeps_page_content(monkeypatch):
    """The pipeline must not touch page text: there is no redaction step."""
    text = await _run_singlepage(monkeypatch, PAGE)

    assert "maria@empresa.com.br" in text
    assert "529.982.247-25" in text
