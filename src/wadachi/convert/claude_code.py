"""Claude Code transcripts. Mapping facts and unmeasured cases are in adapters/claude-code.md."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

from wadachi import dumps, session_id
from wadachi.ids import escape_key
from . import base

HARNESS = "claude-code"
SOURCE_FORMAT = "claude-code-jsonl"
META_FORMAT = "claude-code-subagent-meta-json"
CONVERTER = {"name": "wadachi-claude-code", "version": "0.1.1"}
SELF_FROM_HERDR = True
META_KEY = "f3"  # f2 stays reserved for a hook log

KINDS = {"Read": "read", "Write": "write", "Edit": "edit", "MultiEdit": "edit", "NotebookEdit": "edit",
         "Bash": "shell", "Glob": "search", "Grep": "search", "WebFetch": "fetch", "WebSearch": "fetch",
         "Agent": "subagent", "Task": "subagent"}
# Arguments that name paths, per tool, in the order they are listed.
PATH_ARGS = {"Read": ("file_path",), "Write": ("file_path",), "Edit": ("file_path",), "MultiEdit": ("file_path",),
             "NotebookEdit": ("notebook_path",), "Grep": ("path",), "Glob": ("path",)}
# Who wrote a tool result's text (SPEC.md 4.2). WebFetch answers through a
# second model; the page itself never enters the transcript.
TEXT_ORIGIN = {"WebFetch": "model"}
USAGE = {"input_tokens": "input_tokens", "output_tokens": "output_tokens",
         "cache_read_input_tokens": "cache_read_tokens", "cache_creation_input_tokens": "cache_write_tokens"}
# Text Claude Code writes into user records itself. Exact prefixes, not guesses.
HARNESS_TEXT = ("<local-command-stdout>", "<local-command-stderr>", "<local-command-caveat>")
HANDBACK = ("send", True)  # toolUseResult.handback values that mean hand-back mode
INTERRUPTS = ("[Request interrupted by user]", "[Request interrupted by user for tool use]")


def config_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser()


def _peek(path: Path, limit: int = 200) -> dict:
    """Recorded session id, agent id and cwd from the first lines. Never the filename."""
    found = {}
    with path.open("rb") as stream:
        for _ in range(limit):
            line = stream.readline()
            if not line.endswith(b"\n"):
                break
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            for name in ("sessionId", "agentId", "cwd"):
                if name not in found and isinstance(rec.get(name), str) and rec[name]:
                    found[name] = rec[name]
            if "sessionId" in found and "cwd" in found and ("agentId" in found or not _is_child(path)):
                break
    return found


def _is_child(path: Path) -> bool:
    return path.parent.name == "subagents"


def _native(found: dict) -> str | None:
    sid = found.get("sessionId")
    if not sid:
        return None
    return sid + "/" + found["agentId"] if found.get("agentId") else sid


def discover():
    root = config_home() / "projects"
    paths = sorted([*root.glob("*/*.jsonl"), *root.glob("*/*/subagents/*.jsonl")])
    for path in paths:
        try:
            found = _peek(path)
            stat = path.stat()
            yield base.DiscoveredSession(_native(found), path, stat.st_size, found.get("cwd"), stat.st_mtime_ns)
        except (OSError, ValueError, TypeError):
            yield base.DiscoveredSession(None, path, 0)


def _meta_reader(path: Path) -> base.Snapshot:
    data = path.read_bytes()
    value = json.loads(data)
    return base.Snapshot(data, [(0, value)] if isinstance(value, dict) else [])


def sessions(paths):
    for path in paths or [s.path for s in discover()]:
        sources = [base.Source("f1", path, "record", SOURCE_FORMAT)]
        header = {}
        meta = path.with_name(path.stem + ".meta.json")
        if _is_child(path) and meta.is_file():
            # Read once; the header and the hash come from the same bytes.
            snapshot = _meta_reader(meta)
            sources.append(base.Source(META_KEY, meta, "aux", META_FORMAT,
                                       reader=lambda unused, snapshot=snapshot: snapshot, events=False))
            record = snapshot.records[0][1] if snapshot.records else {}
            if isinstance(record.get("agentType"), str):
                header["agent"] = {"name": record["agentType"]}
            raw = {k: v for k, v in record.items() if k != "agentType"}
            if raw:
                header["raw"] = {"subagent_meta": raw}
        yield base.SessionInput(sources, header=header)


def selected_sessions(discovered):
    yield from sessions([s.path for s in discovered])


def self_id() -> str | None:
    return os.environ.get("CLAUDE_CODE_SESSION_ID")


def caller_present() -> bool:
    return os.environ.get("CLAUDECODE") == "1"


def select_self(discovered, cwd):
    matches = [s for s in discovered if s.cwd == cwd and not _is_child(s.path)]
    return [max(matches, key=lambda s: (s.updated or 0, str(s.path)))] if matches else []


def native_id(records: base.Records) -> str | None:
    found = {}
    for _, rec in records:
        for name in ("sessionId", "agentId"):
            if name not in found and isinstance(rec.get(name), str) and rec[name]:
                found[name] = rec[name]
    return _native(found)


def _text_of(content):
    """Exact text: a string, or the only text block. Several blocks stay in raw."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
        if len(texts) == 1:
            return texts[0]
    return None


def _integer(data, name, value):
    if isinstance(value, int) and not isinstance(value, bool):
        data[name] = value


def _kind(name):
    if isinstance(name, str) and name.startswith("mcp__"):
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
        uuids = Counter(r.get("uuid") for _, r in records if isinstance(r.get("uuid"), str))
        self.positions = {o: "@" + escape_key(r["uuid"]) if isinstance(r.get("uuid"), str) and uuids[r["uuid"]] == 1
                          else str(o) for o, r in records}
        # Claude Code writes one line per content block; lines of one API
        # message share message.id and repeat its usage. Usage is read once,
        # from the message's last line, where the count is final.
        last = {}
        for o, r in records:
            m = r.get("message")
            if r.get("type") == "assistant" and isinstance(m, dict) and isinstance(m.get("id"), str):
                last[m["id"]] = o
        self.usage_lines = set(last.values())
        self.tools, self.agent_calls = {}, {}
        for _, r in records:
            m = r.get("message")
            content = m.get("content") if isinstance(m, dict) else None
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and isinstance(b.get("id"), str):
                    self.tools[b["id"]] = b.get("name")
                if b.get("type") == "tool_result" and isinstance(r.get("toolUseResult"), dict):
                    agent = r["toolUseResult"].get("agentId")
                    if isinstance(agent, str) and isinstance(b.get("tool_use_id"), str):
                        self.agent_calls[agent] = b["tool_use_id"]
        first = {}
        for _, r in records:
            for name in ("sessionId", "agentId", "version", "cwd", "entrypoint", "gitBranch"):
                if name not in first and isinstance(r.get(name), str):
                    first[name] = r[name]
        self.first = first
        self.child = "agentId" in first
        self.skipped = Counter()

    def _event(self, offset, rec, typ, actor, data=None, pointer="", raw_extra=None, **fields):
        raw = {k: v for k, v in rec.items() if k not in ("type", "timestamp", "uuid", "message")}
        if isinstance(rec.get("message"), dict):
            rest = {k: v for k, v in rec["message"].items() if k != "content"}
            if rest:
                raw["message"] = rest
        if raw_extra:
            raw.update(raw_extra)
        event = {"pos": self.positions.get(offset, str(offset)) + pointer, "type": typ, "actor": actor,
                 "data": data or {}, **base.source_time(rec.get("timestamp"), raw, "timestamp"), **fields}
        if raw:
            event["raw"] = raw
        return event

    def session_header(self):
        f = self.first
        header = {"harness": {"name": HARNESS}}
        if "version" in f:
            header["harness"]["version"] = f["version"]
        if "cwd" in f:
            header["cwd"] = f["cwd"]
        model = None
        for _, r in self.records:
            a = r.get("attachment")
            if r.get("type") == "attachment" and isinstance(a, dict) and a.get("type") == "model":
                model = (a.get("identity") or {}).get("modelId")
                break
        if not isinstance(model, str):
            model = next((r["message"]["model"] for _, r in self.records if r.get("type") == "assistant"
                          and isinstance(r.get("message"), dict) and isinstance(r["message"].get("model"), str)), None)
        if isinstance(model, str):
            header["model"] = model
        if self.child:
            header["mode"] = "subagent"
            if "sessionId" in f:
                header["parent"] = {"session": session_id(HARNESS, native_id=f["sessionId"]), "relation": "subagent"}
                header["invoked_by"] = {"kind": "agent", "ref": f["sessionId"]}
        elif f.get("entrypoint") == "cli":
            header["mode"] = "interactive"
        elif f.get("entrypoint", "").startswith("sdk"):
            header["mode"] = "headless"
        raw = {k: f[k] for k in ("entrypoint", "gitBranch") if k in f}
        if raw:
            header["raw"] = raw
        probe = _Session(self.records)
        for offset, rec in self.records:
            if not probe.map_record(offset, rec):
                label = str(rec.get("type", "unknown"))
                if label == "attachment" and isinstance(rec.get("attachment"), dict):
                    label += "/" + str(rec["attachment"].get("type"))
                elif label == "system":
                    label += "/" + str(rec.get("subtype"))
                probe.skipped[label] += 1
        if probe.skipped:
            header["x"] = {HARNESS: {"skipped_records": dict(sorted(probe.skipped.items()))}}
        return header

    def _input(self, offset, rec, text, pointer="", typ="prompt"):
        """A user turn's text. Actor from the recorded origin, else by rule."""
        data = {} if text is None else {"text": text}
        how = {}
        origin = rec.get("origin")
        if isinstance(origin, dict) and origin.get("kind") == "human":
            actor = "human"
        elif isinstance(origin, dict) and isinstance(origin.get("kind"), str):
            actor = "caller"
        elif self.child or rec.get("isSidechain") is True:
            actor, how["actor"] = "caller", "inferred:subagent-task"
        elif rec.get("entrypoint") == "cli":
            actor, how["actor"] = "human", "inferred:interactive-entrypoint"
        else:
            actor, how["actor"] = "caller", "inferred:non-interactive-entrypoint"
        if typ == "steer":
            how["type"] = "inferred:text-beside-tool-result"
        fields = {"how": how} if how else {}
        return [self._event(offset, rec, typ, actor, data, pointer, **fields)]

    def _user(self, offset, rec, m):
        if rec.get("isMeta") is True:
            return []
        content = m.get("content")
        if rec.get("isCompactSummary") is True:
            data = {}
            text = _text_of(content)
            if text is not None:
                data["text"] = text
            return [self._event(offset, rec, "compaction", "harness", data)]
        if isinstance(content, str):
            if content.startswith(HARNESS_TEXT):
                return []
            if content in INTERRUPTS:
                return [self._event(offset, rec, "interrupt", "human", {"reason": content},
                                    how={"type": "inferred:interrupt-marker"})]
            return self._input(offset, rec, content)
        if not isinstance(content, list):
            return []
        events = []
        decision = rec.get("permissionDecision")
        results = [(i, b) for i, b in enumerate(content) if isinstance(b, dict) and b.get("type") == "tool_result"]
        if isinstance(decision, dict) and decision.get("decision") in ("accept", "reject", "deny"):
            data = {"decision": "allowed" if decision["decision"] == "accept" else "denied"}
            if isinstance(decision.get("reasonType"), str):
                data["rule"] = decision["reasonType"]
            actor = "human" if decision.get("source") == "user" else "harness"
            event = self._event(offset, rec, "permission", actor, data, "#/permissionDecision")
            if len(results) == 1 and isinstance(results[0][1].get("tool_use_id"), str):
                event["of_call"] = results[0][1]["tool_use_id"]
            events.append(event)
        for i, b in results:
            data = {}
            call = b.get("tool_use_id")
            if isinstance(call, str):
                data["call_id"] = call
            text = _text_of(b.get("content"))
            if text is not None:
                data["text"] = text
            if "is_error" in b:
                v = b["is_error"]
                data["status_as_recorded"] = v if isinstance(v, str) else dumps(v)
            tool = self.tools.get(call)
            if text is not None:
                result = rec.get("toolUseResult") if isinstance(rec.get("toolUseResult"), dict) else {}
                if tool in ("Agent", "Task"):
                    # In hand-back mode the result is a harness note; the report arrives
                    # separately. "send" is the measured value; others are left unknown.
                    if result.get("handback") in HANDBACK:
                        data["text_origin"] = "tool"
                    elif "handback" not in result:
                        data["text_origin"] = "agent"
                elif tool in TEXT_ORIGIN:
                    data["text_origin"] = TEXT_ORIGIN[tool]
            event = self._event(offset, rec, "tool_result", "tool", data, f"#/message/content/{i}")
            if isinstance(call, str):
                event["of_call"] = call
            events.append(event)
        texts = [(i, b) for i, b in enumerate(content) if isinstance(b, dict) and b.get("type") == "text"
                 and isinstance(b.get("text"), str)]
        others = [b for b in content if isinstance(b, dict) and b.get("type") not in ("text", "tool_result")]
        if not results:
            if len(texts) == 1 and texts[0][1]["text"] in INTERRUPTS:
                return events + [self._event(offset, rec, "interrupt", "human", {"reason": texts[0][1]["text"]},
                                             how={"type": "inferred:interrupt-marker"})]
            if texts or others:
                # One input; several text blocks or images keep their text in raw.
                text = texts[0][1]["text"] if len(texts) == 1 else None
                return events + self._input(offset, rec, text)
            return events
        for i, b in texts:
            if b["text"] in INTERRUPTS:
                events.append(self._event(offset, rec, "interrupt", "human", {"reason": b["text"]},
                                          f"#/message/content/{i}", how={"type": "inferred:interrupt-marker"}))
            else:
                events += self._input(offset, rec, b["text"], f"#/message/content/{i}", typ="steer")
        return events

    def _assistant(self, offset, rec, m):
        content = m.get("content") if isinstance(m.get("content"), list) else []
        if rec.get("isApiErrorMessage") is True:
            data = {}
            if isinstance(rec.get("error"), str):
                data["code"] = rec["error"]
            text = _text_of(content)
            if text is not None:
                data["text"] = text
            events = [self._event(offset, rec, "error", "harness", data)]
        else:
            events = []
            for i, b in enumerate(content):
                if not isinstance(b, dict):
                    continue
                ptr, bt = f"#/message/content/{i}", b.get("type")
                if bt == "text" and isinstance(b.get("text"), str):
                    events.append(self._event(offset, rec, "assistant_text", "agent", {"text": b["text"]}, ptr))
                elif bt == "thinking":
                    data = {}
                    if isinstance(b.get("thinking"), str) and b["thinking"]:
                        data["text"] = b["thinking"]
                    else:
                        data["redacted"] = True
                    extra = {"block": {k: v for k, v in b.items() if k not in ("type", "thinking")}}
                    events.append(self._event(offset, rec, "reasoning", "agent", data, ptr, raw_extra=extra))
                elif bt == "redacted_thinking":
                    events.append(self._event(offset, rec, "reasoning", "agent", {"redacted": True}, ptr,
                                              raw_extra={"block": b}))
                elif bt == "tool_use":
                    name = b.get("name")
                    data = {"kind": _kind(name)}
                    if isinstance(name, str):
                        data["tool"] = name
                    if isinstance(b.get("id"), str):
                        data["call_id"] = b["id"]
                    if "input" in b:
                        data["args"] = b["input"]
                    args = b.get("input") if isinstance(b.get("input"), dict) else {}
                    paths = [args[k] for k in PATH_ARGS.get(name, ()) if isinstance(args.get(k), str)]
                    if paths:
                        data["paths"] = paths
                    extra = {k: v for k, v in b.items() if k not in ("type", "id", "name", "input")}
                    events.append(self._event(offset, rec, "tool_call", "agent", data, ptr,
                                              raw_extra={"block": extra} if extra else None))
        usage = m.get("usage")
        if offset in self.usage_lines and isinstance(usage, dict):
            data = {}
            for name, target in USAGE.items():
                _integer(data, target, usage.get(name))
            events.append(self._event(offset, rec, "usage", "harness", data, "#/message/usage"))
        return events

    def _attachment(self, offset, rec, a):
        typ = a.get("type")
        if typ == "model":
            model = (a.get("identity") or {}).get("modelId")
            return [self._event(offset, rec, "setting", "harness", {"model": model} if isinstance(model, str) else {})]
        if typ != "queued_command":
            return []
        origin = a.get("origin") if isinstance(a.get("origin"), dict) else {}
        text = a.get("prompt") if isinstance(a.get("prompt"), str) else None
        if origin.get("kind") == "peer" and origin.get("handback") is True:
            data = {"text_origin": "agent"}
            if text is not None:
                data["text"] = text
            sender = origin.get("from")
            parent = self.first.get("sessionId")
            if isinstance(sender, str) and parent:
                data["session"] = session_id(HARNESS, native_id=parent + "/" + sender)
            event = self._event(offset, rec, "subagent_end", "agent", data)
            if sender in self.agent_calls:
                event["of_call"] = self.agent_calls[sender]
                event["how"] = {"of": "inferred:agent-id-matches-tool-result"}
            return [event]
        data = {} if text is None else {"text": text}
        if origin.get("kind") == "human":
            return [self._event(offset, rec, "steer", "human", data)]
        if isinstance(origin.get("kind"), str):
            return [self._event(offset, rec, "steer", "caller", data)]
        return []

    def map_record(self, offset, rec):
        typ = rec.get("type")
        m = rec.get("message")
        if typ == "user" and isinstance(m, dict):
            return self._user(offset, rec, m)
        if typ == "assistant" and isinstance(m, dict):
            return self._assistant(offset, rec, m)
        if typ == "attachment" and isinstance(rec.get("attachment"), dict):
            return self._attachment(offset, rec, rec["attachment"])
        if typ == "system" and rec.get("subtype") == "compact_boundary":
            data = {}
            meta = rec.get("compactMetadata")
            if isinstance(meta, dict):
                _integer(data, "before_tokens", meta.get("preTokens"))
            return [self._event(offset, rec, "compaction", "harness", data)]
        return []


def prepare(records):
    return _Session(records)


def map_record(offset, rec):
    """Stateless entry point; base.prepare supplies context for whole sessions."""
    return _Session([(offset, rec)]).map_record(offset, rec)
