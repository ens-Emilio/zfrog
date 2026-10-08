"""Parser and describer for classic five-field cron expressions.

The five fields are, in order: minute, hour, day of month, month and day of week.
Every field accepts `*`, `*/n`, `a`, `a-b`, `a-b/n`, `a,b,c` and mixtures of those
forms (for example `1-10/2,20`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

logger = logging.getLogger(__name__)

MINUTE = "minute"
HOUR = "hour"
DAY_OF_MONTH = "day-of-month"
MONTH = "month"
DAY_OF_WEEK = "day-of-week"

# Field label, inclusive lower bound and inclusive upper bound.
# Day of week accepts 7 as an extra spelling of Sunday and normalises it to 0.
_FIELD_LIMITS: tuple[tuple[str, int, int], ...] = (
    (MINUTE, 0, 59),
    (HOUR, 0, 23),
    (DAY_OF_MONTH, 1, 31),
    (MONTH, 1, 12),
    (DAY_OF_WEEK, 0, 7),
)

_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_WEEKDAY_NAMES = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
_WEEKDAY_PLURALS = (
    "on Sundays",
    "on Mondays",
    "on Tuesdays",
    "on Wednesdays",
    "on Thursdays",
    "on Fridays",
    "on Saturdays",
)

_WEEKEND = frozenset({0, 6})


@dataclass(frozen=True)
class CronSchedule:
    """A validated cron expression.

    The five attributes hold the concrete values each field selects. The `*_star`
    flags record whether the corresponding field was written as a wildcard
    (`*` or `*/n`), which matters for the day-of-month / day-of-week rule.
    """

    minute: frozenset[int]
    hour: frozenset[int]
    dom: frozenset[int]
    month: frozenset[int]
    dow: frozenset[int]
    expr: str
    minute_star: bool = False
    hour_star: bool = False
    dom_star: bool = False
    month_star: bool = False
    dow_star: bool = False

    def matches(self, dt: datetime) -> bool:
        """Return True when `dt` (matched at minute resolution) fires this schedule.

        Standard cron semantics apply, including the day rule: when BOTH the
        day-of-month and the day-of-week fields are restricted (neither is a
        wildcard) a match on EITHER of them is enough — the classic cron OR
        behaviour. If at least one of the two is a wildcard, the restricted one
        alone decides.
        """
        if dt.minute not in self.minute or dt.hour not in self.hour or dt.month not in self.month:
            return False
        return self._day_matches(dt.date())

    def next_after(self, dt: datetime, limit_days: int = 366 * 4) -> datetime | None:
        """Return the first matching minute strictly after `dt`.

        The search walks whole days up to `limit_days` ahead, so schedules that can
        never fire (for example `0 0 30 2 *`) return None instead of looping forever.
        Timezone awareness of `dt` is preserved.
        """
        base = dt.replace(second=0, microsecond=0)
        day = base.date()
        last_day = day + timedelta(days=limit_days)
        hours = sorted(self.hour)
        minutes = sorted(self.minute)

        while day <= last_day:
            if day.month in self.month and self._day_matches(day):
                for hour in hours:
                    for minute in minutes:
                        candidate = datetime.combine(day, time(hour, minute)).replace(tzinfo=base.tzinfo)
                        if candidate > base:
                            return candidate
            day += timedelta(days=1)

        logger.debug("No occurrence found for %r in the next %d days", self.expr, limit_days)
        return None

    def _day_matches(self, day: date) -> bool:
        """Apply the cron day rule to a calendar date."""
        dom_ok = day.day in self.dom
        dow_ok = _cron_weekday(day) in self.dow
        if self.dom_star or self.dow_star:
            return dom_ok and dow_ok
        return dom_ok or dow_ok


def _cron_weekday(day: date) -> int:
    """Return the cron day-of-week number for `day` (Sunday is 0, Monday is 1)."""
    return (day.weekday() + 1) % 7


def _normalise_dow(value: int) -> int:
    """Fold the alternate Sunday spelling (7) onto 0."""
    return 0 if value == 7 else value


def _to_int(text: str, name: str, part: str) -> int:
    """Parse a non-negative integer, raising ValueError with the offending field."""
    if not text.isdigit():
        raise ValueError(f"invalid field {name}: {part!r}")
    return int(text)


def _parse_field(
    text: str,
    name: str,
    low: int,
    high: int,
    normalise=None,
) -> tuple[frozenset[int], bool]:
    """Expand one cron field into its value set plus a wildcard flag."""
    if not text:
        raise ValueError(f"field {name} is empty")
    is_star = text.startswith("*")
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise ValueError(f"invalid field {name}: {text!r}")
        base, separator, step_text = part.partition("/")
        step = 1
        if separator:
            step = _to_int(step_text, name, part)
            if step < 1:
                raise ValueError(f"step must be greater than zero in field {name}: {part!r}")
        if base == "*":
            start, end = low, high
        elif "-" in base:
            bounds = base.split("-")
            if len(bounds) != 2:
                raise ValueError(f"invalid field {name}: {part!r}")
            start = _to_int(bounds[0], name, part)
            end = _to_int(bounds[1], name, part)
            if start > end:
                raise ValueError(f"inverted range in field {name}: {part!r}")
        else:
            start = end = _to_int(base, name, part)

        for bound in (start, end):
            if not low <= bound <= high:
                raise ValueError(
                    f"value out of range {low}-{high} in field {name}: {bound}"
                )

        for value in range(start, end + 1, step):
            values.add(normalise(value) if normalise is not None else value)

    return frozenset(values), is_star


def parse_cron(expr: str) -> CronSchedule:
    """Parse a five-field cron expression.

    Raises:
        ValueError: wrong field count, unknown syntax or out-of-range values.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("empty cron expression")

    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(
            "cron expression must have 5 fields (minute hour day-of-month month day-of-week), "
            f"got {len(fields)}: {expr!r}"
        )

    parsed = []
    for field, (name, low, high) in zip(fields, _FIELD_LIMITS):
        normalise = _normalise_dow if name == DAY_OF_WEEK else None
        parsed.append(_parse_field(field, name, low, high, normalise))

    minute, hour, dom, month, dow = parsed
    return CronSchedule(
        minute=minute[0],
        hour=hour[0],
        dom=dom[0],
        month=month[0],
        dow=dow[0],
        expr=expr.strip(),
        minute_star=minute[1],
        hour_star=hour[1],
        dom_star=dom[1],
        month_star=month[1],
        dow_star=dow[1],
    )


def _join_list(items: list[str]) -> str:
    """Join human-readable items as `a, b and c`."""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _step_of(text: str) -> int | None:
    """Return the step of a bare `*/n` field, or None for any other form."""
    if text.startswith("*/") and text[2:].isdigit():
        return int(text[2:])
    return None


def _is_contiguous(values: list[int]) -> bool:
    """Return True when the sorted values form a run of consecutive integers."""
    return len(values) > 1 and values == list(range(values[0], values[-1] + 1))


def _describe_dom(days: frozenset[int], month_restricted: bool) -> str:
    """Describe a restricted day-of-month field."""
    values = sorted(days)
    suffix = "" if month_restricted else " of every month"

    if _is_contiguous(values):
        return f"from day {values[0]} to day {values[-1]}{suffix}"
    if len(values) == 1:
        return f"on day {values[0]}{suffix}"
    if len(values) == 2:
        return f"on day {values[0]} and {values[1]}{suffix}"
    return "on days " + _join_list([str(value) for value in values]) + suffix


def _describe_dow(days: frozenset[int]) -> str:
    """Describe a restricted day-of-week field."""
    values = sorted(days)

    if set(values) == _WEEKEND:
        return "on weekends"
    if len(values) == 1:
        return _WEEKDAY_PLURALS[values[0]]
    if _is_contiguous(values):
        return f"de {_WEEKDAY_NAMES[values[0]]} a {_WEEKDAY_NAMES[values[-1]]}"
    return "on days " + _join_list([_WEEKDAY_NAMES[value] for value in values])


def _describe_days(schedule: CronSchedule, month_restricted: bool) -> str:
    """Describe the day-of-month / day-of-week part of a schedule."""
    dom_restricted = not schedule.dom_star
    dow_restricted = not schedule.dow_star

    if not dom_restricted and not dow_restricted:
        return "every day"

    dom_text = _describe_dom(schedule.dom, month_restricted) if dom_restricted else ""
    dow_text = _describe_dow(schedule.dow) if dow_restricted else ""

    if dom_text and dow_text:
        return f"{dom_text} ou {dow_text}"
    return dom_text or dow_text


def _describe_months(months: frozenset[int]) -> str:
    """Describe a restricted month field."""
    values = sorted(months)
    names = [_MONTH_NAMES[value - 1] for value in values]

    if len(values) == 1:
        return f"in {names[0]}"
    if _is_contiguous(values):
        return f"from {names[0]} to {names[-1]}"
    return "in " + _join_list(names)


def _describe_time(schedule: CronSchedule, fields: list[str]) -> str:
    """Describe the minute / hour part of a schedule."""
    minutes = sorted(schedule.minute)
    hours = sorted(schedule.hour)
    minute_raw, hour_raw = fields[0], fields[1]
    all_minutes = len(minutes) == 60
    all_hours = len(hours) == 24

    if all_minutes and all_hours:
        return "every minute"

    if all_hours:
        minute_step = _step_of(minute_raw)
        if minute_step and minutes == list(range(0, 60, minute_step)):
            return f"every {minute_step} minutes"
        if minutes == [0]:
            return "every hour"
        if len(minutes) == 1:
            return f"every hour, at minute {minutes[0]:02d}"
        return "every hour, at minutes " + _join_list([f"{minute:02d}" for minute in minutes])

    hour_step = _step_of(hour_raw)
    if hour_step and hours == list(range(0, 24, hour_step)):
        if len(minutes) == 1:
            return f"every {hour_step} hours, at minute {minutes[0]:02d}"
        return f"every {hour_step} hours"

    if len(hours) == 1:
        hour = hours[0]
        if len(minutes) == 1:
            return f"at {hour:02d}:{minutes[0]:02d}"
        minute_step = _step_of(minute_raw)
        if minute_step and minutes == list(range(0, 60, minute_step)):
            return f"every {minute_step} minutes from {hour:02d}:00 to {hour:02d}:59"
        return "at " + _join_list([f"{hour:02d}:{minute:02d}" for minute in minutes])

    if len(minutes) == 1:
        minute = minutes[0]
        return f"from {hours[0]:02d}:{minute:02d} to {hours[-1]:02d}:{minute:02d}"
    return f"from {hours[0]:02d}:{minutes[0]:02d} to {hours[-1]:02d}:{minutes[-1]:02d}"


def describe(expr: str) -> str:
    """Return a short English description of a cron expression.

    Raises:
        ValueError: when `expr` is not a valid five-field cron expression.
    """
    schedule = parse_cron(expr)
    fields = expr.split()

    month_part = "" if schedule.month_star else _describe_months(schedule.month)
    day_part = _describe_days(schedule, bool(month_part))
    time_part = _describe_time(schedule, fields)

    if not month_part and day_part == "every day" and time_part.startswith("every "):
        return time_part

    head = ", ".join(part for part in (month_part, day_part) if part)
    if not head:
        return time_part
    has_weekday = any(name in head for name in _WEEKDAY_NAMES)
    separator = " " if time_part.startswith("at") and not has_weekday else ", "
    return f"{head}{separator}{time_part}"
