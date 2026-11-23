"""The adapter skill's converter template runs, invents nothing, and produces valid output."""

import importlib.util
import json
from pathlib import Path

import pytest

from wadachi.digest import digests
from wadachi.validate import validate_session, validate_store

TEMPLATE = Path(__file__).resolve().parent.parent / "skills" / "wadachi-adapter" / "converter_template.py"


@pytest.fixture
def template():
    spec = importlib.util.spec_from_file_location("converter_template", TEMPLATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict], tail: str = "") -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + tail, encoding="utf-8")


def test_converts_the_toy_format(tmp_path, template):
    record, hooks = tmp_path / "session.jsonl", tmp_path / "hooks.jsonl"
    write_jsonl(record, [
        {"id": "r1", "session": "toy-1", "role": "user", "text": "fix it", "time": "2026-11-23T12:00:00+02:00"},
        {"id": "r2", "role": "assistant", "text": "Running the tests.", "time": "2026-11-23T10:00:02Z",
         "calls": [{"id": "c1", "name": "run", "input": {"command": "make test"}},
                   {"id": "c2", "name": "replace", "input": {"paths": ["src/a.rs"]}}]},
        {"id": "r3", "role": "tool", "call": "c1", "name": "run", "exit": 2, "status": "success", "output": "1 failed"},
        {"id": "r4", "role": "tool", "call": "c2", "name": "replace", "exit": 0, "status": True},
        {"id": "r5", "role": "user", "text": "again"},
    ], tail='{"id": "r6", "role": "user", "te')  # a live file: the last line is half written
    write_jsonl(hooks, [
        {"event": "pre_tool", "call_id": "c1"},
        {"event": "post_tool", "call_id": "c1", "exit_code": 2, "at": "2026-11-23T10:00:05.500Z",
         "tree_before": "git-tree:" + "a" * 40, "tree_after": "git-tree:" + "a" * 40},
    ])
    out = template.write_session(template.convert(record, hooks), tmp_path / "store")

    assert [str(p) for p in validate_store(tmp_path / "store")] == []
    events = validate_session(out).events
    assert [e["type"] for e in events] == [
        "prompt", "assistant_text", "tool_call", "tool_call", "tool_result", "observation", "tool_result", "prompt"]
    assert events[0]["t"] == "2026-11-23T10:00:00Z"
    assert events[5]["t"] == "2026-11-23T10:00:05.5Z"
    assert events[6]["data"]["status_as_recorded"] == "true"
    assert [line for _, line in digests(events)] == ["t1 h6 e1 s1!1 5s @src/a.rs", "t2 h5"]


def test_invents_nothing(tmp_path, template):
    record = tmp_path / "s.jsonl"
    write_jsonl(record, [
        {"id": "r1", "role": "user", "time": "2026-11-23 10:00:00"},  # no text, no zone
        {"id": "r 2#x", "role": "assistant", "calls": [{"id": "c1"}]},  # no name, no input; a key to escape
        {"id": "r3", "role": "tool", "call": "c1"},
    ])
    out = template.write_session(template.convert(record), tmp_path / "store")
    assert [str(p) for p in validate_session(out).problems] == []
    prompt, call, result = validate_session(out).events
    assert prompt["data"] == {} and "t" not in prompt and prompt["raw"] == {"time": "2026-11-23 10:00:00"}
    assert call["data"] == {"kind": "other", "call_id": "c1"} and call["src"] == "f1:@r%202%23x#/calls/0"
    assert result["data"] == {"call_id": "c1"} and result["of"] == call["id"]
    assert [line for _, line in digests([prompt, call, result])] == ["t1 h? o1"]


def test_is_deterministic(tmp_path, template):
    record = tmp_path / "s.jsonl"
    write_jsonl(record, [{"role": "user", "text": "hi"}])  # no ids, no session id, no times
    first = template.convert(record)
    assert first == template.convert(record)
    assert first[0]["id"].startswith("s_") and first[1]["src"] == "f1:0"


def test_refuses_repeated_call_ids(tmp_path, template):
    record = tmp_path / "s.jsonl"
    write_jsonl(record, [{"id": "a", "role": "assistant", "calls": [{"id": "c1", "name": "run"}, {"id": "c1", "name": "run"}]}])
    with pytest.raises(ValueError):
        template.convert(record)


def test_applies_section_2_and_keeps_unmapped_fields(tmp_path, template):
    record = tmp_path / "s.jsonl"
    record.write_bytes(
        b'{"id":"r1","role":"user","text":"cut \\ud83d","big":12345678901234567890}\n'
        b'{"id":"r2","role":"assistant","text":"hi","model":"m1","usage":{"in":3},\r"calls":[{"id":"c1","name":"replace","input":{"paths":[null,5]}}]}\n'
    )
    out = template.write_session(template.convert(record), tmp_path / "store")
    assert [str(p) for p in validate_session(out).problems] == []
    prompt, text, call = validate_session(out).events
    assert prompt["data"]["text"] == "cut \ufffd" and prompt["raw"]["big"] == "12345678901234567890"
    assert text["raw"] == {"model": "m1", "usage": {"in": 3}}
    assert "paths" not in call["data"] and call["data"]["args"] == {"paths": [None, 5]}
