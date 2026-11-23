"""A wadachi converter, as a template.

Copy this file for a new harness. Fill in the three marked parts: KINDS,
native_id() and map_record(). Keep the rest: it implements the parts of the
format every converter shares (source hashes, ordering, turns, ids, canonical
output), and getting those wrong is how converters drift apart.

It reads one JSON Lines record file, and optionally a hook log, and writes one
session file. It runs as is on the toy format described in map_record().
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from wadachi import FORMAT, dumps, event_id, session_id

HARNESS = "example-harness"  # FILL IN: the harness's name, lowercase
SOURCE_FORMAT = "example-jsonl"  # FILL IN: the record format and its version
CONVERTER = {"name": "wadachi-example", "version": "0.1.0"}

# FILL IN: the harness's tool names and their kinds. Versioned with this file.
# A tool missing from the table is "other"; never let a model choose.
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
        if rec.get("session"):
            return rec["session"]
    return None


def map_record(offset: int, rec: dict) -> list[dict]:
    """FILL IN: turn one source record into event specs.

    A spec is a dict with:
      pos     the position part of src: str(offset), or "@" + a stable record
              id when the source has one, plus "#/json/pointer" when the event
              is one part of the record
      type, actor, data   as SPEC.md section 4.2 defines
      t       only if the record holds a time with a zone
      of_call the call_id of the tool_call this event answers (optional)
      raw, how, x         optional, as SPEC.md defines

    Return [] for records that are not events. Never invent a value: leave it
    out. The toy format handled here has records like
      {"id": "r1", "role": "user", "text": "...", "time": "...Z"}
      {"id": "r2", "role": "assistant", "text": "...", "calls": [{"id": "c1", "name": "run", "input": {...}}]}
      {"id": "r3", "role": "tool", "call": "c1", "name": "run", "exit": 0, "output": "..."}
    """
    pos = "@" + rec["id"] if rec.get("id") else str(offset)
    t = {"t": rec["time"]} if rec.get("time") else {}
    role = rec.get("role")
    if role == "user":
        return [{"pos": pos, "type": "prompt", "actor": "human", "data": {"text": rec.get("text", "")}, **t}]
    if role == "assistant":
        specs = []
        if rec.get("text"):
            specs.append({"pos": pos + "#/text", "type": "assistant_text", "actor": "agent", "data": {"text": rec["text"]}, **t})
        for i, call in enumerate(rec.get("calls", [])):
            data = {"tool": call.get("name", ""), "kind": KINDS.get(call.get("name"), "other"), "call_id": call["id"], "args": call.get("input", {})}
            paths = call.get("input", {}).get("paths")  # only where the tool itself names paths
            if paths:
                data["paths"] = list(paths)
            specs.append({"pos": f"{pos}#/calls/{i}", "type": "tool_call", "actor": "agent", "data": data, **t})
        return specs
    if role == "tool":
        data = {"tool": rec.get("name", ""), "kind": KINDS.get(rec.get("name"), "other"), "call_id": rec["call"]}
        if isinstance(rec.get("exit"), int):
            data["exit_code"] = rec["exit"]
        if "status" in rec:
            data["status_as_recorded"] = str(rec["status"])
        if "output" in rec:
            data["text"] = rec["output"]
        return [{"pos": pos, "type": "tool_result", "actor": "tool", "data": data, "of_call": rec["call"], **t}]
    return []


def map_hook(offset: int, rec: dict) -> list[dict]:
    """Hook log lines, as the wadachi-adapter skill recommends writing them."""
    if rec.get("event") != "post_tool":
        return []
    data = {k: rec[k] for k in ("tree_before", "tree_after", "exit_code", "duration_ms", "cwd") if k in rec}
    return [{"pos": str(offset), "type": "observation", "actor": "hook", "data": data, "of_call": rec.get("call_id")}]


# ---- shared machinery: keep as is -------------------------------------------


def _read_jsonl(path: Path) -> list[tuple[int, dict]]:
    """(byte offset, record) for every non-blank line."""
    out, offset = [], 0
    with path.open("rb") as f:
        for line in f:
            if line.strip():
                out.append((offset, json.loads(line)))
            offset += len(line)
    return out


def _display_path(path: Path) -> str:
    home = str(Path.home())
    p = str(path.resolve())
    return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p


def convert(record_path: Path, hook_path: Path | None = None) -> list[dict]:
    """Convert one session. Returns the header followed by the events."""
    files = {"f1": {"path": _display_path(record_path), "role": "record", "format": SOURCE_FORMAT,
                    "sha256": hashlib.sha256(record_path.read_bytes()).hexdigest()}}
    records = _read_jsonl(record_path)
    specs = [dict(s, key="f1") for offset, rec in records for s in map_record(offset, rec)]
    hook_specs = []
    if hook_path and hook_path.exists():
        files["f2"] = {"path": _display_path(hook_path), "role": "hook", "format": "wadachi-hook/0.1",
                       "sha256": hashlib.sha256(hook_path.read_bytes()).hexdigest()}
        hook_specs = [dict(s, key="f2") for offset, rec in _read_jsonl(hook_path) for s in map_hook(offset, rec)]

    nid = native_id(records)
    sid = session_id(HARNESS, native_id=nid) if nid else session_id(HARNESS, path=files["f1"]["path"])
    header = {"type": "session", "format": FORMAT, "id": sid, "harness": {"name": HARNESS},
              "files": files, "converter": CONVERTER}
    if nid:
        header["native_id"] = nid

    # Ids first, so `of` can be resolved and hook events placed (SPEC.md sections 5 and 7).
    for s in specs + hook_specs:
        s["id"] = event_id(sid, files[s["key"]]["path"], s["pos"], s["type"])
    calls = {s["data"]["call_id"]: s["id"] for s in specs if s["type"] == "tool_call" and "call_id" in s["data"]}
    for s in specs + hook_specs:
        if s.get("of_call") in calls:
            s["of"] = calls[s["of_call"]]

    ordered, trailing = list(specs), []
    for s in hook_specs:
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
        e = {"id": s["id"], "seq": seq, "turn": turn, "type": s["type"], "actor": s["actor"],
             "src": f"{s['key']}:{s['pos']}", "data": s["data"]}
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
