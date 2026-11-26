"""A constructed toy converter on top of wadachi.convert.base.

Fill in the constants, KINDS, native_id(), map_record() and discover().
Register the module in wadachi.convert.REGISTRY. For multi-file or database
sessions, also supply sessions(paths); see base.SessionInput and base.Source.
All source reads, ids, ordering and canonical writing belong to base.py.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from wadachi import dumps
from wadachi.convert import base
from wadachi.convert.base import source_time as _time, write_session
from wadachi.ids import escape_key

HARNESS = "example-harness"  # FILL IN: the harness's name, lowercase
SOURCE_FORMAT = "constructed-example-jsonl"  # FILL IN: the record format and its version
CONVERTER = {"name": "wadachi-example-constructed", "version": "0.1.0"}

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


def discover() -> list[base.DiscoveredSession]:
    """FILL IN: list native ids, paths and byte sizes without printing."""
    return []


def convert(record_path: Path, hook_path: Path | None = None) -> list[dict]:
    adapter = SimpleNamespace(HARNESS=HARNESS, SOURCE_FORMAT=SOURCE_FORMAT,
                              CONVERTER=CONVERTER, KINDS=KINDS,
                              native_id=native_id, map_record=map_record, discover=discover)
    # This example is constructed (WHY.md: Forge). Real adapters omit the marker.
    session = base.SessionInput([base.Source("f1", record_path, "record", SOURCE_FORMAT)],
                                header={"x": {"fixture": {"constructed": True}}})
    return base.convert(adapter, session, hook_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=f"Convert a {HARNESS} session to wadachi.")
    parser.add_argument("record", type=Path)
    parser.add_argument("--hooks", type=Path)
    parser.add_argument("--store", type=Path, default=Path("."))
    args = parser.parse_args()
    print(write_session(convert(args.record, args.hooks), args.store))
