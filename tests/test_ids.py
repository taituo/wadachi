import hashlib

import pytest

from wadachi.ids import escape_key, event_id, session_id, split_src


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def test_session_id_from_native_id():
    assert session_id("kiro-cli", native_id="9f2c41") == "s_" + h("kiro-cli\n9f2c41")


def test_session_id_from_path():
    assert session_id("x", path="~/a.log") == "s_" + h("x\npath:~/a.log")


@pytest.mark.parametrize("kwargs", [{}, {"native_id": ""}, {"path": ""}])
def test_session_id_needs_something(kwargs):
    with pytest.raises(ValueError):
        session_id("x", **kwargs)


def test_event_id_depends_on_session_and_src_only():
    a = event_id("s_1", "f1:@u1#/message/content/1")
    assert a == "e_" + h("s_1\nf1:@u1#/message/content/1")
    assert a != event_id("s_1", "f1:@u1#/message/content/2")
    assert a != event_id("s_2", "f1:@u1#/message/content/1")


def test_escape_key():
    assert escape_key("part/prt_01") == "part/prt_01"
    assert escape_key("a b#c%d\te") == "a%20b%23c%25d%09e"
    assert escape_key("é ") == "é%C2%A0"  # a no-break space is whitespace: one %XX per UTF-8 byte


def test_split_src():
    assert split_src("f1:88123") == ("f1", "88123")
    assert split_src("f2:@part/prt_1#/a:b") == ("f2", "@part/prt_1#/a:b")
