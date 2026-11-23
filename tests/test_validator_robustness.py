"""Whatever the validator reads, it reports problems instead of raising."""

import pytest

from wadachi.cli import main
from wadachi.validate import validate_path

BROKEN_HEADERS = [
    '{"type":"session","harness":"x"}',
    '{"type":"session","harness":{"name":"h"},"files":[]}',
    '{"type":"session","format":"wadachi/0.1","harness":{"name":"h"},"files":{"fx":{"role":"record","path":"a"}}}',
    '{"type":"session","format":"wadachi/0.1","harness":{"name":"h"},"files":{"f1":{"role":"record","path":5}}}',
    '{"type":"session","format":"wadachi/0.1","harness":{"name":["h"]},"native_id":"a"}',
    '{"type":"session","format":"wadachi/0.1","harness":{"name":"h"},"native_id":5}',
    '{"type":"session","format":"wadachi/0.1"}',
    '{"type":"session","format":["wadachi/0.1"]}',
]


@pytest.mark.parametrize("header", BROKEN_HEADERS)
def test_broken_headers_are_reported(tmp_path, header):
    f = tmp_path / "s.jsonl"
    f.write_text(header + '\n{"id":5,"seq":"0","turn":null,"src":["f1:0"],"of":{},"data":[]}\n')
    problems = validate_path(f)
    assert problems
    assert {p.code for p in problems} <= {"schema", "canonical", "version", "session-id", "seq", "turn", "header"}


def test_broken_annotations_are_reported(tmp_path):
    (tmp_path / "sessions").mkdir()
    layer = tmp_path / "annotations" / "noise"
    layer.mkdir(parents=True)
    (layer / "s_0000000000000000.jsonl").write_text('{"on":["x"],"layer":"noise"}\n')
    assert [p.code for p in validate_path(tmp_path)] == ["annotation-orphan"]


def test_annotation_with_unhashable_target(tmp_path):
    import shutil
    from pathlib import Path

    shutil.copytree(Path(__file__).resolve().parent.parent / "conformance" / "valid" / "store", tmp_path / "store")
    noise = next((tmp_path / "store" / "annotations" / "noise").glob("*.jsonl"))
    noise.write_text('{"layer":"noise","on":["x"]}\n')
    codes = {p.code for p in validate_path(tmp_path / "store")}
    assert codes == {"schema", "annotation-target"}


def test_missing_path_and_non_store(tmp_path):
    assert [p.code for p in validate_path(tmp_path / "nope.jsonl")] == ["path"]
    assert [p.code for p in validate_path(tmp_path)] == ["store"]


def test_empty_and_odd_files(tmp_path):
    for content, codes in [
        (b"", {"header"}),
        (b"\n", {"encoding"}),
        (b"\xff\xfe", {"encoding"}),
        (b"[1,2]\n", {"json", "header"}),
        (b'"text"\n', {"json", "header"}),
        (b"[" * 5000 + b"]" * 5000 + b"\n", {"json", "header"}),
    ]:
        f = tmp_path / "x.jsonl"
        f.write_bytes(content)
        assert {p.code for p in validate_path(f)} == codes, content[:20]


def test_cli_does_not_raise(tmp_path, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"a":NaN}\n{"b":12345678901234567890}\nnot json\n')
    assert main(["canonical", str(bad)]) == 1
    assert main(["id", "session", "h", "--native-id", ""]) == 1
    assert main(["validate", "-q", str(tmp_path / "missing")]) == 1
    capsys.readouterr()
