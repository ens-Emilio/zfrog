"""Region-aware dispatch: keep work close to the data, and say where it happens.

This is the code half of "edge computing": nothing is provisioned here. The
module only makes the routing decision explicit, pure and testable — which
region should process a URL, why, and how that choice is recorded on a job or a
Kubernetes manifest so a worker can advertise where it runs.

Two inputs come from configuration: ``settings.region`` is where this process
runs, and ``settings.worker_regions`` is the inventory it may dispatch to
(``name[:latency_ms[:workers]]``, comma-separated, ``!`` prefix to disable).
The scoring and the residency tie-break are deliberately coarse heuristics and
are documented next to the code that applies them; a real deployment swaps the
inventory (``known_regions``) while keeping this contract.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

from zfrog.config import settings

logger = logging.getLogger(__name__)

#: Metadata key used on jobs / Kubernetes manifests to pin a workload's region.
REGION_LABEL: Final[str] = "zfrog/region"

# Scoring constants (see ``score_region`` for the formula).
_BASE_SCORE: Final[float] = 100.0
_LATENCY_PENALTY_PER_MS: Final[float] = 0.1
_WORKER_BONUS_PER_WORKER: Final[float] = 0.05
_MAX_WORKER_BONUS: Final[float] = 5.0
_LOCAL_BONUS: Final[float] = 25.0
_TIE_EPSILON: Final[float] = 1e-9

# Coarse country/TLD → region-name affinity, used only to break exact ties.
# Keys are the last label of the host (or any label that is a country code).
# Values are single components of a region name, matched exactly against the
# components of the name split on ``-`` / ``_`` (so ``.br`` matches ``sa-east``
# but not ``usa-east``).
_TLD_AFFINITY: Final[dict[str, tuple[str, ...]]] = {
    "br": ("br", "sa", "latam", "south"),
    "ar": ("ar", "sa", "latam", "south"),
    "cl": ("cl", "sa", "latam", "south"),
    "co": ("co", "sa", "latam", "south"),
    "mx": ("mx", "latam", "north"),
    "pt": ("pt", "eu", "europe", "iberia"),
    "es": ("es", "eu", "europe", "iberia"),
    "de": ("de", "eu", "europe"),
    "fr": ("fr", "eu", "europe"),
    "it": ("it", "eu", "europe"),
    "nl": ("nl", "eu", "europe"),
    "gb": ("gb", "uk", "eu", "europe"),
    "uk": ("gb", "uk", "eu", "europe"),
    "us": ("us", "na", "north"),
    "ca": ("ca", "na", "north"),
    "jp": ("jp", "ap", "asia"),
    "in": ("in", "ap", "asia"),
    "sg": ("sg", "ap", "asia"),
    "au": ("au", "ap", "oceania"),
    "za": ("za", "af", "africa"),
}

@dataclass
class Region:
    """A place work can run: how far it is, and how much capacity it has."""

    name: str
    latency_ms: int = 0
    workers: int = 0
    enabled: bool = True

@dataclass
class RouteDecision:
    """The outcome of a routing decision: where, why, and with what score."""

    region: str
    reason: str
    score: float

def _local_name() -> str:
    """Name of the region this process runs in (never empty)."""
    return (settings.region or "local").strip() or "local"

def _parse_int(value: str, *, field: str, entry: str) -> int:
    """Parse an optional integer field, degrading to 0 with a warning."""
    text = value.strip()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        logger.warning("regions: %s inválido em %r: %r", field, entry, value)
        return 0

def _parse_region(entry: str, local: str) -> Region:
    """Parse one ``[!]name[:latency_ms[:workers]]`` inventory entry."""
    enabled = not entry.startswith("!")
    body = entry[1:] if entry.startswith("!") else entry
    parts = body.split(":")
    name = parts[0].strip()
    latency = _parse_int(parts[1], field="latency_ms", entry=entry) if len(parts) > 1 else 0
    workers = _parse_int(parts[2], field="workers", entry=entry) if len(parts) > 2 else 0
    if name == local:
        # The local region is by definition at zero distance.
        latency = 0
    return Region(name=name, latency_ms=latency, workers=workers, enabled=enabled)

def known_regions() -> list[Region]:
    """Regions this scheduler may dispatch to, local one first.

    Parsed from ``settings.worker_regions`` (``name[:latency_ms[:workers]]``,
    comma-separated, ``!`` prefix disables a region). ``settings.region`` is
    always present with latency 0; an empty inventory yields just that region.
    """
    local = _local_name()
    parsed: list[Region] = []
    seen: set[str] = set()
    for raw in (settings.worker_regions or "").split(","):
        entry = raw.strip()
        if not entry:
            continue
        region = _parse_region(entry, local)
        if not region.name:
            logger.warning("regions: entrada sem nome ignorada: %r", raw)
            continue
        if region.name in seen:
            continue
        seen.add(region.name)
        parsed.append(region)

    if local in seen:
        local_region = next(r for r in parsed if r.name == local)
        return [local_region, *(r for r in parsed if r.name != local)]
    return [Region(name=local), *parsed]

def is_eligible(region: Region, *, require_workers: bool = True) -> bool:
    """Whether ``region`` can take work at all.

    A disabled region is never eligible. When ``require_workers`` is set, a
    region advertising no worker is skipped too — dispatching to it would only
    queue the job somewhere nobody is listening.
    """
    if not region.enabled:
        return False
    if require_workers and region.workers <= 0:
        return False
    return True

def score_region(
    region: Region,
    *,
    prefer_local: bool = True,
    require_workers: bool = True,
) -> float:
    """Score a region for dispatch; higher is better.

    Formula (all terms additive)::

        score = 100.0
              - latency_ms * 0.1          # 100 ms costs 10 points
              + min(workers * 0.05, 5.0)  # capacity, capped at 20 workers' worth
              + 25.0                      # only if prefer_local and region is local

    Ineligible regions (see :func:`is_eligible`) score ``-inf`` so they can
    never win a comparison, whatever their latency looks like.
    """
    if not is_eligible(region, require_workers=require_workers):
        return -math.inf

    score = _BASE_SCORE - region.latency_ms * _LATENCY_PENALTY_PER_MS
    score += min(region.workers * _WORKER_BONUS_PER_WORKER, _MAX_WORKER_BONUS)
    if prefer_local and region.name == _local_name():
        score += _LOCAL_BONUS
    return score

def _name_parts(name: str) -> set[str]:
    """Region name split into comparable components (``sa-east`` → {sa, east})."""
    return {part for part in name.lower().replace("_", "-").split("-") if part}

def _residency_tokens(url: str) -> set[str]:
    """Region-name components hinted at by the URL's host, coarse by design.

    Takes the last label of the host (``example.com.br`` → ``br``) plus any
    label that is a known country code (``br.shop.com`` → ``br``) and expands
    it through :data:`_TLD_AFFINITY`. Unknown labels yield no affinity, so a
    plain ``.com`` never prefers anything.
    """
    host = (urlparse(url).hostname or "").lower()
    labels = [label for label in host.split(".") if label]
    if not labels:
        return set()

    codes = {labels[-1]}
    codes.update(label for label in labels if label in _TLD_AFFINITY)

    tokens: set[str] = set()
    for code in codes:
        tokens.update(_TLD_AFFINITY.get(code, (code,)))
    return tokens

def _matches_residency(region: Region, tokens: set[str]) -> bool:
    """Whether the region's name carries any of the host's affinity tokens."""
    return bool(tokens & _name_parts(region.name))

def _describe(region: Region, score: float, *, residency: bool) -> str:
    """Human-readable (Portuguese) justification for a chosen region."""
    bits = [f"latência {region.latency_ms} ms", f"{region.workers} worker(s)"]
    if region.name == _local_name():
        bits.append("região local")
    if residency:
        bits.append("residência de dados pelo domínio")
    return f"{region.name}: " + ", ".join(bits) + f" (pontuação {score:.2f})"

def route(
    url: str,
    regions: list[Region] | None = None,
    prefer_local: bool = True,
) -> RouteDecision:
    """Pick the best eligible region for ``url``; never raises.

    ``regions`` defaults to :func:`known_regions`. The winner is the highest
    :func:`score_region` among eligible regions; exact ties are broken by the
    URL's residency hint (:func:`_residency_tokens`) and then by name, so the
    result is deterministic for the same inputs.

    ``url`` participates because a real deployment pins data residency by host:
    the TLD / country label is a coarse hint that a ``.br`` site is better
    served by ``sa-east`` than by ``us-east`` when both score the same. When no
    region is eligible — everything disabled, or nobody advertising workers —
    the decision falls back to the local region (``score`` 0.0) and says so in
    ``reason``.
    """
    available = list(regions) if regions is not None else known_regions()
    local = _local_name()

    scored = [
        (score_region(region, prefer_local=prefer_local), region)
        for region in available
        if is_eligible(region)
    ]
    if not scored:
        return RouteDecision(
            region=local,
            reason=(
                "nenhuma região elegível (desativada ou sem workers); "
                f"processando na região local {local}"
            ),
            score=0.0,
        )

    best = max(score for score, _ in scored)
    tied = [(score, region) for score, region in scored if best - score <= _TIE_EPSILON]

    tokens = _residency_tokens(url)
    preferred = [region for _, region in tied if _matches_residency(region, tokens)]
    candidates = preferred or [region for _, region in tied]
    chosen = min(candidates, key=lambda region: region.name)

    return RouteDecision(
        region=chosen.name,
        reason=_describe(chosen, best, residency=chosen in preferred),
        score=best,
    )

def add_region_hint(metadata: dict, region: str) -> dict:
    """Copy of ``metadata`` carrying the ``zfrog/region`` hint.

    The input is never mutated: callers attach the result to a job payload or a
    Kubernetes manifest.
    """
    return {**metadata, REGION_LABEL: region}

def region_from_metadata(metadata: dict) -> str | None:
    """Read the ``zfrog/region`` hint back; ``None`` when absent or blank."""
    value = metadata.get(REGION_LABEL)
    if value is None:
        return None
    text = str(value).strip()
    return text or None

async def dispatch(url: str, job: dict, regions: list[Region] | None = None) -> dict:
    """Decide where ``job`` for ``url`` should run and tag it accordingly.

    Returns ``{"region", "reason", "job"}`` where ``job`` is a copy of the input
    carrying the region hint. Nothing is started here: the caller (scheduler or
    operator) owns execution, which keeps this pure and testable.
    """
    decision = route(url, regions)
    return {
        "region": decision.region,
        "reason": decision.reason,
        "job": add_region_hint(job, decision.region),
    }

def data_residency_note(url: str, region: str) -> str:
    """One-sentence Portuguese note telling the user where the copy is processed."""
    host = urlparse(url).hostname or url.strip() or "esta página"
    target = (region or "").strip() or _local_name()
    return f"Os dados de {host} serão processados na região {target}."
