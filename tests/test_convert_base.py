"""Constructed records only. No values come from real sessions (WHY.md: Forge)."""

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from wadachi import dumps, session_id
from wadachi.convert.base import (
    DiscoveredSession, SessionInput, Snapshot, Source, convert, display_path,
    read_jsonl, read_sqlite, section_2, sessions, write_session,
)
from wadachi.ids import escape_key
from wadachi.validate import validate_session


class ConstructedConverter:
    HARNESS = "constructed"
    SOURCE_FORMAT = "constructed-jsonl"
    CONVERTER = {"name": "constructed-fixture", "version": "0.1.0"}
    KINDS = {}

    def native_id(self, records):
        return next((r["session"] for _, r in records if "session" in r), None)

    def map_record(self, position, record):
        pos = "@" + escape_key(record["id"]) if "id" in record else str(position)
        return [dict(record["event"], pos=pos)] if "event" in record else []

    def discover(self):
        return []


@pytest.fixture
def converter():
    return ConstructedConverter()


def record(kind="prompt", actor="human", data=None, **fields):
    return {"event": {"type": kind, "actor": actor, "data": data or {}, **fields}}


def source(tmp_path, key="f1", role="record", rows=None, **kwargs):
    path = tmp_path / f"constructed-{key}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in (rows or [])), encoding="utf-8")
    return Source(key, path, role, "constructed-jsonl", **kwargs)


def session(*sources, **kwargs):
    return SessionInput(sources, header={"x": {"fixture": {"constructed": True}}}, **kwargs)


def checked(lines, tmp_path):
    path = write_session(lines, tmp_path / "store")
    assert validate_session(path).problems == []
    return path


def test_byte_identical_rerun(tmp_path, converter):
    src = source(tmp_path, rows=[record(data={"text": "invented prompt"})])
    first = checked(convert(converter, session(src)), tmp_path).read_bytes()
    second = checked(convert(converter, session(src)), tmp_path).read_bytes()
    assert first == second
    assert first.endswith(b"\n") and not first.startswith(b"\xef\xbb\xbf")
    assert all(dumps(json.loads(line)).encode() == line for line in first.splitlines())


def test_partial_line_is_not_read_or_hashed(tmp_path, converter):
    src = source(tmp_path)
    complete = b' {"event":{"type":"prompt","actor":"human","data":{"text":"hi"}}}\r\n\n'
    src.path.write_bytes(complete + b'{"broken":')
    snapshot = read_jsonl(src.path)
    assert snapshot.data == complete
    assert len(snapshot.records) == 1
    first = convert(converter, session(src))
    assert first[0]["files"]["f1"]["sha256"] == hashlib.sha256(complete).hexdigest()
    src.path.write_bytes(complete + b'{"a different partial line')
    assert first == convert(converter, session(src))
    src.path.write_bytes(b'{"only":"partial"}')
    assert read_jsonl(src.path) == Snapshot(b"", [])


def test_jsonl_positions_count_bytes_and_only_lf(tmp_path):
    path = tmp_path / "constructed.jsonl"
    first = '{"text":"\u00e9",\r"id":"one"}\n'.encode()
    path.write_bytes(first + b'{"id":"two"}\n')
    assert [pos for pos, _ in read_jsonl(path).records] == [0, len(first)]


def test_native_ids_survive_moving_sources(tmp_path, converter):
    src = source(tmp_path, rows=[dict(record(), session="invented-session", id="record one")])
    before = convert(converter, session(src))
    moved = tmp_path / "archive" / "constructed.jsonl"
    moved.parent.mkdir()
    src.path.rename(moved)
    src.path = moved
    after = convert(converter, session(src))
    assert before[0]["id"] == after[0]["id"]
    assert before[1:] == after[1:]
    assert before[0]["files"]["f1"]["path"] != after[0]["files"]["f1"]["path"]


def test_paths_keep_symlinks_and_shorten_only_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    link = home / "link"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)
    assert display_path(Path("link/session.jsonl")) == "~/link/session.jsonl"
    assert display_path(home) == "~"
    assert display_path(tmp_path / "home-other") == str(tmp_path / "home-other")


def test_multi_file_session_prefers_complete_copy_and_keeps_fixed_keys(tmp_path, converter):
    short = source(tmp_path, "f1", rows=[dict(record(data={"text": "cut"}), session="invented")],
                   truncated=True, events=False)
    full = source(tmp_path, "f2", rows=[dict(record(data={"text": "complete"}), session="invented")])
    more = source(tmp_path, "f3", rows=[record("assistant_text", "agent", {"text": "later"})])
    aux = source(tmp_path, "f10", "aux", [record("setting", "harness", {"model": "invented-model"})])
    inp = session(aux, more, short, full, hook_key="f4")
    before = convert(converter, inp)
    assert list(before[0]["files"]) == ["f1", "f2", "f3", "f10"]
    assert before[0]["files"]["f1"]["truncated"] is True
    assert [e["src"] for e in before[1:]] == ["f2:0", "f3:0", "f10:0"]
    assert before[1]["data"]["text"] == "complete"
    hook = source(tmp_path, "f4", "hook")
    after = convert(converter, inp, hook.path)
    assert list(after[0]["files"]) == ["f1", "f2", "f3", "f4", "f10"]
    assert before[1:] == after[1:]
    checked(after, tmp_path)


def test_hook_placement_turns_chains_and_forward_references(tmp_path, converter):
    rec = source(tmp_path, rows=[
        record(),
        record("tool_call", "agent", {"kind": "shell", "call_id": "invented-call"}),
        record(data={"text": "second prompt"}),
        record("tool_result", "tool", {"call_id": "invented-call"}, of_call="invented-call"),
    ])
    hook = source(tmp_path, "f2", "hook", [
        record("observation", "hook", of_call="invented-call"),
        record("observation", "hook", of_call="invented-call"),
        record("manifest", "hook"),
        record("observation", "hook", of_src="f2:@unlinked"),
        record("observation", "hook", of_src="f2:@later"),
        record("observation", "hook"),
    ])
    rows = read_jsonl(hook.path).records
    for (_, row), rid in zip(rows, ["first", "second", "unlinked", "chain", "forward", "later"]):
        row["id"] = rid
    hook.path.write_text("".join(json.dumps(r) + "\n" for _, r in rows))
    converter.map_hook = converter.map_record
    lines = convert(converter, session(rec, hook))
    events = lines[1:]
    assert [e["type"] for e in events] == [
        "prompt", "tool_call", "prompt", "tool_result", "observation", "observation",
        "manifest", "observation", "observation", "observation"]
    assert [e["turn"] for e in events] == [1, 1] + [2] * 8
    assert [e["seq"] for e in events] == list(range(10))
    assert events[3]["of"] == events[4]["of"] == events[5]["of"] == events[1]["id"]
    assert events[7]["of"] == events[6]["id"]
    assert events[8]["raw"] == {"of_src": "f2:@later"} and "of" not in events[8]
    checked(lines, tmp_path)


def test_hooks_filter_sessions_and_preserve_missing_call(tmp_path, converter):
    rec = source(tmp_path, rows=[dict(record(), session="invented-session")])
    hook = source(tmp_path, "f2", "hook", [
        {"event": "post_tool", "session": "another-session", "call_id": "missing"},
        {"event": "post_tool", "session": "invented-session", "call_id": "missing",
         "at": "2030-01-02 03:04:05", "extra": "invented"},
    ])
    lines = convert(converter, session(rec), hook.path)
    assert len(lines) == 3
    assert "of" not in lines[-1]
    assert lines[-1]["raw"] == {"of_call": "missing", "at": "2030-01-02 03:04:05", "extra": "invented"}
    checked(lines, tmp_path)


def test_forward_record_call_stays_raw(tmp_path, converter):
    src = source(tmp_path, rows=[
        record("tool_result", "tool", of_call="later-call"),
        record("tool_call", "agent", {"call_id": "later-call", "kind": "other"}),
    ])
    lines = convert(converter, session(src))
    assert lines[1]["raw"] == {"of_call": "later-call"} and "of" not in lines[1]
    checked(lines, tmp_path)


def test_custom_snapshot_reader_and_child_session(tmp_path, converter):
    path = tmp_path / "constructed.json"
    path.write_text(json.dumps(dict(record(), session="parent/child", id="child-event")))

    def reader(path):
        data = path.read_bytes()
        return Snapshot(data, [("@child-event", json.loads(data))])

    parent = session_id(converter.HARNESS, native_id="parent")
    inp = session(Source("f1", path, "record", "constructed-json", reader=reader), native_id="parent/child")
    inp.header.update(mode="subagent", parent={"session": parent, "relation": "subagent"})
    converter.sessions = lambda paths: [inp]
    assert list(sessions(converter, [path])) == [inp]
    lines = convert(converter, inp)
    assert lines[0]["parent"]["session"] == parent
    assert lines[0]["native_id"] == "parent/child"
    assert lines[0]["files"]["f1"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    checked(lines, tmp_path)


def test_sqlite_hashes_physical_snapshot_including_wal(tmp_path, converter):
    path = tmp_path / "constructed.sqlite"
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE part (id TEXT PRIMARY KEY, body TEXT)")
        db.execute("INSERT INTO part VALUES (?, ?)", ("part/invented #1", json.dumps(record(data={"text": "invented"}))))
        db.commit()

        def rows(connection):
            return [("@" + escape_key(key), json.loads(body))
                    for key, body in connection.execute("SELECT id, body FROM part ORDER BY id")]

        captured = []

        def reader(path):
            snapshot = read_sqlite(path, rows)
            captured.append(snapshot)
            return snapshot

        src = Source("f1", path, "record", "constructed-sqlite", reader=reader)
        lines = convert(converter, session(src, native_id="invented-db-session"))
        snapshot = captured[0]
        assert snapshot.data.startswith(b"SQLite format 3\x00")
        assert lines[0]["files"]["f1"]["sha256"] == hashlib.sha256(snapshot.data).hexdigest()
        assert lines[1]["src"] == "f1:@part/invented%20%231"
        assert snapshot.data != path.read_bytes()  # committed content is still in WAL
        copy = tmp_path / "constructed-snapshot.sqlite"
        copy.write_bytes(snapshot.data)
        with sqlite3.connect(copy) as check:
            assert rows(check) == snapshot.records
        assert convert(converter, session(src, native_id="invented-db-session")) == lines
        checked(lines, tmp_path)
        db.execute("INSERT INTO part VALUES (?, ?)", ("second", json.dumps(record())))
        db.commit()
        changed = convert(converter, session(src, native_id="invented-db-session"))
        assert len(changed) == 3
        assert changed[0]["files"]["f1"]["sha256"] != lines[0]["files"]["f1"]["sha256"]
    finally:
        db.close()


def test_section_2_applies_recursively_to_header_and_events(tmp_path, converter):
    src = source(tmp_path, rows=[record(data={"text": "cut \ud800", "extra": [10**20, 1.5e300, True]})])
    inp = session(src)
    inp.header["raw"] = {"cut\udfff": 10**20}
    lines = convert(converter, inp)
    assert lines[0]["raw"] == {"cut\ufffd": "100000000000000000000"}
    assert lines[1]["data"]["text"] == "cut \ufffd"
    assert lines[1]["data"]["extra"] == ["100000000000000000000", "1.5e+300", True]
    assert section_2(None) is None


@pytest.mark.parametrize("key,role", [("f0", "record"), ("f2", "record"), ("f1", "hook"), ("f1", "unknown")])
def test_invalid_source_layouts_are_rejected(tmp_path, converter, key, role):
    with pytest.raises(ValueError):
        convert(converter, session(source(tmp_path, key, role)))


def test_duplicate_positions_and_reserved_hook_key_are_rejected(tmp_path, converter):
    src = source(tmp_path, rows=[dict(record(), id="same"), dict(record(), id="same")])
    with pytest.raises(ValueError, match="duplicate src"):
        convert(converter, session(src))
    other = source(tmp_path, "f2")
    with pytest.raises(ValueError, match="unique"):
        convert(converter, session(src, other), other.path)


def test_record_hook_aux_order_is_required(tmp_path, converter):
    rec = source(tmp_path)
    aux = source(tmp_path, "f2", "aux")
    hook = source(tmp_path, "f3", "hook")
    with pytest.raises(ValueError, match="record, hook, then aux"):
        convert(converter, session(rec, aux, hook))


def test_default_discovery_and_explicit_paths(tmp_path, converter):
    src = source(tmp_path)
    converter.discover = lambda: [DiscoveredSession("invented", src.path, src.path.stat().st_size)]
    assert list(sessions(converter, []))[0].sources[0].path == src.path
    assert list(sessions(converter, [src.path]))[0].sources[0].path == src.path
