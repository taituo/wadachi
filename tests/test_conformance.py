"""The conformance suite: valid inputs give no problems; invalid ones give exactly the listed codes."""

import json
from pathlib import Path

import pytest

from wadachi.validate import validate_path

ROOT = Path(__file__).resolve().parent.parent / "conformance"
MANIFEST = json.loads((ROOT / "manifest.json").read_text())


@pytest.mark.parametrize("path", MANIFEST["valid"])
def test_valid(path):
    assert [str(p) for p in validate_path(ROOT / path)] == []


@pytest.mark.parametrize("path,codes", sorted(MANIFEST["invalid"].items()))
def test_invalid(path, codes):
    found = sorted({p.code for p in validate_path(ROOT / path)})
    assert found == sorted(set(codes))


def test_manifest_lists_every_case():
    listed = set(MANIFEST["valid"]) | set(MANIFEST["invalid"])
    on_disk = {f"{d.name}/{p.name}" for d in (ROOT / "valid", ROOT / "invalid") for p in d.iterdir()}
    assert on_disk == listed
