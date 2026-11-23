"""A wadachi converter, as a template.

Copy this file for a new harness. Fill in the parts marked FILL IN: KINDS,
native_id() and map_record(). Keep the rest: it implements what every
converter shares (reading a live file safely, source hashes, ordering, turns,
ids, canonical output), and getting those wrong is how converters drift
apart.

It reads one JSON Lines record file, and optionally a hook log, and writes one
session file. It runs as is on the toy format described in map_record().
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from wadachi import FORMAT, dumps, event_id, session_id
from wadachi.canonical import MAX_SAFE_INTEGER, ecmascript_number
from wadachi.ids import escape_key
from wadachi.times import from_source

HARNESS = "example-harness"  # FILL IN: the harness's name, lowercase
SOURCE_FORMAT = "example-jsonl"  # FILL IN: the record format and its version
CONVERTER = {"name": "wadachi-example", "version": "0.1.0"}

# FILL IN: the harness's tool names and their kinds. Versioned with this file.
# Unknown tools are "other"; a model never chooses a kind.
KINDS = {
    "read_file": "read",
    "write_file": "write",
    "replace": "edit",
    "run": "shell",
    "grep": "search",
}


def native_id(records: list[tuple[int, dict]]) -> str | None:
    """FILL IN: the harness's own session id, if the record holds one."""
    for _, rec in records:
        if isinstance(rec.get("session"), str) and rec["session"]:
            return rec["session"]
    return None


def _time(value: object, raw: dict, name: str) -> dict:
    """{"t": ...} for a source time with a zone; otherwise keep it in raw."""
    if value is None:
        return {}
    t = from_source(value) if isinstance(value, str) else None
    if t is None:
        raw[name] = value
        return {}
    return {"t": t}


def _put(data: dict, key: str, rec: dict, name: str) -> None:
    """Copy a field only if the source has it. Never fill a gap."""
    if name in rec:
        data[key] = rec[name]


def map_record(offset: int, rec: dict) -> list[dict]:
    """FILL IN: turn one source record into event specs.

    A spec is a dict with:
      pos       the part of src after "f1:": str(offset), or "@" + escape_key(id)
                when the source gives the record an id, plus "#/json/pointer"
                when the event is one part of the record
      type, actor, data   as SPEC.md section 4.2 defines
      t         only from a source time with a zone (use _time)
      of_call   the call_id of the tool_call this event answers (optional)
      raw       source fields not mapped, kept as recorded (optional)
      how, x    optional, as SPEC.md defines

    Return [] for records that are not events. Never invent a value: if the
    source does not have it, leave it out. The toy format handled here:
      {"id": "r1", "role": "user", "text": "...", "time": "...Z"}
      {"id": "r2", "role": "assistant", "text": "...", "calls": [{"id": "c1", "name": "run", "input": {...}}]}
      {"id": "r3", "role": "tool", "call": "c1", "name": "run", "exit": 0, "status": "ok", "output": "..."}
    """
    pos = "@" + escape_key(str(rec["id"])) if rec.get("id") is not None else str(offset)
    role = rec.get("role")
    known = {"id", "role", "time", "session"}
    raw: dict = {}
    t = _time(rec.get("time"), raw, "time")

    if role == "user":
        data: dict = {}
        _put(data, "text", rec, "text")
        raw.update({k: v for k, v in rec.items() if k not in known | {"text"}})
        spec = {"pos": pos, "type": "prompt", "actor": "human", "data": data, **t}
        return [spec | ({"raw": raw} if raw else {})]

    if role == "assistant":
        specs = []
        raw.update({k: v for k, v in rec.items() if k not in known | {"text", "calls"}})
        if "text" in rec:
            specs.append({"pos": pos + "#/text", "type": "assistant_text", "actor": "agent", "data": {"text": rec["text"]}, **t})
        for i, call in enumerate(rec.get("calls", [])):
            data = {"kind": KINDS.get(call.get("name"), "other")}
            _put(data, "tool", call, "name")
            _put(data, "call_id", call, "id")
            _put(data, "args", call, "input")
            paths = call.get("input", {}).get("paths") if isinstance(call.get("input"), dict) else None
            if isinstance(paths, list) and all(isinstance(p, str) for p in paths):
                data["paths"] = list(paths)  # the tool's own list, in its order; anything else stays in args
            specs.append({"pos": f"{pos}#/calls/{i}", "type": "tool_call", "actor": "agent", "data": data, **t})
        if raw and specs:
            specs[0]["raw"] = raw
        return specs

    if role == "tool":
        data = {}
        if rec.get("name") is not None:
            data["tool"] = rec["name"]
            data["kind"] = KINDS.get(rec["name"], "other")
        _put(data, "call_id", rec, "call")
        if isinstance(rec.get("exit"), int):
            data["exit_code"] = rec["exit"]
        if "status" in rec:
            status = rec["status"]
            data["status_as_recorded"] = status if isinstance(status, str) else dumps(status)
        _put(data, "text", rec, "output")
        raw.update({k: v for k, v in rec.items() if k not in known | {"call", "name", "exit", "status", "output"}})
        spec = {"pos": pos, "type": "tool_result", "actor": "tool", "data": data, **t}
        if rec.get("call") is not None:
            spec["of_call"] = rec["call"]
        return [spec | ({"raw": raw} if raw else {})]
    return []


def map_hook(offset: int, rec: dict) -> list[dict]:
    """Hook log lines in the format the wadachi-adapter skill recommends."""
    if rec.get("event") != "post_tool":
        return []
    raw: dict = {}
    data = {k: rec[k] for k in ("tree_before", "tree_after", "exit_code", "duration_ms", "cwd") if k in rec}
    spec = {"pos": str(offset), "type": "observation", "actor": "hook", "data": data, **_time(rec.get("at"), raw, "at")}
    if rec.get("call_id") is not None:
        spec["of_call"] = rec["call_id"]
    return [spec | ({"raw": raw} if raw else {})]


# ---- shared machinery: keep as is -------------------------------------------


def _section_2(value: object) -> object:
    """Apply SPEC.md section 2 to a value from a source: lone surrogates become
    U+FFFD, and numbers beyond 2^53 - 1 become strings. Nothing else changes."""
    if isinstance(value, str):
        return "".join("\ufffd" if 0xD800 <= ord(ch) <= 0xDFFF else ch for ch in value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return str(value) if abs(value) > MAX_SAFE_INTEGER else value
    if isinstance(value, float):
        return ecmascript_number(value) if abs(value) > MAX_SAFE_INTEGER else value
    if isinstance(value, list):
        return [_section_2(v) for v in value]
    if isinstance(value, dict):
        return {_section_2(k): _section_2(v) for k, v in value.items()}
    return value


def _read_complete(path: Path) -> tuple[bytes, list[tuple[int, dict]]]:
    """Read once, up to the last complete line. Returns the bytes used and the records.

    A live session may end in a half-written line; it is left for the next
    conversion, and the hash covers exactly the bytes that were converted.
    """
    data = path.read_bytes()
    data = data[: data.rfind(b"\n") + 1]
    records, offset = [], 0
    for line in data.split(b"\n")[:-1]:  # LF only: a bare CR is legal JSON whitespace
        if line.strip():
            records.append((offset, json.loads(line)))
        offset += len(line) + 1
    return data, records


def _display_path(path: Path) -> str:
    """Absolute, symbolic links not resolved, home written as ~ (SPEC.md section 3.3)."""
    p = os.path.abspath(path).replace(os.sep, "/")
    home = os.path.expanduser("~").replace(os.sep, "/")
    return "~" + p[len(home):] if p == home or p.startswith(home + "/") else p


def _source(path: Path, role: str, fmt: str) -> tuple[dict, list[tuple[int, dict]]]:
    data, records = _read_complete(path)
    return {"path": _display_path(path), "role": role, "format": fmt, "sha256": hashlib.sha256(data).hexdigest()}, records


def convert(record_path: Path, hook_path: Path | None = None) -> list[dict]:
    """Convert one session. Returns the header followed by the events."""
    f1, records = _source(record_path, "record", SOURCE_FORMAT)
    files = {"f1": f1}
    records = [(offset, _section_2(rec)) for offset, rec in records]
    specs = [dict(s, key="f1") for offset, rec in records for s in map_record(offset, rec)]
    hook_specs = []
    if hook_path and hook_path.exists():  # key f2 is always the hook log, present or not (SPEC.md section 3.3)
        files["f2"], hooks = _source(hook_path, "hook", "wadachi-hook/0.1")
        hook_specs = [dict(s, key="f2") for offset, rec in hooks for s in map_hook(offset, _section_2(rec))]

    nid = native_id(records)
    sid = session_id(HARNESS, native_id=nid) if nid else session_id(HARNESS, path=f1["path"])
    header = {"type": "session", "format": FORMAT, "id": sid, "harness": {"name": HARNESS},
              "files": files, "converter": CONVERTER}
    if nid:
        header["native_id"] = nid

    # Ids first, so `of` can be resolved and hook events placed (SPEC.md sections 5 and 7).
    for s in specs + hook_specs:
        s["src"] = f"{s['key']}:{s['pos']}"
        s["id"] = event_id(sid, s["src"])
    calls: dict[str, str] = {}
    for s in specs:
        if s["type"] == "tool_call" and "call_id" in s["data"]:
            if s["data"]["call_id"] in calls:
                raise ValueError(f"call id {s['data']['call_id']!r} is used twice; map it explicitly")
            calls[s["data"]["call_id"]] = s["id"]
    for s in specs + hook_specs:
        if s.get("of_call") in calls:
            s["of"] = calls[s["of_call"]]

    ordered, trailing = list(specs), []
    for s in hook_specs:  # one hook file, in source order
        anchor = None
        for k, other in enumerate(ordered):
            if "of" in s and (other["id"] == s["of"] or other.get("of") == s["of"]):
                anchor = k
        if anchor is None:
            trailing.append(s)
        else:
            ordered.insert(anchor + 1, s)
    ordered += trailing

    events, turn = [], 0
    for seq, s in enumerate(ordered):
        if s["type"] == "prompt":
            turn += 1
        e = {"id": s["id"], "seq": seq, "turn": turn, "type": s["type"], "actor": s["actor"], "src": s["src"], "data": s["data"]}
        for opt in ("t", "of", "raw", "how", "x"):
            if opt in s:
                e[opt] = s[opt]
        events.append(e)
    return [header] + events


def write_session(lines: list[dict], store: Path) -> Path:
    out = store / "sessions" / f"{lines[0]['id']}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for obj in lines:
            f.write(dumps(obj) + "\n")
    return out


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=f"Convert a {HARNESS} session to wadachi.")
    parser.add_argument("record", type=Path)
    parser.add_argument("--hooks", type=Path)
    parser.add_argument("--store", type=Path, default=Path("."))
    args = parser.parse_args()
    print(write_session(convert(args.record, args.hooks), args.store))
