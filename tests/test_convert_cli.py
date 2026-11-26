"""CLI checks with constructed toy records only (WHY.md: Forge)."""

import importlib.util
import json
from pathlib import Path

import pytest

from wadachi.cli import main
from wadachi.convert import REGISTRY
from wadachi.convert.base import DiscoveredSession, SessionInput, Source
from wadachi.validate import validate_store


@pytest.fixture
def adapter(monkeypatch):
    template = Path(__file__).resolve().parent.parent / "skills/wadachi-adapter/converter_template.py"
    spec = importlib.util.spec_from_file_location("constructed_template", template)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(REGISTRY, module.HARNESS, module)
    return module


def toy(path, native_id="constructed-session"):
    path.write_text(json.dumps({"session": native_id, "id": "invented-record", "role": "user", "text": "invented prompt"}) + "\n")
    return path


def test_registry_starts_empty():
    assert REGISTRY == {}


def test_unknown_harness_is_clear_and_exits_two(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["convert", "unknown", "--list"])
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "unknown harness: unknown" in output.err


def test_list_prints_only_native_id_path_size(tmp_path, adapter, capsys):
    path = toy(tmp_path / "constructed.jsonl")
    adapter.discover = lambda: [DiscoveredSession("constructed-session", path, path.stat().st_size)]
    assert main(["convert", adapter.HARNESS, "--list"]) == 0
    output = capsys.readouterr()
    assert output.out == f"constructed-session\t{path}\t{path.stat().st_size}\n"
    assert output.err == ""


def test_empty_list_prints_nothing(adapter, capsys):
    assert main(["convert", adapter.HARNESS, "--list"]) == 0
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("arguments", [[], ["--list", "file"], ["--list", "--store", "store"], ["--list", "--hooks", "log"]])
def test_invalid_arguments_exit_two(adapter, arguments):
    with pytest.raises(SystemExit) as exc:
        main(["convert", adapter.HARNESS, *arguments])
    assert exc.value.code == 2


@pytest.mark.parametrize("discover", [False, True])
def test_convert_explicit_or_discovered_paths(tmp_path, adapter, capsys, discover):
    a = toy(tmp_path / "constructed-a.jsonl", "constructed-a")
    b = toy(tmp_path / "constructed-b.jsonl", "constructed-b")
    store = tmp_path / "store"
    adapter.discover = lambda: [DiscoveredSession("constructed-a", a, a.stat().st_size),
                                DiscoveredSession("constructed-b", b, b.stat().st_size)]
    paths = [] if discover else [str(a), str(b)]
    assert main(["convert", adapter.HARNESS, *paths, "--store", str(store)]) == 0
    output = capsys.readouterr()
    assert len(output.out.splitlines()) == 2 and output.err == ""
    assert len(list((store / "sessions").iterdir())) == 2
    assert validate_store(store) == []


def test_convert_passes_hook_path(tmp_path, adapter, capsys):
    path = toy(tmp_path / "constructed.jsonl")
    hook = tmp_path / "constructed-hook.jsonl"
    hook.write_text('{"event":"post_tool","session":"constructed-session","duration_ms":3}\n')
    store = tmp_path / "store"
    assert main(["convert", adapter.HARNESS, str(path), "--store", str(store), "--hooks", str(hook)]) == 0
    lines = Path(capsys.readouterr().out.strip()).read_text().splitlines()
    assert len(lines) == 3
    assert json.loads(lines[-1])["data"] == {"duration_ms": 3}
    assert validate_store(store) == []


def test_adapter_groups_children_from_separate_files(tmp_path, adapter, capsys):
    a = toy(tmp_path / "constructed-parent.jsonl", "constructed-parent")
    b = toy(tmp_path / "constructed-child.jsonl", "constructed-parent/child")

    def grouped(paths):
        assert paths == [a]
        for path in (a, b):
            yield SessionInput([Source("f1", path, "record", adapter.SOURCE_FORMAT)],
                               header={"x": {"fixture": {"constructed": True}}})

    adapter.sessions = grouped
    store = tmp_path / "store"
    assert main(["convert", adapter.HARNESS, str(a), "--store", str(store)]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 2
    assert validate_store(store) == []


def test_io_failure_has_no_traceback(tmp_path, adapter, capsys):
    assert main(["convert", adapter.HARNESS, str(tmp_path / "missing"), "--store", str(tmp_path / "store")]) == 1
    output = capsys.readouterr()
    assert output.out == "" and "cannot convert" in output.err
    assert "Traceback" not in output.err
