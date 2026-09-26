"""Tests for pipeline modules."""

import pytest
import tempfile
import zipfile
from pathlib import Path

from zfrog.pipeline.link_rewriter import rewrite_links, _rewrite_url
from zfrog.pipeline.privacy_cleaner import clean_privacy
from zfrog.pipeline.packager import package_zip


class TestLinkRewriter:
    """Tests for link rewriter."""
    
    @pytest.mark.asyncio
    async def test_rewrite_html_links(self, tmp_path):
        """Test rewriting links in HTML files."""
        # Create test HTML with absolute links
        html_content = """
        <html>
        <head>
            <link rel="stylesheet" href="https://example.com/styles.css">
        </head>
        <body>
            <a href="https://example.com/page2.html">Link</a>
            <img src="https://example.com/image.png">
            <script src="https://example.com/app.js"></script>
        </body>
        </html>
        """
        
        html_file = tmp_path / "index.html"
        html_file.write_text(html_content)
        
        # Create linked files
        (tmp_path / "page2.html").write_text("<p>Page 2</p>")
        (tmp_path / "styles.css").write_text("body { color: red; }")
        (tmp_path / "app.js").write_text("console.log('hello');")
        (tmp_path / "image.png").write_bytes(b'\x89PNG\r\n\x1a\n')  # Fake PNG header
        
        count = await rewrite_links(tmp_path)
        
        # Verify links were rewritten
        result = html_file.read_text()
        assert "./page2.html" in result
        assert "./styles.css" in result
        assert "./app.js" in result
        assert "https://example.com" not in result
    
    @pytest.mark.asyncio
    async def test_preserve_data_uris(self, tmp_path):
        """Test that data URIs are preserved."""
        html_content = '<html><body><img src="data:image/png;base64,abc123"></body></html>'
        html_file = tmp_path / "index.html"
        html_file.write_text(html_content)
        
        count = await rewrite_links(tmp_path)
        
        result = html_file.read_text()
        assert "data:image/png;base64,abc123" in result


class TestPrivacyCleaner:
    """Tests for privacy cleaner."""
    
    @pytest.mark.asyncio
    async def test_remove_google_analytics(self, tmp_path):
        """Test removing Google Analytics scripts."""
        html_content = """
        <html>
        <head>
            <script src="https://www.google-analytics.com/analytics.js"></script>
            <script>
                gtag('config', 'UA-12345-1');
            </script>
        </head>
        <body>
            <h1>Hello</h1>
        </body>
        </html>
        """
        
        html_file = tmp_path / "index.html"
        html_file.write_text(html_content)
        
        count = await clean_privacy(tmp_path)
        
        assert count >= 1
        result = html_file.read_text()
        assert "google-analytics.com" not in result
        assert "gtag(" not in result
    
    @pytest.mark.asyncio
    async def test_remove_facebook_pixel(self, tmp_path):
        """Test removing Facebook Pixel."""
        html_content = """
        <html>
        <body>
            <script>
                fbq('init', '123456789');
                fbq('track', 'PageView');
            </script>
        </body>
        </html>
        """
        
        html_file = tmp_path / "index.html"
        html_file.write_text(html_content)
        
        count = await clean_privacy(tmp_path)
        
        result = html_file.read_text()
        assert "fbq(" not in result


class TestPackager:
    """Tests for packager."""
    
    @pytest.mark.asyncio
    async def test_create_zip(self, tmp_path):
        """Test creating a ZIP archive."""
        # Create source directory with files
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "index.html").write_text("<html></html>")
        (source_dir / "styles.css").write_text("body {}")
        
        sub_dir = source_dir / "js"
        sub_dir.mkdir()
        (sub_dir / "app.js").write_text("console.log();")
        
        # Create ZIP
        output_path = tmp_path / "output" / "archive.zip"
        result = await package_zip(source_dir, output_path)
        
        assert result.exists()
        assert result == output_path
        
        # Verify ZIP contents
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert "index.html" in names
            assert "styles.css" in names
            assert "js/app.js" in names
