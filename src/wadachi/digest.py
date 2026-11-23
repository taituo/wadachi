"""Digests: one counted line per turn (SPEC.md section 11, rule wadachi-digest/1)."""

from __future__ import annotations

import unicodedata
from collections import Counter

from .times import instant_ns

RULE = "wadachi-digest/1"

KIND_LETTERS = [
    ("read", "r"),
    ("write", "w"),
    ("edit", "e"),
    ("shell", "s"),
    ("search", "q"),
    ("fetch", "f"),
    ("subagent", "a"),
    ("mcp", "m"),
    ("other", "o"),
]
MAX_PATHS = 5


def _path_token(path: str) -> str:
    out = ["@"]
    for ch in path:
        if ch == "%" or ch.isspace() or unicodedata.category(ch) == "Cc":
            out.append("".join(f"%{b:02X}" for b in ch.encode("utf-8")))
        else:
            out.append(ch)
    return "".join(out)


def _duration(seconds: int) -> str:
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}h{m}m{s}s"
    if m:
        return f"{m}m{s}s"
    return f"{s}s"


def _data(e: dict) -> dict:
    d = e.get("data")
    return d if isinstance(d, dict) else {}


def digest_turn(turn: list[dict], failed_calls: set[str]) -> str:
    """The digest line of one turn, given its events in order; the first is its prompt."""
    prompt = turn[0]
    tokens = [f"t{prompt['turn']}"]

    letter = "h" if prompt.get("actor") == "human" else "p"
    text = _data(prompt).get("text")
    tokens.append(f"{letter}{len(text)}" if isinstance(text, str) else f"{letter}?")

    calls = [e for e in turn if e.get("type") == "tool_call"]
    counts = Counter(_data(c).get("kind", "other") for c in calls)
    failures = Counter(_data(c).get("kind", "other") for c in calls if c.get("id") in failed_calls)
    for kind, ch in KIND_LETTERS:
        if counts[kind]:
            tokens.append(f"{ch}{counts[kind]}" + (f"!{failures[kind]}" if failures[kind] else ""))

    steers = sum(1 for e in turn if e.get("type") == "steer")
    if steers:
        tokens.append(f"^{steers}")
    if any(e.get("type") == "interrupt" for e in turn):
        tokens.append("x")
    if any(e.get("type") == "compaction" for e in turn):
        tokens.append("c")

    if prompt.get("t"):
        start = instant_ns(prompt["t"])
        latest = max(instant_ns(e["t"]) for e in turn if e.get("t"))
        seconds = (latest - start) // 1_000_000_000
        if seconds >= 1:
            tokens.append(_duration(seconds))

    paths: list[str] = []
    for c in calls:
        if _data(c).get("kind") in ("write", "edit"):
            for path in _data(c).get("paths", []):
                if isinstance(path, str) and path and path not in paths:
                    paths.append(path)
    tokens += [_path_token(p) for p in paths[:MAX_PATHS]]
    if len(paths) > MAX_PATHS:
        tokens.append(f"+{len(paths) - MAX_PATHS}")
    return " ".join(tokens)


def failed_calls(events: list[dict]) -> set[str]:
    """Ids of tool calls that failed, by the rule in SPEC.md section 11."""
    failed = set()
    for e in events:
        target = e.get("of")
        if not isinstance(target, str):
            continue
        exit_code = _data(e).get("exit_code")
        if e.get("type") in ("tool_result", "observation") and isinstance(exit_code, int) and exit_code != 0:
            failed.add(target)
        elif e.get("type") == "error":
            failed.add(target)
    calls = {e.get("id") for e in events if e.get("type") == "tool_call"}
    return failed & calls


def digests(events: list[dict]) -> list[tuple[str, str]]:
    """(prompt event id, digest line) for every turn from 1 on."""
    failed = failed_calls(events)
    turns: dict[int, list[dict]] = {}
    for e in events:
        if isinstance(e.get("turn"), int) and e["turn"] >= 1:
            turns.setdefault(e["turn"], []).append(e)
    return [(turn[0]["id"], digest_turn(turn, failed)) for _, turn in sorted(turns.items())]


def annotations(events: list[dict]) -> list[dict]:
    """Digest annotations, ready to write to annotations/digest/<session-id>.jsonl."""
    return [
        {"on": on, "layer": "digest", "v": line, "by": {"kind": "rule", "ref": RULE}, "origin": "observed"}
        for on, line in digests(events)
    ]
