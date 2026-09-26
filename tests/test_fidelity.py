"""Tests for Fidelity Score and Compare engine."""

import pytest
from pathlib import Path

from zfrog.pipeline.fidelity import compute_fidelity, FidelityResult
from zfrog.engines.compare import CompareEngine
from zfrog.models import JobCreate


class TestFidelityScore:
    def test_identical_content(self):
        html = "<html><body>Hello World</body></html>"
        result = compute_fidelity(html, html)
        assert result.composite == 100.0

    def test_completely_different(self):
        orig = "<html><head><title>A</title></head><body>" + "alpha " * 50 + "</body></html>"
        clone = "<html><head><title>B</title></head><body>" + "bravo " * 50 + "</body></html>"
        result = compute_fidelity(orig, clone)
        assert result.composite < 70

    def test_partial_similarity(self):
        orig = "<html><head><title>Test</title></head><body><p>Hello</p></body></html>"
        clone = "<html><head><title>Test</title></head><body><p>Goodbye</p></body></html>"
        result = compute_fidelity(orig, clone)
        assert 50 < result.composite < 100

    def test_empty_content(self):
        result = compute_fidelity("", "")
        assert result.composite == 100.0

    def test_sub_scores_valid_range(self):
        result = compute_fidelity("<html></html>", "<html></html>")
        assert 0 <= result.visual <= 100
        assert 0 <= result.structural <= 100
        assert 0 <= result.text <= 100
        assert 0 <= result.assets <= 100

    def test_asset_coverage(self):
        from pathlib import Path
        orig_files = [Path("a.html"), Path("b.css"), Path("c.js")]
        clone_files = [Path("a.html"), Path("b.css")]
        result = compute_fidelity("<html></html>", "<html></html>", orig_files, clone_files)
        assert result.assets == pytest.approx(66.7, abs=0.1)


class TestCompareEngine:
    @pytest.mark.asyncio
    async def test_compare_same_url(self, static_page_url):
        """Test compare fetches and produces a valid report."""
        engine = CompareEngine()
        job = JobCreate(url=static_page_url, mode="compare")
        output_dir = Path("/tmp/test-compare")

        result = await engine.execute(job, output_dir)

        assert result.output_dir.exists()
        import json
        report = json.loads((output_dir / "comparison.json").read_text())
        assert "fidelity" in report
        assert 0 <= report["fidelity"]["composite"] <= 100
