"""The adapter skill's converter template runs and produces valid output."""

import importlib.util
import json
from pathlib import Path

from wadachi.digest import digests
from wadachi.validate import validate_session, validate_store

TEMPLATE = Path(__file__).resolve().parent.parent / "skills" / "wadachi-adapter" / "converter_template.py"


def load_template():
    spec = importlib.util.spec_from_file_location("converter_template", TEMPLATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_template_converts_the_toy_format(tmp_path):
    record = tmp_path / "session.jsonl"
    hooks = tmp_path / "hooks.jsonl"
    write_jsonl(record, [
        {"id": "r1", "session": "toy-1", "role": "user", "text": "fix it", "time": "2026-11-23T10:00:00Z"},
        {"id": "r2", "role": "assistant", "text": "Running the tests.", "time": "2026-11-23T10:00:02Z",
         "calls": [{"id": "c1", "name": "run", "input": {"command": "make test"}},
                   {"id": "c2", "name": "replace", "input": {"paths": ["src/a.rs"]}}]},
        {"id": "r3", "role": "tool", "call": "c1", "name": "run", "exit": 2, "status": "success", "output": "1 failed"},
        {"id": "r4", "role": "tool", "call": "c2", "name": "replace", "exit": 0},
        {"id": "r5", "role": "user", "text": "again"},
    ])
    write_jsonl(hooks, [
        {"event": "pre_tool", "call_id": "c1"},
        {"event": "post_tool", "call_id": "c1", "exit_code": 2, "tree_before": "git-tree:aaaaaaa", "tree_after": "git-tree:aaaaaaa"},
    ])
    module = load_template()
    out = module.write_session(module.convert(record, hooks), tmp_path / "store")

    assert [str(p) for p in validate_store(tmp_path / "store")] == []
    events = validate_session(out).events
    assert [e["type"] for e in events] == [
        "prompt", "assistant_text", "tool_call", "tool_call", "tool_result", "observation", "tool_result", "prompt"]
    assert [line for _, line in digests(events)] == ["t1 h6 e1 s1!1 2s src/a.rs", "t2 h5"]


def test_template_is_deterministic(tmp_path):
    record = tmp_path / "s.jsonl"
    write_jsonl(record, [{"role": "user", "text": "hi"}])  # no ids, no session id, no times
    module = load_template()
    first = module.convert(record)
    assert first == module.convert(record)
    assert first[0]["id"].startswith("s_") and first[1]["src"] == "f1:0"
