import unicodedata

import pytest

from wadachi import schemas
from wadachi.escape import ESCAPED_RANGES, bmp_class, needs_escape, percent_escape

WHITE_SPACE = {0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000}


@pytest.mark.skipif(unicodedata.unidata_version != "15.1.0", reason="the list is defined as of Unicode 15.1")
def test_list_is_white_space_and_cc_cf_zl_zp():
    expected = set(WHITE_SPACE)
    for cp in range(0x110000):
        if not 0xD800 <= cp <= 0xDFFF and unicodedata.category(chr(cp)) in ("Cc", "Cf", "Zl", "Zp"):
            expected.add(cp)
    listed = {cp for a, b in ESCAPED_RANGES for cp in range(a, b + 1)}
    assert listed == expected
    assert len(listed) == 254


def test_needs_escape_at_range_edges():
    for a, b in ESCAPED_RANGES:
        assert needs_escape(chr(a)) and needs_escape(chr(b))
        if a > 0 and not any(x <= a - 1 <= y for x, y in ESCAPED_RANGES):
            assert not needs_escape(chr(a - 1))
    assert not needs_escape("a") and not needs_escape("é") and not needs_escape("😀")


def test_percent_escape():
    assert percent_escape("a b%\ufeff\U000e0001é") == "a%20b%25%EF%BB%BF%F3%A0%80%81é"


def test_schema_src_pattern_uses_the_list():
    assert bmp_class() in schemas.load("record")["$defs"]["event"]["properties"]["src"]["pattern"]
