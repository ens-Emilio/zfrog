"""Video / streaming engine — finds HLS and DASH streams on a page and downloads them.

The engine fetches the page, collects every candidate stream URL it can see
(``<video src>``, ``<source src>``, ``<iframe src>`` and absolute ``.m3u8`` /
``.mpd`` URLs inside inline scripts), sniffs each one as a manifest, and then
downloads the segments of the first playable stream into ``segments/``,
concatenating them into ``video.ts``.

Encrypted streams (``#EXT-X-KEY`` / DASH ``ContentProtection``) are reported
but never decrypted, and every request is capped so a plain ``<video
src="movie.mp4">`` can never be pulled down in full just to be sniffed.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from zfrog.config import settings
from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.streams import is_dash, is_master_playlist, parse_m3u8, parse_mpd, select_variant
from zfrog.utils.http import create_client

logger = logging.getLogger(__name__)

# Manifests are a few hundred kilobytes at most; capping the sniff keeps a
# direct <video src="movie.mp4"> from being downloaded in full.
_SNIFF_MAX_BYTES = 2 * 1024 * 1024

# Absolute URLs pointing at a manifest, as found inside inline scripts.
_STREAM_URL_RE = re.compile(
    r"""https?://[^\s"'<>\\]+?\.(?:m3u8|mpd)(?:\?[^\s"'<>\\]*)?""",
    re.IGNORECASE,
)

# Tags whose src may point at a stream (or at a player that embeds one).
_SRC_TAGS: tuple[tuple[str, str], ...] = (
    ("video", "src"),
    ("source", "src"),
    ("iframe", "src"),
)


def find_stream_candidates(html: str, base_url: str) -> list[str]:
    """Return the deduplicated stream/player URLs referenced by ``html``.

    ``<video>``/``<source>``/``<iframe>`` ``src`` values are resolved against
    ``base_url``; inline scripts contribute absolute ``.m3u8``/``.mpd`` URLs.
    Order is preserved so the first candidate stays the preferred one.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    found: list[str] = []

    for tag_name, attribute in _SRC_TAGS:
        for element in soup.find_all(tag_name):
            value = element.get(attribute)
            if isinstance(value, str) and value.strip():
                found.append(urljoin(base_url, value.strip()))

    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        found.extend(match.group(0) for match in _STREAM_URL_RE.finditer(text))

    candidates: list[str] = []
    seen: set[str] = set()
    for candidate in found:
        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    return candidates


async def _fetch_bytes(
    client,
    url: str,
    limit: int | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, bool]:
    """GET ``url`` reading at most ``limit`` bytes (``None`` = unlimited).

    Returns ``(data, truncated)``.
    """
    async with client.stream("GET", url, headers=headers) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            chunks.append(chunk)
            total += len(chunk)
            if limit is not None and total >= limit:
                break
        data = b"".join(chunks)

    if limit is not None and len(data) > limit:
        return data[:limit], True
    return data, False


async def _fetch_text(client, url: str, limit: int | None = _SNIFF_MAX_BYTES) -> tuple[str, bool]:
    """Fetch ``url`` and decode it as UTF-8 text; returns ``(text, truncated)``."""
    data, truncated = await _fetch_bytes(client, url, limit)
    return data.decode("utf-8", errors="replace"), truncated


def _is_hls(text: str) -> bool:
    """True for any HLS playlist — master or media — which start with ``#EXTM3U``."""
    return text.lstrip("\ufeff \t\r\n").startswith("#EXTM3U")


def _format_bytes(count: int) -> str:
    return f"{count:,} bytes"


def _render_markdown(report: dict) -> str:
    """Human-readable summary of a ``streams.json`` report."""
    streams = report["streams"]
    errors = report["errors"]
    lines = [
        f"# Streams — {report['url']}",
        "",
        f"- Streams encontrados: {len(streams)}",
        f"- Erros: {len(errors)}",
        "",
    ]

    if not streams:
        lines += ["Nenhum stream encontrado.", ""]

    for index, stream in enumerate(streams, start=1):
        lines += [
            f"## {index}. {stream['url']}",
            "",
            f"- Tipo: {stream['kind']}",
            f"- Criptografado: {'sim' if stream['encrypted'] else 'não'}",
            f"- Variantes: {len(stream['variants'])}",
        ]
        for variant in stream["variants"]:
            detail = f"  - {variant['resolution'] or '?'} @ {variant['bandwidth']:,} bps"
            if variant["codecs"]:
                detail += f" ({variant['codecs']})"
            lines.append(detail)
        lines += [
            f"- Segmentos: {stream['segments']}",
            f"- Baixado: {'sim' if stream['downloaded'] else 'não'} "
            f"({_format_bytes(stream['bytes'])})",
            "",
        ]

    if errors:
        lines += ["## Erros", ""]
        lines += [f"- {error}" for error in errors]
        lines.append("")

    return "\n".join(lines)


class VideoEngine(EngineAdapter):
    """Engine that detects and downloads HLS/DASH streams referenced by a page."""

    name = "video"

    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        logs: list[str] = []
        errors: list[str] = []
        streams: list[dict] = []
        parsed: list[tuple[dict, dict]] = []
        url = str(job.url)

        if on_progress:
            on_progress("Procurando streams...")

        segment_files: list[Path] = []
        video_path: Path | None = None

        async with create_client() as client:
            html = ""
            try:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
                logs.append(f"Fetched {len(html):,} bytes from {url}")
            except Exception as exc:
                errors.append(f"Falha ao buscar {url}: {exc}")
                logs.append(f"Falha ao buscar {url}: {exc}")

            page_is_manifest = bool(html) and (_is_hls(html) or is_dash(html))
            pending: list[tuple[str, str | None]] = []
            if page_is_manifest:
                pending.append((url, html))
            for candidate in find_stream_candidates(html, url):
                if page_is_manifest and candidate == url:
                    continue
                pending.append((candidate, None))
            logs.append(f"Candidatos de stream: {len(pending)}")

            for candidate, preloaded in pending:
                try:
                    if preloaded is not None:
                        text, truncated = preloaded, False
                    else:
                        text, truncated = await _fetch_text(client, candidate)
                    if truncated:
                        logs.append(
                            f"Manifesto truncado em {_format_bytes(_SNIFF_MAX_BYTES)}: {candidate}"
                        )
                except Exception as exc:
                    errors.append(f"Falha ao buscar {candidate}: {exc}")
                    continue

                if is_dash(text):
                    info = parse_mpd(text, candidate)
                elif is_master_playlist(text) or _is_hls(text):
                    info = parse_m3u8(text, candidate)
                else:
                    logs.append(f"Ignorado (não é um manifesto): {candidate}")
                    continue

                entry = {
                    "url": candidate,
                    "kind": info["kind"],
                    "variants": [asdict(variant) for variant in info["variants"]],
                    "segments": len(info["segments"]),
                    "encrypted": bool(info["encrypted"]),
                    "downloaded": False,
                    "bytes": 0,
                }
                streams.append(entry)
                parsed.append((entry, info))

            # Only the first playable stream is downloaded.
            for entry, info in parsed:
                if video_path is not None:
                    break
                if entry["encrypted"]:
                    logs.append(f"Stream criptografado, download ignorado: {entry['url']}")
                    continue

                segments = list(info["segments"])
                if info["kind"] == "master":
                    variant = select_variant(info["variants"])
                    if variant is None:
                        logs.append(f"Master sem variantes utilizáveis: {entry['url']}")
                        continue
                    try:
                        media_text, _ = await _fetch_text(client, variant.uri)
                    except Exception as exc:
                        errors.append(f"Falha ao buscar {variant.uri}: {exc}")
                        continue
                    media = parse_m3u8(media_text, variant.uri)
                    if media["encrypted"]:
                        entry["encrypted"] = True
                        logs.append(f"Stream criptografado, download ignorado: {variant.uri}")
                        continue
                    segments = list(media["segments"])
                    entry["segments"] = len(segments)

                if not segments:
                    logs.append(f"Sem segmentos para baixar: {entry['url']}")
                    continue

                logs.append(f"Baixando {len(segments)} segmento(s) de {entry['url']}")
                video_path, segment_files, downloaded, _truncated = await self._download_segments(
                    client, segments, output_dir, logs, errors
                )
                if video_path is not None:
                    entry["downloaded"] = True
                    entry["bytes"] = downloaded

        report = {"url": url, "streams": streams, "errors": errors}
        json_path = output_dir / "streams.json"
        json_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        md_path = output_dir / "streams.md"
        md_path.write_text(_render_markdown(report), encoding="utf-8")

        files = [json_path, md_path, *segment_files]
        if video_path is not None:
            files.append(video_path)

        if on_progress:
            on_progress("Streams concluídos")

        return EngineResult(
            output_dir=output_dir,
            files=files,
            total_bytes=sum(path.stat().st_size for path in files),
            logs=logs,
        )

    async def _download_segments(
        self,
        client,
        segments: list,
        output_dir: Path,
        logs: list[str],
        errors: list[str],
    ) -> tuple[Path | None, list[Path], int, bool]:
        """Download ``segments`` and concatenate them into ``video.ts``.

        Stops at ``settings.video_max_segments`` / ``settings.video_max_bytes``
        (logging the truncation) and returns ``(video_path, files, bytes, truncated)``;
        ``video_path`` is ``None`` when nothing could be written.
        """
        segments_dir = output_dir / "segments"
        max_bytes = settings.video_max_bytes
        max_segments = settings.video_max_segments

        chunks: list[bytes] = []
        files: list[Path] = []
        total = 0
        truncated = False

        for index, segment in enumerate(segments):
            if max_segments > 0 and len(chunks) >= max_segments:
                truncated = True
                logs.append(f"Limite de {max_segments} segmentos atingido, download truncado")
                break
            if max_bytes > 0 and total >= max_bytes:
                truncated = True
                logs.append(f"Limite de {_format_bytes(max_bytes)} atingido, download truncado")
                break

            headers: dict[str, str] | None = None
            if segment.byte_range is not None:
                start, end = segment.byte_range
                headers = {"Range": f"bytes={start}-{end - 1}"}

            limit = max_bytes - total if max_bytes > 0 else None
            try:
                data, segment_truncated = await _fetch_bytes(
                    client, segment.uri, limit, headers
                )
            except Exception as exc:
                errors.append(f"Falha ao baixar segmento {segment.uri}: {exc}")
                break

            if segment_truncated:
                truncated = True

            if data:
                segments_dir.mkdir(parents=True, exist_ok=True)
                path = segments_dir / f"segment_{index:05d}.ts"
                path.write_bytes(data)
                files.append(path)
                chunks.append(data)
                total += len(data)

            if truncated:
                logs.append(f"Download truncado no segmento {index} ({_format_bytes(total)})")
                break

        if not chunks:
            return None, files, total, truncated

        video_path = output_dir / "video.ts"
        video_path.write_bytes(b"".join(chunks))
        logs.append(f"video.ts: {_format_bytes(total)} de {len(chunks)} segmento(s)")
        return video_path, files, total, truncated

    def can_handle(self, probe: ProbeResult) -> bool:
        """Video extraction applies to any page — streams are only known once fetched."""
        return True
