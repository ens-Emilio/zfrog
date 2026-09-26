"""Fidelity Score — measures how faithfully a clone matches the original.

Four sub-scores (0-100 each):
1. Visual: pixel diff between screenshots
2. Structural: DOM/HTML similarity
3. Text: content similarity
4. Assets: file coverage (what % of original assets are present)

Composite score = weighted average (configurable).
"""

from __future__ import annotations

import asyncio
import difflib
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz


@dataclass
class FidelityResult:
    """Complete fidelity score breakdown."""
    visual: float = 0.0       # 0-100
    structural: float = 0.0   # 0-100
    text: float = 0.0         # 0-100
    assets: float = 0.0       # 0-100
    composite: float = 0.0    # 0-100 weighted
    details: dict = field(default_factory=dict)


# Default weights
DEFAULT_WEIGHTS = {
    "visual": 0.25,
    "structural": 0.30,
    "text": 0.30,
    "assets": 0.15,
}


def compute_fidelity(
    original_html: str,
    clone_html: str,
    original_files: list[Path] | None = None,
    clone_files: list[Path] | None = None,
    weights: dict[str, float] | None = None,
) -> FidelityResult:
    """Compute fidelity score between original and clone.

    Args:
        original_html: HTML content of the original page.
        clone_html: HTML content of the clone.
        original_files: List of files in original (for asset coverage).
        clone_files: List of files in clone (for asset coverage).
        weights: Custom weights for sub-scores.

    Returns:
        FidelityResult with all sub-scores and composite.
    """
    weights = weights or DEFAULT_WEIGHTS

    visual = _score_visual_similarity(original_html, clone_html)
    structural = _score_structural_similarity(original_html, clone_html)
    text = _score_text_similarity(original_html, clone_html)
    assets = _score_asset_coverage(original_files or [], clone_files or [])

    composite = (
        visual * weights.get("visual", 0.25)
        + structural * weights.get("structural", 0.30)
        + text * weights.get("text", 0.30)
        + assets * weights.get("assets", 0.15)
    )

    return FidelityResult(
        visual=round(visual, 1),
        structural=round(structural, 1),
        text=round(text, 1),
        assets=round(assets, 1),
        composite=round(min(100, max(0, composite)), 1),
        details={
            "weights": weights,
            "original_length": len(original_html),
            "clone_length": len(clone_html),
        },
    )


def _score_visual_similarity(original: str, clone: str) -> float:
    """Score based on structural line-by-line similarity (proxy for visual).

    Since we can't run a real browser here, we compare the HTML line structure
    as a proxy for visual similarity.
    """
    orig_lines = [l.strip() for l in original.splitlines() if l.strip()]
    clone_lines = [l.strip() for l in clone.splitlines() if l.strip()]

    if not orig_lines and not clone_lines:
        return 100.0
    if not orig_lines or not clone_lines:
        return 0.0

    # Use SequenceMatcher for line-level similarity
    matcher = difflib.SequenceMatcher(None, orig_lines, clone_lines)
    ratio = matcher.ratio()
    return ratio * 100


def _score_structural_similarity(original: str, clone: str) -> float:
    """Score based on HTML tag structure similarity."""
    import re

    def extract_tags(html: str) -> list[str]:
        """Extract opening tags in order."""
        return re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)\b", html.lower())

    orig_tags = extract_tags(original)
    clone_tags = extract_tags(clone)

    if not orig_tags and not clone_tags:
        return 100.0
    if not orig_tags or not clone_tags:
        return 0.0

    # Count tag occurrences
    from collections import Counter
    orig_counts = Counter(orig_tags)
    clone_counts = Counter(clone_tags)

    # Compare tag distributions
    all_tags = set(orig_counts.keys()) | set(clone_counts.keys())
    if not all_tags:
        return 100.0

    matches = 0
    for tag in all_tags:
        orig_c = orig_counts.get(tag, 0)
        clone_c = clone_counts.get(tag, 0)
        if orig_c > 0 and clone_c > 0:
            matches += min(orig_c, clone_c)

    total = max(sum(orig_counts.values()), sum(clone_counts.values()))
    return (matches / total * 100) if total > 0 else 100.0


def _score_text_similarity(original: str, clone: str) -> float:
    """Score based on text content similarity using rapidfuzz."""
    import re

    def extract_text(html: str) -> str:
        """Extract visible text from HTML."""
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    orig_text = extract_text(original)
    clone_text = extract_text(clone)

    if not orig_text and not clone_text:
        return 100.0
    if not orig_text or not clone_text:
        return 0.0

    # Token sort ratio is tolerance to word order differences
    return fuzz.token_sort_ratio(orig_text, clone_text)


def _score_asset_coverage(original_files: list[Path], clone_files: list[Path]) -> float:
    """Score based on what percentage of original files exist in the clone."""
    if not original_files:
        return 100.0

    # Normalize paths to just filenames for comparison
    orig_names = {f.name for f in original_files}
    clone_names = {f.name for f in clone_files}

    if not orig_names:
        return 100.0

    covered = orig_names & clone_names
    return (len(covered) / len(orig_names)) * 100
