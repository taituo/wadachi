import pytest

from wadachi.times import from_source, from_unix, instant_ns


@pytest.mark.parametrize(
    "source,expected",
    [
        ("2026-11-23T20:00:00+02:00", "2026-11-23T18:00:00Z"),
        ("2026-11-23T18:00:00-00:30", "2026-11-23T18:30:00Z"),
        ("2026-11-23t18:00:00.120z", "2026-11-23T18:00:00.12Z"),
        ("2026-11-23 18:00:00Z", "2026-11-23T18:00:00Z"),
        ("2026-11-23T18:00:00.000Z", "2026-11-23T18:00:00Z"),
        ("2026-11-23T18:00:00.123456789Z", "2026-11-23T18:00:00.123456789Z"),
        ("2016-12-31T23:59:60Z", "2016-12-31T23:59:60Z"),
        ("2017-01-01T01:59:60+02:00", "2016-12-31T23:59:60Z"),
    ],
)
def test_from_source_converts_exactly(source, expected):
    assert from_source(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "2026-11-23T18:00:00",  # no zone: stays in raw
        "2026-02-31T00:00:00Z",  # no such date
        "2026-11-23T24:00:00Z",
        "2026-11-23T18:30:60Z",  # a leap second only at :59
        "2026-11-23T18:00:00.1234567891Z",  # more than nine digits cannot convert exactly
        "2026-11-23T18:00:00+24:00",
        "yesterday",
    ],
)
def test_from_source_refuses_what_it_cannot_convert(source):
    assert from_source(source) is None


def test_from_unix():
    assert from_unix(1732387200, 123_000_000) == "2024-11-23T18:40:00.123Z"
    assert from_unix(0) == "1970-01-01T00:00:00Z"


def test_instant_is_exact_and_counts_leap_seconds_as_the_next_second():
    assert instant_ns("2016-12-31T23:59:60Z") == instant_ns("2017-01-01T00:00:00Z")
    assert instant_ns("2026-01-01T00:00:01.0000001Z") - instant_ns("2026-01-01T00:00:00.0000005Z") == 999_999_600


@pytest.mark.parametrize("bad", ["2026-11-23T18:00:00+02:00", "2026-11-23T18:00:00.10Z", "2026-02-30T00:00:00Z"])
def test_instant_refuses_other_forms(bad):
    with pytest.raises(ValueError):
        instant_ns(bad)


@pytest.mark.parametrize("source", ["9999-12-31T23:59:59-01:00", "0001-01-01T00:00:00+01:00", "2026-11-23T12:59:60Z"])
def test_from_source_returns_none_outside_what_exists(source):
    assert from_source(source) is None


def test_leap_second_is_checked_in_utc():
    assert from_source("2017-01-01T05:29:60+05:30") == "2016-12-31T23:59:60Z"


def test_from_unix_needs_integers():
    with pytest.raises(TypeError):
        from_unix(1732387200.5)
