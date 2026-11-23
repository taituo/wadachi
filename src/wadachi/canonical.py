"""Canonical JSON serialisation, as defined by RFC 8785 (JCS).

Every line of a wadachi file is serialised this way, so two conversions of the
same source can be compared byte for byte.
"""

from __future__ import annotations

import math
from decimal import Decimal

_MAX_SAFE_INTEGER = 2**53 - 1

_SHORT_ESCAPES = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
    0x22: '\\"',
    0x5C: "\\\\",
}


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
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ValueError(
                f"integer {value} is outside the range JSON numbers hold exactly; write it as a string"
            )
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
        # UTF-16 bytes gives exactly that order.
        for i, key in enumerate(sorted(value, key=lambda k: k.encode("utf-16-be", "surrogatepass"))):
            if i:
                out.append(",")
            out.append(_string(key))
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
        elif code < 0x20 or 0xD800 <= code <= 0xDFFF:
            # Control characters, and lone surrogates, which cannot be encoded
            # as UTF-8, are written as \u escapes in lowercase hex.
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _number(x: float) -> str:
    """Format a double as ECMAScript's Number.prototype.toString does."""
    if math.isnan(x) or math.isinf(x):
        raise ValueError("NaN and infinity are not JSON values")
    if x == 0:
        return "0"  # covers -0.0 as well
    sign = "-" if x < 0 else ""
    # repr gives the shortest digit string that round-trips, as ECMAScript does.
    _, digit_tuple, exponent = Decimal(repr(abs(x))).as_tuple()
    digits = "".join(map(str, digit_tuple)).rstrip("0")
    exponent += len("".join(map(str, digit_tuple))) - len(digits)
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
