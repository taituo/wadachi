import hashlib

import pytest

from wadachi.ids import event_id, session_id, split_src


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def test_session_id_from_native_id():
    assert session_id("kiro-cli", native_id="9f2c41") == "s_" + h("kiro-cli\n9f2c41")


def test_session_id_from_path():
    assert session_id("x", path="~/a.log") == "s_" + h("x\npath:~/a.log")


def test_session_id_needs_something():
    with pytest.raises(ValueError):
        session_id("x")


def test_event_id_includes_pointer_and_type():
    a = event_id("s_1", "~/a.jsonl", "@u1#/message/content/1", "tool_call")
    b = event_id("s_1", "~/a.jsonl", "@u1#/message/content/2", "tool_call")
    c = event_id("s_1", "~/a.jsonl", "@u1#/message/content/1", "tool_result")
    assert len({a, b, c}) == 3
    assert a == "e_" + h("s_1\n~/a.jsonl\n@u1#/message/content/1\ntool_call")


def test_split_src():
    assert split_src("f1:88123") == ("f1", "88123")
    assert split_src("f2:@part/prt_1#/a:b") == ("f2", "@part/prt_1#/a:b")
