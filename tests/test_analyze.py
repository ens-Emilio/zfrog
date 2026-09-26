"""Tests for the Analyze engine."""

import pytest
from pathlib import Path

from zfrog.engines.analyze import AnalyzeEngine, AnalyzeResult
from zfrog.models import JobCreate


@pytest.mark.asyncio
async def test_analyze_static_page(static_page_url):
    """Test analyze against a known static page."""
    engine = AnalyzeEngine()
    job = JobCreate(url=static_page_url, mode="analyze")
    output_dir = Path("/tmp/test-analyze-static")

    result = await engine.execute(job, output_dir)

    assert result.output_dir.exists()
    assert len(result.files) >= 2  # analysis.json + analysis.md

    # Verify JSON report
    report_path = output_dir / "analysis.json"
    assert report_path.exists()
    import json
    report = json.loads(report_path.read_text())
    assert "score" in report
    assert 0 <= report["score"] <= 100
    assert report["content"]["word_count"] > 0
    assert report["seo"]["has_title"] is True
    assert report["seo"]["has_h1"] is True


@pytest.mark.asyncio
async def test_analyze_empty_page():
    """Test analyze against a non-existent port (graceful degradation)."""
    engine = AnalyzeEngine()
    job = JobCreate(url="http://127.0.0.1:1/nonexistent", mode="analyze")
    output_dir = Path("/tmp/test-analyze-empty")

    result = await engine.execute(job, output_dir)

    assert result.output_dir.exists()
    assert len(result.files) >= 2
    # Score should be low but not crash
    import json
    report = json.loads((output_dir / "analysis.json").read_text())
    assert 0 <= report["score"] <= 100


def test_analyze_can_handle():
    """Test that analyze engine can handle any probe."""
    engine = AnalyzeEngine()
    from zfrog.models import ProbeResult
    assert engine.can_handle(ProbeResult(url="https://any.com")) is True
