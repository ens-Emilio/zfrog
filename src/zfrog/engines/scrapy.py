"""Scrapy engine: the discovery and crawling motor of zfrog.

Answers "which pages exist on this site?" — it walks internal links and
pagination, reports the structure it found, and hands the URLs over so
Playwright can capture each one visually.
"""

import asyncio
import csv
import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.utils.http import create_client


class ScrapyEngine(EngineAdapter):
    """Discovery motor: crawls a site to map its pages and pull structured data.

    Features:
    - Maps internal links and follows pagination
    - Extracts text, links, images, metadata
    - Exports the map to JSON/CSV
    """
    
    name = "scrapy"
    
    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        """Execute structured data extraction.
        
        Args:
            job: Job configuration with extraction rules.
            output_dir: Directory to store output.
            on_progress: Optional progress callback.
            
        Returns:
            EngineResult with extracted data.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        logs = []
        extracted_data: list[dict[str, Any]] = []
        
        # Track visited URLs
        visited: set[str] = set()
        to_visit: list[str] = [str(job.url)]
        
        async with create_client() as client:
            pages_scraped = 0
            max_pages = job.max_depth * 10  # Estimate pages to scrape
            
            while to_visit and pages_scraped < max_pages:
                current_url = to_visit.pop(0)
                
                if current_url in visited:
                    continue
                
                visited.add(current_url)
                
                if on_progress:
                    on_progress(f"Scraping page {pages_scraped + 1}: {current_url[:50]}...")
                
                try:
                    response = await client.get(current_url)
                    response.raise_for_status()
                    
                    # Parse HTML
                    soup = BeautifulSoup(response.text, "lxml")
                    
                    # Extract data
                    page_data = self._extract_page_data(soup, current_url)
                    page_data["url"] = current_url
                    page_data["status_code"] = response.status_code
                    
                    extracted_data.append(page_data)
                    pages_scraped += 1
                    
                    logs.append(f"Extracted: {current_url} ({len(page_data.get('text', ''))} chars)")
                    
                    # Follow links if enabled
                    if job.follow_links:
                        links = self._extract_links(soup, current_url)
                        for link in links:
                            if link not in visited and self._should_follow(link, str(job.url)):
                                to_visit.append(link)
                    
                    # Rate limiting delay
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logs.append(f"Error scraping {current_url}: {e}")
                    continue
        
        # Save extracted data as JSON
        json_path = output_dir / "extracted_data.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(extracted_data, f, indent=2, ensure_ascii=False)
        
        # Save as CSV
        csv_path = output_dir / "extracted_data.csv"
        if extracted_data:
            self._save_as_csv(extracted_data, csv_path)
        
        files = [json_path, csv_path]
        total_bytes = sum(f.stat().st_size for f in files)
        
        if on_progress:
            on_progress(f"Extracted {len(extracted_data)} pages ({total_bytes:,} bytes)")
        
        return EngineResult(
            output_dir=output_dir,
            files=files,
            total_bytes=total_bytes,
            logs=logs,
        )
    
    def _extract_page_data(self, soup: BeautifulSoup, url: str) -> dict[str, Any]:
        """Extract structured data from a page."""
        # Title
        title = ""
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)
        
        # Meta description
        meta_desc = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            meta_desc = meta.get("content", "")
        
        # Main text content
        text = ""
        for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"]):
            text += tag.get_text(strip=True) + "\n"
        
        # Images
        images = []
        for img in soup.find_all("img", src=True):
            src = img.get("src")
            alt = img.get("alt", "")
            if src:
                images.append({"src": src, "alt": alt})
        
        # Links
        links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href")
            link_text = a.get_text(strip=True)
            if href:
                links.append({"href": href, "text": link_text})
        
        # Schema.org data
        schema_data = self._extract_schema_data(soup)
        
        return {
            "title": title,
            "meta_description": meta_desc,
            "text": text.strip(),
            "images": images,
            "links": links,
            "schema_data": schema_data,
        }
    
    def _extract_schema_data(self, soup: BeautifulSoup) -> dict | None:
        """Extract JSON-LD schema data."""
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                return data
            except (json.JSONDecodeError, TypeError):
                continue
        return None
    
    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Extract all links from a page."""
        links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href")
            full_url = urljoin(base_url, href)
            links.append(full_url)
        return links
    
    def _should_follow(self, url: str, base_url: str) -> bool:
        """Determine if a URL should be followed."""
        parsed_base = urlparse(base_url)
        parsed_url = urlparse(url)
        
        # Only follow same domain
        if parsed_url.netloc != parsed_base.netloc:
            return False
        
        # Skip anchors, javascript, mailto
        if parsed_url.scheme not in ("http", "https"):
            return False
        
        # Skip common non-content URLs
        skip_patterns = [".pdf", ".jpg", ".png", ".gif", ".zip", ".mp4", ".mp3"]
        if any(url.lower().endswith(p) for p in skip_patterns):
            return False
        
        return True
    
    def _save_as_csv(self, data: list[dict], csv_path: Path):
        """Save extracted data as CSV."""
        if not data:
            return
        
        # Flatten nested structures for CSV
        flat_data = []
        for item in data:
            flat_item = {
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "meta_description": item.get("meta_description", ""),
                "text": item.get("text", "")[:500],  # Truncate long text
                "image_count": len(item.get("images", [])),
                "link_count": len(item.get("links", [])),
                "has_schema": item.get("schema_data") is not None,
            }
            flat_data.append(flat_item)
        
        # Write CSV
        if flat_data:
            keys = flat_data[0].keys()
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(flat_data)
    
    def can_handle(self, probe: ProbeResult) -> bool:
        """Check if this engine should handle the job."""
        # Scrapy engine can handle most sites
        return True
