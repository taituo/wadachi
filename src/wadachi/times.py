"""Times (SPEC.md section 4.5): one written form, exact arithmetic, and conversion from sources."""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone

_NS = 1_000_000_000

# The one form wadachi writes.
WADACHI_TIME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{0,8}[1-9]))?Z$")

# What converters accept from sources: RFC 3339, including its lowercase and
# space-separated variants, with or without a zone.
_SOURCE_TIME = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?([Zz]|[+-]\d{2}:\d{2})?$"
)


def _epoch_ns(y: int, mo: int, d: int, h: int, mi: int, s: int, frac: str, offset_s: int) -> int:
    """Nanoseconds since the epoch; raises ValueError for a time that does not exist."""
    if not 1 <= mo <= 12 or not 1 <= d <= calendar.monthrange(y, mo)[1]:
        raise ValueError("no such date")
    if h > 23 or mi > 59 or s > 60:
        raise ValueError("no such time of day")
    leap = 1 if s == 60 else 0
    seconds = calendar.timegm((y, mo, d, h, mi, s - leap, 0, 0, 0)) - offset_s
    if leap and seconds % 86400 != 86399:
        # A leap second exists only as 23:59:60 in UTC (SPEC.md section 4.5).
        raise ValueError("a leap second is only 23:59:60 UTC")
    return (seconds + leap) * _NS + int((frac or "").ljust(9, "0"))


def instant_ns(value: str) -> int:
    """Nanoseconds since the epoch for a time in wadachi's form.

    A leap second counts as the second after :59. Raises ValueError if the
    value is not in the form, or names a time that does not exist.
    """
    m = WADACHI_TIME.match(value)
    if not m:
        raise ValueError(f"not a wadachi time: {value!r}")
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    return _epoch_ns(y, mo, d, h, mi, s, m.group(7), 0)


def _format(ns: int, leap: bool) -> str:
    seconds, frac = divmod(ns, _NS)
    if leap:
        seconds -= 1
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    text = dt.strftime("%Y-%m-%dT%H:%M:") + ("60" if leap else dt.strftime("%S"))
    fraction = f"{frac:09d}".rstrip("0")
    return text + ("." + fraction if fraction else "") + "Z"


def from_source(value: str) -> str | None:
    """Convert a source's RFC 3339 time to wadachi's form.

    Returns None when the value has no zone, more than nine fractional digits,
    or names a time that does not exist: such values stay in `raw`.
    """
    m = _SOURCE_TIME.match(value)
    if not m or not m.group(8):
        return None
    zone = m.group(8)
    offset = 0
    if zone not in ("Z", "z"):
        oh, om = int(zone[1:3]), int(zone[4:6])
        if oh > 23 or om > 59:
            return None
        offset = (1 if zone[0] == "+" else -1) * (oh * 3600 + om * 60)
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    try:
        return _format(_epoch_ns(y, mo, d, h, mi, s, m.group(7), offset), leap=(s == 60))
    except (ValueError, OverflowError, OSError):
        return None  # no such time, or outside the years 1 to 9999 in UTC


def from_unix(seconds: int, nanos: int = 0) -> str:
    """Convert a Unix time, given as integer seconds and nanoseconds, to wadachi's form.

    A Unix time a source gives as a non-integer number is not converted: its
    decimal value is not exact, so it stays in `raw` (SPEC.md section 4.5).
    """
    if not isinstance(seconds, int) or not isinstance(nanos, int) or isinstance(seconds, bool):
        raise TypeError("Unix times convert exactly only from integers")
    return _format(seconds * _NS + nanos, leap=False)
