"""Shared conversion rules from SPEC.md sections 2 to 7.

Adapters supply the Converter protocol. Positions passed to map_record are
byte offsets for JSONL, or escaped @keys for keyed sources. Event specs have
pos, type, actor and data, plus optional t, raw, how, x and of_call. An of_src
reference names another event's src; of may name its derived event id.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol, Sequence

from wadachi import FORMAT, dumps, event_id, session_id
from wadachi.canonical import MAX_SAFE_INTEGER, ecmascript_number
from wadachi.times import from_source

Position = int | str
Records = list[tuple[Position, dict]]


@dataclass
class Snapshot:
    """The exact bytes hashed, and records read from those same bytes."""

    data: bytes
    records: Records


def section_2(value: object) -> object:
    """Replace lone surrogates and stringify numbers beyond 2^53 - 1."""
    if isinstance(value, str):
        return "".join("\ufffd" if 0xD800 <= ord(ch) <= 0xDFFF else ch for ch in value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return str(value) if abs(value) > MAX_SAFE_INTEGER else value
    if isinstance(value, float):
        return ecmascript_number(value) if abs(value) > MAX_SAFE_INTEGER else value
    if isinstance(value, list):
        return [section_2(v) for v in value]
    if isinstance(value, dict):
        return {section_2(k): section_2(v) for k, v in value.items()}
    return value


def read_jsonl(path: Path) -> Snapshot:
    """Read once, through the last LF. Ignore and do not hash a partial line."""
    data = path.read_bytes()
    data = data[:data.rfind(b"\n") + 1]
    records, offset = [], 0
    for line in data.split(b"\n")[:-1]:
        if line.strip():
            rec = json.loads(line)
            if not isinstance(rec, dict):
                raise ValueError(f"{path}:{offset}: expected an object")
            records.append((offset, rec))
        offset += len(line) + 1
    return Snapshot(data, records)


@contextmanager
def sqlite_backup(path: Path):
    """A consistent physical copy. The live source is opened read-only.

    Adapters can share this copy across many sessions without loading the
    entire database into memory for each one. No migrations or write locks.
    """
    with tempfile.TemporaryDirectory(prefix="wadachi-snapshot-") as directory:
        copy = Path(directory) / "snapshot.sqlite"
        source = sqlite3.connect(Path(os.path.abspath(path)).as_uri() + "?mode=ro", uri=True)
        try:
            target = sqlite3.connect(copy)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        yield copy


def read_sqlite(path: Path, rows: Callable[[sqlite3.Connection], Records]) -> Snapshot:
    """Hash the same physical snapshot whose rows are read (SPEC.md 3.3).

    SQLite backup includes committed WAL data. No row dump or concatenation
    of the live database and WAL is used as the hash input.
    """
    with sqlite_backup(path) as copy:
        data = copy.read_bytes()
        snapshot = sqlite3.connect(copy.as_uri() + "?mode=ro", uri=True)
        try:
            snapshot.execute("PRAGMA query_only = ON")
            records = list(rows(snapshot))
        finally:
            snapshot.close()
    return Snapshot(data, records)


def display_path(path: Path) -> str:
    """Absolute, without resolving symlinks, with home written as ~."""
    p = os.path.abspath(path).replace(os.sep, "/")
    home = os.path.expanduser("~").replace(os.sep, "/")
    return "~" + p[len(home):] if p == home or p.startswith(home + "/") else p


@dataclass
class Source:
    """A fixed file key. Omit absent sources; never renumber other keys.

    Use events=False for a duplicate truncated transcript or a metadata file.
    A custom reader must return bytes and records from one consistent snapshot.
    """

    key: str
    path: Path
    role: str
    format: str
    reader: Callable[[Path], Snapshot] = read_jsonl
    truncated: bool = False
    events: bool = True


@dataclass
class SessionInput:
    """One session, possibly from many files or a shared database.

    header holds recorded session metadata, including parent for children.
    For a child id unique only within its parent, supply native_id='parent/child'.
    Reserve hook_key in the adapter's file layout even when no log is present.
    """

    sources: Sequence[Source]
    native_id: str | None = None
    header: dict = field(default_factory=dict)
    hook_key: str = "f2"


@dataclass
class DiscoveredSession:
    native_id: str | None
    path: Path
    size: int
    cwd: str | None = None
    updated: int | None = None


class Converter(Protocol):
    HARNESS: str
    SOURCE_FORMAT: str
    CONVERTER: dict[str, str]
    KINDS: dict

    def native_id(self, records: Records) -> str | None: ...

    def map_record(self, position: Position, record: dict) -> list[dict]: ...

    def discover(self) -> Iterable[DiscoveredSession]: ...

    # Optional: map_hook(position, record), sessions(paths) -> SessionInput items.
    # sessions([]) discovers all inputs, including children. Without sessions(),
    # each explicit or discovered path is treated as one JSONL session.


def source_time(value: object, raw: dict, name: str) -> dict:
    """A zoned time, or its untouched source value in raw."""
    if value is None:
        return {}
    t = from_source(value) if isinstance(value, str) else None
    if t is None:
        raw[name] = value
        return {}
    return {"t": t}


def map_hook(position: Position, rec: dict) -> list[dict]:
    """The skill's recommended wadachi-hook/0.1 format."""
    if rec.get("event") != "post_tool":
        return []
    raw = {k: v for k, v in rec.items() if k not in {
        "event", "session", "call_id", "at", "tree_before", "tree_after", "exit_code", "duration_ms", "cwd"}}
    data = {k: rec[k] for k in ("tree_before", "tree_after", "exit_code", "duration_ms", "cwd") if k in rec}
    spec = {"pos": str(position), "type": "observation", "actor": "hook", "data": data,
            **source_time(rec.get("at"), raw, "at")}
    if rec.get("call_id") is not None:
        spec["of_call"] = rec["call_id"]
    return [spec | ({"raw": raw} if raw else {})]


def sessions(converter: Converter, paths: Sequence[Path]) -> Iterable[SessionInput]:
    """Use an adapter's grouping, or one JSONL file per session."""
    if hasattr(converter, "sessions"):
        yield from converter.sessions(paths)
    else:
        inputs = paths if paths else [s.path for s in converter.discover()]
        for path in inputs:
            yield SessionInput([Source("f1", path, "record", converter.SOURCE_FORMAT)])


def _file_number(source: Source) -> int:
    if not re.fullmatch(r"f[1-9][0-9]*", source.key):
        raise ValueError(f"invalid file key: {source.key!r}")
    return int(source.key[1:])


def convert(converter: Converter, session: SessionInput | Path, hook_path: Path | None = None) -> list[dict]:
    """Build one header and its events. All shared ordering and ids live here."""
    if isinstance(session, Path):
        session = SessionInput([Source("f1", session, "record", converter.SOURCE_FORMAT)])
    sources = list(session.sources)
    if hook_path is not None:
        sources.append(Source(session.hook_key, hook_path, "hook", "wadachi-hook/0.1"))
    sources.sort(key=_file_number)
    if not sources or sources[0].key != "f1" or sources[0].role != "record":
        raise ValueError("f1 must be the main record source")
    if len({s.key for s in sources}) != len(sources):
        raise ValueError("file keys must be unique; reserve a fixed hook_key")
    roles = {"record": 0, "hook": 1, "aux": 2}
    if any(s.role not in roles for s in sources):
        raise ValueError("source role must be record, hook or aux")
    order = [roles[s.role] for s in sources]
    if order != sorted(order):
        raise ValueError("file keys must order record, hook, then aux sources")
    files, loaded, records = {}, [], []
    for source in sources:
        snapshot = source.reader(source.path)
        info = {"path": display_path(source.path), "role": source.role, "format": source.format,
                "sha256": hashlib.sha256(snapshot.data).hexdigest()}
        if source.truncated:
            info["truncated"] = True
        files[source.key] = info
        cleaned = [(pos, section_2(rec)) for pos, rec in snapshot.records]
        loaded.append((source, cleaned))
        if source.role == "record" and source.events:
            records.extend(cleaned)
    # A fresh adapter may need session context for duplicate views and steers.
    # It sees only records from this same snapshot, never a second live read.
    if hasattr(converter, "prepare"):
        converter = converter.prepare(records)
    metadata = converter.session_header() if hasattr(converter, "session_header") else {}
    for name, value in session.header.items():
        if name in ("x", "raw", "how") and isinstance(metadata.get(name), dict) and isinstance(value, dict):
            metadata[name] = metadata[name] | value
        else:
            metadata[name] = value
    nid = section_2(session.native_id or converter.native_id(records))
    sid = session_id(converter.HARNESS, native_id=nid, path=files["f1"]["path"])
    header = {"type": "session", "format": FORMAT, "id": sid, "harness": {"name": converter.HARNESS},
              "files": files, "converter": converter.CONVERTER}
    if nid:
        header["native_id"] = nid
    if (header.keys() - {"harness"}) & metadata.keys():
        raise ValueError("session metadata must not replace derived header fields")
    header.update(metadata)
    if header["harness"].get("name") != converter.HARNESS:
        raise ValueError("session metadata must keep the converter's harness name")

    specs, extra = [], []
    for source, rows in loaded:
        if not source.events:
            continue
        mapper = converter.map_record if source.role != "hook" else getattr(converter, "map_hook", map_hook)
        for pos, rec in rows:
            if source.role == "hook" and "session" in rec and rec["session"] != nid:
                continue
            for mapped in mapper(pos, rec):
                s = section_2(dict(mapped))
                s["src"] = f"{source.key}:{s.pop('pos')}"
                s["id"] = event_id(sid, s["src"])
                (specs if source.role == "record" else extra).append(s)
    all_specs = specs + extra
    by_src = {s["src"]: s["id"] for s in all_specs}
    if len(by_src) != len(all_specs):
        raise ValueError("duplicate src; use a pointer for each part of a record")
    calls = {}
    for s in specs:
        if s["type"] == "tool_call" and "call_id" in s["data"]:
            call = s["data"]["call_id"]
            if call in calls:
                raise ValueError(f"call id {call!r} is used twice; map it explicitly")
            calls[call] = s["id"]

    def resolve(s: dict, earlier: set[str]) -> None:
        for name, table in (("of_call", calls), ("of_src", by_src)):
            if name in s:
                ref = s.pop(name)
                target = table.get(ref)
                if target in earlier:
                    s["of"] = target
                else:
                    s.setdefault("raw", {})[name] = ref
        if "of" in s and s["of"] not in earlier:
            s.setdefault("raw", {})["of"] = s.pop("of")

    earlier = set()
    for s in specs:
        resolve(s, earlier)
        earlier.add(s["id"])
    ordered, trailing = list(specs), []
    for s in extra:
        resolve(s, earlier)
        if "of" in s:
            # A preceding unlinked extra is pending at the end, but can be a target.
            pool = trailing if any(e["id"] == s["of"] for e in trailing) else ordered
            anchor = max(i for i, e in enumerate(pool) if e["id"] == s["of"] or e.get("of") == s["of"])
            pool.insert(anchor + 1, s)
        else:
            trailing.append(s)
        earlier.add(s["id"])
    ordered += trailing
    events, turn = [], 0
    for seq, s in enumerate(ordered):
        turn += s["type"] == "prompt"
        e = {k: s[k] for k in ("id", "type", "actor", "src", "data", "t", "of", "raw", "how", "x") if k in s}
        events.append(e | {"seq": seq, "turn": turn})
    return section_2([header] + events)


def write_session(lines: list[dict], store: Path) -> Path:
    out = store / "sessions" / f"{lines[0]['id']}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(dumps(obj) + "\n" for obj in lines), encoding="utf-8", newline="\n")
    return out
