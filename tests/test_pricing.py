"""Tests for price monitoring (parsing, history, thresholds, snapshots)."""

import json
import logging
import stat

import pytest

from zfrog import pricing
from zfrog.config import settings
from zfrog.diff import url_slug
from zfrog.pricing import (
    Price,
    PriceChange,
    PriceTracker,
    extract_from_html,
    format_change,
    parse_prices,
    watch_url,
)

URL = "https://loja.example.com/notebook"


@pytest.fixture(autouse=True)
def _isolated_analysis(tmp_path, monkeypatch):
    """Keep price history out of the repo's real analysis/ directory."""
    monkeypatch.setattr(settings, "analysis_dir", tmp_path / "analysis")


def _price(label: str, value: float, currency: str = "BRL") -> Price:
    return Price(label=label, value=value, currency=currency, raw="", context="")


def _snapshot_file(tmp_path, url: str, captured_at: str, pages: list[dict]) -> str:
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {"url": url, "captured_at": captured_at, "engine": "mirror", "pages": pages}
        ),
        encoding="utf-8",
    )
    return str(path)


# ── Parsing ──


def test_parse_brazilian_and_us_amounts():
    assert [p.value for p in parse_prices("R$ 1.234,56")] == [1234.56]
    assert [p.value for p in parse_prices("R$ 1.234")] == [1234.0]
    assert [p.value for p in parse_prices("R$1234")] == [1234.0]
    assert [p.value for p in parse_prices("$1,234.56")] == [1234.56]
    assert [p.value for p in parse_prices("$ 1,234")] == [1234.0]
    assert [p.value for p in parse_prices("€ 89,90")] == [89.9]
    assert [p.value for p in parse_prices("£ 1.234,56")] == [1234.56]


def test_parse_assigns_currency_codes():
    assert parse_prices("R$ 1.234,56")[0].currency == "BRL"
    assert parse_prices("$1,234.56")[0].currency == "USD"
    assert parse_prices("€ 89,90")[0].currency == "EUR"


def test_numbers_without_a_currency_signal_are_not_prices():
    assert parse_prices("Publicado em 2026") == []
    assert parse_prices("10 unidades em estoque") == []
    assert parse_prices("custa 1234") == []


def test_currency_words_are_prices():
    prices = parse_prices("Notebook por 1234 reais")
    assert [p.value for p in prices] == [1234.0]
    assert prices[0].currency == "BRL"
    assert parse_prices("Notebook por 1234 BRL")[0].value == 1234.0


def test_label_comes_from_preceding_text_and_context_from_sentence():
    prices = parse_prices("O Notebook custa R$ 3.499,00 com frete grátis.")
    assert len(prices) == 1
    assert prices[0].label == "O Notebook custa"
    assert prices[0].context == "O Notebook custa R$ 3.499,00 com frete grátis."


def test_label_is_empty_without_preceding_text():
    assert parse_prices("R$ 1.234,56")[0].label == ""


def test_context_does_not_split_a_thousands_separator():
    prices = parse_prices("Preço promocional: R$ 1.234,56 hoje")
    assert prices[0].value == 1234.56
    assert "1.234,56" in prices[0].context


def test_duplicate_prices_are_collapsed():
    prices = parse_prices("Notebook R$ 1.234,56\nNotebook R$ 1.234,56")
    assert len(prices) == 1
    assert prices[0].label == "Notebook"
    # Same amount, different labels: two different offers, both kept.
    assert len(parse_prices("Notebook R$ 1.234,56\nCapa R$ 1.234,56")) == 2


def test_extract_from_html_finds_prose_and_markup_and_dedupes():
    html = """
    <html><body>
      <div class="product">
        <h2 itemprop="name">Notebook</h2>
        <span itemprop="price">R$ 3.499,00</span>
      </div>
      <p>O Notebook custa R$ 3.499,00 hoje.</p>
      <p>Frete R$ 199,90.</p>
    </body></html>
    """
    prices = extract_from_html(html)
    values = [price.value for price in prices]
    assert values.count(3499.0) == 1
    assert 199.9 in values
    structured = next(price for price in prices if price.value == 3499.0)
    assert structured.label == "Notebook"


def test_extract_from_html_reads_data_price_attributes():
    html = '<div data-price="3499.00" data-currency="BRL" data-label="Notebook Pro"></div>'
    prices = extract_from_html(html)
    assert [(p.value, p.currency, p.label) for p in prices] == [(3499.0, "BRL", "Notebook Pro")]


# ── History ──


def test_record_and_history_round_trip_oldest_first():
    tracker = PriceTracker()
    tracker.record(URL, [_price("Notebook", 3499.0)], captured_at="2026-02-01T00:00:00Z")
    tracker.record(URL, [_price("Notebook", 3199.0)], captured_at="2026-01-01T00:00:00Z")

    history = tracker.history(URL)
    points = history["notebook"]
    assert [point.value for point in points] == [3199.0, 3499.0]
    assert points[0].captured_at == "2026-01-01T00:00:00Z"
    assert tracker.labels(URL) == ["notebook"]
    assert tracker.urls() == [URL]


def test_re_recording_a_label_appends_and_filters_by_label():
    tracker = PriceTracker()
    tracker.record(URL, [_price("Notebook", 3499.0)], captured_at="2026-01-01T00:00:00Z")
    tracker.record(URL, [_price("Notebook", 3499.0)], captured_at="2026-02-01T00:00:00Z")
    tracker.record(URL, [_price("Frete", 19.9)], captured_at="2026-02-01T00:00:00Z")

    assert len(tracker.history(URL)["notebook"]) == 2
    assert list(tracker.history(URL, "Notebook ")) == ["notebook"]
    assert [point.value for point in tracker.history(URL, "frete")["frete"]] == [19.9]


def test_record_without_prices_is_a_noop():
    tracker = PriceTracker()
    assert tracker.record(URL, []) == 0
    assert tracker.history(URL) == {}
    assert not (tracker.root / f"{url_slug(URL)}.json").exists()


def test_remove_deletes_the_history_file():
    tracker = PriceTracker()
    tracker.record(URL, [_price("Notebook", 3499.0)], captured_at="2026-01-01T00:00:00Z")
    assert tracker.remove(URL) is True
    assert tracker.remove(URL) is False
    assert tracker.history(URL) == {}


def test_history_file_is_private_and_atomic():
    tracker = PriceTracker()
    tracker.record(URL, [_price("Notebook", 3499.0)], captured_at="2026-01-01T00:00:00Z")
    path = tracker.root / f"{url_slug(URL)}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(tracker.root.glob("*.tmp"))


def test_corrupt_history_reads_as_empty(tmp_path, caplog):
    tracker = PriceTracker()
    path = tracker.root / f"{url_slug(URL)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="zfrog.pricing"):
        assert tracker.history(URL) == {}
    assert any("corrupt" in record.getMessage() for record in caplog.records)


# ── Changes and thresholds ──


def test_changes_reports_percentage_and_direction():
    tracker = PriceTracker()
    tracker.record(URL, [_price("Notebook", 3499.0)], captured_at="2026-01-01T00:00:00Z")
    tracker.record(URL, [_price("Notebook", 3199.0)], captured_at="2026-02-01T00:00:00Z")
    tracker.record(URL, [_price("Frete", 10.0)], captured_at="2026-01-01T00:00:00Z")
    tracker.record(URL, [_price("Frete", 12.0)], captured_at="2026-02-01T00:00:00Z")
    tracker.record(URL, [_price("Capa", 50.0)], captured_at="2026-01-01T00:00:00Z")
    tracker.record(URL, [_price("Capa", 50.0)], captured_at="2026-02-01T00:00:00Z")

    by_label = {change.label: change for change in tracker.changes(URL)}
    assert by_label["notebook"].direction == "down"
    assert by_label["notebook"].change_pct == pytest.approx(-8.57, abs=0.01)
    assert by_label["notebook"].before == 3499.0
    assert by_label["notebook"].after == 3199.0
    assert by_label["notebook"].points == 2
    assert by_label["notebook"].first_seen == "2026-01-01T00:00:00Z"
    assert by_label["notebook"].last_seen == "2026-02-01T00:00:00Z"
    assert by_label["frete"].direction == "up"
    assert by_label["frete"].change_pct == pytest.approx(20.0)
    assert by_label["capa"].direction == "same"
    assert by_label["capa"].change_pct == 0.0


def test_significance_respects_configured_thresholds(monkeypatch):
    monkeypatch.setattr(settings, "price_alert_drop_pct", 5.0)
    monkeypatch.setattr(settings, "price_alert_rise_pct", 5.0)

    tracker = PriceTracker()
    for label, before, after in (("forte", 100.0, 92.0), ("leve", 100.0, 98.0), ("alta", 100.0, 103.0)):
        tracker.record(URL, [_price(label, before)], captured_at="2026-01-01T00:00:00Z")
        tracker.record(URL, [_price(label, after)], captured_at="2026-02-01T00:00:00Z")

    by_label = {change.label: change for change in tracker.changes(URL)}
    assert by_label["forte"].significant is True
    assert by_label["leve"].significant is False
    assert by_label["alta"].significant is False


def test_rise_threshold_is_independent_of_drop_threshold():
    tracker = PriceTracker()
    tracker.record(URL, [_price("Notebook", 100.0)], captured_at="2026-01-01T00:00:00Z")
    tracker.record(URL, [_price("Notebook", 106.0)], captured_at="2026-02-01T00:00:00Z")

    change = tracker.changes(URL, drop_pct=5.0, rise_pct=10.0)[0]
    assert change.direction == "up"
    assert change.significant is False
    assert tracker.changes(URL, drop_pct=5.0, rise_pct=3.0)[0].significant is True


def test_format_change_shows_both_values_and_percentage():
    change = PriceChange(
        label="Notebook",
        before=3499.0,
        after=3199.0,
        currency="BRL",
        change_pct=-8.573,
        direction="down",
        first_seen="2026-01-01T00:00:00Z",
        last_seen="2026-02-01T00:00:00Z",
        points=2,
        significant=True,
    )
    text = format_change(change)
    assert "3.499,00" in text
    assert "3.199,00" in text
    assert "-8.6%" in text
    assert "Notebook" in text


def test_format_change_uses_us_grouping_for_dollars():
    change = PriceChange(
        label="Laptop",
        before=1999.0,
        after=1799.0,
        currency="USD",
        change_pct=-10.0,
        direction="down",
        first_seen="2026-01-01T00:00:00Z",
        last_seen="2026-02-01T00:00:00Z",
        points=2,
        significant=True,
    )
    assert "1,999.00" in format_change(change)


# ── Snapshots ──


def test_watch_url_records_prices_from_the_latest_snapshot(tmp_path, monkeypatch):
    snapshot = _snapshot_file(
        tmp_path,
        URL,
        "2026-02-01T00:00:00Z",
        [
            {"path": "index.html", "text": "Notebook Pro R$ 3.199,00"},
            {"path": "acessorios.html", "text": "Capa R$ 99,90"},
        ],
    )
    monkeypatch.setattr(pricing, "latest_snapshot", lambda url: snapshot)

    tracker = PriceTracker()
    tracker.record(URL, [_price("Notebook Pro", 3499.0)], captured_at="2026-01-01T00:00:00Z")

    result = watch_url(URL, tracker)
    assert result["url"] == URL
    assert result["prices"] == 2
    assert len(result["changes"]) == 2
    notebook = next(change for change in result["changes"] if change["label"] == "notebook pro")
    assert notebook["direction"] == "down"
    assert notebook["before"] == 3499.0
    assert notebook["after"] == 3199.0
    assert [point.value for point in tracker.history(URL)["notebook pro"]] == [3499.0, 3199.0]


def test_watch_url_without_a_snapshot_returns_zeros(tmp_path, monkeypatch):
    monkeypatch.setattr(pricing, "latest_snapshot", lambda url: None)
    result = watch_url(URL)
    assert result == {"url": URL, "prices": 0, "changes": []}
    assert PriceTracker().history(URL) == {}


def test_extract_from_html_does_not_double_count_nested_markup():
    html = """
    <div class="product">
      <h2 itemprop="name">Notebook</h2>
      <div class="price"><span itemprop="price">R$ 3.499,00</span></div>
    </div>
    """
    prices = extract_from_html(html)
    assert [price.value for price in prices] == [3499.0]
    assert prices[0].label == "Notebook"


def test_watch_url_uses_the_real_snapshot_store(tmp_path, monkeypatch):
    """End-to-end against zfrog.diff, not a patched lookup."""
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    snapshots = tmp_path / "output" / "snapshots" / url_slug(URL)
    snapshots.mkdir(parents=True)
    (snapshots / "20260101T000000Z.json").write_text(
        json.dumps(
            {
                "url": URL,
                "captured_at": "2026-01-01T00:00:00Z",
                "engine": "mirror",
                "pages": [{"path": "index.html", "text": "Notebook R$ 3.499,00"}],
            }
        ),
        encoding="utf-8",
    )
    (snapshots / "20260201T000000Z.json").write_text(
        json.dumps(
            {
                "url": URL,
                "captured_at": "2026-02-01T00:00:00Z",
                "engine": "mirror",
                "pages": [{"path": "index.html", "text": "Notebook R$ 3.199,00"}],
            }
        ),
        encoding="utf-8",
    )

    tracker = PriceTracker(root=tmp_path / "prices")
    tracker.record(URL, [_price("Notebook", 3499.0)], captured_at="2026-01-01T00:00:00Z")

    result = watch_url(URL, tracker)
    assert result["prices"] == 1
    assert result["changes"][0]["direction"] == "down"
    assert result["changes"][0]["significant"] is True
    assert [point.value for point in tracker.history(URL)["notebook"]] == [3499.0, 3199.0]
