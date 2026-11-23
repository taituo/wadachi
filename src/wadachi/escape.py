"""The characters wadachi writes as %XX in src keys and digest paths (SPEC.md section 6).

One explicit list, so every implementation in every language escapes the same
characters: Unicode's White_Space property, plus the general categories Cc
(control), Cf (format, such as U+200B and U+FEFF), Zl and Zp, as of Unicode
15.1. A test keeps the JSON Schema's src pattern in step with this list.
"""

from __future__ import annotations

from bisect import bisect_right

ESCAPED_RANGES: tuple[tuple[int, int], ...] = (
    (0x0000, 0x0020),
    (0x007F, 0x00A0),
    (0x00AD, 0x00AD),
    (0x0600, 0x0605),
    (0x061C, 0x061C),
    (0x06DD, 0x06DD),
    (0x070F, 0x070F),
    (0x0890, 0x0891),
    (0x08E2, 0x08E2),
    (0x1680, 0x1680),
    (0x180E, 0x180E),
    (0x2000, 0x200F),
    (0x2028, 0x202F),
    (0x205F, 0x2064),
    (0x2066, 0x206F),
    (0x3000, 0x3000),
    (0xFEFF, 0xFEFF),
    (0xFFF9, 0xFFFB),
    (0x110BD, 0x110BD),
    (0x110CD, 0x110CD),
    (0x13430, 0x1343F),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0001, 0xE0001),
    (0xE0020, 0xE007F),
)
_STARTS = [a for a, _ in ESCAPED_RANGES]


def needs_escape(ch: str) -> bool:
    """True for the characters in ESCAPED_RANGES."""
    cp = ord(ch)
    i = bisect_right(_STARTS, cp) - 1
    return i >= 0 and cp <= ESCAPED_RANGES[i][1]


def percent_escape(text: str, also: str = "%") -> str:
    """Write `also` and every character in ESCAPED_RANGES as %XX per UTF-8 byte, in uppercase hex."""
    out = []
    for ch in text:
        if ch in also or needs_escape(ch):
            out.append("".join(f"%{b:02X}" for b in ch.encode("utf-8")))
        else:
            out.append(ch)
    return "".join(out)


def bmp_class() -> str:
    """The ranges below U+10000 as a regular expression class body, for the JSON Schema.

    Code points above U+FFFF are matched differently by regular expression
    engines with and without Unicode mode, so the schema checks only these;
    the validator checks the full list.
    """
    parts = []
    for a, b in ESCAPED_RANGES:
        if a > 0xFFFF:
            break
        parts.append(f"\\u{a:04X}" if a == b else f"\\u{a:04X}-\\u{b:04X}")
    return "".join(parts)
