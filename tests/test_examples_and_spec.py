"""The examples are valid, their digests are current, and SPEC.md agrees with the schemas and the validator."""

import json
import re
from pathlib import Path

from wadachi import schemas
from wadachi.cli import main
from wadachi.digest import annotations
from wadachi.validate import CODES, validate_session, validate_store

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


def _section(heading: str) -> str:
    return SPEC.split(heading, 1)[1].split("\n## ", 1)[0].split("\n### ", 1)[0]


def _first_column(heading: str) -> list[str]:
    return re.findall(r"^\| `([a-z_-]+)` \|", _section(heading), re.M)


def test_spec_event_types_match_schema():
    assert _first_column("### 4.2 Types") == schemas.load("record")["$defs"]["event"]["properties"]["type"]["enum"]


def _rules():
    return {r["if"]["properties"]["type"]["const"]: r["then"] for r in schemas.load("record")["$defs"]["event"]["allOf"]}


def test_spec_kinds_match_schema():
    assert _first_column("### 4.4 Tool kinds") == _rules()["tool_call"]["properties"]["data"]["properties"]["kind"]["enum"]


def test_spec_actors_and_data_fields_per_type_match_schema():
    rows = re.findall(r"^\| `([a-z_]+)` \| ([a-z, ]+) \| (.*) \|$", _section("### 4.2 Types"), re.M)
    rules = _rules()
    for type_, actors, fields in rows:
        then = rules[type_]
        assert [a.strip() for a in actors.split(",")] == then["properties"]["actor"]["enum"], type_
        spec_fields = re.findall(r"`([a-z0-9_]+)`", fields.split(":")[0] if type_ in ("steer", "setting", "manifest") else fields)
        spec_fields = [f for f in spec_fields if f not in ("asked", "allowed", "denied")]
        assert sorted(spec_fields) == sorted(then["properties"]["data"]["properties"]), type_


def test_spec_problem_codes_match_validator():
    assert tuple(_first_column("## 14. Conformance")) == CODES


def test_spec_layers_have_schema_rules():
    defined = _first_column("## 10. Annotations")[6:]  # skip the field table: on, layer, v, by, origin, at
    with_rules = [r["if"]["properties"]["layer"]["const"] for r in schemas.load("annotation")["allOf"] if "layer" in r["if"].get("properties", {})]
    assert sorted(defined) == sorted(with_rules)


def test_cli_validate_and_digest(capsys):
    assert main(["validate", "-q", str(STORE)]) == 0
    session = next((STORE / "sessions").glob("*.jsonl"))
    assert main(["digest", str(session)]) == 0
    assert capsys.readouterr().out.startswith("t1 ")
    bad = ROOT / "conformance" / "invalid" / "seq-gap.jsonl"
    assert main(["validate", "-q", str(bad)]) == 1
