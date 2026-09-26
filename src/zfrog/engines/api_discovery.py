"""API discovery engine — report the REST/GraphQL endpoints a page talks to.

Fetches the page, then its same-origin scripts (best effort), and writes
``api_endpoints.json`` and ``api_endpoints.md`` describing every endpoint
:mod:`zfrog.apidisc` recognised, so the user can scrape the API instead of the
rendered HTML.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from zfrog.apidisc import Endpoint, extract_endpoints, group_by_kind
from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.utils.http import create_client

logger = logging.getLogger(__name__)

# Budgets: a page can reference hundreds of bundles, and one of them can be huge.
MAX_SCRIPTS = 10
MAX_SCRIPT_BYTES = 2_000_000


def _progress(on_progress: Callable[[str], Any] | None, message: str) -> None:
    """Report progress when the caller asked for it."""
    if on_progress:
        on_progress(message)


def _same_origin(url: str, base_url: str) -> bool:
    """Whether a URL points at the same scheme and host as the page."""
    target, base = urlparse(url), urlparse(base_url)
    return (target.scheme, target.netloc) == (base.scheme, base.netloc)


def _script_urls(html: str, base_url: str, logs: list[str]) -> list[str]:
    """Same-origin ``<script src>`` URLs of a page, capped and deduplicated."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:  # noqa: BLE001 - broken HTML must not fail the run
        logger.warning("failed to parse %s: %s", base_url, exc)
        logs.append(f"Falha ao analisar a página: {exc}")
        return []

    urls: list[str] = []
    for tag in soup.find_all("script", src=True):
        raw = str(tag.get("src") or "").strip()
        if not raw:
            continue
        resolved = urljoin(base_url, raw)
        if not _same_origin(resolved, base_url) or resolved in urls:
            continue
        urls.append(resolved)

    if len(urls) > MAX_SCRIPTS:
        logs.append(
            f"Limite de {MAX_SCRIPTS} scripts atingido; "
            f"ignorando {len(urls) - MAX_SCRIPTS} restantes"
        )
        urls = urls[:MAX_SCRIPTS]
    return urls


async def _fetch_scripts(
    client: httpx.AsyncClient,
    html: str,
    base_url: str,
) -> tuple[list[str], list[str]]:
    """Fetch the page's same-origin scripts; a failure is logged, never fatal."""
    logs: list[str] = []
    bodies: list[str] = []
    for src in _script_urls(html, base_url, logs):
        try:
            response = await client.get(src)
        except httpx.HTTPError as exc:
            logger.warning("script request failed for %s: %s", src, exc)
            logs.append(f"Falha ao buscar script {src}: {exc}")
            continue
        if response.status_code >= 400:
            logs.append(f"HTTP {response.status_code} para o script {src}")
            continue
        body = response.content
        if len(body) > MAX_SCRIPT_BYTES:
            logs.append(f"Script {src} truncado em {MAX_SCRIPT_BYTES} bytes")
            body = body[:MAX_SCRIPT_BYTES]
        bodies.append(body.decode("utf-8", errors="replace"))
        logs.append(f"Script analisado: {src} ({len(body)} bytes)")
    return bodies, logs


def _render_markdown(base_url: str, by_kind: dict[str, list[Endpoint]]) -> str:
    """Markdown report: one table per kind of endpoint."""
    lines = ["# Endpoints de API", "", f"Página: {base_url}", ""]
    total = sum(len(items) for items in by_kind.values())
    if not total:
        lines.append("Nenhum endpoint encontrado.")
        return "\n".join(lines) + "\n"

    lines.extend([f"Total: {total}", ""])
    for kind, items in by_kind.items():
        lines.extend([f"## {kind}", "", "| Método | Tipo | URL |", "| --- | --- | --- |"])
        for endpoint in items:
            lines.append(f"| {endpoint.method} | {endpoint.kind} | {endpoint.url} |")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


class ApiDiscoveryEngine(EngineAdapter):
    """Finds the API endpoints a page calls and reports them as JSON and Markdown."""

    name = "api_discovery"

    def can_handle(self, probe: ProbeResult) -> bool:
        """API discovery is meaningful for any page."""
        return True

    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress: Callable[[str], Any] | None = None,
    ) -> EngineResult:
        """Scan ``job.url`` and its scripts for API endpoints."""
        output_dir.mkdir(parents=True, exist_ok=True)
        logs: list[str] = []
        url = str(job.url)
        _progress(on_progress, "Procurando APIs...")

        html = ""
        base_url = url
        js_bodies: list[str] = []
        try:
            async with create_client() as client:
                response = await client.get(url)
                base_url = str(response.url)
                html = response.text
                logs.append(f"Página obtida: {len(html)} bytes de {base_url}")
                js_bodies, script_logs = await _fetch_scripts(client, html, base_url)
                logs.extend(script_logs)
        except httpx.HTTPError as exc:
            logger.warning("api discovery request failed for %s: %s", url, exc)
            logs.append(f"Falha ao buscar {url}: {exc}")

        endpoints = extract_endpoints(html, base_url, js_bodies)
        by_kind = group_by_kind(endpoints)

        json_path = output_dir / "api_endpoints.json"
        md_path = output_dir / "api_endpoints.md"
        json_path.write_text(
            json.dumps(
                {
                    "url": base_url,
                    "endpoints": [asdict(endpoint) for endpoint in endpoints],
                    "by_kind": {
                        kind: [asdict(endpoint) for endpoint in items]
                        for kind, items in by_kind.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        md_path.write_text(_render_markdown(base_url, by_kind), encoding="utf-8")

        _progress(on_progress, f"APIs encontradas: {len(endpoints)}")
        logs.append(f"APIs encontradas: {len(endpoints)}")

        files = [json_path, md_path]
        return EngineResult(
            output_dir=output_dir,
            files=files,
            total_bytes=sum(path.stat().st_size for path in files),
            logs=logs,
        )
