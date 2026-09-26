"""Tests for provenance watermarking."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Comment

from zfrog.pipeline.watermark import (
    MARK_RE,
    META_ATTR,
    META_NAME,
    Watermark,
    decode_payload,
    encode_payload,
    extract_html,
    extract_text_mark,
    inject_html,
    inject_text,
    make_mark,
    strip_text_carriers,
    verify_directory,
    verify_html,
    watermark_directory,
)
from zfrog.utils.text import extract_text

SOURCE = "https://example.com/docs/page"

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Example page</title>
</head>
<body>
  <h1>Hello world</h1>
  <p>Visible copy that has to survive watermarking unchanged.</p>
</body>
</html>
"""

NOTES = "# Notes\n\nBody copy with accents: ação, café.\n"


def _carrier_counts(html: str) -> tuple[int, int, int]:
    """Count (meta tags, html attributes, zfrog comments) in a document."""
    soup = BeautifulSoup(html, "lxml")
    metas = soup.find_all("meta", attrs={"name": META_NAME})
    attrs = sum(1 for tag in soup.find_all(True) if META_ATTR in tag.attrs)
    comments = sum(
        1
        for node in soup.find_all(string=lambda s: isinstance(s, Comment))
        if "zfrog:" in str(node)
    )
    return len(metas), attrs, comments


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """A cloned tree: one HTML page, one nested text file, one ignored file."""
    root = tmp_path / "site"
    (root / "sub").mkdir(parents=True)
    (root / "index.html").write_text(PAGE, encoding="utf-8")
    (root / "sub" / "notes.txt").write_text(NOTES, encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "notafile.html").mkdir()
    return root


class TestMakeMark:
    def test_shape_and_uniqueness(self):
        first = make_mark(SOURCE)
        second = make_mark(SOURCE)

        assert MARK_RE.fullmatch(first.mark)
        assert first.mark != second.mark
        assert first.mark < second.mark  # 14-char stamps keep marks sortable

    def test_payload_carries_source_and_version(self):
        watermark = make_mark(SOURCE)

        assert watermark.payload["mark"] == watermark.mark
        assert watermark.payload["source_url"] == SOURCE
        assert watermark.payload["created_at"] == watermark.created_at
        assert watermark.payload["tool"] == "zfrog"
        assert watermark.payload["version"]

    def test_extras_are_kept_but_cannot_spoof_core_fields(self):
        watermark = make_mark(SOURCE, {"engine": "static", "mark": "spoofed"})

        assert watermark.payload["engine"] == "static"
        assert watermark.payload["mark"] == watermark.mark
        assert watermark.payload["source_url"] == SOURCE


class TestPayloadTokens:
    def test_round_trip(self):
        watermark = make_mark(SOURCE, {"engine": "static"})
        token = encode_payload(watermark)

        assert "=" not in token and not any(char.isspace() for char in token)
        assert decode_payload(token) == watermark.payload

    @pytest.mark.parametrize(
        "token",
        [
            "",
            "not a token!!",
            "eyJtYXJrIjog",  # base64url of '{"mark": ' — truncated JSON
            "WzEsMl0",  # base64url of '[1,2]' — valid JSON, not an object
        ],
    )
    def test_corrupt_token_raises(self, token):
        with pytest.raises(ValueError):
            decode_payload(token)


class TestInjectHtml:
    def test_visible_text_is_unchanged(self):
        injected = inject_html(PAGE, make_mark(SOURCE))

        assert extract_text(injected) == extract_text(PAGE)
        assert "Visible copy that has to survive watermarking unchanged." in extract_text(injected)

    def test_adds_each_carrier_once_and_is_idempotent(self):
        watermark = make_mark(SOURCE)
        token = encode_payload(watermark)
        injected = inject_html(PAGE, watermark)

        assert _carrier_counts(injected) == (1, 1, 1)
        soup = BeautifulSoup(injected, "lxml")
        meta = soup.find("meta", attrs={"name": META_NAME})
        assert meta["content"] == token
        assert soup.head.contents[-1] is meta  # last child of <head>
        assert soup.find("html")[META_ATTR] == token
        assert injected.index(f"<!-- zfrog:{token} -->") > injected.index("</html>")

        twice = inject_html(injected, watermark)
        assert twice == injected
        assert _carrier_counts(twice) == (1, 1, 1)

    def test_fragment_without_head_still_gets_a_document(self):
        watermark = make_mark(SOURCE)
        injected = inject_html("<p>only a fragment</p>", watermark)

        soup = BeautifulSoup(injected, "lxml")
        assert soup.find("html") is not None
        assert soup.head is not None
        assert _carrier_counts(injected) == (1, 1, 1)
        assert extract_html(injected) == watermark.payload
        assert "only a fragment" in extract_text(injected)

    def test_empty_input_still_gets_a_document(self):
        watermark = make_mark(SOURCE)

        assert extract_html(inject_html("", watermark)) == watermark.payload


class TestExtractHtml:
    def test_reads_the_meta_tag(self):
        watermark = make_mark(SOURCE)

        assert extract_html(inject_html(PAGE, watermark)) == watermark.payload

    def test_survives_with_only_the_comment(self):
        watermark = make_mark(SOURCE)
        soup = BeautifulSoup(inject_html(PAGE, watermark), "lxml")
        soup.find("meta", attrs={"name": META_NAME}).decompose()
        soup.find("html").attrs.pop(META_ATTR)
        comment_only = str(soup)

        assert _carrier_counts(comment_only) == (0, 0, 1)
        assert extract_html(comment_only) == watermark.payload

    def test_survives_with_only_the_attribute(self):
        watermark = make_mark(SOURCE)
        soup = BeautifulSoup(inject_html(PAGE, watermark), "lxml")
        soup.find("meta", attrs={"name": META_NAME}).decompose()
        for node in soup.find_all(string=lambda s: isinstance(s, Comment) and "zfrog:" in str(s)):
            node.extract()
        attribute_only = str(soup)

        assert _carrier_counts(attribute_only) == (0, 1, 0)
        assert extract_html(attribute_only) == watermark.payload

    def test_corrupt_meta_falls_back_to_the_comment(self):
        watermark = make_mark(SOURCE)
        soup = BeautifulSoup(inject_html(PAGE, watermark), "lxml")
        soup.find("meta", attrs={"name": META_NAME})["content"] = "!!"
        soup.find("html").attrs.pop(META_ATTR)
        corrupted = str(soup)

        assert extract_html(corrupted) == watermark.payload

    def test_unmarked_or_corrupt_documents_return_none(self):
        assert extract_html(PAGE) is None
        assert extract_html("") is None
        assert extract_html('<html data-zfrog-provenance="!!!"><body>x</body></html>') is None
        assert (
            extract_html('<html><head><meta name="zfrog-provenance" content="!!"></head></html>')
            is None
        )


class TestVerifyHtml:
    def test_matching_watermark(self):
        watermark = make_mark(SOURCE)

        assert verify_html(inject_html(PAGE, watermark), watermark) is True

    def test_different_watermark_or_unmarked_page(self):
        watermark = make_mark(SOURCE)
        other = make_mark("https://other.example/")
        marked = inject_html(PAGE, watermark)

        assert verify_html(marked, other) is False
        assert verify_html(PAGE, watermark) is False

    def test_same_mark_from_another_source_is_rejected(self):
        watermark = make_mark(SOURCE)
        forged = Watermark(
            mark=watermark.mark,
            created_at=watermark.created_at,
            source_url="https://elsewhere.example/",
            payload={**watermark.payload, "source_url": "https://elsewhere.example/"},
        )

        assert verify_html(inject_html(PAGE, watermark), forged) is False


class TestInjectText:
    def test_visible_text_is_unchanged(self):
        watermark = make_mark(SOURCE)
        marked = inject_text(NOTES, watermark)

        assert marked.startswith(NOTES.rstrip())
        assert marked.startswith(NOTES)
        assert strip_text_carriers(marked) == NOTES
        assert marked.index(NOTES) == 0

    def test_zero_width_carrier_round_trips(self):
        watermark = make_mark(SOURCE)
        marked = inject_text(NOTES, watermark)

        token = extract_text_mark(marked)
        assert token == encode_payload(watermark)
        assert decode_payload(token)["mark"] == watermark.mark

    def test_reinjection_does_not_duplicate(self):
        watermark = make_mark(SOURCE)
        marked = inject_text(NOTES, watermark)

        assert inject_text(marked, watermark) == marked
        assert marked.count("<!-- zfrog:") == 1
        assert extract_text_mark(marked) == encode_payload(watermark)

    def test_plain_text_has_no_mark(self):
        assert extract_text_mark(NOTES) is None
        assert extract_text_mark("") is None


class TestDirectories:
    async def test_watermark_and_verify(self, site: Path):
        result = await watermark_directory(site, source_url=SOURCE)

        assert result["files"] == 2  # .png and the .html *directory* are ignored
        assert result["marked"] == 2
        assert MARK_RE.fullmatch(result["mark"])

        report = await verify_directory(site)
        assert report["files"] == 2
        assert report["marked"] == 2
        assert report["marks"] == [result["mark"]]
        assert report["sources"] == [SOURCE]

        html = (site / "index.html").read_text(encoding="utf-8")
        assert _carrier_counts(html) == (1, 1, 1)
        assert extract_text(html) == extract_text(PAGE)
        assert extract_html(html)["source_url"] == SOURCE

        text = (site / "sub" / "notes.txt").read_text(encoding="utf-8")
        text_payload = decode_payload(extract_text_mark(text))
        assert text_payload["mark"] == result["mark"]
        assert text_payload["source_url"] == SOURCE
        assert strip_text_carriers(text) == NOTES

    async def test_unmarked_tree_reports_nothing(self, site: Path):
        report = await verify_directory(site)

        assert report == {"files": 2, "marked": 0, "marks": [], "sources": []}

    async def test_given_watermark_is_reused(self, site: Path):
        watermark = make_mark(SOURCE)
        result = await watermark_directory(site, watermark=watermark)

        assert result["mark"] == watermark.mark
        assert (await verify_directory(site))["marks"] == [watermark.mark]

    async def test_repeated_runs_keep_exactly_one_carrier_set(self, site: Path):
        watermark = make_mark(SOURCE)
        first = await watermark_directory(site, watermark=watermark)
        html_first = (site / "index.html").read_text(encoding="utf-8")
        text_first = (site / "sub" / "notes.txt").read_text(encoding="utf-8")

        assert first["marked"] == 2
        assert _carrier_counts(html_first) == (1, 1, 1)
        assert html_first.count("<!-- zfrog:") == 1
        assert text_first.count("<!-- zfrog:") == 1

        second = await watermark_directory(site, watermark=watermark)
        assert second["marked"] == 2
        assert (site / "index.html").read_text(encoding="utf-8") == html_first
        assert (site / "sub" / "notes.txt").read_text(encoding="utf-8") == text_first

        newer = make_mark(SOURCE)
        await watermark_directory(site, watermark=newer)
        html_third = (site / "index.html").read_text(encoding="utf-8")
        assert _carrier_counts(html_third) == (1, 1, 1)
        assert extract_html(html_third)["mark"] == newer.mark
        assert extract_text(html_third) == extract_text(PAGE)
        assert extract_text_mark((site / "sub" / "notes.txt").read_text(encoding="utf-8")) == (
            encode_payload(newer)
        )

    async def test_markdown_files_are_marked(self, tmp_path: Path):
        root = tmp_path / "md"
        root.mkdir()
        (root / "readme.md").write_text(NOTES, encoding="utf-8")

        result = await watermark_directory(root, source_url=SOURCE)

        assert result["files"] == 1
        assert result["marked"] == 1
        marked = (root / "readme.md").read_text(encoding="utf-8")
        assert strip_text_carriers(marked) == NOTES
        assert decode_payload(extract_text_mark(marked))["source_url"] == SOURCE

    async def test_undecodable_files_are_skipped(self, tmp_path: Path):
        root = tmp_path / "mixed"
        root.mkdir()
        (root / "good.html").write_text(PAGE, encoding="utf-8")
        (root / "bad.html").write_bytes(b"\xff\xfe\x00\x00 not utf-8")

        result = await watermark_directory(root, source_url=SOURCE)

        assert result["files"] == 2
        assert result["marked"] == 1
        assert (root / "bad.html").read_bytes() == b"\xff\xfe\x00\x00 not utf-8"
        assert (await verify_directory(root))["marked"] == 1
