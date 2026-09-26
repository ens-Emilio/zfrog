"""Price monitoring — pull prices out of cloned pages and alert when they move.

The crawling half of price tracking already exists: `zfrog.diff` captures a
snapshot of a site every time a delta/mirror job runs, `zfrog.cron` can schedule
those runs, and `zfrog.significance` judges whether a page changed enough to
matter. This module is the domain layer on top of them:

- :func:`parse_prices` finds amounts in arbitrary text, handling Brazilian
  (``R$ 1.234,56``) and US/European (``$ 1,234.56``, ``€ 89,90``) conventions.
- :func:`extract_from_html` runs that over a page's text and also honours
  structured markup (``itemprop="price"``, ``data-price``, ``class="price"``),
  which is where shops put the real price when prose is ambiguous.
- :class:`PriceTracker` keeps one JSON history per URL and reports the first
  point versus the last, so "the notebook dropped 8%" is a query, not a diff.
- :func:`watch_url` glues it to the snapshot store: read the latest snapshot of
  a URL, record every price in it, report what moved.

Storage is deliberately outside ``output/`` (which ``JobCleanup`` prunes after
24h): one file per URL slug under ``analysis/prices/``, written atomically and
mode 0600, because price history is user data.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from zfrog.config import settings
from zfrog.diff import latest_snapshot, url_slug
from zfrog.utils.text import extract_text

logger = logging.getLogger(__name__)

# Kept so `_latest_snapshot_for` can tell a patched collaborator from the original.
_ORIGINAL_LATEST_SNAPSHOT = latest_snapshot

# ── Currency vocabulary ──

_SYMBOL_TO_CODE = {"R$": "BRL", "US$": "USD", "$": "USD", "€": "EUR", "£": "GBP"}
_CODE_TO_SYMBOL = {"BRL": "R$", "USD": "$", "EUR": "€", "GBP": "£"}
_WORD_TO_CODE = {
    "real": "BRL",
    "reais": "BRL",
    "brl": "BRL",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "dolar": "USD",
    "dolares": "USD",
    "dólar": "USD",
    "dólares": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "gbp": "GBP",
    "libra": "GBP",
    "libras": "GBP",
}
# Currencies that write 1,234.56; everything else (BRL, EUR, GBP, ...) writes
# 1.234,56. This decides what a lone separator means: ``R$ 1.234`` is 1234,00.
_DOT_DECIMAL_CODES = {"USD", "CAD", "AUD", "NZD", "JPY", "CNY", "INR", "KRW"}

_SYMBOLS_ALT = r"R\$|US\$|€|£|\$"
_NUMBER = r"\d[\d.,]*\d|\d"

_PREFIX_PRICE_RE = re.compile(rf"(?P<sym>{_SYMBOLS_ALT})\s?(?P<num>{_NUMBER})")
_SUFFIX_PRICE_RE = re.compile(rf"(?P<num>{_NUMBER})\s?(?P<sym>{_SYMBOLS_ALT})")
_WORD_PRICE_RE = re.compile(
    rf"(?P<num>{_NUMBER})\s*(?P<word>reais|real|BRL|USD|EUR|GBP|euros?|libras?|"
    rf"d[óo]lares?|dollars?)\b",
    re.IGNORECASE,
)

_LABEL_TRIM_CHARS = " \t:|-–—•·,;<>«»←→"
_TRAILING_SYMBOL_RE = re.compile(rf"({_SYMBOLS_ALT})\s*$")
_LABEL_MAX = 60
_CONTEXT_MAX = 200

# Where structured markup advertises a price.
_HINT_SELECTOR = '[itemprop="price"], [data-price], [class*="price"], [class*="preco"]'


@dataclass
class Price:
    """A single amount found on a page."""

    label: str
    value: float
    currency: str
    raw: str
    context: str


@dataclass
class PricePoint:
    """One observation of a price at a point in time."""

    captured_at: str
    value: float
    currency: str


@dataclass
class PriceChange:
    """First-versus-last movement of one tracked label."""

    label: str
    before: float
    after: float
    currency: str
    change_pct: float
    direction: str
    first_seen: str
    last_seen: str
    points: int
    significant: bool


# ── Number and currency parsing ──


def _decimal_separator(currency: str) -> str:
    """Return the decimal separator used by a currency code (default: comma)."""
    return "." if (currency or "").upper() in _DOT_DECIMAL_CODES else ","


def _resolve_currency(token: str, currency_hint: str = "") -> str:
    """Map a currency symbol or word to an ISO-ish code.

    ``$`` is ambiguous (USD on a US site, BRL on a Brazilian one that drops the
    ``R``), so a non-USD hint wins for a bare ``$``. The hint never invents a
    currency for a number that carries no signal at all.
    """
    token = token.strip()
    hint = (currency_hint or "").strip().upper()
    code = _SYMBOL_TO_CODE.get(token)
    if code is not None:
        if code == "USD" and token == "$" and hint and hint != "USD":
            return hint
        return code
    code = _WORD_TO_CODE.get(token.lower())
    if code is not None:
        return code
    return hint


def _parse_number(raw: str, currency: str) -> float | None:
    """Convert a price-shaped number to a float, or None when malformed.

    The separator convention comes from the currency and the *last* separator
    wins when both appear: ``1.234,56`` -> 1234.56, ``1,234.56`` -> 1234.56.
    With a single separator, a 3-digit tail behind a separator the currency does
    not use for decimals is grouping, so ``R$ 1.234`` -> 1234.0 while
    ``€ 89,90`` -> 89.9.
    """
    num = raw.strip().rstrip(".,")
    if not num or not re.fullmatch(r"\d[\d.,]*", num):
        return None
    separators = [char for char in num if char in ".,"]
    if not separators:
        return float(num) if num.isdigit() else None

    decimal = _decimal_separator(currency)
    if len(set(separators)) == 2:
        last = separators[-1]
        head, _, tail = num.rpartition(last)
        head_digits = head.replace(",", "").replace(".", "")
        if not head_digits.isdigit() or not tail.isdigit():
            return None
        if len(tail) == 3:
            # e.g. ``1.234,567`` — the tail reads as a group, not as cents.
            return float(head_digits + tail)
        if len(tail) > 2:
            return None
        return float(f"{head_digits}.{tail}")

    last = separators[-1]
    parts = num.split(last)
    if not all(part.isdigit() for part in parts):
        return None
    if len(parts) > 2:
        if all(len(part) == 3 for part in parts[1:]) and len(parts[0]) <= 3:
            return float("".join(parts))
        return None
    if not parts[1]:
        return None
    if len(parts[1]) == 3 and len(parts[0]) <= 3:
        if last != decimal:
            return float(parts[0] + parts[1])
        return float(f"{parts[0]}.{parts[1]}")
    if len(parts[1]) in (1, 2):
        return float(f"{parts[0]}.{parts[1]}")
    return None


def _format_amount(value: float, currency: str) -> str:
    """Format an amount the way its currency is written, prefixed by its symbol."""
    body = f"{value:,.2f}"
    if _decimal_separator(currency) == ",":
        body = body.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    symbol = _CODE_TO_SYMBOL.get((currency or "").upper())
    return f"{symbol} {body}" if symbol else f"{currency} {body}".strip()


def _preceding_label(text: str, index: int, floor: int = 0) -> str:
    """Return the nearest preceding text on the same line, trimmed to 60 chars.

    ``floor`` is where the previous price on the line ended, so a row like
    ``Notebook R$ 3.499,00 -> R$ 3.199,00`` labels the first amount "Notebook"
    and leaves the second without a label instead of repeating the first.
    """
    line_start = text.rfind("\n", 0, index) + 1
    start = max(line_start, floor)
    prefix = _TRAILING_SYMBOL_RE.sub("", text[start:index].rstrip())
    # "hoje. Frete R$ 199,90" labels the price "Frete", not the previous sentence.
    sentence_end = max(
        (match.end() for match in re.finditer(r"[.!?]\s", prefix)),
        default=0,
    )
    prefix = " ".join(prefix[sentence_end:].rstrip(_LABEL_TRIM_CHARS).split())
    return prefix[-_LABEL_MAX:].strip() if prefix else ""


def _is_sentence_end(text: str, pos: int) -> bool:
    """Return whether ``text[pos]`` ends a sentence.

    A ``.`` between digits is a thousands separator (``R$ 1.234,56``), not a
    full stop, so it must not split the context in half.
    """
    if text[pos] not in ".!?":
        return False
    before = text[pos - 1] if pos > 0 else ""
    after = text[pos + 1] if pos + 1 < len(text) else ""
    if before.isdigit() and (after.isdigit() or after == ""):
        return False
    return after == "" or after.isspace()


def _sentence(text: str, start: int, end: int) -> str:
    """Return the sentence around a match, collapsed and capped at 200 chars.

    When the sentence is longer than the cap the window is moved so the amount
    itself stays inside it — a context that dropped the price would be useless.
    """
    line_start = text.rfind("\n", 0, start) + 1
    left = line_start - 1
    for pos in range(start - 1, line_start - 1, -1):
        if _is_sentence_end(text, pos):
            left = pos
            break
    right = len(text)
    for pos in range(end, len(text)):
        if text[pos] == "\n":
            right = pos
            break
        if _is_sentence_end(text, pos):
            right = pos + 1  # keep the full stop that closes the sentence
            break

    raw = text[left + 1:right]
    sentence = " ".join(raw.split())
    if len(sentence) > _CONTEXT_MAX:
        rel = max(0, start - (left + 1))
        low = max(0, rel - _CONTEXT_MAX // 2)
        high = min(len(raw), low + _CONTEXT_MAX)
        low = max(0, high - _CONTEXT_MAX)
        sentence = " ".join(raw[low:high].split())[:_CONTEXT_MAX]
    return sentence


# ── Text and HTML extraction ──


def parse_prices(text: str, currency_hint: str = "") -> list[Price]:
    """Find every price in a piece of text.

    Recognises symbol-first (``R$ 1.234,56``), symbol-last (``89,90 €``) and
    currency-word (``1234 reais``, ``1234 BRL``) forms. A number with no
    currency signal at all is not a price — a bare ``2026`` is a year.

    Args:
        text: Any text, typically a page's extracted text.
        currency_hint: Currency code used to disambiguate a bare ``$``.

    Returns:
        Prices in the order they appear, deduplicated by label/value/currency.
    """
    if not text:
        return []

    candidates: list[tuple[int, int, str, str]] = []
    for match in _PREFIX_PRICE_RE.finditer(text):
        candidates.append((match.start(), match.end(), match.group("sym"), match.group("num")))
    for match in _SUFFIX_PRICE_RE.finditer(text):
        candidates.append((match.start(), match.end(), match.group("sym"), match.group("num")))
    for match in _WORD_PRICE_RE.finditer(text):
        candidates.append((match.start(), match.end(), match.group("word"), match.group("num")))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    prices: list[Price] = []
    seen: set[tuple[str, float, str]] = set()
    floor = 0
    previous_end = 0
    for start, end, token, number in candidates:
        if start < floor:
            continue  # overlaps a longer match already accepted
        floor = end
        label_floor = previous_end
        previous_end = end
        currency = _resolve_currency(token, currency_hint)
        value = _parse_number(number, currency)
        if value is None:
            continue
        label = _preceding_label(text, start, floor=label_floor)
        key = (label, value, currency)
        if key in seen:
            continue
        seen.add(key)
        prices.append(
            Price(
                label=label,
                value=value,
                currency=currency,
                raw=text[start:end],
                context=_sentence(text, start, end),
            )
        )
    return prices


def _element_currency(el, text: str, currency_hint: str = "") -> str:
    """Pick the currency for a structured price element.

    Explicit markup (``data-currency``, ``itemprop="priceCurrency"``) beats a
    symbol in the text, which beats the caller's hint, which beats the
    configured default. Only used for elements that already declare themselves
    as prices, so a default here cannot turn random text into a price.
    """
    for attr in ("data-currency", "data-currency-code", "currency"):
        code = str(el.get(attr) or "").strip().upper()
        if code:
            return code
    meta = el.find(attrs={"itemprop": "priceCurrency"})
    if meta is not None:
        code = str(meta.get("content") or meta.get_text(" ", strip=True)).strip().upper()
        if code:
            return code
    symbol = re.search(rf"({_SYMBOLS_ALT})", text)
    if symbol:
        return _resolve_currency(symbol.group(1), currency_hint)
    word = re.search(
        r"\b(reais|real|BRL|USD|EUR|GBP|euros?|libras?|d[óo]lares?|dollars?)\b",
        text,
        re.IGNORECASE,
    )
    if word:
        return _resolve_currency(word.group(1), currency_hint)
    if currency_hint.strip():
        return currency_hint.strip().upper()
    return (settings.price_currency_hint or "").strip().upper() or "BRL"


def _price_from_element(el, currency_hint: str) -> Price | None:
    """Build a Price from a markup element that declares itself a price."""
    text = el.get_text(" ", strip=True)
    container = el.parent if el.parent is not None else el
    container_text = container.get_text(" ", strip=True)
    currency = _element_currency(el, text, currency_hint)

    raw = str(el.get("data-price") or "").strip()
    price: Price | None = None
    if raw:
        parsed = parse_prices(raw, currency_hint)
        if parsed:
            price = parsed[0]
        else:
            value = _parse_number(raw, currency)
            if value is not None:
                price = Price(label="", value=value, currency=currency, raw=raw, context="")
    if price is None:
        parsed = parse_prices(text, currency_hint)
        if not parsed:
            return None
        price = parsed[0]

    label = str(el.get("data-label") or el.get("aria-label") or "").strip()
    if not label:
        holder = el.find_parent(attrs={"itemtype": True}) or container
        name_el = holder.find(attrs={"itemprop": "name"}) if holder is not None else None
        if name_el is not None:
            label = name_el.get_text(" ", strip=True)

    needle = price.raw.strip()
    index = container_text.find(needle) if needle else -1
    if index < 0 and text:
        index = container_text.find(text[:20])
    if not label and index > 0:
        label = _preceding_label(container_text, index)

    price.label = " ".join(label.split())[: _LABEL_MAX]
    if index >= 0:
        price.context = _sentence(container_text, index, index + max(len(needle), 1))
    else:
        price.context = " ".join(container_text.split())[:_CONTEXT_MAX]
    return price


def extract_from_html(html: str, currency_hint: str = "") -> list[Price]:
    """Extract prices from HTML, structured markup first.

    An element carrying ``itemprop="price"``, ``data-price`` or a price-ish
    class wins for its label, and a plain-prose pass still runs afterwards so a
    price written only in a paragraph is not missed. A prose amount that matches
    a structured price is dropped: the structured one already described it.

    Args:
        html: Raw HTML.
        currency_hint: Currency code used for ambiguous amounts.

    Returns:
        Prices, structured ones first.
    """
    if not html or not html.strip():
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        logger.warning("could not parse HTML for prices")
        return []

    prices: list[Price] = []
    declared: set[tuple[float, str]] = set()
    for el in soup.select(_HINT_SELECTOR):
        price = _price_from_element(el, currency_hint)
        if price is None:
            continue
        # A wrapper (``class="price"``) and the span inside it describe the same
        # amount; the wrapper comes first and carries the better label.
        key = (price.value, price.currency)
        if key in declared:
            continue
        declared.add(key)
        prices.append(price)

    for price in parse_prices(extract_text(html), currency_hint):
        if (price.value, price.currency) in declared:
            continue
        prices.append(price)
    return prices


# ── History storage ──


def _now() -> str:
    """Return the current UTC timestamp in ISO-8601 (sortable as text)."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_label(label: str) -> str:
    """Normalize a price label into a history key."""
    return " ".join((label or "").split()).lower()


def _to_points(raw_points) -> list[PricePoint]:
    """Convert stored JSON entries into PricePoints, oldest first."""
    points: list[PricePoint] = []
    for entry in raw_points or []:
        if not isinstance(entry, dict):
            continue
        try:
            value = float(entry.get("value"))
        except (TypeError, ValueError):
            continue
        points.append(
            PricePoint(
                captured_at=str(entry.get("captured_at") or ""),
                value=value,
                currency=str(entry.get("currency") or ""),
            )
        )
    points.sort(key=lambda point: point.captured_at)
    return points


class PriceTracker:
    """Keep a per-URL price history and report movements between snapshots."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path(settings.analysis_dir) / "prices"

    def _path(self, url: str) -> Path:
        """Return the JSON history file for a URL."""
        return self.root / f"{url_slug(url)}.json"

    def _load(self, url: str) -> dict:
        """Load a history file; a corrupt or missing one reads as empty."""
        path = self._path(url)
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("ignoring corrupt price history %s: %s", path, exc)
            return {}
        if not isinstance(data, dict) or not isinstance(data.get("labels"), dict):
            logger.warning("ignoring malformed price history %s", path)
            return {}
        return data

    def _save(self, url: str, labels: dict) -> None:
        """Write the history atomically, mode 0600, replacing any previous file."""
        path = self._path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"url": url, "updated_at": _now(), "labels": labels}
        tmp = path.with_name(f"{path.name}.tmp")
        handle = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        os.chmod(path, 0o600)

    def record(self, url: str, prices: list[Price], captured_at: str = "") -> int:
        """Append one point per price, keyed by its normalized label.

        Args:
            url: Page the prices came from.
            prices: Prices extracted from that page.
            captured_at: Observation timestamp; defaults to now (UTC).

        Returns:
            How many points were appended (0 when there is nothing to record).
        """
        if not prices:
            return 0
        labels = self._load(url).get("labels") or {}
        stamp = captured_at or _now()
        count = 0
        for price in prices:
            key = _normalize_label(price.label)
            points = labels.setdefault(key, [])
            points.append(
                {
                    "captured_at": stamp,
                    "value": float(price.value),
                    "currency": price.currency,
                }
            )
            count += 1
        self._save(url, labels)
        return count

    def history(self, url: str, label: str = "") -> dict[str, list[PricePoint]]:
        """Return label -> points (oldest first), optionally for one label."""
        labels = self._load(url).get("labels") or {}
        wanted = _normalize_label(label)
        history: dict[str, list[PricePoint]] = {}
        for key, raw_points in labels.items():
            if wanted and key != wanted:
                continue
            points = _to_points(raw_points)
            if points:
                history[key] = points
        return history

    def changes(
        self,
        url: str,
        drop_pct: float | None = None,
        rise_pct: float | None = None,
    ) -> list[PriceChange]:
        """Compare the first and last point of every label.

        Args:
            url: Page to report on.
            drop_pct: Drop threshold in percent; defaults to settings.
            rise_pct: Rise threshold in percent; defaults to settings.

        Returns:
            One PriceChange per label, ordered by label.
        """
        drop_threshold = settings.price_alert_drop_pct if drop_pct is None else drop_pct
        rise_threshold = settings.price_alert_rise_pct if rise_pct is None else rise_pct

        changes: list[PriceChange] = []
        for label, points in self.history(url).items():
            first, last = points[0], points[-1]
            if first.value:
                change_pct = (last.value - first.value) / first.value * 100.0
            else:
                change_pct = 0.0
            if last.value < first.value:
                direction = "down"
            elif last.value > first.value:
                direction = "up"
            else:
                direction = "same"
            significant = False
            if direction == "down":
                significant = abs(change_pct) >= abs(drop_threshold)
            elif direction == "up":
                significant = change_pct >= abs(rise_threshold)
            changes.append(
                PriceChange(
                    label=label,
                    before=first.value,
                    after=last.value,
                    currency=last.currency or first.currency,
                    change_pct=change_pct,
                    direction=direction,
                    first_seen=first.captured_at,
                    last_seen=last.captured_at,
                    points=len(points),
                    significant=significant,
                )
            )
        changes.sort(key=lambda change: change.label)
        return changes

    def labels(self, url: str) -> list[str]:
        """Return the tracked labels for a URL, sorted."""
        return sorted(self.history(url))

    def urls(self) -> list[str]:
        """Return every URL with a stored history."""
        if not self.root.is_dir():
            return []
        found: list[str] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("ignoring corrupt price history %s: %s", path, exc)
                continue
            url = data.get("url") if isinstance(data, dict) else None
            found.append(str(url) if url else path.stem)
        return sorted(found)

    def remove(self, url: str) -> bool:
        """Delete a URL's history; returns whether a file was removed."""
        path = self._path(url)
        if not path.is_file():
            return False
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("could not remove price history %s: %s", path, exc)
            return False
        return True


# ── Reporting ──


def format_change(change: PriceChange) -> str:
    """Render a change as a Portuguese sentence with both values.

    Example: ``Notebook: R$ 3.499,00 → R$ 3.199,00 (-8.6%)``.
    """
    label = change.label or "Preço"
    before = _format_amount(change.before, change.currency)
    after = _format_amount(change.after, change.currency)
    percent = "0.0%" if change.direction == "same" else f"{change.change_pct:+.1f}%"
    return f"{label}: {before} → {after} ({percent})"


def _latest_snapshot_for(url: str) -> Path | None:
    """Return the newest snapshot for a URL, honouring a patched collaborator.

    ``latest_snapshot`` is bound at import time so callers can replace it on
    this module; a test that patches ``zfrog.diff.latest_snapshot`` instead is
    also honoured, because the name is re-read from the source module unless it
    is still the original function.
    """
    source = sys.modules.get("zfrog.diff")
    getter = getattr(source, "latest_snapshot", None) if source is not None else None
    if getter is None or getter is _ORIGINAL_LATEST_SNAPSHOT:
        getter = latest_snapshot
    return getter(url)


def watch_url(url: str, tracker: PriceTracker | None = None) -> dict:
    """Record every price in a URL's latest snapshot and report the movements.

    Args:
        url: Site whose snapshot history should be read.
        tracker: Tracker to write to; a default one is created when omitted.

    Returns:
        ``{"url", "prices", "changes"}`` — prices is the number of points
        recorded, changes the asdict of each PriceChange. With no snapshot the
        counts are zero and nothing is written.
    """
    tracker = tracker or PriceTracker()
    snapshot = _latest_snapshot_for(url)
    if snapshot is None:
        return {"url": url, "prices": 0, "changes": []}

    try:
        data = json.loads(Path(snapshot).read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("could not read snapshot %s: %s", snapshot, exc)
        return {"url": url, "prices": 0, "changes": []}

    captured_at = str(data.get("captured_at") or "")
    prices: list[Price] = []
    for page in data.get("pages") or []:
        if isinstance(page, dict):
            prices.extend(parse_prices(str(page.get("text") or "")))

    recorded = tracker.record(url, prices, captured_at=captured_at)
    changes = [asdict(change) for change in tracker.changes(url)]
    return {"url": url, "prices": recorded, "changes": changes}
