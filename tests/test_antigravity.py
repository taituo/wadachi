"""Constructed Antigravity CLI conversation. Every content value is invented (WHY: Forge)."""

from pathlib import Path

from wadachi import dumps
from wadachi.convert import REGISTRY, base, antigravity as ag
from wadachi.digest import digests
from wadachi.dump import dump
from wadachi.validate import validate_session, validate_store

ROOT = Path(__file__).parent / "fixtures" / "antigravity"
CONVERSATION = "00000000-0000-4000-8000-0000000a9e01"
FULL = ROOT / "brain" / CONVERSATION / ".system_generated" / "logs" / "transcript_full.jsonl"


def convert():
    inp = next(ag.sessions([FULL]))
    inp.header["x"] = {"fixture": {"constructed": True}}
    return base.convert(ag, inp)


def golden(lines):
    prefix = base.display_path(ROOT)
    for f in lines[0]["files"].values():
        f["path"] = f["path"].replace(prefix, "/home/user/constructed")
    for f in lines[0].get("unread", []):
        f["path"] = f["path"].replace(prefix, "/home/user/constructed")
    return "".join(dumps(r) + "\n" for r in lines)


def test_matches_expected_output(tmp_path):
    lines = convert()
    assert validate_session(base.write_session(lines, tmp_path / "store")).problems == []
    assert lines == convert()
    assert golden(lines) == (ROOT / "expected.jsonl").read_text(encoding="utf-8")


def test_events_and_links():
    lines = convert()
    header, events = lines[0], lines[1:]
    assert header["native_id"] == CONVERSATION
    assert header["how"] == {"native_id": "inferred:conversation-directory"}
    assert "version" not in header["harness"]  # not recorded in the conversation's files
    assert header["files"]["f3"] == {**header["files"]["f3"], "role": "aux", "truncated": True}
    assert [(e["type"], e["actor"]) for e in events] == [
        ("context", "harness"), ("prompt", "human"),
        ("reasoning", "agent"), ("tool_call", "agent"), ("usage", "harness"), ("tool_result", "tool"),
        ("setting", "harness"), ("tool_call", "agent"), ("usage", "harness"), ("tool_result", "tool"),
        ("error", "tool"), ("context", "harness"), ("assistant_text", "agent"), ("usage", "harness"),
        ("record", "harness")]
    calls = [e for e in events if e["type"] == "tool_call"]
    results = [e for e in events if e["type"] == "tool_result"]
    assert [r["of"] for r in results] == [c["id"] for c in calls]
    assert all(r["how"] == {"of": "inferred:next-step-answers-call"} for r in results)
    assert calls[0]["data"]["kind"] == "shell" and calls[1]["data"]["paths"] == ["/home/user/project/a.txt"]
    assert results[1]["data"]["status_as_recorded"] == "ERROR"
    # Nothing is left out: the unknown step keeps its content; other files are listed.
    assert events[-1]["raw"]["content"] == "Invented future content."
    unread = [u["path"].rsplit(CONVERSATION + "/", 1)[1] for u in header["unread"]]
    assert unread == [".system_generated/logs/chunks/transcript_full/00000000.jsonl",
                      ".system_generated/logs/chunks/transcript_full/00000001.jsonl",
                      ".system_generated/messages/read.json", ".system_generated/steps/3/output.txt",
                      "scratch/invented.py"]
    # Raw keeps only what data does not hold.
    assert "content" not in events[1]["raw"] and "tool_calls" not in events[2].get("raw", {})
    assert [d for _, d in digests(events)] == ["t1 h48 r1!1 s1 8s"]  # the error event marks the read failed


def test_dump_discovers_with_its_own_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WADACHI_ANTIGRAVITY_HOME", str(ROOT))
    assert [s.native_id for s in ag.discover()] == [CONVERSATION]
    assert "antigravity" in REGISTRY
    store = tmp_path / "store"
    assert dump(store, harness="antigravity", keep_raw=True) == 0
    assert validate_store(store) == []
    # --keep-raw keeps the unread files too.
    assert len(list((store / "raw").iterdir())) == 2 + 5
