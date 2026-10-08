"""Analyze engine — technical audit of a website.

Runs multiple analysis tools and produces a unified report:
- Content extraction (trafilatura)
- Accessibility audit (axe-core via Playwright)
- Performance hints (response times, size)
- SEO basics (title, meta, headings)
- Stack detection (framework, CMS hints)
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from urllib.parse import urlparse

import httpx

from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.utils.http import create_client


@dataclass
class ContentAnalysis:
    title: str = ""
    description: str = ""
    word_count: int = 0
    reading_time_min: float = 0.0
    language: str = ""
    main_text: str = ""


@dataclass
class SeoAnalysis:
    has_title: bool = False
    title_length: int = 0
    has_meta_description: bool = False
    meta_description_length: int = 0
    has_h1: bool = False
    h1_count: int = 0
    heading_hierarchy: list[int] = field(default_factory=list)
    has_canonical: bool = False
    has_og_tags: bool = False
    issues: list[str] = field(default_factory=list)


@dataclass
class AccessibilityIssue:
    rule_id: str
    impact: str  # critical, serious, moderate, minor
    description: str
    help_url: str = ""
    nodes_affected: int = 0


@dataclass
class AccessibilityAnalysis:
    score: int = 0  # 0-100
    issues: list[AccessibilityIssue] = field(default_factory=list)
    passes: int = 0
    incomplete: int = 0


@dataclass
class PerformanceAnalysis:
    response_time_ms: int = 0
    content_size_bytes: int = 0
    uncompressed_size_bytes: int = 0
    num_resources: int = 0
    largest_resource_bytes: int = 0


@dataclass
class AnalyzeResult:
    url: str
    analyzed_at: str = ""
    content: ContentAnalysis = field(default_factory=ContentAnalysis)
    seo: SeoAnalysis = field(default_factory=SeoAnalysis)
    accessibility: AccessibilityAnalysis = field(default_factory=AccessibilityAnalysis)
    performance: PerformanceAnalysis = field(default_factory=PerformanceAnalysis)
    detected_stack: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    score: int = 0  # overall 0-100


class AnalyzeEngine(EngineAdapter):
    """Engine that audits a website's technical quality."""

    name = "analyze"

    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        logs = []
        url = str(job.url)

        if on_progress:
            on_progress("Starting technical analysis...")

        # 1. Fetch and measure
        if on_progress:
            on_progress("Measuring response time...")
        perf, html, final_url = await self._measure_performance(url)
        logs.append(f"Performance: {perf.response_time_ms}ms, {perf.content_size_bytes} bytes")

        # 2. Content analysis
        if on_progress:
            on_progress("Extracting main content...")
        content = self._analyze_content(html)
        logs.append(f"Content: {content.word_count} words, {content.reading_time_min:.1f} min read")

        # 3. SEO analysis
        if on_progress:
            on_progress("Checking SEO...")
        seo = self._analyze_seo(html)
        logs.append(f"SEO: {len(seo.issues)} issues found")

        # 4. Stack detection
        if on_progress:
            on_progress("Detecting tech stack...")
        stack = self._detect_stack(html)
        logs.append(f"Stack: {', '.join(stack) if stack else 'unknown'}")

        # 5. Accessibility (axe-core via Playwright)
        if on_progress:
            on_progress("Checking accessibility...")
        a11y = await self._check_accessibility(url)
        logs.append(f"A11y: score={a11y.score}, {len(a11y.issues)} issues")

        # 6. Compute overall score
        score = self._compute_score(seo, a11y, perf, content)

        # 7. Build result
        from datetime import datetime, timezone
        result = AnalyzeResult(
            url=url,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            content=content,
            seo=seo,
            accessibility=a11y,
            performance=perf,
            detected_stack=stack,
            score=score,
        )
        result.issues = seo.issues + [f"[a11y:{i.impact}] {i.description}" for i in a11y.issues[:10]]

        # 8. Save report
        report_path = output_dir / "analysis.json"
        report_path.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False), encoding="utf-8")

        # Also save readable summary
        summary_path = output_dir / "analysis.md"
        summary_path.write_text(self._to_markdown(result), encoding="utf-8")

        if on_progress:
            on_progress(f"Technical analysis complete — score: {score}/100")

        files = [report_path, summary_path]
        total_bytes = sum(f.stat().st_size for f in files)

        return EngineResult(
            output_dir=output_dir,
            files=files,
            total_bytes=total_bytes,
            logs=logs,
        )

    def can_handle(self, probe: ProbeResult) -> bool:
        return True  # analyze works on any site

    # --- Analysis methods ---

    async def _measure_performance(self, url: str) -> tuple[PerformanceAnalysis, str, str]:
        """Fetch URL and measure performance metrics."""
        perf = PerformanceAnalysis()
        html = ""
        final_url = url

        try:
            async with create_client() as client:
                start = time.monotonic()
                response = await client.get(url)
                elapsed_ms = int((time.monotonic() - start) * 1000)

                perf.response_time_ms = elapsed_ms
                perf.content_size_bytes = len(response.content)
                perf.uncompressed_size_bytes = len(response.text.encode("utf-8"))
                html = response.text
                final_url = str(response.url)

                # Count resources referenced in HTML
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "lxml")
                resources = (
                    len(soup.find_all("link", rel="stylesheet"))
                    + len(soup.find_all("script", src=True))
                    + len(soup.find_all("img", src=True))
                )
                perf.num_resources = resources
        except Exception:
            pass

        return perf, html, final_url

    def _analyze_content(self, html: str) -> ContentAnalysis:
        """Extract main content using trafilatura or fallback."""
        content = ContentAnalysis()

        try:
            import trafilatura

            extracted = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                favor_precision=False,
            )
            if extracted:
                content.main_text = extracted[:5000]
                words = extracted.split()
                content.word_count = len(words)
                content.reading_time_min = max(1, len(words) / 200)  # ~200 wpm
        except ImportError:
            # Fallback: basic extraction
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            texts = [t.get_text(strip=True) for t in soup.find_all(["p", "h1", "h2", "h3", "li", "td"])]
            combined = " ".join(texts)
            content.main_text = combined[:5000]
            words = combined.split()
            content.word_count = len(words)
            content.reading_time_min = max(1, len(words) / 200)

        # Title
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("title")
        if title_tag:
            content.title = title_tag.get_text(strip=True)

        # Language
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            content.language = html_tag["lang"]

        return content

    def _analyze_seo(self, html: str) -> SeoAnalysis:
        """Analyze SEO basics."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        seo = SeoAnalysis()

        # Title
        title_tag = soup.find("title")
        if title_tag:
            seo.has_title = True
            seo.title_length = len(title_tag.get_text(strip=True))
            if seo.title_length < 30:
                seo.issues.append("Title too short (< 30 characters)")
            elif seo.title_length > 60:
                seo.issues.append("Title too long (> 60 characters)")

        # Meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            seo.has_meta_description = True
            seo.meta_description_length = len(meta_desc.get("content", ""))
            if seo.meta_description_length < 70:
                seo.issues.append("Meta description curta (< 70 caracteres)")
            elif seo.meta_description_length > 160:
                seo.issues.append("Meta description longa (> 160 caracteres)")
        else:
            seo.issues.append("Meta description ausente")

        # Headings
        headings = []
        for level in range(1, 7):
            count = len(soup.find_all(f"h{level}"))
            headings.append(count)
            if level == 1 and count == 0:
                seo.issues.append("H1 ausente")
            elif level == 1 and count > 1:
                seo.issues.append(f"Multiple H1s ({count})")
        seo.heading_hierarchy = headings
        seo.h1_count = headings[0] if headings else 0
        seo.has_h1 = seo.h1_count > 0

        # Canonical
        canonical = soup.find("link", rel="canonical")
        seo.has_canonical = canonical is not None
        if not seo.has_canonical:
            seo.issues.append("Canonical tag ausente")

        # Open Graph
        og_tags = soup.find_all("meta", attrs={"property": lambda x: x and x.startswith("og:")})
        seo.has_og_tags = len(og_tags) > 0
        if not seo.has_og_tags:
            seo.issues.append("Open Graph tags ausentes")

        return seo

    async def _check_accessibility(self, url: str) -> AccessibilityAnalysis:
        """Run axe-core via Playwright for accessibility audit."""
        a11y = AccessibilityAnalysis()

        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                context = await browser.new_context(viewport={"width": 1280, "height": 800})
                page = await context.new_page()

                await page.goto(url, wait_until="networkidle", timeout=20000)

                # Inject axe-core
                axe_script = await self._fetch_axe_core()
                if axe_script:
                    await page.evaluate(axe_script)
                    axe_results = await page.evaluate("axe.run()")

                    a11y.passes = len(axe_results.get("passes", []))
                    a11y.incomplete = len(axe_results.get("incomplete", []))

                    for violation in axe_results.get("violations", []):
                        issue = AccessibilityIssue(
                            rule_id=violation.get("id", ""),
                            impact=violation.get("impact", "unknown"),
                            description=violation.get("description", ""),
                            help_url=violation.get("helpUrl", ""),
                            nodes_affected=len(violation.get("nodes", [])),
                        )
                        a11y.issues.append(issue)

                    # Score: based on passes vs violations
                    total_checks = a11y.passes + len(a11y.issues)
                    if total_checks > 0:
                        a11y.score = min(100, int((a11y.passes / total_checks) * 100))

                await context.close()
                await browser.close()

        except Exception:
            # Playwright or axe-core not available
            a11y.score = -1  # indicate unable to check

        return a11y

    async def _fetch_axe_core(self) -> str | None:
        """Fetch axe-core script from CDN."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.8.4/axe.min.js")
                if resp.status_code == 200:
                    return resp.text
        except Exception:
            pass
        return None

    def _detect_stack(self, html: str) -> list[str]:
        """Detect web stack from HTML signatures."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        html_lower = html.lower()
        stack = []

        # Frameworks
        if "next" in html_lower and ("_next/" in html_lower or "__next" in html_lower):
            stack.append("Next.js")
        if "nuxt" in html_lower and ("__nuxt" in html_lower or "_nuxt/" in html_lower):
            stack.append("Nuxt")
        if "react" in html_lower or "reactroot" in html_lower:
            stack.append("React")
        if "vue" in html_lower or "vuejs" in html_lower:
            stack.append("Vue")
        if "angular" in html_lower or "ng-version" in html_lower:
            stack.append("Angular")

        # CMS
        generator = soup.find("meta", attrs={"name": "generator"})
        if generator:
            gen = generator.get("content", "").lower()
            if "wordpress" in gen:
                stack.append("WordPress")
            elif "drupal" in gen:
                stack.append("Drupal")
            elif "joomla" in gen:
                stack.append("Joomla")
            elif "hugo" in gen:
                stack.append("Hugo")
            elif "gatsby" in gen:
                stack.append("Gatsby")

        # Build tools
        if "webpack" in html_lower:
            stack.append("Webpack")
        if "vite" in html_lower:
            stack.append("Vite")

        # Analytics
        if "google-analytics" in html_lower or "gtag" in html_lower:
            stack.append("Google Analytics")
        if "hotjar" in html_lower:
            stack.append("Hotjar")
        if "clarity.ms" in html_lower:
            stack.append("Microsoft Clarity")

        return list(dict.fromkeys(stack))  # deduplicate preserving order

    def _compute_score(
        self,
        seo: SeoAnalysis,
        a11y: AccessibilityAnalysis,
        perf: PerformanceAnalysis,
        content: ContentAnalysis,
    ) -> int:
        """Compute overall analysis score 0-100."""
        scores = []

        # SEO score (0-30)
        seo_score = 30
        if not seo.has_title:
            seo_score -= 10
        elif seo.title_length < 30 or seo.title_length > 60:
            seo_score -= 3
        if not seo.has_meta_description:
            seo_score -= 8
        if not seo.has_h1:
            seo_score -= 5
        if not seo.has_canonical:
            seo_score -= 4
        if not seo.has_og_tags:
            seo_score -= 3
        scores.append(max(0, seo_score))

        # Accessibility score (0-30)
        if a11y.score >= 0:
            scores.append(int(a11y.score * 0.3))
        else:
            scores.append(15)  # neutral if unable to check

        # Performance score (0-20)
        perf_score = 20
        if perf.response_time_ms > 3000:
            perf_score -= 10
        elif perf.response_time_ms > 1000:
            perf_score -= 5
        if perf.content_size_bytes > 5_000_000:
            perf_score -= 5
        scores.append(max(0, perf_score))

        # Content score (0-20)
        content_score = 20
        if content.word_count < 100:
            content_score -= 10
        elif content.word_count < 300:
            content_score -= 5
        if not content.title:
            content_score -= 5
        scores.append(max(0, content_score))

        return min(100, sum(scores))

    def _to_markdown(self, result: AnalyzeResult) -> str:
        """Generate a readable markdown report."""
        lines = [
            f"# Technical Analysis — {result.url}",
            f"*Generated at {result.analyzed_at}*",
            f"## Score Geral: {result.score}/100",
            "",
            "## Content",
            f"- **Title:** {result.content.title or '(not found)'}",
            f"- **Palavras:** {result.content.word_count}",
            f"- **Reading time:** {result.content.reading_time_min:.1f} min",
            f"- **Language:** {result.content.language or 'not detected'}",
            "",
            "## SEO",
            f"- Title: {'✅' if result.seo.has_title else '❌'} ({result.seo.title_length} chars)",
            f"- Meta description: {'✅' if result.seo.has_meta_description else '❌'}",
            f"- H1: {'✅' if result.seo.has_h1 else '❌'} ({result.seo.h1_count})",
            f"- Canonical: {'✅' if result.seo.has_canonical else '❌'}",
            f"- Open Graph: {'✅' if result.seo.has_og_tags else '❌'}",
        ]
        if result.seo.issues:
            lines.append("")
            lines.append("**SEO issues:**")
            for issue in result.seo.issues:
                lines.append(f"- {issue}")

        lines.extend([
            "",
            "## Accessibility",
            f"- **Score:** {result.accessibility.score}/100" if result.accessibility.score >= 0 else "- Could not verify",
            f"- Passes: {result.accessibility.passes}",
            f"- Issues: {len(result.accessibility.issues)}",
        ])
        if result.accessibility.issues:
            lines.append("")
            for issue in result.accessibility.issues[:5]:
                lines.append(f"- [{issue.impact}] {issue.description} ({issue.rule_id})")

        lines.extend([
            "",
            "## Performance",
            f"- Response time: {result.performance.response_time_ms}ms",
            f"- Size: {result.performance.content_size_bytes:,} bytes",
            f"- Recursos referenciados: {result.performance.num_resources}",
            "",
            "## Detected Stack",
            ", ".join(result.detected_stack) if result.detected_stack else "Not detected",
        ])

        return "\n".join(lines)
