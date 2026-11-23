import math

import pytest

from wadachi.canonical import dumps

# Values from RFC 8785, Appendix B, and ECMAScript's Number.prototype.toString.
NUMBERS = [
    (0.0, "0"),
    (-0.0, "0"),
    (1e21, "1e+21"),
    (1e-7, "1e-7"),
    (333333333.3333333, "333333333.3333333"),
    (1e23, "1e+23"),
    (5e-324, "5e-324"),
    (1.7976931348623157e308, "1.7976931348623157e+308"),
    (9007199254740992.0, "9007199254740992"),
    (0.000001, "0.000001"),
    (123456789012345680000.0, "123456789012345680000"),
    (295147905179352830000.0, "295147905179352830000"),
    (4.5, "4.5"),
    (0.002, "0.002"),
    (0.1 + 0.2, "0.30000000000000004"),
    (-1.5e-9, "-1.5e-9"),
    (1e16, "10000000000000000"),
]


@pytest.mark.parametrize("value,expected", NUMBERS)
def test_numbers(value, expected):
    assert dumps(value) == expected


def test_key_order_is_utf16():
    # RFC 8785 section 3.2.3: the emoji sorts before U+FB33 in UTF-16.
    obj = {"\u20ac": 1, "\r": 2, "\ufb33": 3, "1": 4, "\U0001f600": 5, "\u0080": 6, "\u00f6": 7}
    assert dumps(obj) == '{"\\r":2,"1":4,"\u0080":6,"\u00f6":7,"\u20ac":1,"\U0001f600":5,"\ufb33":3}'


def test_string_escapes():
    assert dumps("\b\t\n\f\r\"\\\x01\x1f\x7f\u2028") == '"\\b\\t\\n\\f\\r\\"\\\\\\u0001\\u001f\x7f\u2028"'


def test_lone_surrogate_is_escaped():
    assert dumps("\ud800") == '"\\ud800"'


def test_structure_has_no_whitespace():
    assert dumps({"b": [1, True, None, "x"], "a": {}}) == '{"a":{},"b":[1,true,null,"x"]}'


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected(bad):
    with pytest.raises(ValueError):
        dumps(bad)


def test_unsafe_integers_are_rejected():
    assert dumps(2**53 - 1) == "9007199254740991"
    with pytest.raises(ValueError):
        dumps(2**53)


def test_non_string_keys_are_rejected():
    with pytest.raises(TypeError):
        dumps({1: "a"})
