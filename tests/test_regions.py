"""Tests for region-aware dispatch: inventory, scoring, routing and the hint."""

from __future__ import annotations

import math

import pytest

from zfrog.config import settings
from zfrog.regions import (
    REGION_LABEL,
    Region,
    add_region_hint,
    data_residency_note,
    dispatch,
    is_eligible,
    known_regions,
    region_from_metadata,
    route,
    score_region,
)

@pytest.fixture
def local_config(monkeypatch):
    """A scheduler running in the ``local`` region with an empty inventory."""
    monkeypatch.setattr(settings, "region", "local")
    monkeypatch.setattr(settings, "worker_regions", "")
    return settings

def _equal_latency_pair() -> list[Region]:
    """Two regions that score identically, ``ap-east`` sorting first by name."""
    return [Region(name="ap-east", latency_ms=20, workers=4), Region(name="sa-east", latency_ms=20, workers=4)]

# ── inventory ────────────────────────────────────────────────────────────────

def test_known_regions_parses_inventory(local_config, monkeypatch):
    monkeypatch.setattr(settings, "worker_regions", "sa-east:20,us-east:180")

    regions = known_regions()

    assert [r.name for r in regions] == ["local", "sa-east", "us-east"]
    by_name = {r.name: r for r in regions}
    assert by_name["sa-east"].latency_ms == 20
    assert by_name["us-east"].latency_ms == 180
    assert by_name["local"].latency_ms == 0
    assert all(r.workers == 0 and r.enabled for r in regions)

def test_known_regions_blank_config_is_only_local(local_config, monkeypatch):
    assert known_regions() == [Region(name="local", latency_ms=0, workers=0, enabled=True)]

    monkeypatch.setattr(settings, "worker_regions", " , ")
    assert [r.name for r in known_regions()] == ["local"]

def test_known_regions_parses_workers_and_disabled_flag(local_config, monkeypatch):
    monkeypatch.setattr(settings, "worker_regions", "sa-east:20:4, !us-east:180:8")

    by_name = {r.name: r for r in known_regions()}

    assert (by_name["sa-east"].workers, by_name["sa-east"].enabled) == (4, True)
    assert (by_name["us-east"].workers, by_name["us-east"].enabled) == (8, False)

def test_known_regions_local_entry_is_zero_latency(monkeypatch):
    monkeypatch.setattr(settings, "region", "sa-east")
    monkeypatch.setattr(settings, "worker_regions", "sa-east:20:6,us-east:180")

    regions = known_regions()

    assert [r.name for r in regions] == ["sa-east", "us-east"]
    assert regions[0].latency_ms == 0
    assert regions[0].workers == 6

def test_known_regions_degrades_on_bad_numbers(local_config, monkeypatch):
    monkeypatch.setattr(settings, "worker_regions", "sa-east:abc:xyz")

    (region,) = [r for r in known_regions() if r.name == "sa-east"]

    assert (region.latency_ms, region.workers) == (0, 0)

# ── scoring ──────────────────────────────────────────────────────────────────

def test_score_region_prefers_lower_latency(local_config):
    near = Region(name="sa-east", latency_ms=20, workers=4)
    far = Region(name="us-east", latency_ms=180, workers=4)

    assert score_region(near) > score_region(far)

def test_score_region_gives_local_bonus_only_when_prefer_local(local_config):
    here = Region(name="local", latency_ms=0, workers=4)
    elsewhere = Region(name="sa-east", latency_ms=0, workers=4)

    assert score_region(here, prefer_local=True) > score_region(elsewhere, prefer_local=True)
    assert score_region(here, prefer_local=False) == score_region(elsewhere, prefer_local=False)

def test_zero_worker_region_is_ineligible_but_scoreable(local_config):
    idle = Region(name="sa-east", latency_ms=5, workers=0)

    assert is_eligible(idle, require_workers=True) is False
    assert is_eligible(idle, require_workers=False) is True
    assert score_region(idle) == -math.inf
    assert math.isfinite(score_region(idle, require_workers=False))

def test_disabled_region_never_scores(local_config):
    off = Region(name="sa-east", latency_ms=0, workers=8, enabled=False)

    assert is_eligible(off, require_workers=False) is False
    assert score_region(off, require_workers=False) == -math.inf

# ── routing ──────────────────────────────────────────────────────────────────

def test_route_picks_best_eligible_region(local_config):
    regions = [
        Region(name="sa-east", latency_ms=20, workers=4),
        Region(name="us-east", latency_ms=180, workers=4),
        Region(name="sa-north", latency_ms=40, workers=0),  # ineligible: no workers
    ]

    decision = route("https://example.com", regions)

    assert decision.region == "sa-east"
    assert decision.score == score_region(regions[0])
    assert "sa-east" in decision.reason
    assert "20 ms" in decision.reason

def test_route_prefers_the_local_region_when_it_can_serve(local_config):
    regions = [
        Region(name="local", latency_ms=0, workers=4),
        Region(name="sa-east", latency_ms=0, workers=100),
    ]

    nearby = route("https://example.com", regions)
    assert nearby.region == "local"
    assert nearby.score == score_region(regions[0])
    assert "local region" in nearby.reason

    assert route("https://example.com", regions, prefer_local=False).region == "sa-east"

def test_route_falls_back_to_local_when_nothing_is_eligible(local_config, monkeypatch):
    no_workers = [Region(name="sa-east", latency_ms=20), Region(name="us-east", latency_ms=180)]
    decision = route("https://example.com", no_workers)

    assert decision.region == "local"
    assert decision.score == 0.0
    assert "local" in decision.reason
    assert "no eligible region" in decision.reason

    monkeypatch.setattr(settings, "region", "sa-east")
    disabled = [Region(name="us-east", latency_ms=180, workers=8, enabled=False)]
    fallback = route("https://example.com", disabled)

    assert fallback.region == "sa-east"
    assert "sa-east" in fallback.reason
    assert "no eligible region" in fallback.reason

def test_route_is_deterministic(local_config):
    pair = _equal_latency_pair()

    first = route("https://example.com", pair, prefer_local=False)
    assert first.region == "ap-east"

    for _ in range(5):
        again = route("https://example.com", pair, prefer_local=False)
        assert (again.region, again.reason, again.score) == (first.region, first.reason, first.score)

    reversed_order = route("https://example.com", list(reversed(pair)), prefer_local=False)
    assert reversed_order.region == first.region

def test_route_never_raises_on_unparseable_url(local_config):
    decision = route("not a url at all", [Region(name="sa-east", latency_ms=5, workers=1)])

    assert decision.region == "sa-east"

def test_route_uses_host_tld_as_tie_breaker(local_config):
    pair = _equal_latency_pair()

    brazilian = route("https://loja.example.com.br/", pair, prefer_local=False)
    assert brazilian.region == "sa-east"
    assert "data residency" in brazilian.reason

    # No residency hint at all: the alphabetical order decides.
    assert route("https://shop.example.com/", pair, prefer_local=False).region == "ap-east"

def test_route_tld_affinity_matches_name_components_not_substrings(local_config):
    regions = [Region(name="usa-east", latency_ms=20, workers=4), Region(name="sa-east", latency_ms=20, workers=4)]

    # "br" maps to the components {br, sa, latam, south}; "usa" is not "sa".
    assert route("https://loja.com.br/", regions, prefer_local=False).region == "sa-east"

def test_route_tld_affinity_reads_country_label_not_only_the_last_one(local_config):
    regions = [Region(name="ap-east", latency_ms=20, workers=4), Region(name="sa-east", latency_ms=20, workers=4)]

    assert route("https://br.shop.example.com/", regions, prefer_local=False).region == "sa-east"

# ── metadata hint ────────────────────────────────────────────────────────────

def test_region_hint_round_trip_does_not_mutate_input(local_config):
    metadata = {"job": "crawl", "nested": {"depth": 2}}

    hinted = add_region_hint(metadata, "sa-east")

    assert hinted is not metadata
    assert hinted[REGION_LABEL] == "sa-east"
    assert hinted["nested"] == {"depth": 2}
    assert REGION_LABEL not in metadata
    assert metadata == {"job": "crawl", "nested": {"depth": 2}}

    assert region_from_metadata(hinted) == "sa-east"
    assert region_from_metadata(metadata) is None
    assert region_from_metadata({REGION_LABEL: "   "}) is None

def test_region_hint_overwrites_a_previous_region(local_config):
    assert add_region_hint({REGION_LABEL: "us-east"}, "sa-east")[REGION_LABEL] == "sa-east"

# ── dispatch ─────────────────────────────────────────────────────────────────

async def test_dispatch_tags_job_with_the_chosen_region(monkeypatch):
    monkeypatch.setattr(settings, "region", "local")
    monkeypatch.setattr(settings, "worker_regions", "sa-east:20:4")
    job = {"url": "https://loja.example.com.br/", "steps": ["fetch"]}

    result = await dispatch("https://loja.example.com.br/", job)

    assert result["region"] == "sa-east"
    assert "sa-east" in result["reason"]
    assert region_from_metadata(result["job"]) == "sa-east"
    assert result["job"]["steps"] == ["fetch"]
    assert result["job"] is not job
    assert REGION_LABEL not in job

async def test_dispatch_falls_back_to_local_when_inventory_is_empty(local_config):
    result = await dispatch("https://example.com", {"steps": []})

    assert result["region"] == "local"
    assert region_from_metadata(result["job"]) == "local"
    assert "no eligible region" in result["reason"]

# ── user-facing note ─────────────────────────────────────────────────────────

def test_data_residency_note_mentions_region_and_host(local_config):
    note = data_residency_note("https://loja.example.com.br/pagina", "sa-east")

    assert "sa-east" in note
    assert "loja.example.com.br" in note
    assert note.endswith(".")
    assert "\n" not in note

def test_data_residency_note_degrades_without_region_or_host(local_config):
    note = data_residency_note("", "")

    assert "local" in note
    assert note.endswith(".")
