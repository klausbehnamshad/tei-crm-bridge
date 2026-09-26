"""TEI dates as bounded intervals, without invented precision.

``when="1889"`` covers the whole year, ``when="1889-08"`` the whole month,
``when="1889-08-02T14:30"`` that minute; ``notBefore``/``notAfter`` (or
``from``/``to``) give outer bounds. The bounds map to CIDOC CRM
``P82a_begin_of_the_begin`` and ``P82b_end_of_the_end``.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, time

from lxml import etree

_ISO = re.compile(
    r"^(?P<year>\d{4})(?:-(?P<month>\d{2})(?:-(?P<day>\d{2})"
    r"(?:T(?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2})(?P<fraction>\.\d+)?)?(?P<zone>Z|[+-]\d{2}:\d{2})?)?)?)?$"
)


@dataclass(frozen=True)
class Interval:
    begin: str | None  # xsd:dateTime, earliest possible start
    end: str | None  # xsd:dateTime, latest possible end
    source: str  # the TEI attributes used


def sort_key(value: str) -> datetime:
    """Comparable bound; offset-bearing values are ordered by their UTC instant."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _comparable(values: list[str]) -> list[datetime]:
    """Reject mixed zoned/floating dates instead of assuming a timezone."""
    keys = [sort_key(value) for value in values]
    if len({key.tzinfo is not None for key in keys}) > 1:
        raise ValueError("cannot compare dates with and without a timezone")
    return keys


def bounds(value: str) -> tuple[str, str]:
    """First and last instant of a TEI year, month, day, minute or second value."""
    match = _ISO.match(value.strip())
    if not match:
        raise ValueError(f"unsupported TEI date value {value!r}")
    parts = {key: int(part) for key, part in match.groupdict().items() if part and key not in {"zone", "fraction"}}
    fraction = match.group("fraction") or ""
    zone = match.group("zone") or ""
    if len(fraction) > 7:  # Python datetime compares microseconds; never truncate finer input silently.
        raise ValueError(f"unsupported TEI date value {value!r}: more than six fractional digits")
    if zone and zone != "Z":
        hours, minutes = int(zone[1:3]), int(zone[4:6])
        if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
            raise ValueError(f"invalid TEI date value {value!r}: timezone offset exceeds 14 hours")
    try:
        if "month" not in parts:
            first, last = date(parts["year"], 1, 1), date(parts["year"], 12, 31)
        elif "day" not in parts:
            first = date(parts["year"], parts["month"], 1)
            last = date(parts["year"], parts["month"], calendar.monthrange(parts["year"], parts["month"])[1])
        else:
            first = last = date(parts["year"], parts["month"], parts["day"])
        if "hour" in parts:
            start = time(parts["hour"], parts["minute"], parts.get("second", 0))
            stop = start.replace(second=59) if "second" not in parts else start
            return f"{first.isoformat()}T{start.isoformat()}{fraction}{zone}", f"{last.isoformat()}T{stop.isoformat()}{fraction}{zone}"
    except ValueError as error:
        raise ValueError(f"invalid TEI date value {value!r}: {error}") from None
    return f"{first.isoformat()}T00:00:00{zone}", f"{last.isoformat()}T23:59:59{zone}"


def interval(node: etree._Element) -> Interval | None:
    """Interval for a TEI ``date``; ``None`` without machine-readable attributes."""

    def attribute(name: str) -> str | None:
        return node.get(name) or node.get(f"{name}-iso")

    when = attribute("when")
    if when:
        begin, end = bounds(when)
        return Interval(begin, end, f'when="{when}"')
    lower = attribute("notBefore") or attribute("from")
    upper = attribute("notAfter") or attribute("to")
    if not lower and not upper:
        return None
    begin = bounds(lower)[0] if lower else None
    end = bounds(upper)[1] if upper else None
    if begin and end:
        first, last = _comparable([begin, end])
        if first > last:
            raise ValueError(f"lower bound {lower!r} is after upper bound {upper!r}")
    used = [f'{name}="{attribute(name)}"' for name in ("notBefore", "from", "notAfter", "to") if attribute(name)]
    return Interval(begin, end, " ".join(used))


def intersect(intervals: list[Interval]) -> Interval:
    """The time all dates of one action agree on; ValueError if they exclude each other."""
    begins = [item.begin for item in intervals if item.begin]
    ends = [item.end for item in intervals if item.end]
    _comparable(begins + ends)
    begin = max(begins, key=sort_key) if begins else None
    end = min(ends, key=sort_key) if ends else None
    if begin and end and sort_key(begin) > sort_key(end):
        raise ValueError("the dates of this action exclude each other: " + "; ".join(item.source for item in intervals))
    return Interval(begin, end, "; ".join(item.source for item in intervals))
