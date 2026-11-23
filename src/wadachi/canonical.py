"""Canonical JSON serialisation, as defined by RFC 8785 (JCS).

Every line of a wadachi file is serialised this way, so two conversions of the
same source can be compared byte for byte. Two rules from SPEC.md section 2
apply on top: strings must be valid Unicode (RFC 8785 requires an error for
lone surrogates), and no number may exceed 2^53 - 1 in magnitude (write it as
a string instead), so every reader gets back exactly what was written.
"""

from __future__ import annotations

import math
from decimal import Decimal

MAX_SAFE_INTEGER = 2**53 - 1

_SHORT_ESCAPES = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
    0x22: '\\"',
    0x5C: "\\\\",
}


class CanonicalError(ValueError):
    """A value that has no canonical form under SPEC.md section 2."""


def dumps(value: object) -> str:
    """Serialise a JSON value canonically (RFC 8785). Returns a str."""
    parts: list[str] = []
    _write(value, parts)
    return "".join(parts)


def _write(value: object, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise CanonicalError(f"the number {value} exceeds 2^53 - 1; write it as a string")
        out.append(str(value))
    elif isinstance(value, float):
        out.append(_number(value))
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _write(item, out)
        out.append("]")
    elif isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise TypeError(f"object keys must be strings, not {type(key).__name__}")
        out.append("{")
        # RFC 8785 sorts keys by their UTF-16 code units. Comparing big-endian
        # UTF-16 bytes gives exactly that order. Keys are valid Unicode by the
        # time this runs, because _string has rejected lone surrogates.
        keys = [(_string(k), k) for k in value]
        for i, (encoded, key) in enumerate(sorted(keys, key=lambda kk: kk[1].encode("utf-16-be"))):
            if i:
                out.append(",")
            out.append(encoded)
            out.append(":")
            _write(value[key], out)
        out.append("}")
    else:
        raise TypeError(f"{type(value).__name__} is not a JSON value")


def _string(s: str) -> str:
    """Escape a string as ECMAScript's JSON.stringify does."""
    out = ['"']
    for ch in s:
        code = ord(ch)
        if code in _SHORT_ESCAPES:
            out.append(_SHORT_ESCAPES[code])
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        elif 0xD800 <= code <= 0xDFFF:
            raise CanonicalError("a string holds a lone surrogate, which is not valid Unicode")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _number(x: float) -> str:
    if math.isnan(x) or math.isinf(x):
        raise CanonicalError("NaN and infinity are not JSON values")
    if abs(x) > MAX_SAFE_INTEGER:
        raise CanonicalError(f"the number {x!r} exceeds 2^53 - 1; write it as a string")
    return ecmascript_number(x)


def ecmascript_number(x: float) -> str:
    """Format a finite double as ECMAScript's Number.prototype.toString does (RFC 8785 section 3.2.2.3)."""
    if x == 0:
        return "0"  # covers -0.0 as well
    sign = "-" if x < 0 else ""
    # repr gives the shortest digit string that round-trips, as ECMAScript does.
    _, digit_tuple, exponent = Decimal(repr(abs(x))).as_tuple()
    all_digits = "".join(map(str, digit_tuple))
    digits = all_digits.rstrip("0")
    exponent += len(all_digits) - len(digits)
    k = len(digits)
    n = exponent + k  # the value is 0.digits * 10**n
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
        body = f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + body
