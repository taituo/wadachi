"""The examples are valid, their digests are current, and SPEC.md agrees with the schemas."""

import json
import re
from pathlib import Path

from wadachi import schemas
from wadachi.cli import main
from wadachi.digest import annotations
from wadachi.validate import validate_session, validate_store

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "examples" / "store"
SPEC = (ROOT / "SPEC.md").read_text()


def test_example_store_is_valid():
    assert [str(p) for p in validate_store(STORE)] == []


def test_example_digests_are_current():
    for f in (STORE / "sessions").glob("*.jsonl"):
        events = validate_session(f).events
        stored = [json.loads(line) for line in (STORE / "annotations" / "digest" / f.name).read_text().splitlines()]
        assert stored == annotations(events), f.name


def _table_column(heading: str) -> list[str]:
    """First-column values of the first table after a heading in SPEC.md."""
    section = SPEC.split(heading, 1)[1]
    rows = re.findall(r"^\| `([a-z_-]+)` \|", section.split("\n## ", 1)[0].split("\n### ", 1)[0], re.M)
    return rows


def test_spec_event_types_match_schema():
    schema_types = schemas.load("record")["$defs"]["event"]["properties"]["type"]["enum"]
    assert _table_column("### 4.2 Types") == schema_types


def test_spec_kinds_match_schema():
    rules = schemas.load("record")["$defs"]["event"]["allOf"]
    tool_call = next(r for r in rules if r["if"]["properties"]["type"]["const"] == "tool_call")
    kinds = tool_call["then"]["properties"]["data"]["properties"]["kind"]["enum"]
    assert _table_column("### 4.4 Tool kinds") == kinds


def test_spec_actors_per_type_match_schema():
    section = SPEC.split("### 4.2 Types", 1)[1].split("\n### ", 1)[0]
    spec = {t: [a.strip() for a in actors.split(",")] for t, actors in re.findall(r"^\| `([a-z_]+)` \| ([a-z, ]+) \|", section, re.M)}
    rules = schemas.load("record")["$defs"]["event"]["allOf"]
    schema = {r["if"]["properties"]["type"]["const"]: r["then"]["properties"]["actor"]["enum"] for r in rules}
    assert spec == schema


def test_cli_validate_and_digest(capsys):
    assert main(["validate", "-q", str(STORE)]) == 0
    session = next((STORE / "sessions").glob("*.jsonl"))
    assert main(["digest", str(session)]) == 0
    assert capsys.readouterr().out.startswith("t1 ")
    bad = ROOT / "conformance" / "invalid" / "seq-gap.jsonl"
    assert main(["validate", "-q", str(bad)]) == 1
