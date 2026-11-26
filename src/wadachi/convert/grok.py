"""Grok CLI sessions. Mapping facts and gaps are in adapters/grok.md."""

from __future__ import annotations

import json
import os
from pathlib import Path

from wadachi.ids import escape_key
from . import base

HARNESS = "grok"
SOURCE_FORMAT = "grok-chat-history-jsonl"
CONVERTER = {"name": "wadachi-grok", "version": "0.2.0", "measured": ["1.0.92"]}
SELF_FROM_HERDR = True
# f1 chat history; f2 reserved for a hook log; then fixed aux keys.
AUX = {"f3": ("events.jsonl", "grok-events-jsonl", True),
       "f4": ("system_prompt.txt", "grok-system-prompt-text", True),
       "f5": ("tool_definitions.json", "grok-tool-definitions-json", True),
       "f6": ("summary.json", "grok-summary-json", False),
       "f7": ("prompt_context.json", "grok-prompt-context-json", False),
       "f8": ("usage.json", "grok-usage-json", False)}
KINDS = {"read_file": "read", "list_dir": "read", "write": "write", "search_replace": "edit",
         "run_terminal_command": "shell", "grep": "search"}
DECISIONS = {"allow": "allowed", "deny": "denied", "reject": "denied"}


def grok_home() -> Path:
    return Path(os.environ.get("GROK_HOME", str(Path.home() / ".grok"))).expanduser()


def _json_reader(path: Path) -> base.Snapshot:
    data = path.read_bytes()
    value = json.loads(data)
    return base.Snapshot(data, [(0, value if isinstance(value, dict) else {"value": value})])


def _text_reader(path: Path) -> base.Snapshot:
    data = path.read_bytes()
    return base.Snapshot(data, [(0, {"text": data.decode("utf-8", errors="surrogateescape")})])


def _summary(directory: Path) -> dict:
    try:
        value = json.loads((directory / "summary.json").read_bytes())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def discover():
    for path in sorted((grok_home() / "sessions").glob("*/*/chat_history.jsonl")):
        info = _summary(path.parent).get("info") or {}
        try:
            stat = path.stat()
            nid = info.get("id") if isinstance(info.get("id"), str) else None
            cwd = info.get("cwd") if isinstance(info.get("cwd"), str) else None
            yield base.DiscoveredSession(nid, path, stat.st_size, cwd, stat.st_mtime_ns)
        except OSError:
            yield base.DiscoveredSession(None, path, 0)


def sessions(paths):
    for path in paths or [s.path for s in discover()]:
        directory = path.parent
        sources = [base.Source("f1", path, "record", SOURCE_FORMAT)]
        for key, (name, fmt, events) in AUX.items():
            p = directory / name
            if not p.is_file():
                continue
            reader = base.read_jsonl if name.endswith(".jsonl") else _text_reader if name.endswith(".txt") else _json_reader
            snapshot = reader(p)  # read once: the header and the hash use the same bytes
            sources.append(base.Source(key, p, "aux", fmt, reader=lambda unused, s=snapshot: s, events=events))
        read = {s.path for s in sources}
        unread = [p for p in sorted(directory.rglob("*")) if p.is_file() and p not in read]
        summary = next((s.reader(s.path).records[0][1] for s in sources if s.key == "f6"), {})
        info = summary.get("info") if isinstance(summary.get("info"), dict) else {}
        nid = info.get("id") if isinstance(info.get("id"), str) and info["id"] else None
        yield base.SessionInput(sources, native_id=nid, unread=unread)


def selected_sessions(discovered):
    yield from sessions([s.path for s in discovered])


def select_self(discovered, cwd):
    matches = [s for s in discovered if s.cwd == cwd]
    return [max(matches, key=lambda s: (s.updated or 0, str(s.path)))] if matches else []


def native_id(records):
    return None  # chat history lines carry no session id; attach_aux reads summary.json


class _Session:
    HARNESS = HARNESS
    SOURCE_FORMAT = SOURCE_FORMAT
    CONVERTER = CONVERTER
    KINDS = KINDS

    def __init__(self, records):
        self.records = records
        self.aux = {}
        self.model = None
        ids = [r.get("id") for _, r in records if r.get("type") == "reasoning"]
        self.reasoning_ids = {i for i in ids if isinstance(i, str) and ids.count(i) == 1}

    def attach_aux(self, aux):
        self.aux = aux

    def _one(self, key):
        rows = self.aux.get(key) or []
        return rows[0][1] if rows else {}

    native_id = staticmethod(native_id)

    def session_header(self):
        summary, context, usage = self._one("f6"), self._one("f7"), self._one("f8")
        header = {"harness": {"name": HARNESS}}
        # prompt_context.version is the prompt format's number, not the CLI's version; none is recorded.
        info = summary.get("info") or {}
        if isinstance(info.get("cwd"), str):
            header["cwd"] = info["cwd"]
        first = next((r.get("model_id") for _, r in self.aux.get("f3") or []
                      if r.get("type") == "turn_started" and isinstance(r.get("model_id"), str)), None)
        if first:
            header["model"] = first  # the starting model; summary.json has the latest
        elif isinstance(summary.get("current_model_id"), str):
            header["model"] = summary["current_model_id"]
        self.model = header.get("model")
        t = base.source_time(summary.get("created_at"), {}, "created_at")
        if t:
            header["started_at"] = t["t"]
        if isinstance(context.get("is_non_interactive"), bool):
            header["mode"] = "headless" if context["is_non_interactive"] else "interactive"
        raw = {k: v for k, v in (("summary", summary), ("prompt_context", context), ("usage", usage)) if v}
        if raw:
            header["raw"] = raw
        return header

    def _pos(self, offset, rec):
        if rec.get("type") == "reasoning" and rec.get("id") in self.reasoning_ids:
            return "@" + escape_key("reasoning/" + rec["id"])
        return str(offset)

    def _event(self, offset, rec, typ, actor, data, pointer="", mapped=(), **fields):
        raw = {k: v for k, v in rec.items() if k not in mapped}
        event = {"pos": self._pos(offset, rec) + pointer, "type": typ, "actor": actor, "data": data, **fields}
        if raw:
            event["raw"] = raw
        return event

    def map_record(self, offset, rec):
        typ = rec.get("type")
        content = rec.get("content")
        text = content if isinstance(content, str) else None
        if isinstance(content, list):
            texts = [b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
            text = texts[0] if len(texts) == 1 and len(content) == 1 else None
        mapped = ("content",) if text is not None else ()
        if typ == "system":
            return [self._event(offset, rec, "context", "harness",
                                {"role": "system", **({} if text is None else {"text": text})}, mapped=mapped)]
        if typ == "user":
            if isinstance(rec.get("synthetic_reason"), str):
                data = {"name": rec["synthetic_reason"], "role": "user", **({} if text is None else {"text": text})}
                return [self._event(offset, rec, "context", "harness", data, mapped=mapped + ("synthetic_reason",))]
            if "prompt_index" not in rec:
                # Every measured prompt has prompt_index; user lines without one are the
                # harness's own blocks (user info, rules) at the start of a session.
                data = {"role": "user", **({} if text is None else {"text": text})}
                return [self._event(offset, rec, "context", "harness", data, mapped=mapped,
                                    how={"type": "inferred:user-line-without-prompt-index"})]
            headless = self._one("f7").get("is_non_interactive")
            actor = "caller" if headless is True else "human"
            fields = {"how": {"actor": "inferred:session-interactivity"}}
            return [self._event(offset, rec, "prompt", actor, {} if text is None else {"text": text},
                                mapped=mapped, **fields)]
        if typ == "assistant":
            events = []
            calls = rec.get("tool_calls")
            plain = isinstance(calls, list) and all(isinstance(c, dict) and set(c) <= {"id", "name", "arguments"}
                                                    for c in calls)
            mapped_a = (("content",) if text else ()) + (("tool_calls",) if plain else ())
            if text:
                events.append(self._event(offset, rec, "assistant_text", "agent", {"text": text}, "#/content",
                                          mapped=mapped_a))
            for i, call in enumerate(rec.get("tool_calls") or []):
                if not isinstance(call, dict):
                    continue
                name = call.get("name")
                data = {"kind": KINDS.get(name, "mcp" if isinstance(name, str) and name.startswith("mcp") else "other")}
                if isinstance(name, str):
                    data["tool"] = name
                if isinstance(call.get("id"), str):
                    data["call_id"] = call["id"]
                if "arguments" in call:
                    data["args"] = call["arguments"]  # a JSON-encoded string, kept as recorded
                events.append(self._event(offset, rec, "tool_call", "agent", data, f"#/tool_calls/{i}",
                                          mapped=mapped_a))
            if events and "raw" in events[0]:
                for e in events[1:]:
                    e.pop("raw", None)  # the record's other fields, once
            return events
        if typ == "reasoning":
            summary = [b.get("text") for b in rec.get("summary") or [] if isinstance(b, dict)]
            data = {"redacted": True}
            mapped_r = ()
            if len(summary) == 1 and isinstance(summary[0], str):
                data["text"] = summary[0]
                mapped_r = ("summary",)
            return [self._event(offset, rec, "reasoning", "agent", data, mapped=mapped_r)]
        if typ == "tool_result":
            data = {}
            if isinstance(rec.get("tool_call_id"), str):
                data["call_id"] = rec["tool_call_id"]
            if text is not None:
                data["text"] = text
            event = self._event(offset, rec, "tool_result", "tool", data, mapped=mapped + ("tool_call_id",))
            if "call_id" in data:
                event["of_call"] = data["call_id"]
            return [event]
        return []

    def map_aux(self, key, offset, rec):
        """events.jsonl, system_prompt.txt and tool_definitions.json."""
        if key == "f4":
            data = {"name": "system_prompt", "role": "system"}
            if isinstance(rec.get("text"), str):
                data["text"] = rec["text"]
            return [{"pos": str(offset), "type": "context", "actor": "harness", "data": data}]
        if key == "f5":
            return [{"pos": str(offset), "type": "context", "actor": "harness", "data": {"name": "tool_definitions"},
                     "raw": rec}]
        typ = rec.get("type")
        drop = {"ts"}
        if typ == "permission_resolved" and rec.get("decision") in DECISIONS:
            out, data = "permission", {"decision": DECISIONS[rec["decision"]]}
            drop.add("decision")
        elif typ == "permission_requested":
            out, data = "permission", {"decision": "asked"}
        elif typ == "tool_completed" and rec.get("outcome") == "error":
            out, data = "error", {"code": "error"}
            drop.add("outcome")
        elif typ == "turn_started" and isinstance(rec.get("model_id"), str) and rec["model_id"] != self.model:
            out, data = "setting", {"model": rec["model_id"]}
            drop.add("model_id")
            self.model = rec["model_id"]
        elif typ == "turn_ended" and rec.get("outcome") == "cancelled":
            out, data = "interrupt", {}
            if isinstance(rec.get("cancellation_category"), str):
                data["reason"] = rec["cancellation_category"]
                drop.add("cancellation_category")
        else:
            out, data = "record", ({"name": typ} if isinstance(typ, str) else {})
        raw = {k: v for k, v in rec.items() if k not in drop}
        timed = base.source_time(rec.get("ts"), raw, "ts")
        actor = "human" if out == "interrupt" and (rec.get("cancellation_context") or {}).get("trigger") == "ctrl_c" else "harness"
        how = {"actor": "inferred:ctrl-c-trigger"} if actor == "human" else {}
        spec = {"pos": str(offset), "type": out, "actor": actor, "data": data, "raw": raw, **timed}
        if how:
            spec["how"] = how
        if isinstance(rec.get("tool_call_id"), str):
            spec["of_call"] = rec["tool_call_id"]
        return [spec]


def prepare(records):
    return _Session(records)


def map_record(offset, rec):
    return _Session([(offset, rec)]).map_record(offset, rec)
