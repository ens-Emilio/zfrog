"""Tests for design token extraction.

The browser pass is not exercised here — it needs Chromium and a live page. What is
tested is the interpretation: colour parsing, ranking, role assignment and the report.
Those are where a silent mistake would produce a plausible-but-wrong palette.
"""

from __future__ import annotations

import json

from zfrog.tokens import (
    ColorUse,
    DesignTokens,
    assign_roles,
    extract_tokens,
    parse_color,
    tokens_to_json,
    tokens_to_markdown,
)


class TestParseColor:
    def test_rgb_and_alpha(self):
        assert parse_color("rgb(12, 27, 20)") == ("#0C1B14", 1.0)
        assert parse_color("rgba(59, 212, 135, 0.5)") == ("#3BD487", 0.5)
        assert parse_color("rgba(255, 255, 255, 1)") == ("#FFFFFF", 1.0)

    def test_percentage_alpha(self):
        assert parse_color("rgba(1, 2, 3, 40%)") == ("#010203", 0.4)

    def test_out_of_range_channels_are_clamped(self):
        # A browser can report a rounded 255.4; clamping beats an invalid hex.
        assert parse_color("rgb(300, -5, 128)") == ("#FF0080", 1.0)

    def test_unsupported_syntaxes_return_none(self):
        # The point of returning None: the caller counts them instead of guessing.
        assert parse_color("color(srgb 0.1 0.2 0.3)") is None
        assert parse_color("transparent") is None
        assert parse_color("") is None
        assert parse_color("currentColor") is None

    def test_uppercase_hex(self):
        assert parse_color("rgb(171, 205, 239)") == ("#ABCDEF", 1.0)


class TestAssignRoles:
    def test_most_used_is_primary(self):
        palette = [ColorUse("#111111", 100), ColorUse("#222222", 50)]
        assign_roles(palette)
        assert palette[0].role == "primary"

    def test_accent_skips_neutrals(self):
        """A grey-heavy page must not report grey as its brand colour."""
        palette = [
            ColorUse("#111111", 100),  # primary (page background)
            ColorUse("#333333", 80),  # neutral: too desaturated for accent
            ColorUse("#888888", 70),  # neutral
            ColorUse("#FF0000", 5),  # saturated: the actual accent
        ]
        assign_roles(palette)
        assert palette[0].role == "primary"
        assert palette[3].role == "accent"
        assert palette[1].role is None
        assert palette[2].role is None

    def test_secondary_takes_the_next_saturated_colour(self):
        palette = [
            ColorUse("#111111", 100),
            ColorUse("#FF0000", 20),
            ColorUse("#00FF00", 10),
        ]
        assign_roles(palette)
        assert [c.role for c in palette] == ["primary", "accent", "secondary"]

    def test_empty_palette_is_not_an_error(self):
        palette: list[ColorUse] = []
        assign_roles(palette)
        assert palette == []

    def test_saturation_of_greys_is_zero(self):
        assert ColorUse("#808080", 1).saturation == 0.0
        assert ColorUse("#FF0000", 1).saturation > 0.9


class TestExtractTokens:
    def _snapshot(self):
        return {
            "url": "https://exemplo.com/",
            "title": "Exemplo",
            "elements": 3,
            "colors": {
                "rgb(255, 255, 255)": {"count": 5, "props": {"color": 5}},
                "rgba(255, 255, 255, 1)": {"count": 2, "props": {"backgroundColor": 2}},
                "rgba(0, 0, 0, 0)": {"count": 9, "props": {"backgroundColor": 9}},
                "color(srgb 0 0 0)": {"count": 4, "props": {"color": 4}},
            },
            "fonts": {
                "Inter": {
                    "count": 10,
                    "sizes": {"16px": 8, "24px": 2},
                    "weights": {"400": 8, "700": 2},
                    "headings": 2,
                    "body": 6,
                }
            },
            "sizes": {"16px": 10, "24px": 2},
            "weights": {"400": 10, "700": 2},
            "padding": {"0px": 4, "16px": 6},
            "margin": {"0px": 9, "8px": 1},
            "radii": {"0px": 3, "8px": 2},
            "shadows": {"rgba(0, 0, 0, 0.1) 0px 1px 2px 0px": 1},
            "images": [{"src": "https://exemplo.com/a.png", "w": 100, "h": 50, "alt": "A"}],
            "backgrounds": ["https://exemplo.com/bg.jpg"],
        }

    def test_merges_the_same_colour_written_two_ways(self):
        """`rgb(255,255,255)` and `rgba(255,255,255,1)` are one colour, not two."""
        tokens = extract_tokens(self._snapshot())
        white = [c for c in tokens.palette if c.hex == "#FFFFFF"]
        assert len(white) == 1
        assert white[0].count == 7
        assert white[0].properties == {"color": 5, "backgroundColor": 2}

    def test_fully_transparent_colours_are_dropped(self):
        tokens = extract_tokens(self._snapshot())
        assert "#000000" not in tokens.hex_palette

    def test_unreadable_syntaxes_are_counted_not_guessed(self):
        tokens = extract_tokens(self._snapshot())
        assert tokens.unreadable_colors == 4

    def test_zero_padding_and_margin_are_dropped_from_the_ranking(self):
        tokens = extract_tokens(self._snapshot())
        assert ("0px", 4) not in tokens.padding
        assert ("16px", 6) in tokens.padding
        assert ("0px", 9) not in tokens.margin
        # Radii keep 0px: "no rounding anywhere" is itself a design decision.
        assert ("0px", 3) in tokens.radii

    def test_ranking_is_by_count_then_value(self):
        tokens = extract_tokens(self._snapshot())
        assert tokens.font_sizes[0] == ("16px", 10)
        assert tokens.font_sizes[1] == ("24px", 2)

    def test_fonts_carry_sizes_weights_and_where_they_are_used(self):
        tokens = extract_tokens(self._snapshot())
        font = tokens.fonts[0]
        assert font.family == "Inter"
        assert font.headings == 2
        assert font.body == 6
        assert list(font.sizes)[0] == "16px"

    def test_assets_include_images_and_backgrounds(self):
        tokens = extract_tokens(self._snapshot())
        kinds = {asset.kind for asset in tokens.assets}
        assert kinds == {"img", "background"}
        image = next(a for a in tokens.assets if a.kind == "img")
        assert (image.width, image.height, image.alt) == (100, 50, "A")

    def test_empty_snapshot_yields_empty_tokens(self):
        tokens = extract_tokens({})
        assert tokens.palette == []
        assert tokens.fonts == []
        assert tokens.hex_palette == []

    def test_json_round_trips(self):
        tokens = extract_tokens(self._snapshot())
        payload = json.loads(tokens_to_json(tokens))
        assert payload["title"] == "Exemplo"
        assert payload["unreadable_colors"] == 4
        assert payload["palette"][0]["hex"] == "#FFFFFF"


class TestMarkdown:
    def test_report_names_the_palette_roles_and_the_unreadable_note(self):
        tokens = DesignTokens(
            url="https://exemplo.com/",
            title="Exemplo",
            palette=[ColorUse("#0B120E", 10, {"backgroundColor": 10}, role="primary")],
            unreadable_colors=3,
        )
        report = tokens_to_markdown(tokens)
        assert "# Design tokens — Exemplo" in report
        assert "`#0B120E` ×10" in report
        assert "*primary*" in report
        assert "3 uso(s) de cor em sintaxe não suportada" in report

    def test_empty_token_set_does_not_crash(self):
        report = tokens_to_markdown(DesignTokens())
        assert "Design tokens" in report
