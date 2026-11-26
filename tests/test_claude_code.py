"""Constructed Claude Code transcripts. Every content value is invented (WHY: Forge)."""

import json
from pathlib import Path

import pytest

from wadachi import dumps, session_id
from wadachi.convert import REGISTRY, base, claude_code as cc
from wadachi.digest import digests
from wadachi.dump import dump
from wadachi.validate import validate_session, validate_store

ROOT = Path(__file__).parent / "fixtures" / "claude-code"
PARENT = ROOT / "parent.constructed.jsonl"
CHILD = ROOT / "parent-session" / "subagents" / "agent-a0constructed01.jsonl"
PARENT_NID = "00000000-0000-4000-8000-00000000c0de"


def convert(path):
    inp = next(cc.sessions([path]))
    inp.header.setdefault("x", {})["fixture"] = {"constructed": True}
    return base.convert(cc, inp)


def golden(lines):
    for f in lines[0]["files"].values():
        f["path"] = "/home/user/constructed/" + Path(f["path"]).name
    return "".join(dumps(r) + "\n" for r in lines)


@pytest.mark.parametrize("path,name", [(PARENT, "parent"), (CHILD, "child")])
def test_constructed_sessions_match_expected_output(tmp_path, path, name):
    lines = convert(path)
    assert validate_session(base.write_session(lines, tmp_path / "store")).problems == []
    assert lines == convert(path)
    assert golden(lines) == (ROOT / f"{name}.expected.jsonl").read_text(encoding="utf-8")


def test_parent_events():
    lines = convert(PARENT)
    header = lines[0]
    records = [e for e in lines[1:] if e["type"] == "record"]
    events = [e for e in lines[1:] if e["type"] != "record"]
    assert header["native_id"] == PARENT_NID and header["mode"] == "interactive"
    assert header["model"] == "constructed-model-1"
    assert [(e["type"], e["actor"]) for e in events] == [
        ("setting", "harness"), *[("context", "harness")] * 5, ("prompt", "human"), ("reasoning", "agent"), ("tool_call", "agent"),
        ("usage", "harness"), ("permission", "harness"), ("tool_result", "tool"), ("subagent_end", "agent"),
        ("assistant_text", "agent"), ("usage", "harness"),
        ("prompt", "human"), ("context", "harness"), ("context", "harness"),
        ("prompt", "human"), ("tool_call", "agent"), ("tool_call", "agent"), ("usage", "harness"),
        ("tool_result", "tool"), ("tool_result", "tool"), ("interrupt", "human"),
        ("prompt", "human"), ("error", "harness"), ("usage", "harness")]
    by_type = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)
    # Empty thinking with a signature is redacted, not an empty text.
    assert by_type["reasoning"][0]["data"] == {"redacted": True}
    # One usage per API message, from its last line.
    assert [u["data"]["output_tokens"] for u in by_type["usage"]] == [20, 5, 9, 0]
    agent_call, fetch_call, read_call = by_type["tool_call"]
    assert agent_call["data"]["kind"] == "subagent"
    assert read_call["data"]["paths"] == ["/home/user/project/a.txt"]
    note, fetched, failed = by_type["tool_result"]
    assert note["of"] == agent_call["id"] and note["data"]["text_origin"] == "tool"
    assert fetched["of"] == fetch_call["id"] and fetched["data"]["text_origin"] == "model"
    assert failed["data"]["status_as_recorded"] == "true" and "text_origin" not in failed["data"]
    assert by_type["permission"][0]["of"] == agent_call["id"]
    end = by_type["subagent_end"][0]
    assert end["of"] == agent_call["id"] and end["how"] == {"of": "inferred:agent-id-matches-tool-result"}
    assert end["data"]["session"] == session_id("claude-code", native_id=PARENT_NID + "/a0constructed01")
    assert end["data"]["text_origin"] == "agent" and "Invented report text." in end["data"]["text"]
    # Harness-written user text is not a prompt; a slash command is, with an inferred actor.
    texts = [e["data"].get("text") for e in by_type["prompt"]]
    assert not any(t.startswith("<local-command") for t in texts)
    assert by_type["prompt"][1]["how"] == {"actor": "inferred:interactive-entrypoint"}
    # Nothing is left out: bookkeeping lines are record events, kept whole.
    assert [r["data"]["name"] for r in records] == [
        "mode", "permission-mode", "attachment/credential_org", "queue-operation", "system/turn_duration",
        "cost-state", "last-prompt"]
    assert all(r["turn"] in (0, 1, 4) for r in records) and records[3]["raw"]["operation"] == "enqueue"
    assert header["x"]["claude-code"]["cost_state"]["totalCostUSD"] == "0.25"
    # is_error is a recorded status, not an exit code, so it does not mark the call failed.
    assert [d for _, d in digests(events)][2] == "t3 h20 r1 f1 x 3s"


def test_child_links_to_parent():
    parent, child = convert(PARENT), convert(CHILD)
    header = child[0]
    assert header["native_id"] == PARENT_NID + "/a0constructed01"
    assert header["mode"] == "subagent" and header["agent"] == {"name": "web-fetch"}
    assert header["parent"] == {"session": parent[0]["id"], "relation": "subagent"}
    assert header["files"]["f3"]["role"] == "aux" and "f2" not in header["files"]
    end = next(e for e in parent[1:] if e["type"] == "subagent_end")
    assert end["data"]["session"] == header["id"]
    prompt = child[1]
    assert header["converter"]["measured"] == ["2.1.296"]
    assert (prompt["type"], prompt["actor"], prompt["how"]) == ("prompt", "caller", {"actor": "inferred:subagent-task"})


def test_usage_read_once_per_message(tmp_path):
    rows = [{"type": "assistant", "uuid": f"u{i}", "sessionId": "s", "timestamp": "2031-01-01T00:00:00Z",
             "message": {"id": "m", "content": [{"type": "text", "text": "x"}], "usage": {"output_tokens": i}}}
            for i in (1, 2, 3)]
    path = tmp_path / "one.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    events = base.convert(cc, path)[1:]
    assert [e["data"] for e in events if e["type"] == "usage"] == [{"output_tokens": 3}]


def test_text_beside_tool_result_is_a_steer(tmp_path):
    rows = [{"type": "assistant", "uuid": "a", "sessionId": "s", "message": {"id": "m", "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "true"}}]}},
            {"type": "user", "uuid": "b", "sessionId": "s", "entrypoint": "cli", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                {"type": "text", "text": "Invented steer."}]}}]
    path = tmp_path / "steer.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    events = base.convert(cc, path)[1:]
    assert [(e["type"], e["turn"]) for e in events] == [("tool_call", 0), ("tool_result", 0), ("steer", 0)]
    assert events[2]["how"] == {"actor": "inferred:interactive-entrypoint", "type": "inferred:text-beside-tool-result"}


def test_no_uuid_falls_back_to_offsets_and_no_time_without_zone(tmp_path):
    rows = [{"type": "user", "sessionId": "s", "timestamp": "2031-01-01T00:00:00", "origin": {"kind": "human"},
             "message": {"content": "a"}},
            {"type": "user", "sessionId": "s", "origin": {"kind": "human"}, "message": {"content": "b"}}]
    path = tmp_path / "plain.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    lines = base.convert(cc, path)
    assert [e["src"] for e in lines[1:]] == ["f1:0", "f1:" + str(len(json.dumps(rows[0])) + 1)]
    assert "t" not in lines[1] and lines[1]["raw"]["timestamp"] == "2031-01-01T00:00:00"


def test_discovery_and_dump(tmp_path, monkeypatch):
    home = tmp_path / "claude"
    project = home / "projects" / "-home-user-project"
    (project / PARENT_NID / "subagents").mkdir(parents=True)
    (project / f"{PARENT_NID}.jsonl").write_bytes(PARENT.read_bytes())
    for f in CHILD.parent.iterdir():
        (project / PARENT_NID / "subagents" / f.name).write_bytes(f.read_bytes())
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    found = {s.native_id: s for s in cc.discover()}
    assert set(found) == {PARENT_NID, PARENT_NID + "/a0constructed01"}
    assert found[PARENT_NID].cwd == "/home/user/project"
    assert cc.select_self(list(found.values()), "/home/user/project") == [found[PARENT_NID]]
    assert "claude-code" in REGISTRY
    store = tmp_path / "store"
    assert dump(store, harness="claude-code") == 0
    assert len(list((store / "sessions").glob("*.jsonl"))) == 2
    assert validate_store(store) == []
    assert dump(store, harness="claude-code") == 0  # unchanged sources are skipped


@pytest.mark.parametrize("handback,origin", [("send", "tool"), (None, "agent"), ("later", None)])
def test_agent_result_origin(tmp_path, handback, origin):
    result = {"agentId": "a1"} | ({} if handback is None else {"handback": handback})
    rows = [{"type": "assistant", "uuid": "a", "sessionId": "s", "message": {"id": "m", "content": [
                {"type": "tool_use", "id": "t1", "name": "Agent", "input": {}}]}},
            {"type": "user", "uuid": "b", "sessionId": "s", "toolUseResult": result, "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "Invented."}]}}]
    path = tmp_path / "agent.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    data = base.convert(cc, path)[-1]["data"]
    assert data.get("text_origin") == origin


def test_context_is_what_the_model_was_given():
    events = [e for e in convert(PARENT)[1:] if e["type"] != "record"]
    context = [e for e in events if e["type"] == "context"]
    assert [(e["data"].get("name"), e["data"].get("role"), e["data"].get("text")) for e in context] == [
        ("model", "system", "Invented model note."),
        ("date", "system", "Invented date line."),
        ("session_context", "user", "Invented contact line."),
        ("prompt_snapshot", "system", "Invented system section one."),
        ("prompt_snapshot", "system", "Invented system section two."),
        (None, "user", "<local-command-stdout>Invented output</local-command-stdout>"),
        (None, "user", "<local-command-caveat>Invented caveat</local-command-caveat>")]
    # The rest of a record is kept once, not on every section.
    assert "systemPrompt" not in context[3]["raw"]["attachment"] and "attachment" not in context[4].get("raw", {})
    assert "rendered" not in context[1]["raw"] and context[1]["raw"]["attachment"]["type"] == "date"
    # The setting from the model attachment keeps the record; its context part does not repeat it.
    assert "raw" not in context[0] or set(context[0]["raw"]) <= {"timestamp"}
    # Context starts no turn and is not in digests.
    assert all(e["turn"] == 0 for e in context[:5])
    assert [d for _, d in digests(events)][0].startswith("t1 h20 a1")
