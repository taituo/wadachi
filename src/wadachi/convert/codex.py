"""Codex rollouts. Mapping facts and unmeasured cases are in adapters/codex.md."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from wadachi import dumps, session_id
from wadachi.ids import escape_key
from . import base

HARNESS = "codex"
SOURCE_FORMAT = "codex-rollout-jsonl"
CONVERTER = {"name": "wadachi-codex", "version": "0.1.2"}
# The outer exec tool runs JavaScript, not a shell. Inner commands have their
# own CommandExecution records. Do not classify JavaScript by its contents.
KINDS = {"exec": "other", "wait": "other", "sleep": "other", "request_user_input_async": "other",
         "search_service.web_run": "mcp", "github.list_repositories": "mcp", "github.search_repositories": "mcp"}
ITEM_KINDS = {"CommandExecution": "shell", "FileChange": "edit", "ImageView": "read",
              "McpToolCall": "mcp"}
USAGE = {"input_tokens": "input_tokens", "output_tokens": "output_tokens",
         "cached_input_tokens": "cache_read_tokens", "cache_write_input_tokens": "cache_write_tokens"}


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def native_id(records: base.Records) -> str | None:
    for _, rec in records:
        if rec.get("type") == "session_meta":
            value = rec.get("payload", {}).get("id")
            if isinstance(value, str) and value:
                return value
    return None


def discover():
    for path in sorted((codex_home() / "sessions").rglob("*.jsonl")):
        # Discovery needs only metadata, not all the conversation text.
        nid = None
        try:
            with path.open("rb") as stream:
                line = stream.readline()
            if line.endswith(b"\n"):
                import json
                nid = native_id([(0, json.loads(line))])
            yield base.DiscoveredSession(nid, path, path.stat().st_size)
        except (OSError, ValueError, TypeError, AttributeError):
            # Keep unreadable inputs visible to dump's per-session failure count.
            yield base.DiscoveredSession(None, path, 0)


def sessions(paths):
    for path in paths or [s.path for s in discover()]:
        yield base.SessionInput([base.Source("f1", path, "record", SOURCE_FORMAT)])


def self_id() -> str | None:
    return os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")


def caller_present() -> bool:
    return bool(os.environ.get("CODEX_TOOL_CALL_ID"))


def _position(offset, rec):
    p = rec.get("payload", {})
    if rec.get("type") == "response_item" and isinstance(p.get("id"), str) and p["id"]:
        return "@" + escape_key("response/" + p.get("type", "") + "/" + p["id"])
    if rec.get("type") == "event_msg" and p.get("type") == "item_completed":
        item = p.get("item", {})
        if isinstance(item.get("id"), str) and item["id"]:
            return "@" + escape_key("item/" + item.get("type", "") + "/" + item["id"])
    return str(offset)


def _integer(data, name, value):
    if isinstance(value, int) and not isinstance(value, bool):
        data[name] = value


def _text(data, value):
    if isinstance(value, str):
        data["text"] = value


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
        self.meta = next((r.get("payload", {}) for _, r in records if r.get("type") == "session_meta"), {})
        source = self.meta.get("source")
        driven = source == "exec" or isinstance(source, dict) and "subagent" in source
        self.actor = "caller" if driven else "human"
        positions = Counter(_position(o, r) for o, r in records)
        self.positions = {o: _position(o, r) if positions[_position(o, r)] == 1 else str(o) for o, r in records}
        self.response_ids = {(r.get("payload", {}).get("type"), r.get("payload", {}).get("id"))
                             for _, r in records if r.get("type") == "response_item"}
        self.user_responses = Counter()
        for _, r in records:
            p = r.get("payload", {})
            if r.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
                meta = p.get("internal_chat_message_metadata_passthrough", {})
                kinds = meta.get("content_item_kinds")
                if kinds is None or any(k in ("user.text", "user.image") for k in kinds):
                    self.user_responses[meta.get("turn_id")] += 1
        self.user_items_seen = Counter()
        self.calls = {}
        self.prompted = set()
        self.active_turn = None
        self.serial = 0
        self.skipped = Counter()

    def _event(self, offset, rec, typ, actor, data=None, suffix="", payload=None, **fields):
        raw = {k: v for k, v in rec.items() if k not in ("timestamp", "payload", "type")}
        raw["payload"] = rec.get("payload") if payload is None else payload
        event = {"pos": self.positions.get(offset, _position(offset, rec)) + suffix,
                 "type": typ, "actor": actor, "data": data or {}, "raw": raw,
                 **base.source_time(rec.get("timestamp"), raw, "timestamp"), **fields}
        return event

    def session_header(self):
        m = self.meta
        header = {"harness": {"name": HARNESS}}
        if isinstance(m.get("cli_version"), str):
            header["harness"]["version"] = m["cli_version"]
        for name in ("cwd", "model"):
            if isinstance(m.get(name), str):
                header[name] = m[name]
        git = m.get("git", {})
        if isinstance(git, dict) and isinstance(git.get("commit_hash"), str):
            header["repo_commit"] = git["commit_hash"]
        raw = {"session_meta": m}
        time = base.source_time(m.get("timestamp"), raw, "timestamp")
        if time:
            header["started_at"] = time["t"]
        source = m.get("source")
        if source == "exec":
            header["mode"] = "headless"
        elif source == "cli":
            header["mode"] = "interactive"
        # These parent shapes are supported but were not present in the measured
        # corpus. Never infer a parent from paths, adjacent files or turn ids.
        if isinstance(m.get("forked_from_id"), str):
            header["parent"] = {"session": session_id(HARNESS, native_id=m["forked_from_id"]), "relation": "fork"}
        sub = source.get("subagent", {}) if isinstance(source, dict) else {}
        spawn = sub.get("thread_spawn", {}) if isinstance(sub, dict) else {}
        if isinstance(spawn, dict) and isinstance(spawn.get("parent_thread_id"), str):
            header["mode"] = "subagent"
            header["parent"] = {"session": session_id(HARNESS, native_id=spawn["parent_thread_id"]), "relation": "subagent"}
        header["raw"] = raw
        # Count records with no mapped event, without putting them on a neighbour.
        probe = _Session(self.records)
        for offset, rec in self.records:
            if not probe.map_record(offset, rec) and rec.get("type") != "session_meta":
                p = rec.get("payload", {})
                label = rec.get("type", "unknown")
                if label in ("event_msg", "response_item"):
                    label += "/" + str(p.get("type", "unknown"))
                probe.skipped[label] += 1
        if probe.skipped:
            header["x"] = {HARNESS: {"skipped_records": dict(probe.skipped)}}
        return header

    def _prompt(self, offset, rec, p, text, turn, goal=False):
        # task_started precedes even the first prompt. Active alone is not steer.
        key = turn if turn is not None else self.active_turn
        if key is None:
            self.serial += 1
            key = ("unmarked", self.serial)
        typ = "steer" if key in self.prompted else "prompt"
        self.prompted.add(key)
        data = {}
        _text(data, text)
        how = {"type": "inferred:shared-turn-user-message"} if typ == "steer" else {}
        if goal:
            how.setdefault("type", "inferred:goal-context-input")
            how["actor"] = "inferred:goal-context-input"
        fields = {"how": how} if how else {}
        return [self._event(offset, rec, typ, "caller" if goal else self.actor, data, **fields)]

    def map_record(self, offset, rec):
        typ, p = rec.get("type"), rec.get("payload", {})
        if not isinstance(p, dict):
            return []
        pt = p.get("type")
        if typ == "session_meta":
            return []
        if typ in ("turn_context", "world_state") or (typ == "event_msg" and pt == "thread_settings_applied") or (typ == "response_item" and pt in ("configuration_update", "additional_tools")):
            settings = p.get("state", {}) if typ == "world_state" else p.get("thread_settings", {}) if pt == "thread_settings_applied" else p
            data = {k: settings[k] for k in ("model", "cwd", "effort") if isinstance(settings.get(k), str)}
            if isinstance(settings.get("reasoning_effort"), str):
                data["effort"] = settings["reasoning_effort"]
            if pt == "configuration_update" and isinstance(p.get("reasoning", {}).get("effort"), str):
                data["effort"] = p["reasoning"]["effort"]
            return [self._event(offset, rec, "setting", "harness", data)]
        if typ == "compacted" or (typ == "event_msg" and pt == "context_compacted"):
            data = {}
            _text(data, p.get("message"))
            return [self._event(offset, rec, "compaction", "harness", data)]
        if typ == "token_usage_record" or (typ == "event_msg" and pt == "token_count"):
            usage = p.get("usage", {}) if typ == "token_usage_record" else (p.get("info") or {}).get("last_token_usage", {})
            data = {}
            if isinstance(usage, dict):
                for name, target in USAGE.items():
                    _integer(data, target, usage.get(name))
            return [self._event(offset, rec, "usage", "harness", data)]
        if typ == "event_msg":
            if pt == "task_started":
                self.active_turn = p.get("turn_id")
                return []
            if pt in ("task_complete", "turn_aborted"):
                self.active_turn = None
                if pt == "turn_aborted":
                    data = {"reason": p["reason"]} if isinstance(p.get("reason"), str) else {}
                    return [self._event(offset, rec, "interrupt", "harness", data)]
                return []  # a completed turn does not end the session
            if pt == "user_message":
                return self._prompt(offset, rec, p, p.get("message"), p.get("turn_id"))
            if pt in ("agent_message", "agent_reasoning"):
                data = {}
                _text(data, p.get("message", p.get("text")))
                return [self._event(offset, rec, "reasoning" if pt == "agent_reasoning" else "assistant_text", "agent", data)]
            if pt == "item_completed":
                return self._item(offset, rec, p)
            return []
        if typ != "response_item":
            return []
        if pt == "message":
            role = p.get("role")
            content = p.get("content", [])
            if role == "user":
                kinds = p.get("internal_chat_message_metadata_passthrough", {}).get("content_item_kinds")
                user_input = isinstance(kinds, list) and any(k in ("user.text", "user.image") for k in kinds)
                goal = isinstance(kinds, list) and "goal.internal_context" in kinds and not user_input
                if isinstance(kinds, list) and not user_input and not goal:
                    return []
                text_kind = "goal.internal_context" if goal else "user.text"
                texts = [b["text"] for i, b in enumerate(content)
                         if isinstance(b, dict) and isinstance(b.get("text"), str)
                         and (not isinstance(kinds, list) or i < len(kinds) and kinds[i] == text_kind)]
                turn = p.get("internal_chat_message_metadata_passthrough", {}).get("turn_id")
                return self._prompt(offset, rec, p, texts[0] if len(texts) == 1 else None, turn, goal=goal)
            if role != "assistant":
                return []
            return [self._event(offset, rec, "assistant_text", "agent", {"text": b["text"]}, f"#/payload/content/{i}")
                    for i, b in enumerate(content) if isinstance(b, dict) and isinstance(b.get("text"), str)]
        if pt == "reasoning":
            result = []
            for field in ("summary", "content"):
                for i, block in enumerate(p.get(field) or []):
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        data = {"text": block["text"]}
                        if field == "summary":
                            data["redacted"] = True
                        result.append(self._event(offset, rec, "reasoning", "agent", data, f"#/payload/{field}/{i}"))
            if not result:
                data = {"redacted": True} if p.get("encrypted_content") is not None else {}
                result.append(self._event(offset, rec, "reasoning", "agent", data))
            return result
        if pt in ("function_call", "custom_tool_call"):
            data = {"kind": _kind(p.get("name"))}
            for name, target in (("name", "tool"), ("call_id", "call_id"), ("arguments", "args") if pt == "function_call" else ("input", "args")):
                if name in p:
                    data[target] = p[name]
            event = self._event(offset, rec, "tool_call", "agent", data)
            if isinstance(p.get("call_id"), str):
                self.calls[p["call_id"]] = event["pos"]
            return [event]
        if pt in ("function_call_output", "custom_tool_call_output"):
            data = {"call_id": p["call_id"]} if "call_id" in p else {}
            out = p.get("output")
            _text(data, out)
            if isinstance(out, list):
                # A single text block is exact. Multiple blocks stay in raw;
                # inventing separators would alter the recorded output.
                text = [b["text"] for b in out if isinstance(b, dict) and isinstance(b.get("text"), str)]
                if len(text) == 1:
                    data["text"] = text[0]
            event = self._event(offset, rec, "tool_result", "tool", data)
            if p.get("call_id") in self.calls:
                event["of_src"] = "f1:" + self.calls[p["call_id"]]
            return [event]
        return []

    def _item(self, offset, rec, p):
        item = p.get("item", {})
        typ = item.get("type")
        if typ == "UserMessage":
            turn = p.get("turn_id")
            self.user_items_seen[turn] += 1
            if self.user_items_seen[turn] <= self.user_responses[turn]:
                return []
            text = [b["text"] for b in item.get("content", []) if isinstance(b, dict) and isinstance(b.get("text"), str)]
            return self._prompt(offset, rec, p, text[0] if len(text) == 1 else None, turn)
        if typ in ("AgentMessage", "Reasoning"):
            response_type = "message" if typ == "AgentMessage" else "reasoning"
            if (response_type, item.get("id")) in self.response_ids:
                return []
            if typ == "Reasoning":
                result = []
                for field in ("raw_content", "summary_text"):
                    for i, text in enumerate(item.get(field) or []):
                        if isinstance(text, str):
                            data = {"text": text}
                            if field == "summary_text":
                                data["redacted"] = True
                            result.append(self._event(offset, rec, "reasoning", "agent", data, f"#/payload/item/{field}/{i}"))
                return result or [self._event(offset, rec, "reasoning", "agent")]
            return [self._event(offset, rec, "assistant_text", "agent", {"text": b["text"]}, f"#/payload/item/content/{i}")
                    for i, b in enumerate(item.get("content", [])) if isinstance(b, dict) and isinstance(b.get("text"), str)]
        if typ == "ContextCompaction":
            return [self._event(offset, rec, "compaction", "harness")]
        if typ not in (*ITEM_KINDS, "Extension"):
            return []
        data = {}
        if typ in ITEM_KINDS:
            data["kind"] = ITEM_KINDS[typ]
        elif item.get("kind") == "web.search":
            data["kind"] = "fetch"
        elif item.get("kind") == "clock.sleep":
            data["kind"] = "other"
        if isinstance(item.get("tool"), str):
            data["tool"] = item["tool"]
        if "status" in item:
            value = item["status"]
            data["status_as_recorded"] = value if isinstance(value, str) else dumps(value)
        _integer(data, "exit_code", item.get("exit_code"))
        _text(data, item.get("aggregated_output"))
        if typ == "ImageView" and isinstance(item.get("path"), str):
            data["paths"] = [item["path"]]
        if typ == "FileChange" and isinstance(item.get("changes"), dict):
            data["paths"] = list(item["changes"])
        event = self._event(offset, rec, "tool_result", "tool", data)
        if item.get("id") in self.calls:
            event["of_src"] = "f1:" + self.calls[item["id"]]
            event["how"] = {"of": "inferred:item-id-matches-call"}
        return [event]


def prepare(records):
    return _Session(records)


def map_record(offset, rec):
    """Stateless entry point; base.prepare supplies context for whole sessions."""
    return _Session([(offset, rec)]).map_record(offset, rec)
