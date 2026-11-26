"""Constructed SQLite rows only. No values are copied from owner data (WHY: Forge)."""

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from wadachi import dumps, session_id
from wadachi.cli import main
from wadachi.convert import base, opencode
from wadachi import dump as dumping
from wadachi.validate import validate_session, validate_store

T = 2200000000000  # invented Unix milliseconds
SCHEMA = '''
CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT NOT NULL, vcs TEXT, name TEXT,
 icon_url TEXT, icon_url_override TEXT, icon_color TEXT, time_created INTEGER NOT NULL,
 time_updated INTEGER NOT NULL, time_initialized INTEGER, sandboxes TEXT NOT NULL, commands TEXT);
CREATE TABLE session (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, workspace_id TEXT, parent_id TEXT,
 slug TEXT NOT NULL, directory TEXT NOT NULL, path TEXT, title TEXT NOT NULL, version TEXT NOT NULL,
 share_url TEXT, summary_additions INTEGER, summary_deletions INTEGER, summary_files INTEGER,
 summary_diffs TEXT, metadata TEXT, cost REAL NOT NULL DEFAULT 0, tokens_input INTEGER NOT NULL DEFAULT 0,
 tokens_output INTEGER NOT NULL DEFAULT 0, tokens_reasoning INTEGER NOT NULL DEFAULT 0,
 tokens_cache_read INTEGER NOT NULL DEFAULT 0, tokens_cache_write INTEGER NOT NULL DEFAULT 0,
 revert TEXT, permission TEXT, agent TEXT, model TEXT, time_created INTEGER NOT NULL,
 time_updated INTEGER NOT NULL, time_compacting INTEGER, time_archived INTEGER,
 FOREIGN KEY(project_id) REFERENCES project(id));
CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, time_created INTEGER NOT NULL,
 time_updated INTEGER NOT NULL, data TEXT NOT NULL, FOREIGN KEY(session_id) REFERENCES session(id));
CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT NOT NULL, session_id TEXT NOT NULL,
 time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL,
 FOREIGN KEY(message_id) REFERENCES message(id));
CREATE TABLE permission (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, action TEXT NOT NULL,
 resource TEXT NOT NULL, time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL);
'''


class ConstructedDB:
    def __init__(self, path):
        self.path = path
        self.c = sqlite3.connect(path)
        self.c.executescript(SCHEMA)
        self.c.execute("INSERT INTO project (id,worktree,time_created,time_updated,sandboxes) VALUES (?,?,?,?,?)",
                       ("constructed-project", "/home/user/project", T, T, "[]"))
        self.c.commit()

    def session(self, sid, parent=None, created=T, **extra):
        values = dict(id=sid, project_id="constructed-project", parent_id=parent, slug="constructed-slug",
                      directory="/home/user/project", title="Invented session.", version="9.8.7",
                      time_created=created, time_updated=created, **extra)
        columns = list(values)
        self.c.execute(f"INSERT INTO session ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", list(values.values()))

    def message(self, mid, sid, role="user", created=T, parent=None, **extra):
        d = {"role": role, "time": {"created": created}, **extra}
        if parent:
            d["parentID"] = parent
        self.c.execute("INSERT INTO message VALUES (?,?,?,?,?)", (mid, sid, created, created, json.dumps(d)))

    def part(self, pid, mid, sid, data, created=T):
        self.c.execute("INSERT INTO part VALUES (?,?,?,?,?,?)", (pid, mid, sid, created, created, json.dumps(data)))

    def commit(self):
        self.c.commit()

    def text(self, sid, mid, pid, text="Invented input.", created=T):
        self.message(mid, sid, created=created)
        self.part(pid, mid, sid, {"type": "text", "text": text}, created)


@pytest.fixture
def db(tmp_path, monkeypatch):
    constructed = ConstructedDB(tmp_path / "constructed.sqlite")
    monkeypatch.setenv("OPENCODE_DB", str(constructed.path))
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    monkeypatch.delenv("HERDR_PANE_ID", raising=False)
    converter = {"name": "constructed-opencode-fixture", "version": "9.8.7"}
    monkeypatch.setattr(opencode, "CONVERTER", converter)
    monkeypatch.setattr(opencode._Session, "CONVERTER", converter)
    monkeypatch.setattr(opencode, "SOURCE_FORMAT", "constructed-opencode-session-sqlite")
    selected = opencode.selected_sessions

    def marked(found):
        for inp in selected(found):
            inp.header = {"x": {"fixture": {"constructed": True}}}
            yield inp

    monkeypatch.setattr(opencode, "selected_sessions", marked)
    yield constructed
    constructed.c.close()


def converted(db, tmp_path, sid="ses_constructed_parent"):
    db.commit()
    found = [d for d in opencode.discover() if d.native_id == sid]
    inp = next(opencode.selected_sessions(found))
    snap = inp.sources[0].reader(inp.sources[0].path)
    lines = base.convert(opencode, inp)
    assert lines == base.convert(opencode, inp)
    assert lines[0]["files"]["f1"]["sha256"] == hashlib.sha256(snap.data).hexdigest()
    assert snap.data.startswith(b"SQLite format 3\x00")
    out = base.write_session(lines, tmp_path / "store")
    assert validate_session(out).problems == []
    return lines, snap


def setup_parent(db):
    sid = "ses_constructed_parent"
    db.session(sid)
    db.text(sid, "msg_constructed_user", "prt_constructed_user")
    db.message("msg_constructed_assistant", sid, "assistant", T + 1, "msg_constructed_user",
               tokens={"input": 13, "output": 5, "cache": {"read": 2, "write": 1}, "reasoning": 3}, cost=0.0125,
               time={"created": T + 1, "completed": T + 30})
    return sid


def test_all_measured_part_types_and_compaction_summary(db, tmp_path):
    sid = setup_parent(db)
    db.part("prt_constructed_reasoning", "msg_constructed_assistant", sid,
            {"type": "reasoning", "text": "Invented reasoning.", "time": {"start": T + 2, "end": T + 3}})
    db.part("prt_constructed_start", "msg_constructed_assistant", sid, {"type": "step-start", "snapshot": "constructed-snapshot"})
    db.part("prt_constructed_text", "msg_constructed_assistant", sid, {"type": "text", "text": "Invented answer.", "time": {"start": T + 20}})
    db.part("prt_constructed_finish", "msg_constructed_assistant", sid,
            {"type": "step-finish", "reason": "stop", "tokens": {"input": 13, "output": 5, "cache": {"read": 2, "write": 1}}, "cost": 0.0125}, T + 29)
    db.part("prt_constructed_patch", "msg_constructed_assistant", sid,
            {"type": "patch", "hash": "constructed-snapshot", "files": ["/home/user/a.py", "/home/user/b.py"]})
    db.message("msg_constructed_compaction", sid, created=T + 40)
    db.part("prt_constructed_compaction", "msg_constructed_compaction", sid, {"type": "compaction", "auto": True}, T + 40)
    db.message("msg_constructed_summary", sid, "assistant", T + 41, "msg_constructed_compaction", summary=True)
    db.part("prt_constructed_summary", "msg_constructed_summary", sid, {"type": "text", "text": "Invented model summary."}, T + 42)
    lines, _ = converted(db, tmp_path)
    events = lines[1:]
    assert sum(e["type"] == "prompt" for e in events) == 1
    assert any(e["type"] == "reasoning" and e["data"]["text"] == "Invented reasoning." for e in events)
    assert [e["data"]["text"] for e in events if e["type"] == "assistant_text"] == ["Invented answer."]
    assert any(e["type"] == "compaction" and e["data"].get("text") == "Invented model summary." for e in events)
    # Nothing is left out: parts without another event type are record events.
    kept = [e for e in events if e["type"] == "record"]
    names = [e["data"]["name"] for e in kept]
    assert sorted(n for n in names if n.startswith("part/")) == ["part/patch", "part/step-start"]
    assert set(names) == {"part/patch", "part/step-start", "message"}  # assistant message metadata rows
    assert any(e["raw"]["row"]["id"] == "prt_constructed_patch" for e in kept)
    usage = [e for e in events if e["type"] == "usage" and e["data"].get("input_tokens") == 13]
    assert len(usage) == 2
    assert all(e["x"]["opencode"]["cost"] == "0.0125" for e in usage)


def test_tool_phases_failures_truncation_and_own_times(db, tmp_path):
    sid = setup_parent(db)
    db.part("prt_constructed_bash", "msg_constructed_assistant", sid,
            {"type": "tool", "tool": "bash", "callID": "constructed-call", "state": {
                "status": "completed", "input": {"command": "invented command"}, "output": "Invented failing output.",
                "metadata": {"exit": 7, "truncated": True}, "time": {"start": T + 3, "end": T + 13}}})
    db.part("prt_constructed_error", "msg_constructed_assistant", sid,
            {"type": "tool", "tool": "read", "callID": "constructed-error", "state": {
                "status": "error", "input": {"filePath": "/home/user/missing"}, "error": "Invented failure.",
                "metadata": {"exit": None}, "time": {"start": T + 14, "end": T + 15}}})
    lines, _ = converted(db, tmp_path)
    call, result = [e for e in lines[1:] if e["data"].get("call_id") == "constructed-call"]
    assert call["data"]["args"] == {"command": "invented command"} and "paths" not in call["data"]
    assert result["data"]["exit_code"] == 7 and result["data"]["status_as_recorded"] == "completed"
    assert result["data"]["text_truncated"] is True and result["of"] == call["id"]
    assert call["t"] != result["t"] and call["src"] != result["src"]
    failed = next(e for e in lines[1:] if e["type"] == "tool_result" and e["data"].get("call_id") == "constructed-error")
    assert failed["data"]["text"] == "Invented failure." and "exit_code" not in failed["data"]


@pytest.mark.parametrize("status", ["pending", "running"])
def test_unfinished_tools_have_no_invented_result_or_time(db, tmp_path, status):
    sid = setup_parent(db)
    db.part("prt_constructed_running", "msg_constructed_assistant", sid,
            {"type": "tool", "tool": "invented_tool", "callID": "constructed-running", "state": {"status": status, "input": {}}})
    lines, _ = converted(db, tmp_path)
    events = [e for e in lines[1:] if e["data"].get("call_id") == "constructed-running"]
    assert len(events) == 1 and events[0]["type"] == "tool_call" and "t" not in events[0]
    assert events[0]["data"]["kind"] == "other"


def test_arguments_stay_as_recorded_and_all_file_paths_survive(db, tmp_path):
    sid = setup_parent(db)
    db.part("prt_constructed_patch_tool", "msg_constructed_assistant", sid,
            {"type": "tool", "tool": "apply_patch", "callID": "constructed-patch", "state": {
                "status": "completed", "input": "invented patch string", "output": "Invented patch result.",
                "metadata": {"files": [{"filePath": "/home/user/a", "movePath": "/home/user/b"}, {"filePath": "/home/user/c"}]},
                "time": {"start": T + 2, "end": T + 3}}})
    lines, _ = converted(db, tmp_path)
    call, result = [e for e in lines[1:] if e["data"].get("call_id") == "constructed-patch"]
    assert call["data"]["args"] == "invented patch string"
    assert result["data"]["paths"] == ["/home/user/a", "/home/user/b", "/home/user/c"]


@pytest.mark.parametrize("tool,kind", [("read", "read"), ("write", "write"), ("edit", "edit"), ("apply_patch", "edit"),
                                      ("glob", "search"), ("grep", "search"), ("bash", "shell"), ("task", "subagent"),
                                      ("webfetch", "fetch"), ("websearch", "fetch"), ("rea_open_binary", "mcp"),
                                      ("mcp__invented__read", "mcp"), ("invented_unknown", "other")])
def test_fixed_tool_kind_table(db, tmp_path, tool, kind):
    sid = setup_parent(db)
    db.part("prt_constructed_tool", "msg_constructed_assistant", sid,
            {"type": "tool", "tool": tool, "callID": "constructed-tool", "state": {"status": "running", "input": {"filePath": "/home/user/a"}, "time": {"start": T + 1}}})
    lines, _ = converted(db, tmp_path)
    call = next(e for e in lines[1:] if e["type"] == "tool_call")
    assert call["data"]["kind"] == kind
    if tool in ("read", "write", "edit"):
        assert call["data"]["paths"] == ["/home/user/a"]


def child_setup(db):
    parent = setup_parent(db)
    child = "ses_constructed_child"
    db.session(child, parent)
    db.text(child, "msg_constructed_child_user", "prt_constructed_child_user", "Invented delegated request.", T + 6)
    db.part("prt_constructed_task", "msg_constructed_assistant", parent,
            {"type": "tool", "tool": "task", "callID": "constructed-task", "state": {
                "status": "completed", "input": {"prompt": "Invented delegated request.", "subagent_type": "invented_agent"},
                "output": "Invented child result.", "metadata": {"sessionId": child, "parentSessionId": parent},
                "time": {"start": T + 5, "end": T + 20}}})
    return parent, child


def test_subagent_links_are_recorded_and_parent_ambiguity_is_not_guessed(db, tmp_path):
    parent, child = child_setup(db)
    child_lines, snap = converted(db, tmp_path, child)
    retained = tmp_path / "constructed-child-snapshot.sqlite"
    retained.write_bytes(snap.data)
    with sqlite3.connect(retained) as c:
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert child_lines[0]["mode"] == "subagent"
    assert child_lines[0]["parent"] == {"session": session_id("opencode", native_id=parent), "relation": "subagent"}
    assert next(e for e in child_lines[1:] if e["type"] == "prompt")["actor"] == "caller"
    parent_lines, _ = converted(db, tmp_path, parent)
    spawn = next(e for e in parent_lines[1:] if e["type"] == "subagent_start")
    assert spawn["data"]["session"] == child_lines[0]["id"] and "t" not in spawn
    db.session("ses_constructed_ambiguous", parent)
    ambiguous, _ = converted(db, tmp_path, "ses_constructed_ambiguous")
    assert "parent" not in ambiguous[0] and ambiguous[0]["raw"]["session"]["parent_id"] == parent


def test_per_session_snapshot_is_valid_deterministic_and_ignores_unrelated_rows(db, tmp_path):
    parent, child = child_setup(db)
    db.session("ses_constructed_other")
    db.text("ses_constructed_other", "msg_constructed_other", "prt_constructed_other")
    first, snap = converted(db, tmp_path, parent)
    path = tmp_path / "constructed-retained.sqlite"
    path.write_bytes(snap.data)
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute("SELECT id FROM session").fetchall() == [(parent,)]
        assert c.execute("SELECT count(*) FROM message WHERE session_id<>?", (parent,)).fetchone()[0] == 0
    db.c.execute("UPDATE session SET title=? WHERE id=?", ("Invented changed title.", "ses_constructed_other"))
    db.c.execute("UPDATE part SET data=? WHERE id=?", (json.dumps({"type": "text", "text": "Invented changed input."}), "prt_constructed_other"))
    second, second_snap = converted(db, tmp_path, parent)
    assert snap.data == second_snap.data and first == second
    db.c.execute("UPDATE part SET data=? WHERE id=?", (json.dumps({"type": "text", "text": "Invented changed parent input."}), "prt_constructed_user"))
    third, third_snap = converted(db, tmp_path, parent)
    assert third_snap.data != snap.data and third[0]["id"] == first[0]["id"]


def test_dump_reconverts_only_changed_session_and_keeps_physical_raw(db, tmp_path, capsys):
    child_setup(db)
    db.session("ses_constructed_other")
    db.text("ses_constructed_other", "msg_constructed_other", "prt_constructed_other")
    db.commit()
    store = tmp_path / "dump-store"
    assert dumping.dump(store, harness="opencode", keep_raw=True) == 0
    assert capsys.readouterr().out == "opencode: converted=3 skipped=0 failed=0\n"
    db.c.execute("UPDATE session SET title=? WHERE id=?", ("Invented changed title.", "ses_constructed_other"))
    db.commit()
    assert dumping.dump(store, harness="opencode") == 0
    assert capsys.readouterr().out == "opencode: converted=1 skipped=2 failed=0\n"
    assert dumping.dump(store, harness="opencode") == 0
    assert capsys.readouterr().out == "opencode: converted=0 skipped=3 failed=0\n"
    assert validate_store(store) == []
    for path in (store / "raw").iterdir():
        assert path.read_bytes().startswith(b"SQLite format 3\x00")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == path.name


def test_database_discovery_and_env_paths(db, tmp_path, monkeypatch):
    setup_parent(db)
    db.commit()
    found = list(opencode.discover())
    assert len(found) == 1 and found[0].native_id == "ses_constructed_parent"
    assert found[0].path == db.path and found[0].cwd == "/home/user/project"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("OPENCODE_DB", "constructed.sqlite")
    assert opencode.databases() == [tmp_path / "opencode/constructed.sqlite"]
    monkeypatch.delenv("OPENCODE_DB")
    root = tmp_path / "opencode"
    root.mkdir()
    for name in ("opencode.db", "opencode-preview.db"):
        (root / name).touch()
    assert len(opencode.databases()) == 2
    monkeypatch.setenv("OPENCODE_DISABLE_CHANNEL_DB", "true")
    assert opencode.databases() == [root / "opencode.db"]
    monkeypatch.setenv("OPENCODE_DB", ":memory:")
    with pytest.raises(ValueError, match="on-disk"):
        opencode.databases()


def test_self_uses_explicit_plugin_id_even_with_shared_database_path(db, tmp_path, monkeypatch, capsys):
    parent, child = child_setup(db)
    db.commit()
    monkeypatch.setenv("OPENCODE_SESSION_ID", child)
    store = tmp_path / "self-store"
    assert main(["dump", "--harness", "opencode", "--self", "--store", str(store)]) == 0
    assert capsys.readouterr() == ("opencode: converted=1 skipped=0 failed=0\n", "")
    header = json.loads(next((store / "sessions").iterdir()).read_text().splitlines()[0])
    assert header["native_id"] == child


def test_self_uses_current_herdr_pane_and_from_herdr_preserves_selected_ids(db, tmp_path, monkeypatch, capsys):
    parent, child = child_setup(db)
    db.commit()
    panes = [{"pane_id": "constructed-pane", "agent_session": {"agent": "opencode", "kind": "id", "value": child}},
             {"pane_id": "constructed-other-pane", "agent_session": {"agent": "codex", "kind": "id", "value": "constructed-thread"}}]
    monkeypatch.setenv("HERDR_PANE_ID", "constructed-pane")
    monkeypatch.setattr(dumping.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps({"result": {"snapshot": {"panes": panes}}})))
    assert dumping.dump(tmp_path / "self", harness="opencode", self_only=True) == 0
    assert capsys.readouterr().out == "opencode: converted=1 skipped=0 failed=0\n"
    assert dumping.dump(tmp_path / "herdr", harness="opencode", from_herdr=True) == 0
    assert capsys.readouterr().out == "opencode: converted=1 skipped=0 failed=0\n"


def test_self_fallback_uses_recorded_directory_and_update_time(db, tmp_path, monkeypatch, capsys):
    parent, child = child_setup(db)
    db.c.execute("UPDATE session SET directory=?,time_updated=? WHERE id=?", (str(tmp_path), T + 200, child))
    db.commit()
    monkeypatch.chdir(tmp_path)
    assert dumping.dump(tmp_path / "self", harness="opencode", self_only=True) == 0
    out = capsys.readouterr()
    assert out.out == "opencode: converted=1 skipped=0 failed=0\n" and "--self fallback" in out.err
    header = json.loads(next((tmp_path / "self/sessions").iterdir()).read_text().splitlines()[0])
    assert header["native_id"] == child


def test_late_stored_input_precedes_its_replies_without_borrowing_time(db, tmp_path):
    sid = "ses_constructed_parent"
    db.session(sid)
    db.message("msg_constructed_user", sid, created=T)
    db.part("prt_constructed_input", "msg_constructed_user", sid, {"type": "text", "text": "Invented input."}, T + 100)
    db.message("msg_constructed_reply", sid, "assistant", T + 1, "msg_constructed_user")
    db.part("prt_constructed_reply", "msg_constructed_reply", sid,
            {"type": "text", "text": "Invented reply.", "time": {"start": T + 2}}, T + 2)
    lines, _ = converted(db, tmp_path)
    prompt = next(e for e in lines[1:] if e["type"] == "prompt")
    reply = next(e for e in lines[1:] if e["type"] == "assistant_text")
    assert prompt["seq"] < reply["seq"] and prompt["turn"] == reply["turn"] == 1
    assert prompt["t"] == opencode._ms(T + 100)  # its own row, not the message's time
    assert reply["t"] == opencode._ms(T + 2)


def test_multiple_calls_in_one_message_have_distinct_sources(db, tmp_path):
    sid = setup_parent(db)
    for i in range(2):
        db.part(f"prt_constructed_call_{i}", "msg_constructed_assistant", sid,
                {"type": "tool", "tool": "bash", "callID": f"constructed-call-{i}", "state": {
                    "status": "completed", "input": {"command": f"invented command {i}"}, "output": "Invented output.",
                    "time": {"start": T + 2, "end": T + 3}}})
    lines, _ = converted(db, tmp_path)
    events = [e for e in lines[1:] if e["type"] in ("tool_call", "tool_result")]
    assert len(events) == len({e["src"] for e in events}) == 4
    calls = {e["data"]["call_id"]: e for e in events if e["type"] == "tool_call"}
    for result in (e for e in events if e["type"] == "tool_result"):
        assert result["of"] == calls[result["data"]["call_id"]]["id"]


def test_missing_fields_and_noninteger_counts_stay_in_raw(db, tmp_path):
    sid = setup_parent(db)
    db.part("prt_constructed_missing", "msg_constructed_assistant", sid, {"type": "tool", "state": {"status": "running"}})
    db.part("prt_constructed_fractional", "msg_constructed_assistant", sid,
            {"type": "step-finish", "tokens": {"input": 2.5, "output": True}, "cost": 0.125}, T + 2)
    lines, _ = converted(db, tmp_path)
    call = next(e for e in lines[1:] if e["type"] == "tool_call")
    assert call["data"] == {"kind": "other"} and "t" not in call
    usage = next(e for e in lines[1:] if e["type"] == "usage" and e.get("x", {}).get("opencode", {}).get("cost") == "0.125")
    assert usage["data"] == {}
    assert json.loads(usage["raw"]["row"]["data"])["tokens"] == {"input": 2.5, "output": True}


def test_synthetic_input_is_caller_and_policy_is_not_a_permission_decision(db, tmp_path):
    sid = setup_parent(db)
    db.c.execute("UPDATE part SET data=? WHERE id=?", (json.dumps({"type": "text", "text": "Invented continuation.", "synthetic": True}), "prt_constructed_user"))
    policy = json.dumps([{"permission": "invented_rule", "action": "allow", "pattern": "invented-resource"}])
    db.c.execute("UPDATE session SET permission=? WHERE id=?", (policy, sid))
    lines, _ = converted(db, tmp_path)
    assert next(e for e in lines[1:] if e["type"] == "prompt")["actor"] == "caller"
    assert not any(e["type"] == "permission" for e in lines[1:])
    assert lines[0]["raw"]["session"]["permission"] == policy


def test_new_user_message_is_marked_as_inferred_boundary_when_delivery_is_absent(db, tmp_path):
    sid = setup_parent(db)
    db.part("prt_constructed_long_tool", "msg_constructed_assistant", sid,
            {"type": "tool", "tool": "bash", "callID": "constructed-long", "state": {
                "status": "completed", "input": {}, "output": "Invented output.", "time": {"start": T + 2, "end": T + 50}}})
    db.text(sid, "msg_constructed_queued", "prt_constructed_queued", "Invented next input.", T + 10)
    lines, _ = converted(db, tmp_path)
    prompts = [e for e in lines[1:] if e["type"] == "prompt"]
    assert len(prompts) == 2 and [e["turn"] for e in prompts] == [1, 2]
    assert all(e["how"]["type"] == "inferred:user-message-boundary" for e in prompts)
    result = next(e for e in lines[1:] if e["type"] == "tool_result")
    assert result["turn"] == 2  # SPEC counts prompts in source order; no guessed delivery mode


def test_live_source_bytes_and_wal_are_unchanged_by_read_only_backup(db, tmp_path):
    db.c.execute("PRAGMA journal_mode=WAL")
    setup_parent(db)
    db.commit()
    paths = [db.path, Path(str(db.path) + "-wal")]
    before = {p: p.read_bytes() for p in paths}
    converted(db, tmp_path)
    assert {p: p.read_bytes() for p in paths} == before


def test_batch_reads_one_consistent_backup_even_if_live_rows_change(db):
    setup_parent(db)
    db.session("ses_constructed_second")
    db.text("ses_constructed_second", "msg_constructed_second", "prt_constructed_second", "Invented before snapshot.")
    db.commit()
    inputs = opencode.selected_sessions(list(opencode.discover()))
    first = next(inputs)
    db.c.execute("UPDATE part SET data=? WHERE id=?", (json.dumps({"type": "text", "text": "Invented after snapshot."}), "prt_constructed_second"))
    db.commit()
    second = next(inputs)
    list(inputs)  # close the shared backup; inputs must remain usable afterward
    lines = base.convert(opencode, second)
    assert second.native_id == "ses_constructed_second"
    assert next(e for e in lines[1:] if e["type"] == "prompt")["data"]["text"] == "Invented before snapshot."
    assert base.convert(opencode, first)[0]["native_id"] == "ses_constructed_parent"


def test_row_key_ids_survive_database_move(db, tmp_path, monkeypatch):
    setup_parent(db)
    before, snapshot = converted(db, tmp_path)
    moved = tmp_path / "constructed-archive.sqlite"
    db.path.rename(moved)
    db.path = moved
    monkeypatch.setenv("OPENCODE_DB", str(moved))
    after, moved_snapshot = converted(db, tmp_path)
    assert before[0]["id"] == after[0]["id"] and before[1:] == after[1:]
    assert snapshot.data == moved_snapshot.data
    assert before[0]["files"]["f1"]["path"] != after[0]["files"]["f1"]["path"]


def test_reasoning_on_summary_message_remains_reasoning(db, tmp_path):
    sid = setup_parent(db)
    db.message("msg_constructed_summary_reasoning", sid, "assistant", T + 40, "msg_constructed_user", summary=True)
    db.part("prt_constructed_summary_reasoning", "msg_constructed_summary_reasoning", sid,
            {"type": "reasoning", "text": "Invented thoughts about a summary.", "time": {"start": T + 41}}, T + 41)
    lines, _ = converted(db, tmp_path)
    event = next(e for e in lines[1:] if e["data"].get("text") == "Invented thoughts about a summary.")
    assert event["type"] == "reasoning" and event["actor"] == "agent"


def test_delayed_step_finish_storage_uses_request_completion_only_for_order(db, tmp_path):
    sid = setup_parent(db)
    db.part("prt_constructed_delayed_finish", "msg_constructed_assistant", sid,
            {"type": "step-finish", "tokens": {"input": 23, "output": 8}}, T + 200)
    db.text(sid, "msg_constructed_next", "prt_constructed_next", "Invented next request.", T + 100)
    lines, _ = converted(db, tmp_path)
    usage = next(e for e in lines[1:] if e["type"] == "usage" and e["data"].get("input_tokens") == 23)
    assert usage["turn"] == 1  # completion was before the next request
    assert usage["t"] == opencode._ms(T + 200)  # no copied completion timestamp
    assert usage["how"]["t"] == "inferred:row-created-time"


def test_core_process_and_initial_route_are_not_treated_as_session_identity(monkeypatch):
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    monkeypatch.setenv("OPENCODE_PID", "12345")
    monkeypatch.setenv("OPENCODE_ROUTE", json.dumps({"type": "session", "sessionID": "ses_constructed_stale"}))
    assert opencode.self_id() is None
    monkeypatch.setenv("XDG_DATA_HOME", "")
    monkeypatch.setenv("HOME", "/home/user")
    assert opencode.data_home() == Path("/home/user/.local/share/opencode")


def test_user_metadata_missing_created_marks_own_row_clock(db, tmp_path):
    sid, mid = "ses_constructed_parent", "msg_constructed_missing_created"
    db.session(sid, created=0)
    data = {"role": "user", "time": {}, "model": {"modelID": "constructed-model"}}
    db.message(mid, sid, created=1000)
    db.c.execute("UPDATE message SET data=? WHERE id=?", (json.dumps(data), mid))
    db.part("prt_constructed_native_time", mid, sid,
            {"type": "text", "text": "Invented input.", "time": {"start": 2000}}, 3000)
    lines, _ = converted(db, tmp_path)
    setting = next(e for e in lines[1:] if e["type"] == "setting")
    # Expected output is constructed, including the clock and exact source row.
    assert {k: setting[k] for k in ("type", "actor", "data", "t", "how", "raw")} == {
        "type": "setting", "actor": "harness", "data": {"model": "constructed-model"},
        "t": "1970-01-01T00:00:01Z",
        "how": {"type": "inferred:message-settings", "t": "inferred:row-created-time"},
        "raw": {"row": {"id": mid, "session_id": sid, "time_created": 1000,
                        "time_updated": 1000, "data": json.dumps(data)}}}
    prompt = next(e for e in lines[1:] if e["type"] == "prompt")
    assert prompt["t"] == "1970-01-01T00:00:02Z" and "t" not in prompt["how"]
