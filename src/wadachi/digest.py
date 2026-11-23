"""Digests: one counted line per turn (SPEC.md section 11, rule wadachi-digest/1)."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

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

_TS = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|([+-])(\d{2}):(\d{2}))$"
)


def parse_time(value: str) -> datetime:
    """Parse an RFC 3339 timestamp, keeping at most microseconds."""
    m = _TS.match(value)
    if not m:
        raise ValueError(f"not an RFC 3339 timestamp: {value!r}")
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    micro = int((m.group(7) or "0")[:6].ljust(6, "0"))
    dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    if m.group(8) != "Z":
        sign = 1 if m.group(9) == "+" else -1
        dt -= sign * (int(m.group(10)) * 3600 + int(m.group(11)) * 60) * _SECOND
    return dt


_SECOND = datetime(2000, 1, 1, 0, 0, 1) - datetime(2000, 1, 1)


def _escape_path(path: str) -> str:
    return path.replace("%", "%25").replace(" ", "%20").replace("\t", "%09").replace("\n", "%0A")


def _duration(seconds: int) -> str:
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}h{m}m{s}s"
    if m:
        return f"{m}m{s}s"
    return f"{s}s"


def digest_turn(turn: list[dict], failed_calls: set[str]) -> str:
    """The digest line of one turn, given its events in order."""
    prompt = turn[0]
    tokens = [f"t{prompt['turn']}"]

    letter = "h" if prompt.get("actor") == "human" else "p"
    text = prompt.get("data", {}).get("text")
    tokens.append(f"{letter}{len(text)}" if isinstance(text, str) else f"{letter}?")

    calls = [e for e in turn if e.get("type") == "tool_call"]
    counts = Counter(c.get("data", {}).get("kind", "other") for c in calls)
    failures = Counter(c.get("data", {}).get("kind", "other") for c in calls if c.get("id") in failed_calls)
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
        start = parse_time(prompt["t"])
        latest = max(parse_time(e["t"]) for e in turn if e.get("t"))
        seconds = int((latest - start).total_seconds())
        if seconds > 0:
            tokens.append(_duration(seconds))

    paths: list[str] = []
    for c in calls:
        if c.get("data", {}).get("kind") in ("write", "edit"):
            for path in c.get("data", {}).get("paths", []):
                if path not in paths:
                    paths.append(path)
    tokens += [_escape_path(x) for x in paths[:MAX_PATHS]]
    if len(paths) > MAX_PATHS:
        tokens.append(f"+{len(paths) - MAX_PATHS}")
    return " ".join(tokens)


def failed_calls(events: list[dict]) -> set[str]:
    """Ids of tool calls that failed, by the rule in SPEC.md section 11."""
    failed = set()
    for e in events:
        target = e.get("of")
        if not target:
            continue
        exit_code = e.get("data", {}).get("exit_code")
        if e.get("type") in ("tool_result", "observation") and isinstance(exit_code, int) and exit_code != 0:
            failed.add(target)
        elif e.get("type") == "error":
            failed.add(target)
    calls = {e["id"] for e in events if e.get("type") == "tool_call"}
    return failed & calls


def digests(events: list[dict]) -> list[tuple[str, str]]:
    """(prompt event id, digest line) for every turn from 1 on."""
    failed = failed_calls(events)
    turns: dict[int, list[dict]] = {}
    for e in events:
        if e.get("turn", 0) >= 1:
            turns.setdefault(e["turn"], []).append(e)
    return [(turn[0]["id"], digest_turn(turn, failed)) for _, turn in sorted(turns.items())]


def annotations(events: list[dict]) -> list[dict]:
    """Digest annotations, ready to write to annotations/digest/<session-id>.jsonl."""
    return [
        {"on": on, "layer": "digest", "v": line, "by": {"kind": "rule", "ref": RULE}, "origin": "observed"}
        for on, line in digests(events)
    ]
