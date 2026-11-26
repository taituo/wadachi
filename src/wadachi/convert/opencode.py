"""OpenCode's SQLite session records. See adapters/opencode.md for limits."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from wadachi import dumps, session_id
from wadachi.ids import escape_key
from wadachi.times import from_unix
from . import base

HARNESS = "opencode"
SOURCE_FORMAT = "opencode-session-sqlite/1"
CONVERTER = {"name": "wadachi-opencode", "version": "0.1.4"}
SELF_FROM_HERDR = True
KINDS = {"read": "read", "write": "write", "edit": "edit", "apply_patch": "edit", "bash": "shell",
         "glob": "search", "grep": "search", "webfetch": "fetch", "websearch": "fetch", "task": "subagent",
         "invalid": "other", "question": "other", "skill": "other", "todowrite": "other"}
for _name in ("binary_overview", "binary_session", "close_binary", "execute_rizin_command", "export_evidence_bundle",
              "get_evidence_bundle", "inspect_analysis_settings", "inspect_binary_hardening", "inspect_elf_dependencies",
              "inspect_elf_notes", "inspect_go_binary", "inspect_native_exports", "inspect_rust_binary", "inspect_with_objdump",
              "open_binary", "search_guidance", "update_analysis_settings"):
    KINDS["rea_" + _name] = "mcp"


def data_home():
    root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(root).expanduser() / "opencode"


def databases():
    explicit = os.environ.get("OPENCODE_DB")
    if explicit == ":memory:":
        raise ValueError("OPENCODE_DB=:memory: has no on-disk session source")
    if explicit:
        p = Path(explicit).expanduser()
        return [p if p.is_absolute() else data_home() / p]
    if os.environ.get("OPENCODE_DISABLE_CHANNEL_DB") in ("1", "true"):
        path = data_home() / "opencode.db"
        return [path] if path.is_file() else []
    return sorted(data_home().glob("opencode*.db"))


def _connect(path):
    c = sqlite3.connect(Path(os.path.abspath(path)).as_uri() + "?mode=ro", uri=True)
    c.execute("PRAGMA query_only = ON")
    c.row_factory = sqlite3.Row
    return c


def discover():
    for path in databases():
        with base.sqlite_backup(path) as copy:
            c = _connect(copy)
            try:
                for r in c.execute("SELECT id,directory,time_updated FROM session ORDER BY id COLLATE BINARY"):
                    yield base.DiscoveredSession(r["id"], path, path.stat().st_size, r["directory"], r["time_updated"])
            finally:
                c.close()


def self_id():
    # Optional wrapper/plugin convention. Core 1.19.6 does not export this.
    return os.environ.get("OPENCODE_SESSION_ID")


def caller_present():
    return os.environ.get("OPENCODE") == "1"


def select_self(discovered, cwd):
    matches = [s for s in discovered if s.cwd == cwd]
    return [max(matches, key=lambda s: (s.updated or 0, s.native_id or ""))] if matches else []


def native_id(records):
    return next((r["row"]["id"] for _, r in records if r["table"] == "session" and r.get("primary")), None)


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _rows(c, table, where, params):
    return [dict(r) for r in c.execute(f"SELECT * FROM {_quote(table)} WHERE {where} ORDER BY id COLLATE BINARY", params)]


def _task_links(c):
    links = {}
    for r in c.execute("SELECT * FROM part WHERE json_extract(data,'$.type')='tool' AND json_extract(data,'$.tool')='task' ORDER BY id COLLATE BINARY"):
        data = json.loads(r["data"])
        child = data.get("state", {}).get("metadata", {}).get("sessionId")
        if isinstance(child, str):
            links.setdefault(child, []).append(dict(r))
    return links


def _session_snapshot(c, nid, links):
    """Copy unchanged rows from one backup into a deterministic physical subset.

    This is a scoped database snapshot, not a JSON digest. Original table DDL,
    column values and JSON strings stay untouched. Referenced project and
    parent context rows keep foreign keys complete. Selection and order are fixed.
    """
    selected = {"session": _rows(c, "session", "id=?", (nid,)),
                "message": _rows(c, "message", "session_id=?", (nid,)),
                "part": _rows(c, "part", "session_id=?", (nid,))}
    if not selected["session"]:
        raise ValueError("selected OpenCode session is absent")
    parent = selected["session"][0].get("parent_id")
    context = [r for r in links.get(nid, []) if r["session_id"] == parent]
    if context:
        selected["session"] += _rows(c, "session", "id=?", (parent,))
        mids = sorted({r["message_id"] for r in context})
        for mid in mids:
            selected["message"] += _rows(c, "message", "id=?", (mid,))
    for table in ("session", "message"):
        selected[table].sort(key=lambda r: r["id"])
    projects = []
    for pid in sorted({r["project_id"] for r in selected["session"]}):
        projects += _rows(c, "project", "id=?", (pid,))
    selected = {"project": projects, **selected}
    part_ids = {r["id"] for r in selected["part"]}
    selected["part"] += [r for r in context if r["id"] not in part_ids]
    selected["part"].sort(key=lambda r: r["id"])
    with tempfile.TemporaryDirectory(prefix="wadachi-opencode-") as directory:
        path = Path(directory) / "session.sqlite"
        target = sqlite3.connect(path)
        try:
            target.execute("PRAGMA foreign_keys = ON")
            for table, rows in selected.items():
                ddl = c.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (table,)).fetchone()[0]
                target.execute(ddl)
                if rows:
                    columns = list(rows[0])
                    sql = f"INSERT INTO {_quote(table)} ({','.join(_quote(k) for k in columns)}) VALUES ({','.join('?' for _ in columns)})"
                    target.executemany(sql, [tuple(r[k] for k in columns) for r in rows])
            target.commit()
        finally:
            target.close()
        data = path.read_bytes()
        # Read the records from the very database whose bytes will be hashed.
        view = _connect(path)
        try:
            records = _records(view, nid)
        finally:
            view.close()
    return base.Snapshot(data, records)


def selected_sessions(discovered):
    grouped = {}
    for found in discovered:
        grouped.setdefault(found.path, set()).add(found.native_id)
    for path, ids in grouped.items():
        with base.sqlite_backup(path) as copy:
            c = _connect(copy)
            try:
                links = _task_links(c)
                for nid in sorted(ids):
                    snapshot = _session_snapshot(c, nid, links)
                    reader = lambda unused, snapshot=snapshot: snapshot
                    yield base.SessionInput([base.Source("f1", path, "record", SOURCE_FORMAT, reader=reader)], native_id=nid)
            finally:
                c.close()


def sessions(paths):
    paths = list(dict.fromkeys(paths or databases()))
    found = []
    for path in paths:
        with base.sqlite_backup(path) as copy:
            c = _connect(copy)
            try:
                ids = [r[0] for r in c.execute("SELECT id FROM session ORDER BY id COLLATE BINARY")]
            finally:
                c.close()
        found.extend(base.DiscoveredSession(nid, path, path.stat().st_size) for nid in ids)
    yield from selected_sessions(found)


def _ms(value):
    if isinstance(value, int) and not isinstance(value, bool):
        try:
            return from_unix(value // 1000, value % 1000 * 1_000_000)
        except ValueError:
            pass
    return None


def _records(c, nid):
    """Source order: fact time, phase, then stable table/key; never rowid."""
    result = []
    def add(table, r, phase, time, priority=1, order_time=None, clock=None, decoded=None, **extra):
        d = decoded if decoded is not None else json.loads(r["data"]) if table != "session" else r
        rec = {"table": table, "row": r, "data": d, "phase": phase, "time": time, "clock": clock, **extra}
        ordering = order_time if order_time is not None else time
        result.append((ordering if isinstance(ordering, int) and not isinstance(ordering, bool) else r.get("time_created", 0),
                       priority, table, r["id"], "@" + escape_key(table + "/" + r["id"]), rec))
    for r in _rows(c, "session", "id=?", (nid,)):
        add("session", r, "header", r["time_created"], primary=True)
    messages = _rows(c, "message", "session_id=?", (nid,))
    message_data = {r["id"]: json.loads(r["data"]) for r in messages}
    for r in messages:
        d = json.loads(r["data"])
        add("message", r, "metadata", d.get("time", {}).get("created", r["time_created"]),
            clock=None if "created" in d.get("time", {}) else "row-created-time")
        if d.get("role") == "assistant":
            clock = None if "completed" in d.get("time", {}) else "row-updated-time"
            add("message", r, "usage", d.get("time", {}).get("completed", r["time_updated"]), 3, clock=clock)
            if "error" in d:
                add("message", r, "error", d.get("time", {}).get("completed", r["time_updated"]), 2, clock=clock)
    for r in _rows(c, "part", "1", ()):
        d = json.loads(r["data"])
        if r["session_id"] != nid:
            add("part", r, "context", r["time_created"], decoded=d)
            continue
        if d.get("type") == "tool":
            state = d.get("state", {})
            time = state.get("time", {})
            add("part", r, "call", time.get("start"), 0, decoded=d)
            if d.get("tool") == "task" and isinstance(state.get("metadata", {}).get("sessionId"), str):
                add("part", r, "child", time.get("start"), 1, decoded=d)
            if state.get("status") in ("completed", "error"):
                add("part", r, "result", time.get("end"), 2, decoded=d)
        else:
            message = message_data.get(r["message_id"], {})
            # A text part can be persisted after replies already started.
            # Its message's creation orders the input, but never supplies t.
            order_time = message.get("time", {}).get("created") if message.get("role") == "user" else None
            if d.get("type") == "step-finish":
                order_time = message.get("time", {}).get("completed", message.get("time", {}).get("created"))
            add("part", r, "part", d.get("time", {}).get("start", r["time_created"]),
                0 if d.get("type") == "text" else 1, order_time=order_time,
                clock=None if "start" in d.get("time", {}) else "row-created-time", decoded=d)
    result.sort(key=lambda x: x[:4])
    return [(r[4], r[5]) for r in result]


def _paths(tool, args):
    if not isinstance(args, dict):
        return None
    name = "filePath" if tool in ("read", "write", "edit") else "path" if tool in ("glob", "grep") else None
    if name and isinstance(args.get(name), str):
        return [args[name]]
    return None


class _Session:
    HARNESS, SOURCE_FORMAT, CONVERTER, KINDS = HARNESS, SOURCE_FORMAT, CONVERTER, KINDS
    native_id = staticmethod(native_id)

    def __init__(self, records):
        self.records = records
        self.sid = native_id(records)
        self.session = next(r["row"] for _, r in records if r["table"] == "session" and r.get("primary"))
        # Metadata supplies roles and summary flags, not neighbouring clocks.
        self.parent_task = next((r for _, r in records if r.get("phase") == "context"), None)
        self.messages = {r["row"]["id"]: r["data"] for _, r in records if r["table"] == "message"}
        self.first_text = {}
        for pos, rec in records:
            if rec["table"] == "part" and rec["data"].get("type") == "text":
                self.first_text.setdefault(rec["row"]["message_id"], pos)

    def session_header(self):
        s = self.session
        header = {"harness": {"name": HARNESS, "version": s["version"]}, "cwd": s["directory"], "raw": {"session": s}}
        t = _ms(s.get("time_created"))
        if t:
            header["started_at"] = t
        if self.parent_task:
            header["mode"] = "subagent"
            header["parent"] = {"session": session_id(HARNESS, native_id=s["parent_id"]), "relation": "subagent"}
            header["how"] = {"mode": "inferred:task-child", "parent.relation": "inferred:task-child"}
            header["raw"]["parent_task"] = self.parent_task["row"]
        skipped = Counter()
        for pos, rec in self.records:
            if rec["table"] == "part" and rec["phase"] == "part" and not self.map_record(pos, rec):
                skipped[rec["data"].get("type", "unknown")] += 1
        if skipped:
            header["x"] = {HARNESS: {"skipped_parts": dict(skipped)}}
        return header

    def _event(self, pos, rec, typ, actor, data=None, pointer="", **fields):
        event = {"pos": pos + pointer, "type": typ, "actor": actor, "data": data or {},
                 "raw": {"row": rec["row"]}, **fields}
        t = _ms(rec.get("time"))
        if t:
            event["t"] = t
            if rec.get("clock"):
                event.setdefault("how", {})["t"] = "inferred:" + rec["clock"]
        return event

    def _usage(self, pos, rec, pointer):
        d = rec["data"]
        tokens = d.get("tokens", {})
        data = {}
        for name in ("input", "output"):
            v = tokens.get(name)
            if isinstance(v, int) and not isinstance(v, bool):
                data[name + "_tokens"] = v
        for name in ("read", "write"):
            v = tokens.get("cache", {}).get(name)
            if isinstance(v, int) and not isinstance(v, bool):
                data["cache_" + name + "_tokens"] = v
        fields = {}
        if "cost" in d:
            cost = d["cost"]
            fields["x"] = {HARNESS: {"cost": cost if isinstance(cost, str) else dumps(cost)}}
        return self._event(pos, rec, "usage", "harness", data, pointer, **fields)

    def map_record(self, pos, rec):
        table, phase, d = rec["table"], rec["phase"], rec["data"]
        if table == "session" or phase == "context":
            return []
        if table == "message":
            if phase == "metadata":
                if d.get("role") != "user":
                    return []
                model = d.get("model", {})
                data = {"model": model["modelID"]} if isinstance(model, dict) and isinstance(model.get("modelID"), str) else {}
                return [self._event(pos, rec, "setting", "harness", data,
                                    how={"type": "inferred:message-settings"})]
            if phase == "usage":
                return [self._usage(pos, rec, "#/data/tokens")]
            error = d.get("error", {})
            data = {}
            if isinstance(error.get("name"), str):
                data["code"] = error["name"]
            if isinstance(error.get("data", {}).get("message"), str):
                data["text"] = error["data"]["message"]
            return [self._event(pos, rec, "error", "harness", data, "#/data/error")]
        typ = d.get("type")
        if typ == "tool":
            state, tool = d.get("state", {}), d.get("tool")
            meta = state.get("metadata", {})
            kind = KINDS.get(tool, "mcp" if isinstance(tool, str) and tool.startswith("mcp__") else "other")
            data = {"kind": kind}
            if isinstance(tool, str):
                data["tool"] = tool
            if isinstance(d.get("callID"), str):
                data["call_id"] = d["callID"]
            if phase == "call":
                if "input" in state:
                    data["args"] = state["input"]
                paths = _paths(tool, state.get("input"))
                if paths is not None:
                    data["paths"] = paths
                return [self._event(pos, rec, "tool_call", "agent", data, "#/data")]
            if phase == "child":
                child = meta["sessionId"]
                event = self._event(pos, rec, "subagent_start", "agent", {"session": session_id(HARNESS, native_id=child)},
                                    "#/data/state/metadata/sessionId", how={"type": "inferred:task-session-link"})
                event.pop("t", None)  # metadata has no recorded child-start clock
                return [event]
            data["status_as_recorded"] = state["status"]
            if isinstance(meta.get("exit"), int) and not isinstance(meta["exit"], bool):
                data["exit_code"] = meta["exit"]
            text = state.get("output", state.get("error"))
            if isinstance(text, str):
                data["text"] = text
            if isinstance(meta.get("truncated"), bool):
                data["text_truncated"] = meta["truncated"]
            files = meta.get("files")
            if isinstance(files, list):
                paths = []
                for f in files:
                    if isinstance(f, dict):
                        paths.extend(f[k] for k in ("filePath", "movePath") if isinstance(f.get(k), str))
                if paths:
                    data["paths"] = paths
            event = self._event(pos, rec, "tool_result", "tool", data, "#/data/state")
            event["of_src"] = "f1:" + pos + "#/data"
            return [event]
        if typ in ("text", "reasoning"):
            message = self.messages.get(rec["row"]["message_id"], {})
            data = {"text": d["text"]} if isinstance(d.get("text"), str) else {}
            if message.get("role") == "user":
                if self.first_text.get(rec["row"]["message_id"]) != pos:
                    return []
                actor = "caller" if self.parent_task or d.get("synthetic") is True else "human"
                return [self._event(pos, rec, "prompt", actor, data,
                                    how={"type": "inferred:user-message-boundary", "actor": "inferred:input-origin"})]
            if typ == "text" and message.get("summary") is True:
                return [self._event(pos, rec, "compaction", "harness", data, how={"type": "inferred:summary-message"})]
            return [self._event(pos, rec, "reasoning" if typ == "reasoning" else "assistant_text", "agent", data)]
        if typ == "step-finish":
            return [self._usage(pos, rec, "")]
        if typ == "compaction":
            return [self._event(pos, rec, "compaction", "harness")]
        return []


def prepare(records):
    return _Session(records)


def map_record(pos, rec):
    raise ValueError("OpenCode mapping needs the prepared session context")
