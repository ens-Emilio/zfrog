"""Tests for probe module."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch

from zfrog.probe import probe_url, _detect_framework, _needs_js_rendering, _suggest_engine
from zfrog.models import ProbeResult
from zfrog.utils.http import create_client


class TestDetectFramework:
    """Tests for framework detection."""
    
    def test_nextjs_detection(self):
        html = '<html><head><meta name="generator" content="Next.js"></head></html>'
        assert _detect_framework(html, None) == "next"
    
    def test_nuxt_detection(self):
        html = '<div id="__nuxt"></div><script src="/_nuxt/runtime.js"></script>'
        assert _detect_framework(html, None) == "nuxt"
    
    def test_react_detection(self):
        html = '<div id="root"></div><script src="/static/js/bundle.js"></script>'
        assert _detect_framework(html, None) == "react"
    
    def test_vue_detection(self):
        html = '<div id="app"></div><script src="/js/chunk-vendors.js"></script>'
        assert _detect_framework(html, None) == "vue"
    
    def test_angular_detection(self):
        html = '<app-root ng-version="15.0.0"></app-root>'
        assert _detect_framework(html, None) == "angular"
    
    def test_static_site(self):
        html = '<html><head><title>Static</title></head><body><p>Hello</p></body></html>'
        assert _detect_framework(html, None) is None


class TestNeedsJsRendering:
    """Tests for JS rendering detection."""
    
    def test_simple_html(self):
        from bs4 import BeautifulSoup
        html = "<html><body><p>Hello World</p></body></html>"
        soup = BeautifulSoup(html, "lxml")
        assert _needs_js_rendering(html, soup) is False
    
    def test_spa_with_scripts(self):
        from bs4 import BeautifulSoup
        html = """
        <html><head>
        <script src="/js/chunk-vendors.js"></script>
        <script src="/js/app.js"></script>
        <script src="/js/runtime.js"></script>
        <script src="/js/main.js"></script>
        </head><body><div id="app"></div></body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        assert _needs_js_rendering(html, soup) is True


class TestSuggestEngine:
    """Tests for engine suggestion."""
    
    def test_spa_suggests_playwright(self):
        probe = ProbeResult(url="https://nextjs.com", is_spa=True)
        assert _suggest_engine(probe) == "playwright"
    
    def test_static_suggests_static_file(self):
        probe = ProbeResult(url="https://example.com", is_spa=False, status_code=200)
        assert _suggest_engine(probe) == "static_file"

    def test_unreadable_page_suggests_playwright(self):
        """A page the probe could not read may still render in a browser."""
        probe = ProbeResult(url="https://example.com", is_spa=False, status_code=None)
        assert _suggest_engine(probe) == "playwright"


@pytest.mark.asyncio
async def test_probe_example_com():
    """Integration test: probe a real static site."""
    async with create_client() as client:
        result = await probe_url("https://example.com", client)
        
        assert result.url == "https://example.com"
        assert result.is_spa is False
        assert result.has_js_rendering is False
        assert result.suggested_engine == "static_file"
        assert "text/html" in result.content_type
