"""Tests for engine adapters."""

import pytest
import tempfile
from pathlib import Path

from zfrog.engines.wget import WgetEngine
from zfrog.engines.static_file import StaticFileEngine
from zfrog.engines.playwright import PlaywrightEngine
from zfrog.models import JobCreate, ProbeResult


class TestWgetEngine:
    """Tests for WgetEngine."""
    
    def test_can_handle_static_site(self):
        engine = WgetEngine()
        probe = ProbeResult(url="https://example.com", suggested_engine="wget")
        assert engine.can_handle(probe) is True
    
    def test_cannot_handle_spa(self):
        engine = WgetEngine()
        probe = ProbeResult(url="https://nextjs.com", suggested_engine="playwright")
        assert engine.can_handle(probe) is False
    
    def test_engine_name(self):
        engine = WgetEngine()
        assert engine.name == "wget"


class TestStaticFileEngine:
    """Tests for StaticFileEngine."""
    
    def test_can_handle_singlepage_mode(self):
        engine = StaticFileEngine()
        probe = ProbeResult(url="https://example.com", suggested_engine="static_file")
        assert engine.can_handle(probe) is True
    
    def test_engine_name(self):
        engine = StaticFileEngine()
        assert engine.name == "static_file"


class TestPlaywrightEngine:
    """Tests for PlaywrightEngine."""
    
    def test_can_handle_spa(self):
        engine = PlaywrightEngine()
        probe = ProbeResult(url="https://nextjs.com", suggested_engine="playwright")
        assert engine.can_handle(probe) is True
    
    def test_cannot_handle_static(self):
        engine = PlaywrightEngine()
        probe = ProbeResult(url="https://example.com", suggested_engine="wget")
        assert engine.can_handle(probe) is False
    
    def test_engine_name(self):
        engine = PlaywrightEngine()
        assert engine.name == "playwright"


class TestEngineRegistry:
    """Tests for engine registry."""
    
    def test_get_engine_wget(self):
        from zfrog.engines import get_engine
        engine = get_engine("wget")
        assert isinstance(engine, WgetEngine)
    
    def test_get_engine_static_file(self):
        from zfrog.engines import get_engine
        engine = get_engine("static_file")
        assert isinstance(engine, StaticFileEngine)
    
    def test_get_engine_playwright(self):
        from zfrog.engines import get_engine
        engine = get_engine("playwright")
        assert isinstance(engine, PlaywrightEngine)
    
    def test_get_engine_invalid(self):
        from zfrog.engines import get_engine
        with pytest.raises(ValueError):
            get_engine("invalid_engine")

class TestPdfEngine:
    """Tests for PdfEngine."""

    def test_pdf_engine_registered(self):
        from zfrog.engines import get_engine
        from zfrog.engines.pdf import PdfEngine
        assert isinstance(get_engine("pdf"), PdfEngine)

    def test_pdf_can_handle(self):
        from zfrog.engines.pdf import PdfEngine
        engine = PdfEngine()
        assert engine.can_handle(ProbeResult(url="https://example.com", suggested_engine="playwright")) is True
        assert engine.can_handle(ProbeResult(url="https://example.com", suggested_engine="wget")) is False

    def test_sanitize_pdf_name(self):
        from zfrog.engines.pdf import sanitize_pdf_name
        # Separators/spaces/! become "_"; the leading dots from "../../" are
        # stripped, so no traversal prefix survives.
        assert sanitize_pdf_name("../../evil name!") == "_.._evil_name_"
        assert sanitize_pdf_name("a/b\\c") == "a_b_c"

    def test_sanitize_pdf_name_traversal(self):
        from zfrog.engines.pdf import sanitize_pdf_name
        assert sanitize_pdf_name("..") == "index"
        assert sanitize_pdf_name("") == "index"

    def test_sanitize_pdf_name_keeps_dots(self):
        from zfrog.engines.pdf import sanitize_pdf_name
        assert sanitize_pdf_name("my.report.v2") == "my.report.v2"

class TestSummarizeEngine:
    """Tests for SummarizeEngine."""

    def test_summarize_engine_registered(self):
        from zfrog.engines import get_engine
        from zfrog.engines.summarize import SummarizeEngine
        engine = get_engine("summarize")
        assert isinstance(engine, SummarizeEngine)
        assert engine.can_handle(ProbeResult(url="https://example.com")) is True
