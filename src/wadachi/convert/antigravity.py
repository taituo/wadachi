"""Antigravity CLI (agy) transcripts. Mapping facts and gaps are in adapters/antigravity.md."""

from __future__ import annotations

import os
from pathlib import Path

from wadachi.ids import escape_key
from . import base

HARNESS = "antigravity"
SOURCE_FORMAT = "antigravity-transcript-jsonl"
CONVERTER = {"name": "wadachi-antigravity", "version": "0.2.1", "measured": ["1.5.12", "1.5.13", "1.5.18"]}
SHORT_KEY = "f3"  # the truncated transcript; f2 stays reserved for a hook log

KINDS = {"run_command": "shell", "view_file": "read", "write_to_file": "write", "search_web": "fetch",
         "read_url_content": "fetch", "call_mcp_tool": "mcp", "invoke_subagent": "subagent",
         "manage_task": "other", "manage_subagents": "other", "send_message": "other"}
PATH_ARGS = {"view_file": ("AbsolutePath",), "write_to_file": ("TargetFile",)}
USAGE = {"input_tokens": "input_tokens", "output_tokens": "output_tokens", "cache_read_tokens": "cache_read_tokens"}


def home() -> Path:
    # Antigravity documents no variable for this; WADACHI_ANTIGRAVITY_HOME is wadachi's own.
    return Path(os.environ.get("WADACHI_ANTIGRAVITY_HOME", str(Path.home() / ".gemini/antigravity-cli"))).expanduser()


def _logs(conversation: Path) -> Path:
    return conversation / ".system_generated" / "logs"


def _full(conversation: Path) -> Path:
    return _logs(conversation) / "transcript_full.jsonl"


def discover():
    # Every conversation directory, so one without a transcript is reported, not skipped.
    for conversation in sorted(p for p in (home() / "brain").glob("*") if p.is_dir()):
        path = _full(conversation)
        try:
            stat = path.stat()
            yield base.DiscoveredSession(conversation.name, path, stat.st_size, None, stat.st_mtime_ns)
        except OSError:
            yield base.DiscoveredSession(conversation.name, path, 0)


def _unread(conversation: Path, sources: list[Path]) -> list[Path]:
    """Every other file the harness keeps for the conversation (SPEC.md 3.3)."""
    keep = {p.resolve() for p in sources}
    found = []
    for path in sorted(conversation.rglob("*")):
        if path.is_file() and path.resolve() not in keep:
            found.append(path)
    # The CLI's own per-conversation files outside the conversation directory.
    cli = conversation.parent.parent
    for path in (cli / "conversations" / f"{conversation.name}.db", cli / "annotations" / f"{conversation.name}.pbtxt"):
        if path.is_file():
            found.append(path)
    return found


def sessions(paths):
    for path in paths or [s.path for s in discover()]:
        conversation = path.parents[2]
        # A conversation without a transcript keeps its f1 path: reading it fails, and
        # dump counts the conversation as failed instead of leaving it out silently.
        short = path.with_name("transcript.jsonl")
        sources = [base.Source("f1", path, "record", SOURCE_FORMAT)]
        if short.is_file():
            # Same steps, with tool calls and content cut short: listed, not read for events.
            sources.append(base.Source(SHORT_KEY, short, "aux", SOURCE_FORMAT, truncated=True, events=False))
        yield base.SessionInput(sources, native_id=conversation.name,
                                header={"how": {"native_id": "inferred:conversation-directory"}},
                                unread=_unread(conversation, [s.path for s in sources]))


def selected_sessions(discovered):
    yield from sessions([s.path for s in discovered])


def native_id(records):
    return None  # not recorded in the lines; sessions() supplies the conversation directory's id


MAPPED = {"USER_INPUT": ("content",), "SYSTEM_MESSAGE": ("content",), "EPHEMERAL_MESSAGE": ("content",),
          "PLANNER_RESPONSE": ("content", "thinking", "tool_calls", *USAGE), "GENERIC": ("content", "status", "error")}


def _mapped(typ, name, value, model_mapped=False):
    """Fields an event's data holds exactly, for this step type; everything else stays in raw."""
    if name == "created_at":
        return True
    if name == "model":
        return model_mapped and isinstance(value, str)
    if name not in MAPPED.get(typ, ()):
        return False
    if name in ("content", "thinking", "status", "error"):
        return isinstance(value, str)
    if name in USAGE:
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "tool_calls":
        return isinstance(value, list) and all(isinstance(c, dict) and set(c) <= {"name", "args"} for c in value)
    return False


def _kind(name):
    if isinstance(name, str) and name.startswith("mcp_"):
        return "mcp"
    return KINDS.get(name, "other")


class _Session:
    HARNESS = HARNESS
    SOURCE_FORMAT = SOURCE_FORMAT
    CONVERTER = CONVERTER
    KINDS = KINDS
    native_id = staticmethod(native_id)

    def __init__(self, records):
        self.records = records
        steps = [r.get("step_index") for _, r in records]
        unique = len(set(steps)) == len(steps) and all(isinstance(s, int) and not isinstance(s, bool) for s in steps)
        self.positions = {o: ("@" + escape_key(f"step/{r['step_index']}") if unique else str(o)) for o, r in records}
        # A planner step's tool call is answered by the next step when that is a
        # GENERIC step: measured one to one (adapters/antigravity.md).
        # A model is recorded on some planner steps. The header takes the first; a
        # setting event marks only a step whose model differs from the one before.
        self.model_changes, last = set(), None
        for o, r in records:
            if isinstance(r.get("model"), str):
                if last is not None and r["model"] != last:
                    self.model_changes.add(o)
                last = r["model"]
        self.answers = {}
        for (o, r), (o2, r2) in zip(records, records[1:]):
            if r.get("type") == "PLANNER_RESPONSE" and r.get("tool_calls") and r2.get("type") == "GENERIC":
                self.answers[o2] = self.positions[o] + "#/tool_calls/0"

    def session_header(self):
        header = {"harness": {"name": HARNESS}}
        model = next((r["model"] for _, r in self.records if isinstance(r.get("model"), str)), None)
        if model:
            header["model"] = model
        return header

    def _event(self, offset, rec, typ, actor, data=None, pointer="", raw=True, **fields):
        model_mapped = offset in self.model_changes
        kept = {k: v for k, v in rec.items() if not _mapped(rec.get("type"), k, v, model_mapped)} if raw else {}
        event = {"pos": self.positions[offset] + pointer, "type": typ, "actor": actor, "data": data or {},
                 **base.source_time(rec.get("created_at"), kept, "created_at"), **fields}
        if kept:
            event["raw"] = kept
        return event

    def unmapped(self, offset, rec):
        """A step of a type no row maps: kept whole, content included."""
        data = {"name": rec["type"]} if isinstance(rec.get("type"), str) else {}
        kept = {k: v for k, v in rec.items() if k != "created_at"}
        event = {"pos": self.positions[offset], "type": "record", "actor": "harness", "data": data,
                 **base.source_time(rec.get("created_at"), kept, "created_at")}
        event["raw"] = kept
        return event

    def map_record(self, offset, rec):
        typ = rec.get("type")
        text = rec.get("content") if isinstance(rec.get("content"), str) else None
        if typ == "USER_INPUT":
            actor = "human" if rec.get("source") == "USER_EXPLICIT" else "caller"
            fields = {} if rec.get("source") == "USER_EXPLICIT" else {"how": {"actor": "inferred:not-user-explicit"}}
            return [self._event(offset, rec, "prompt", actor, {} if text is None else {"text": text}, **fields)]
        if typ in ("SYSTEM_MESSAGE", "EPHEMERAL_MESSAGE"):
            data = {"name": typ}
            if text is not None:
                data["text"] = text
            return [self._event(offset, rec, "context", "harness", data)]
        if typ == "PLANNER_RESPONSE":
            events, first = [], True

            def add(*args, **kwargs):
                nonlocal first
                events.append(self._event(offset, rec, *args, raw=first, **kwargs))
                first = False

            if offset in self.model_changes:
                add("setting", "harness", {"model": rec["model"]}, "#/model")
            if isinstance(rec.get("thinking"), str):
                add("reasoning", "agent", {"text": rec["thinking"]}, "#/thinking")
            if text is not None:
                add("assistant_text", "agent", {"text": text}, "#/content")
            for i, call in enumerate(rec.get("tool_calls") or []):
                if not isinstance(call, dict):
                    continue
                name = call.get("name")
                data = {"kind": _kind(name)}
                if isinstance(name, str):
                    data["tool"] = name
                if "args" in call:
                    data["args"] = call["args"]
                args = call.get("args") if isinstance(call.get("args"), dict) else {}
                paths = [args[k] for k in PATH_ARGS.get(name, ()) if isinstance(args.get(k), str)]
                if paths:
                    data["paths"] = paths
                add("tool_call", "agent", data, f"#/tool_calls/{i}")
            usage = {}
            for name, target in USAGE.items():
                v = rec.get(name)
                if isinstance(v, int) and not isinstance(v, bool):
                    usage[target] = v
            if usage:
                add("usage", "harness", usage, "#/" + next(k for k in USAGE if k in usage))
            return events
        if typ == "GENERIC":
            data = {}
            if text is not None:
                data["text"] = text
            if isinstance(rec.get("status"), str):
                data["status_as_recorded"] = rec["status"]
            fields = {}
            if offset in self.answers:
                fields = {"of_src": "f1:" + self.answers[offset], "how": {"of": "inferred:next-step-answers-call"}}
            events = [self._event(offset, rec, "tool_result", "tool", data, **fields)]
            if isinstance(rec.get("error"), str):
                err = self._event(offset, rec, "error", "tool", {"text": rec["error"]}, "#/error", raw=False, **fields)
                events.append(err)
            return events
        return []


def prepare(records):
    return _Session(records)


def map_record(offset, rec):
    return _Session([(offset, rec)]).map_record(offset, rec)
