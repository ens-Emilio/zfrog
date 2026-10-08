"""Tests for HLS/DASH manifest parsing and the video engine."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from zfrog.config import settings
from zfrog.engines.video import VideoEngine, find_stream_candidates
from zfrog.models import JobCreate
from zfrog.streams import (
    Variant,
    is_dash,
    is_master_playlist,
    parse_m3u8,
    parse_mpd,
    select_variant,
)

PAGE_URL = "https://site.test/watch"
MASTER_URL = "https://cdn.test/hls/master.m3u8"
LOW_URL = "https://cdn.test/hls/low/index.m3u8"
HIGH_URL = "https://cdn.test/hls/high/index.m3u8"

MASTER = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=640x360,CODECS="avc1.4d401e,mp4a.40.2"
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
high/index.m3u8
"""

MEDIA = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:9.009,
seg0.ts
#EXTINF:8.5,
seg1.ts
#EXTINF:4.25,
sub/seg2.ts
#EXT-X-ENDLIST
"""

RANGED_MEDIA = """#EXTM3U
#EXT-X-TARGETDURATION:10
#EXTINF:10.0,
#EXT-X-BYTERANGE:1000@0
pack.ts
#EXTINF:10.0,
#EXT-X-BYTERANGE:500
pack.ts
#EXTINF:10.0,
#EXT-X-BYTERANGE:250@5000
pack.ts
#EXT-X-ENDLIST
"""

ENCRYPTED_MEDIA = """#EXTM3U
#EXT-X-TARGETDURATION:10
#EXT-X-KEY:METHOD=AES-128,URI="https://cdn.test/key.bin"
#EXTINF:10.0,
seg0.ts
#EXT-X-ENDLIST
"""

CLEAR_KEY_MEDIA = """#EXTM3U
#EXT-X-TARGETDURATION:10
#EXT-X-KEY:METHOD=NONE
#EXTINF:10.0,
seg0.ts
#EXT-X-ENDLIST
"""

MPD_URL = "https://cdn.test/dash/manifest.mpd"

MPD = """<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" maxSegmentDuration="PT4S">
  <Period>
    <AdaptationSet mimeType="video/mp4">
      <BaseURL>video/</BaseURL>
      <Representation id="v0" bandwidth="800000" width="640" height="360" codecs="avc1.4d401e"/>
      <Representation id="v1" bandwidth="4000000" width="1920" height="1080" codecs="avc1.640028">
        <BaseURL>1080/</BaseURL>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
"""

PROTECTED_MPD = """<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">
  <Period>
    <AdaptationSet mimeType="video/mp4">
      <ContentProtection schemeIdUri="urn:mpeg:dash:mp4protection:2011" value="cenc"/>
      <Representation id="v0" bandwidth="1000000" width="1280" height="720"/>
    </AdaptationSet>
  </Period>
</MPD>
"""

PAGE_WITH_INLINE_STREAM = """<html><body>
<script>var player = {src: "https://cdn.test/hls/master.m3u8"};</script>
</body></html>
"""


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _job(url: str = PAGE_URL) -> JobCreate:
    return JobCreate(url=url, mode="video")


# ── manifest parsing ──


def test_is_master_playlist_and_is_dash_discriminate():
    assert is_master_playlist(MASTER) is True
    assert is_master_playlist(MEDIA) is False
    assert is_master_playlist("") is False

    assert is_dash(MPD) is True
    assert is_dash(PROTECTED_MPD) is True
    assert is_dash(MEDIA) is False
    assert is_dash(MASTER) is False


def test_parse_m3u8_master_variants_and_relative_uris():
    result = parse_m3u8(MASTER, MASTER_URL)

    assert result["kind"] == "master"
    assert result["segments"] == []
    assert result["encrypted"] is False
    assert result["variants"] == [
        Variant(
            uri=LOW_URL,
            bandwidth=1280000,
            resolution="640x360",
            codecs="avc1.4d401e,mp4a.40.2",
        ),
        Variant(
            uri=HIGH_URL,
            bandwidth=5000000,
            resolution="1920x1080",
            codecs="avc1.640028,mp4a.40.2",
        ),
    ]


def test_parse_m3u8_media_segments_keep_order_and_durations():
    result = parse_m3u8(MEDIA, "https://cdn.test/hls/high/index.m3u8")

    assert result["kind"] == "media"
    assert result["variants"] == []
    assert result["target_duration"] == 10.0
    assert [segment.uri for segment in result["segments"]] == [
        "https://cdn.test/hls/high/seg0.ts",
        "https://cdn.test/hls/high/seg1.ts",
        "https://cdn.test/hls/high/sub/seg2.ts",
    ]
    assert [segment.duration for segment in result["segments"]] == [9.009, 8.5, 4.25]
    assert all(segment.byte_range is None for segment in result["segments"])


def test_parse_m3u8_byterange_offsets_accumulate_per_uri():
    result = parse_m3u8(RANGED_MEDIA, "https://cdn.test/hls/pack/index.m3u8")

    assert [segment.byte_range for segment in result["segments"]] == [
        (0, 1000),
        (1000, 1500),
        (5000, 5250),
    ]
    assert {segment.uri for segment in result["segments"]} == {"https://cdn.test/hls/pack/pack.ts"}


def test_parse_m3u8_key_sets_encrypted_only_for_real_methods():
    encrypted = parse_m3u8(ENCRYPTED_MEDIA, "https://cdn.test/hls/index.m3u8")
    clear = parse_m3u8(CLEAR_KEY_MEDIA, "https://cdn.test/hls/index.m3u8")

    assert encrypted["encrypted"] is True
    assert clear["encrypted"] is False


def test_parse_mpd_representations_become_variants():
    result = parse_mpd(MPD, MPD_URL)

    assert result["kind"] == "dash"
    assert result["segments"] == []
    assert result["encrypted"] is False
    assert result["target_duration"] == 4.0
    assert [(v.uri, v.bandwidth, v.resolution, v.codecs) for v in result["variants"]] == [
        ("https://cdn.test/dash/video/", 800000, "640x360", "avc1.4d401e"),
        ("https://cdn.test/dash/video/1080/", 4000000, "1920x1080", "avc1.640028"),
    ]


def test_parse_mpd_content_protection_sets_encrypted_and_falls_back_to_mpd_path():
    result = parse_mpd(PROTECTED_MPD, MPD_URL)

    assert result["encrypted"] is True
    assert [variant.uri for variant in result["variants"]] == [MPD_URL]


def test_select_variant_prefers_bandwidth_and_respects_max_height():
    variants = parse_m3u8(MASTER, MASTER_URL)["variants"]

    assert select_variant(variants) == variants[1]
    assert select_variant(variants, max_height=720) == variants[0]
    assert select_variant(variants, max_height=360) == variants[0]
    assert select_variant([], max_height=720) is None
    assert select_variant([]) is None


def test_find_stream_candidates_resolves_relative_and_dedupes():
    html = (
        '<html><body><video src="/v/clip.m3u8"></video>'
        '<iframe src="https://cdn.test/embed"></iframe>'
        '<script>var a="https://cdn.test/a.m3u8";var b="https://cdn.test/a.m3u8";</script>'
        "</body></html>"
    )

    assert find_stream_candidates(html, "https://site.test/page") == [
        "https://site.test/v/clip.m3u8",
        "https://cdn.test/embed",
        "https://cdn.test/a.m3u8",
    ]
    assert find_stream_candidates("", "https://site.test/page") == []


# ── engine ──


@pytest.mark.asyncio
async def test_video_engine_downloads_the_best_variant_end_to_end(tmp_path):
    output_dir = tmp_path / "job"
    progress: list[str] = []

    with respx.mock(assert_all_called=False) as mock:
        mock.get(PAGE_URL).mock(
            return_value=httpx.Response(
                200, headers={"content-type": "text/html"}, text=PAGE_WITH_INLINE_STREAM
            )
        )
        master_route = mock.get(MASTER_URL).mock(return_value=httpx.Response(200, text=MASTER))
        high_route = mock.get(HIGH_URL).mock(return_value=httpx.Response(200, text=MEDIA))
        mock.get(f"{HIGH_URL.rsplit('/', 1)[0]}/seg0.ts").mock(
            return_value=httpx.Response(200, content=b"AAA")
        )
        mock.get(f"{HIGH_URL.rsplit('/', 1)[0]}/seg1.ts").mock(
            return_value=httpx.Response(200, content=b"BBBB")
        )
        mock.get(f"{HIGH_URL.rsplit('/', 1)[0]}/sub/seg2.ts").mock(
            return_value=httpx.Response(200, content=b"CC")
        )
        result = await VideoEngine().execute(_job(), output_dir, on_progress=progress.append)

    assert master_route.called and high_route.called
    assert progress[0] == "Scanning for streams..."
    assert progress[-1] == "Streams complete"

    assert (output_dir / "video.ts").read_bytes() == b"AAABBBBCC"

    report = _read_json(output_dir / "streams.json")
    assert report["url"] == PAGE_URL
    assert report["errors"] == []
    assert len(report["streams"]) == 1

    stream = report["streams"][0]
    assert stream["url"] == MASTER_URL
    assert stream["kind"] == "master"
    assert stream["encrypted"] is False
    assert stream["downloaded"] is True
    assert stream["bytes"] == 9
    assert stream["segments"] == 3
    assert stream["variants"] == [
        {
            "uri": LOW_URL,
            "bandwidth": 1280000,
            "resolution": "640x360",
            "codecs": "avc1.4d401e,mp4a.40.2",
        },
        {
            "uri": HIGH_URL,
            "bandwidth": 5000000,
            "resolution": "1920x1080",
            "codecs": "avc1.640028,mp4a.40.2",
        },
    ]

    markdown = (output_dir / "streams.md").read_text(encoding="utf-8")
    assert MASTER_URL in markdown
    assert "Downloaded: yes (9 bytes)" in markdown

    assert set(result.files) >= {
        output_dir / "streams.json",
        output_dir / "streams.md",
        output_dir / "video.ts",
    }
    assert result.total_bytes == sum(path.stat().st_size for path in result.files)


@pytest.mark.asyncio
async def test_video_engine_skips_encrypted_streams(tmp_path):
    output_dir = tmp_path / "job"
    url = "https://cdn.test/hls/enc/index.m3u8"
    page = f'<html><body><script>var s="{url}";</script></body></html>'

    with respx.mock(assert_all_called=False) as mock:
        mock.get(PAGE_URL).mock(return_value=httpx.Response(200, text=page))
        mock.get(url).mock(return_value=httpx.Response(200, text=ENCRYPTED_MEDIA))
        result = await VideoEngine().execute(_job(), output_dir)

    report = _read_json(output_dir / "streams.json")
    assert len(report["streams"]) == 1
    stream = report["streams"][0]
    assert stream["encrypted"] is True
    assert stream["downloaded"] is False
    assert stream["bytes"] == 0

    assert not (output_dir / "segments").exists()
    assert not (output_dir / "video.ts").exists()
    assert (output_dir / "streams.md").exists()
    assert any("Encrypted stream" in log for log in result.logs)


@pytest.mark.asyncio
async def test_video_engine_page_without_streams_writes_empty_report(tmp_path):
    output_dir = tmp_path / "job"
    page = "<html><body><p>no video here</p></body></html>"

    with respx.mock(assert_all_called=False) as mock:
        mock.get(PAGE_URL).mock(return_value=httpx.Response(200, text=page))
        await VideoEngine().execute(_job(), output_dir)

    report = _read_json(output_dir / "streams.json")
    assert report == {"url": PAGE_URL, "streams": [], "errors": []}
    assert (output_dir / "streams.md").read_text(encoding="utf-8").count(
        "No streams found."
    ) == 1
    assert not (output_dir / "video.ts").exists()


@pytest.mark.asyncio
async def test_video_engine_ignores_candidates_that_are_not_manifests(tmp_path):
    output_dir = tmp_path / "job"
    page = '<html><body><video src="/media/clip.mp4"></video></body></html>'
    clip = "https://site.test/media/clip.mp4"

    with respx.mock(assert_all_called=False) as mock:
        mock.get(PAGE_URL).mock(return_value=httpx.Response(200, text=page))
        clip_route = mock.get(clip).mock(
            return_value=httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
        )
        await VideoEngine().execute(_job(), output_dir)

    assert clip_route.called
    report = _read_json(output_dir / "streams.json")
    assert report["streams"] == []
    assert report["errors"] == []


@pytest.mark.asyncio
async def test_video_engine_treats_a_manifest_url_as_the_target_itself(tmp_path):
    output_dir = tmp_path / "job"
    job = _job(MASTER_URL)

    with respx.mock(assert_all_called=False) as mock:
        page_route = mock.get(MASTER_URL).mock(return_value=httpx.Response(200, text=MASTER))
        mock.get(HIGH_URL).mock(return_value=httpx.Response(200, text=MEDIA))
        mock.get(f"{HIGH_URL.rsplit('/', 1)[0]}/seg0.ts").mock(
            return_value=httpx.Response(200, content=b"AAA")
        )
        mock.get(f"{HIGH_URL.rsplit('/', 1)[0]}/seg1.ts").mock(
            return_value=httpx.Response(200, content=b"BBBB")
        )
        mock.get(f"{HIGH_URL.rsplit('/', 1)[0]}/sub/seg2.ts").mock(
            return_value=httpx.Response(200, content=b"CC")
        )
        await VideoEngine().execute(job, output_dir)

    assert page_route.call_count == 1
    report = _read_json(output_dir / "streams.json")
    assert [stream["url"] for stream in report["streams"]] == [MASTER_URL]
    assert report["streams"][0]["downloaded"] is True
    assert (output_dir / "video.ts").read_bytes() == b"AAABBBBCC"


@pytest.mark.asyncio
async def test_video_engine_sends_range_headers_for_byteranges(tmp_path):
    output_dir = tmp_path / "job"
    url = "https://cdn.test/hls/pack/index.m3u8"
    page = f'<html><body><script>var s="{url}";</script></body></html>'
    ranges: list[str | None] = []

    def ranged(request: httpx.Request) -> httpx.Response:
        ranges.append(request.headers.get("range"))
        if request.headers.get("range") == "bytes=0-999":
            return httpx.Response(206, content=b"P" * 10)
        return httpx.Response(206, content=b"Q" * 5)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(PAGE_URL).mock(return_value=httpx.Response(200, text=page))
        mock.get(url).mock(return_value=httpx.Response(200, text=RANGED_MEDIA))
        mock.get("https://cdn.test/hls/pack/pack.ts").mock(side_effect=ranged)
        await VideoEngine().execute(_job(), output_dir)

    assert ranges == ["bytes=0-999", "bytes=1000-1499", "bytes=5000-5249"]
    assert (output_dir / "video.ts").read_bytes() == b"P" * 10 + b"Q" * 10


@pytest.mark.asyncio
async def test_video_engine_stops_at_the_segment_limit(tmp_path, monkeypatch):
    output_dir = tmp_path / "job"
    monkeypatch.setattr(settings, "video_max_segments", 1)
    monkeypatch.setattr(settings, "video_max_bytes", 500_000_000)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(PAGE_URL).mock(
            return_value=httpx.Response(200, text=PAGE_WITH_INLINE_STREAM)
        )
        mock.get(MASTER_URL).mock(return_value=httpx.Response(200, text=MASTER))
        mock.get(HIGH_URL).mock(return_value=httpx.Response(200, text=MEDIA))
        mock.get(f"{HIGH_URL.rsplit('/', 1)[0]}/seg0.ts").mock(
            return_value=httpx.Response(200, content=b"AAA")
        )
        result = await VideoEngine().execute(_job(), output_dir)

    assert (output_dir / "video.ts").read_bytes() == b"AAA"
    report = _read_json(output_dir / "streams.json")
    assert report["streams"][0]["bytes"] == 3
    assert any("truncated" in log for log in result.logs)
