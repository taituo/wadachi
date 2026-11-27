"""A constructed toy converter on top of wadachi.convert.base.

Fill in the constants, KINDS, native_id(), map_record() and discover().
prepare(), session_header() and unmapped() show the metadata record and
records of an unknown role; keep them if your harness has those.
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
# measured: the harness versions whose real files you checked this converter against.
CONVERTER = {"name": "wadachi-example-constructed", "version": "0.1.0", "measured": []}

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


class _Prepared:
    """One conversion's context; everything else is this module's."""

    def __init__(self, meta: dict | None):
        self.meta = meta

    def __getattr__(self, name):
        try:
            return globals()[name]
        except KeyError:
            raise AttributeError(name) from None

    def session_header(self) -> dict:
        return session_header(self.meta)

    def map_record(self, offset: int, rec: dict) -> list[dict] | None:
        return map_record(offset, rec, self.meta)


def prepare(records: list[tuple[int, dict]]) -> _Prepared:
    """Session context from the same snapshot the base hashes. Here: the first meta record."""
    return _Prepared(next((rec for _, rec in records if rec.get("role") == "meta"), None))


def session_header(meta: dict | None = None) -> dict:
    """FILL IN: header fields the harness recorded, and its metadata record kept whole."""
    if meta is None:
        return {}
    header: dict = {"harness": {"name": HARNESS}, "raw": {"meta": meta}}
    if isinstance(meta.get("version"), str):
        header["harness"]["version"] = meta["version"]
    for name in ("cwd", "model"):
        if isinstance(meta.get(name), str):
            header[name] = meta[name]
    return header


def unmapped(offset: int, rec: dict) -> dict:
    """A record no event type fits, kept whole. This format names records by role."""
    pos = "@" + escape_key(str(rec["id"])) if rec.get("id") is not None else str(offset)
    data = {"name": rec["role"]} if isinstance(rec.get("role"), str) else {}
    return {"pos": pos, "type": "record", "actor": "harness", "data": data, "raw": rec}


def _put(data: dict, key: str, rec: dict, name: str) -> None:
    """Copy a field only if the source has it. Never fill a gap."""
    if name in rec:
        data[key] = rec[name]


def map_record(offset: int, rec: dict, meta: dict | None = None) -> list[dict] | None:
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

    Return None only for the metadata record that session_header() keeps whole.
    Return [] for anything else you cannot map: the base then calls unmapped()
    and keeps it as a record event. Never invent a value: if the source does
    not have it, leave it out. The toy format handled here:
      {"id": "r0", "role": "meta", "session": "...", "version": "1.2.3", "cwd": "/work", "model": "..."}
      {"id": "r1", "role": "user", "text": "...", "time": "...Z"}
      {"id": "r2", "role": "assistant", "text": "...", "calls": [{"id": "c1", "name": "run", "input": {...}}]}
      {"id": "r3", "role": "tool", "call": "c1", "name": "run", "exit": 0, "status": "ok", "output": "..."}
    """
    pos = "@" + escape_key(str(rec["id"])) if rec.get("id") is not None else str(offset)
    role = rec.get("role")
    if role == "meta" and rec is meta:
        return None  # kept whole in the header's raw.meta
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
        exit_code = rec.get("exit")
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            data["exit_code"] = exit_code
        elif "exit" in rec:
            raw["exit"] = exit_code  # null or a string is not an exit code; keep it as recorded
        if "status" in rec:
            status = rec["status"]
            data["status_as_recorded"] = status if isinstance(status, str) else dumps(status)
        _put(data, "text", rec, "output")
        raw.update({k: v for k, v in rec.items() if k not in known | {"call", "name", "exit", "status", "output"} | raw.keys()})
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
                              native_id=native_id, map_record=map_record, discover=discover,
                              prepare=prepare, unmapped=unmapped)
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
