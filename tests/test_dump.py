"""Constructed discovery, environments and Herdr snapshots only (WHY: Forge)."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from wadachi.cli import main
from wadachi.convert import REGISTRY, base
from wadachi import dump as dumping


class Constructed:
    HARNESS = "constructed"
    SOURCE_FORMAT = "constructed-jsonl"
    CONVERTER = {"name": "constructed-converter", "version": "9.8.7"}
    KINDS = {}

    def __init__(self, paths):
        self.paths = paths
        self.mapped = 0

    def native_id(self, records):
        return next((r["payload"]["id"] for _, r in records if r.get("type") == "session_meta"), None)

    def discover(self):
        for path in self.paths:
            try:
                nid = self.native_id(base.read_jsonl(path).records)
            except ValueError:
                nid = None
            yield base.DiscoveredSession(nid, path, path.stat().st_size)

    def sessions(self, paths):
        for path in paths:
            yield base.SessionInput([base.Source("f1", path, "record", self.SOURCE_FORMAT)],
                                    header={"x": {"fixture": {"constructed": True}}})

    def map_record(self, position, rec):
        self.mapped += 1
        return [{"pos": str(position), "type": "prompt", "actor": "human", "data": {"text": rec["text"]}}] if "text" in rec else []

    def self_id(self):
        return os.environ.get("CONSTRUCTED_SELF_ID")


def rollout(path, nid="constructed-one", cwd="/home/user/project"):
    path.write_text(json.dumps({"type": "session_meta", "payload": {"id": nid, "cwd": cwd}}) + "\n" +
                    json.dumps({"text": "Invented prompt, never console output."}) + "\n")
    return path


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for name in list(REGISTRY):
        monkeypatch.delitem(REGISTRY, name)
    path = rollout(tmp_path / "constructed-one.jsonl")
    adapter = Constructed([path])
    monkeypatch.setitem(REGISTRY, adapter.HARNESS, adapter)
    monkeypatch.delenv("CONSTRUCTED_SELF_ID", raising=False)
    return adapter, tmp_path / "store"


def test_dump_all_registered_and_incremental_skips_mapping(setup, capsys):
    adapter, store = setup
    assert main(["dump", "--store", str(store)]) == 0
    assert capsys.readouterr() == ("constructed: converted=1 skipped=0 failed=0\n", "")
    mapped = adapter.mapped
    output = next((store / "sessions").iterdir())
    before = output.read_bytes(), output.stat().st_mtime_ns
    assert main(["dump", "--store", str(store)]) == 0
    assert adapter.mapped == mapped
    assert (output.read_bytes(), output.stat().st_mtime_ns) == before
    assert capsys.readouterr() == ("constructed: converted=0 skipped=1 failed=0\n", "")
    with adapter.paths[0].open("a") as stream:
        stream.write('{"text":"Invented second prompt."}\n')
    assert main(["dump", "--store", str(store)]) == 0
    assert capsys.readouterr().out == "constructed: converted=1 skipped=0 failed=0\n"


def test_converter_version_change_invalidates_skip(setup, capsys):
    adapter, store = setup
    assert dumping.dump(store) == 0
    adapter.CONVERTER = dict(adapter.CONVERTER, version="9.8.8")
    assert dumping.dump(store) == 0
    assert capsys.readouterr().out.count("converted=1 skipped=0 failed=0") == 2


def test_keep_raw_hash_matches_converted_prefix_even_when_skipped(setup, capsys):
    adapter, store = setup
    complete = adapter.paths[0].read_bytes()
    with adapter.paths[0].open("ab") as stream:
        stream.write(b'{"half":')
    assert dumping.dump(store) == 0
    assert not (store / "raw").exists()
    assert dumping.dump(store, keep_raw=True) == 0
    raw = store / "raw" / hashlib.sha256(complete).hexdigest()
    assert raw.read_bytes() == complete
    assert "skipped=1" in capsys.readouterr().out


def test_source_and_converter_failures_count_and_continue(setup, tmp_path, capsys):
    adapter, store = setup
    broken = tmp_path / "constructed-broken.jsonl"
    broken.write_text('{"invalid"}\n')
    adapter.paths.insert(0, broken)
    assert dumping.dump(store) == 1
    assert capsys.readouterr() == ("constructed: converted=1 skipped=0 failed=1\n", "")


def test_default_store_uses_environment_then_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WADACHI_STORE", str(tmp_path / "constructed-store"))
    assert dumping.default_store() == tmp_path / "constructed-store"
    monkeypatch.delenv("WADACHI_STORE")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert dumping.default_store() == tmp_path / ".wadachi/store"


def test_cli_default_and_harness_filter(setup, tmp_path, monkeypatch, capsys):
    adapter, store = setup
    other = Constructed([rollout(tmp_path / "constructed-other.jsonl", "constructed-other")])
    other.HARNESS = "constructed-other"
    monkeypatch.setitem(REGISTRY, other.HARNESS, other)
    monkeypatch.setenv("WADACHI_STORE", str(store))
    assert main(["dump", "--harness", adapter.HARNESS]) == 0
    assert other.mapped == 0
    assert capsys.readouterr().out == "constructed: converted=1 skipped=0 failed=0\n"


@pytest.mark.parametrize("gitfile", [False, True])
def test_inside_git_is_refused_unless_explicitly_allowed(setup, tmp_path, capsys, gitfile):
    _, store = setup
    if gitfile:
        (tmp_path / ".git").write_text("gitdir: /home/user/constructed-git\n")
    else:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git/HEAD").write_text("ref: refs/heads/constructed\n")
    assert main(["dump", "--store", str(store)]) == 2
    assert not store.exists()
    output = capsys.readouterr()
    assert output.out == "" and "--allow-inside-git" in output.err
    assert main(["dump", "--store", str(store), "--allow-inside-git"]) == 0


def test_symlink_into_git_is_refused(setup, tmp_path):
    _, store = setup
    repo = tmp_path / "constructed-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git/HEAD").write_text("ref: refs/heads/constructed\n")
    store.symlink_to(repo, target_is_directory=True)
    with pytest.raises(dumping.DumpError, match="git working tree"):
        dumping.dump(store)


def test_session_file_symlink_into_git_cannot_receive_real_output(setup, tmp_path):
    _, store = setup
    assert dumping.dump(store) == 0
    out = next((store / "sessions").iterdir())
    repo = tmp_path / "constructed-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git/HEAD").write_text("ref: refs/heads/constructed\n")
    target = repo / "constructed-output"
    out.unlink()
    out.symlink_to(target)
    with pytest.raises(dumping.DumpError, match="git working tree"):
        dumping.dump(store)
    assert not target.exists()


def test_self_selects_environment_id_without_fallback(setup, tmp_path, monkeypatch, capsys):
    adapter, store = setup
    adapter.paths.append(rollout(tmp_path / "constructed-two.jsonl", "constructed-two"))
    monkeypatch.setenv("CONSTRUCTED_SELF_ID", "constructed-two")
    assert main(["dump", "--store", str(store), "--self"]) == 0
    output = capsys.readouterr()
    assert "converted=1" in output.out and output.err == ""
    header = json.loads(next((store / "sessions").iterdir()).read_text().splitlines()[0])
    assert header["native_id"] == "constructed-two"


def test_self_fallback_reports_selection_without_content(setup, tmp_path, monkeypatch, capsys):
    adapter, store = setup
    monkeypatch.chdir(tmp_path)
    a = rollout(tmp_path / "constructed-a.jsonl", "constructed-a", str(tmp_path))
    b = rollout(tmp_path / "constructed-b.jsonl", "constructed-b", str(tmp_path))
    os.utime(a, ns=(1000000000, 1000000000))
    os.utime(b, ns=(2000000000, 2000000000))
    adapter.paths.extend([a, b])
    assert dumping.dump(store, self_only=True) == 0
    output = capsys.readouterr()
    assert output.out == "constructed: converted=1 skipped=0 failed=0\n"
    assert "--self fallback" in output.err and "recorded cwd" in output.err
    assert "Invented" not in output.err
    header = json.loads(next((store / "sessions").iterdir()).read_text().splitlines()[0])
    assert header["native_id"] == "constructed-b"


def test_self_missing_is_a_failure_without_dumping_all(setup, capsys):
    _, store = setup
    assert dumping.dump(store, self_only=True) == 1
    assert capsys.readouterr().out == "constructed: converted=0 skipped=0 failed=1\n"
    assert not store.exists()


def test_herdr_snapshot_selects_ids_deduplicates_panes_and_ignores_non_id_kinds(setup, tmp_path, monkeypatch, capsys):
    adapter, store = setup
    adapter.paths.append(rollout(tmp_path / "constructed-two.jsonl", "constructed-two"))
    panes = [{"agent": "constructed", "agent_session": {"agent": "constructed", "kind": "id", "value": "constructed-two"}},
             {"agent": "constructed", "agent_session": {"agent": "constructed", "kind": "id", "value": "constructed-two"}},
             {"agent": "constructed", "agent_session": {"agent": "constructed", "kind": "path", "value": "/home/user/constructed"}},
             {"agent": "constructed", "agent_status": "stopped", "agent_session": {"agent": "constructed", "kind": "id", "value": "constructed-one"}}]

    def snapshot(argv, **kwargs):
        assert argv == ["herdr", "api", "snapshot"]
        return SimpleNamespace(stdout=json.dumps({"result": {"snapshot": {"panes": panes}}}))

    monkeypatch.setattr(dumping.subprocess, "run", snapshot)
    assert main(["dump", "--store", str(store), "--from-herdr"]) == 0
    assert capsys.readouterr().out == "constructed: converted=1 skipped=0 failed=0\n"
    header = json.loads(next((store / "sessions").iterdir()).read_text().splitlines()[0])
    assert header["native_id"] == "constructed-two"


def test_herdr_aliases_and_errors_do_not_echo_snapshot(monkeypatch):
    panes = [{"agent_session": {"agent": a, "kind": "id", "value": "constructed-id"}} for a in ("codex", "claude", "agy", "opencode")]
    monkeypatch.setattr(dumping.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps({"result": {"snapshot": {"panes": panes}}})))
    assert set(dumping.herdr_sessions()) == {"codex", "claude-code", "antigravity", "opencode"}
    monkeypatch.setattr(dumping.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="Invented invalid snapshot."))
    with pytest.raises(dumping.DumpError, match="cannot read Herdr"):
        dumping.herdr_sessions()


def test_unknown_harness_and_conflicting_selectors_exit_two(setup):
    with pytest.raises(SystemExit) as exc:
        main(["dump", "--harness", "constructed-unknown"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        main(["dump", "--self", "--from-herdr"])
    assert exc.value.code == 2


def test_selection_keeps_distinct_native_ids_when_paths_are_shared(setup, tmp_path, monkeypatch, capsys):
    adapter, store = setup
    path = adapter.paths[0]
    adapter.discover = lambda: [base.DiscoveredSession("constructed-one", path, 1), base.DiscoveredSession("constructed-two", path, 1)]
    monkeypatch.setenv("CONSTRUCTED_SELF_ID", "constructed-two")
    seen = []

    def selected(found):
        seen.extend(s.native_id for s in found)
        for s in found:
            yield base.SessionInput([base.Source("f1", path, "record", adapter.SOURCE_FORMAT)], native_id=s.native_id,
                                    header={"x": {"fixture": {"constructed": True}}})

    adapter.selected_sessions = selected
    assert dumping.dump(store, self_only=True) == 0
    assert seen == ["constructed-two"]
    assert capsys.readouterr() == ("constructed: converted=1 skipped=0 failed=0\n", "")


def test_unqualified_self_does_not_dump_a_peer_harness_fallback(setup, tmp_path, monkeypatch, capsys):
    adapter, store = setup
    other = Constructed([rollout(tmp_path / "constructed-peer.jsonl", "constructed-peer")])
    other.HARNESS = "constructed-peer"
    other.self_id = lambda: None
    monkeypatch.setitem(REGISTRY, other.HARNESS, other)
    monkeypatch.setenv("CONSTRUCTED_SELF_ID", "constructed-one")
    assert dumping.dump(store, self_only=True) == 0
    assert other.mapped == 0
    assert capsys.readouterr() == ("constructed: converted=1 skipped=0 failed=0\n", "")


def test_unqualified_self_without_a_session_id_uses_caller_marker(setup, tmp_path, monkeypatch, capsys):
    adapter, store = setup
    monkeypatch.chdir(tmp_path)
    rollout(adapter.paths[0], "constructed-one", str(tmp_path))
    adapter.caller_present = lambda: True
    other = Constructed([])
    other.HARNESS = "constructed-peer"
    monkeypatch.setitem(REGISTRY, other.HARNESS, other)
    assert dumping.dump(store, self_only=True) == 0
    assert "--self fallback" in capsys.readouterr().err
    assert other.mapped == 0
