"""Constructed Grok CLI session. Every content value is invented (WHY: Forge)."""

from pathlib import Path

from wadachi import dumps
from wadachi.convert import REGISTRY, base, grok
from wadachi.digest import digests
from wadachi.dump import dump
from wadachi.validate import validate_session, validate_store

ROOT = Path(__file__).parent / "fixtures" / "grok"
SID = "00000000-0000-4000-8000-00000000690c"
HISTORY = ROOT / "sessions" / "%2Fhome%2Fuser%2Fproject" / SID / "chat_history.jsonl"


def convert():
    inp = next(grok.sessions([HISTORY]))
    inp.header["x"] = {"fixture": {"constructed": True}}
    return base.convert(grok, inp)


def golden(lines):
    prefix = base.display_path(ROOT)
    for f in [*lines[0]["files"].values(), *lines[0].get("unread", [])]:
        f["path"] = f["path"].replace(prefix, "/home/user/constructed")
    return "".join(dumps(r) + "\n" for r in lines)


def test_matches_expected_output(tmp_path):
    lines = convert()
    assert validate_session(base.write_session(lines, tmp_path / "store")).problems == []
    assert lines == convert()
    assert golden(lines) == (ROOT / "expected.jsonl").read_text(encoding="utf-8")


def test_events_sources_and_links():
    lines = convert()
    header, events = lines[0], lines[1:]
    assert header["native_id"] == SID
    assert "version" not in header["harness"]  # prompt_context.version is a format number, not the CLI's
    assert header["mode"] == "headless" and header["cwd"] == "/home/user/project"
    assert list(header["files"]) == ["f1", "f3", "f4", "f5", "f6", "f7", "f8"]
    assert [u["path"].rsplit(SID + "/", 1)[1] for u in header["unread"]] == [
        "plan.json", "terminal/call-constructed-2-1.log", "updates.jsonl"]
    by = lambda t: [e for e in events if e["type"] == t]
    ctx = by("context")
    assert [e["data"].get("name") for e in ctx] == [None, None, "system_reminder", "system_prompt", "tool_definitions"]
    # A user line without prompt_index is the harness's own block, not a prompt.
    assert ctx[1]["how"] == {"type": "inferred:user-line-without-prompt-index"} and ctx[1]["turn"] == 0
    assert len(by("prompt")) == 1
    calls, results = by("tool_call"), by("tool_result")
    assert [r["of"] for r in results] == [c["id"] for c in calls]
    assert calls[0]["data"]["args"] == '{"target_file": "/home/user/project/a.txt"}'  # kept as recorded
    assert by("reasoning")[0]["data"] == {"redacted": True, "text": "Invented summary."}
    # Chat history has no times; telemetry does, and it is never copied across.
    assert all("t" not in e for e in events if e["src"].startswith("f1:"))
    assert all("t" in e for e in events if e["src"].startswith("f3:"))
    err = by("error")[0]
    assert err["of"] == calls[1]["id"] and "outcome" not in err["raw"]  # mapped, not repeated
    assert [p["data"] for p in by("permission")] == [{"decision": "asked"}, {"decision": "allowed"}]
    assert "decision" not in by("permission")[1]["raw"]
    stop = by("interrupt")[0]
    assert (stop["actor"], stop["data"], stop["how"]) == ("human", {"reason": "mid_turn_abort"},
                                                          {"actor": "inferred:ctrl-c-trigger"})
    # The model did not change, so turn_started is a record, not a setting.
    assert not by("setting") and header["model"] == "constructed-grok"
    # An unresolved reference is not repeated in raw when raw keeps the source field.
    assert all("of_call" not in e.get("raw", {}) for e in events)
    future = [e for e in events if e["type"] == "record" and e["src"].startswith("f1:")]
    assert future[0]["raw"]["content"] == "Invented future line."
    assert [d for _, d in digests(events)] == ["t1 p17 r1 s1!1 x"]  # the prompt has no time, so no duration


def test_dump_with_grok_home(tmp_path, monkeypatch):
    monkeypatch.setenv("GROK_HOME", str(ROOT))
    found = list(grok.discover())
    assert [(s.native_id, s.cwd) for s in found] == [(SID, "/home/user/project")]
    assert grok.select_self(found, "/home/user/project") == found
    assert "grok" in REGISTRY
    store = tmp_path / "store"
    assert dump(store, harness="grok") == 0 and validate_store(store) == []
