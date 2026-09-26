"""StaticFile engine: the light motor of zfrog.

For pages that render without JavaScript — blogs, docs, simple institutional
sites — where starting a browser would only cost time.
"""

import base64
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.utils.http import create_client


class StaticFileEngine(EngineAdapter):
    """Light motor: inlines a page that renders without JavaScript into a
    single self-contained HTML file."""
    
    name = "static_file"
    
    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        """Fetch and inline a webpage into a single HTML file.
        
        Args:
            job: Job configuration.
            output_dir: Directory to store output.
            on_progress: Optional progress callback.
            
        Returns:
            EngineResult with inlined HTML file.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        logs = []
        
        async with create_client() as client:
            # Fetch the main page
            if on_progress:
                on_progress("Fetching HTML...")
            
            response = await client.get(str(job.url))
            response.raise_for_status()
            
            # Decode with proper encoding detection
            content = response.content
            content_type_header = response.headers.get("content-type", "")
            encoding = None
            if "charset=" in content_type_header:
                encoding = content_type_header.split("charset=")[-1].strip().split(";")[0]
            if not encoding:
                if content.startswith(b'\xef\xbb\xbf'):
                    encoding = 'utf-8-sig'
                elif content.startswith(b'\xff\xfe'):
                    encoding = 'utf-16-le'
                elif content.startswith(b'\xfe\xff'):
                    encoding = 'utf-16-be'
                else:
                    encoding = 'utf-8'
            try:
                html = content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                html = content.decode('latin-1')
            logs.append(f"Fetched {len(content):,} bytes (encoding={encoding})")
            
            soup = BeautifulSoup(html, "lxml")
            base_url = str(job.url)
            
            # Inline CSS stylesheets
            if on_progress:
                on_progress("Inlining CSS...")
            
            for link in soup.find_all("link", rel="stylesheet"):
                href = link.get("href")
                if href:
                    css_url = urljoin(base_url, href)
                    try:
                        css_response = await client.get(css_url)
                        css_response.raise_for_status()
                        css_content = css_response.content
                        css_ct = css_response.headers.get("content-type", "")
                        css_enc = "utf-8"
                        if "charset=" in css_ct:
                            css_enc = css_ct.split("charset=")[-1].strip().split(";")[0]
                        try:
                            css_text = css_content.decode(css_enc)
                        except (UnicodeDecodeError, LookupError):
                            css_text = css_content.decode('latin-1')
                        style_tag = soup.new_tag("style")
                        style_tag.string = css_text
                        link.replace_with(style_tag)
                        logs.append(f"Inlined CSS: {css_url}")
                    except Exception as e:
                        logs.append(f"Failed to inline CSS {css_url}: {e}")
            
            # Inline JavaScript
            if on_progress:
                on_progress("Inlining JavaScript...")
            
            for script in soup.find_all("script", src=True):
                src = script.get("src")
                if src:
                    js_url = urljoin(base_url, src)
                    try:
                        js_response = await client.get(js_url)
                        js_response.raise_for_status()
                        js_content = js_response.content
                        js_ct = js_response.headers.get("content-type", "")
                        js_enc = "utf-8"
                        if "charset=" in js_ct:
                            js_enc = js_ct.split("charset=")[-1].strip().split(";")[0]
                        try:
                            js_text = js_content.decode(js_enc)
                        except (UnicodeDecodeError, LookupError):
                            js_text = js_content.decode('latin-1')
                        new_script = soup.new_tag("script")
                        new_script.string = js_text
                        script.replace_with(new_script)
                        logs.append(f"Inlined JS: {js_url}")
                    except Exception as e:
                        logs.append(f"Failed to inline JS {js_url}: {e}")
            
            # Inline images as base64
            if on_progress:
                on_progress("Inlining images...")
            
            for img in soup.find_all("img", src=True):
                src = img.get("src")
                if src and not src.startswith("data:"):
                    img_url = urljoin(base_url, src)
                    try:
                        img_response = await client.get(img_url)
                        img_response.raise_for_status()
                        content_type = img_response.headers.get("content-type", "image/png")
                        b64_data = base64.b64encode(img_response.content).decode("utf-8")
                        img["src"] = f"data:{content_type};base64,{b64_data}"
                        logs.append(f"Inlined image: {img_url}")
                    except Exception as e:
                        logs.append(f"Failed to inline image {img_url}: {e}")
            
            # Handle meta og:image and other external resources
            for meta in soup.find_all("meta", attrs={"property": "og:image"}):
                content = meta.get("content")
                if content and not content.startswith("data:"):
                    img_url = urljoin(base_url, content)
                    try:
                        img_response = await client.get(img_url)
                        img_response.raise_for_status()
                        content_type = img_response.headers.get("content-type", "image/png")
                        b64_data = base64.b64encode(img_response.content).decode("utf-8")
                        meta["content"] = f"data:{content_type};base64,{b64_data}"
                    except Exception:
                        pass
        
        # Write the final HTML
        output_file = output_dir / "single_page.html"
        output_file.write_text(str(soup), encoding="utf-8")
        
        files = [output_file]
        total_bytes = output_file.stat().st_size
        
        if on_progress:
            on_progress(f"Created single page: {total_bytes:,} bytes")
        
        return EngineResult(
            output_dir=output_dir,
            files=files,
            total_bytes=total_bytes,
            logs=logs,
        )
    
    def can_handle(self, probe: ProbeResult) -> bool:
        """Check if this engine should handle the job."""
        return probe.suggested_engine == "static_file"
