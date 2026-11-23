"""Validation of wadachi files and stores (SPEC.md section 14).

Every problem has a stable code, so tools and the conformance suite can check
for exactly the failure they expect:

    encoding           not UTF-8, a byte order mark, CR, a blank line or no final LF
    json               a line that is not a JSON object
    canonical          a line not serialised as RFC 8785 defines
    schema             a line that does not match the JSON Schema
    header             no header on the first line, or a header elsewhere
    session-id         the header's id is not the one SPEC.md section 7 derives
    seq                seq does not count from 0 without gaps
    turn               turn does not follow SPEC.md section 4.3
    duplicate-id       two events with the same id
    id                 an event id that is not the derived one
    unknown-source     src names a file key the header does not define
    dangling-of        of names an event that is not in the session
    of-order           of names an event that comes later
    order              an event from a hook or aux source is not where SPEC.md section 5 puts it
    annotation-orphan  an annotation file for a session the store does not hold
    annotation-layer   an annotation whose layer is not its directory's name
    annotation-target  an annotation on an event or session that does not exist
    compression        a .jsonl.zst file and no zstandard module to read it
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from . import schemas
from .canonical import dumps
from .ids import event_id, session_id, split_src


@dataclass(frozen=True)
class Problem:
    code: str
    path: str
    line: int  # 1-based; 0 for the file as a whole
    message: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.code}: {self.message}"


@dataclass
class Session:
    path: str
    header: dict | None = None
    events: list[dict] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    @property
    def ids(self) -> set[str]:
        return {e["id"] for e in self.events if isinstance(e.get("id"), str)}


def _validator(name: str, ref: str | None = None) -> Draft202012Validator:
    schema = schemas.load(name)
    if ref:
        schema = {"$ref": f"#/$defs/{ref}", "$defs": schema["$defs"]}
    return Draft202012Validator(schema, format_checker=FormatChecker())


_HEADER = _validator("record", "header")
_EVENT = _validator("record", "event")
_ANNOTATION = _validator("annotation")


def _read_bytes(path: Path) -> bytes:
    if path.name.endswith(".zst"):
        import zstandard  # optional; the caller reports its absence

        return zstandard.ZstdDecompressor().stream_reader(path.open("rb")).read()
    return path.read_bytes()


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not a JSON value")


def read_lines(path: Path, problems: list[Problem]) -> list[tuple[int, dict]]:
    """Read a .jsonl file, checking encoding, JSON and canonical form."""
    p = str(path)
    try:
        data = _read_bytes(path)
    except ImportError:
        problems.append(Problem("compression", p, 0, "install the zstandard package to read .zst files"))
        return []
    if data.startswith(b"\xef\xbb\xbf"):
        problems.append(Problem("encoding", p, 0, "the file starts with a byte order mark"))
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as err:
        problems.append(Problem("encoding", p, 0, f"not valid UTF-8: {err}"))
        return []
    if "\r" in text:
        problems.append(Problem("encoding", p, 0, "lines must end in LF, not CR LF"))
        text = text.replace("\r\n", "\n")
    if text and not text.endswith("\n"):
        problems.append(Problem("encoding", p, 0, "the file must end with a line feed"))
        text += "\n"
    out: list[tuple[int, dict]] = []
    for n, line in enumerate(text.split("\n")[:-1], start=1):
        if not line:
            problems.append(Problem("encoding", p, n, "blank line"))
            continue
        try:
            obj = json.loads(line, parse_constant=_reject_constant)
        except ValueError as err:
            problems.append(Problem("json", p, n, str(err)))
            continue
        if not isinstance(obj, dict):
            problems.append(Problem("json", p, n, "a line must be a JSON object"))
            continue
        try:
            canonical = dumps(obj)
        except (TypeError, ValueError) as err:
            problems.append(Problem("canonical", p, n, str(err)))
        else:
            if canonical != line:
                problems.append(Problem("canonical", p, n, "not serialised as RFC 8785 defines"))
        out.append((n, obj))
    return out


def _schema_problems(validator: Draft202012Validator, obj: dict, p: str, n: int) -> list[Problem]:
    found = []
    for err in sorted(validator.iter_errors(obj), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(x) for x in err.absolute_path) or "(line)"
        found.append(Problem("schema", p, n, f"{where}: {err.message}"))
    return found


def _expected_session_id(header: dict) -> str | None:
    harness = header.get("harness", {}).get("name")
    if not harness:
        return None
    if header.get("native_id"):
        return session_id(harness, native_id=header["native_id"])
    records = sorted(
        (k for k, f in header.get("files", {}).items() if isinstance(f, dict) and f.get("role") == "record"),
        key=lambda k: int(k[1:]),
    )
    if not records:
        return None
    return session_id(harness, path=header["files"][records[0]].get("path", ""))


def validate_session(path: str | Path) -> Session:
    """Validate one session file on its own."""
    path = Path(path)
    p = str(path)
    s = Session(p)
    lines = read_lines(path, s.problems)
    if not lines:
        if not s.problems:
            s.problems.append(Problem("header", p, 0, "the file is empty"))
        return s

    first_n, first = lines[0]
    if first.get("type") != "session":
        s.problems.append(Problem("header", p, first_n, "the first line must be the session header"))
        body = lines
    else:
        s.header = first
        s.problems += _schema_problems(_HEADER, first, p, first_n)
        expected = _expected_session_id(first)
        if expected is None:
            s.problems.append(Problem("session-id", p, first_n, "cannot derive the id: no native_id and no record source"))
        elif first.get("id") != expected:
            s.problems.append(Problem("session-id", p, first_n, f"id should be {expected}"))
        body = lines[1:]

    files = (s.header or {}).get("files", {}) if isinstance((s.header or {}).get("files"), dict) else {}
    sid = (s.header or {}).get("id")
    seen: dict[str, int] = {}  # id -> seq
    prompts = 0
    numbered: list[tuple[int, dict]] = []  # (line number, event)
    for n, ev in body:
        if ev.get("type") == "session":
            s.problems.append(Problem("header", p, n, "a header may appear only on the first line"))
            continue
        i = len(s.events)
        s.events.append(ev)
        numbered.append((n, ev))
        s.problems += _schema_problems(_EVENT, ev, p, n)

        if ev.get("seq") != i:
            s.problems.append(Problem("seq", p, n, f"seq should be {i}"))

        if ev.get("type") == "prompt":
            prompts += 1
        if ev.get("turn") != prompts:
            s.problems.append(Problem("turn", p, n, f"turn should be {prompts}"))

        eid = ev.get("id")
        if isinstance(eid, str):
            if eid in seen:
                s.problems.append(Problem("duplicate-id", p, n, f"{eid} already used"))
            seen.setdefault(eid, i)

        src = ev.get("src")
        if isinstance(src, str) and ":" in src:
            key, position = split_src(src)
            if key not in files:
                s.problems.append(Problem("unknown-source", p, n, f"{key} is not in the header's files"))
            elif isinstance(sid, str) and isinstance(ev.get("type"), str) and isinstance(files[key], dict):
                expected = event_id(sid, files[key].get("path", ""), position, ev["type"])
                if eid != expected:
                    s.problems.append(Problem("id", p, n, f"id should be {expected}"))

    _check_order(s, numbered, files)

    seqs = {e["id"]: k for k, e in enumerate(s.events) if isinstance(e.get("id"), str)}
    for k, (n, ev) in enumerate(numbered):
        target = ev.get("of")
        if not isinstance(target, str):
            continue
        if target not in seqs:
            s.problems.append(Problem("dangling-of", p, n, f"{target} is not in this session"))
        elif seqs[target] >= k:
            s.problems.append(Problem("of-order", p, n, f"{target} must come before the event that refers to it"))
    return s


def _check_order(s: Session, numbered: list[tuple[int, dict]], files: dict) -> None:
    """Check SPEC.md section 5: where events from hook and aux sources are placed.

    The relative order of record events comes from their sources and cannot be
    checked here; the placement of every other event follows from it.
    """

    def role(ev: dict) -> str | None:
        key = str(ev.get("src", "")).partition(":")[0]
        f = files.get(key)
        return f.get("role") if isinstance(f, dict) else None

    record = [ev for _, ev in numbered if role(ev) == "record"]
    secondary = [ev for _, ev in numbered if role(ev) in ("hook", "aux")]
    if len(record) + len(secondary) != len(numbered):
        return  # unknown sources are reported elsewhere

    expected = list(record)
    trailing = []
    for ev in secondary:
        target = ev.get("of")
        anchor = None
        for k, other in enumerate(expected):
            if other.get("id") == target or (other.get("of") == target and target is not None):
                anchor = k
        if target is None or anchor is None:
            trailing.append(ev)
        else:
            expected.insert(anchor + 1, ev)
    expected += trailing

    for (n, actual), want in zip(numbered, expected):
        if actual is not want:
            s.problems.append(Problem("order", s.path, n, f"expected {want.get('id')} here (SPEC.md section 5)"))
            return


def validate_store(root: str | Path) -> list[Problem]:
    """Validate a store: every session, and every annotation layer."""
    root = Path(root)
    problems: list[Problem] = []
    sessions: dict[str, Session] = {}
    for f in sorted((root / "sessions").glob("*.jsonl*")):
        s = validate_session(f)
        problems += s.problems
        name = f.name.split(".")[0]
        if s.header and s.header.get("id") != name:
            problems.append(Problem("session-id", str(f), 0, f"the file should be named after its id, {s.header.get('id')}"))
        sessions[name] = s
    for f in sorted((root / "annotations").glob("*/*.jsonl*")):
        layer, sid = f.parent.name, f.name.split(".")[0]
        p = str(f)
        if sid not in sessions:
            problems.append(Problem("annotation-orphan", p, 0, f"no session {sid} in this store"))
            continue
        targets = sessions[sid].ids | {sid}
        for n, ann in read_lines(f, problems):
            problems += _schema_problems(_ANNOTATION, ann, p, n)
            if ann.get("layer") != layer:
                problems.append(Problem("annotation-layer", p, n, f"layer should be {layer!r}, the directory's name"))
            if ann.get("on") not in targets:
                problems.append(Problem("annotation-target", p, n, f"{ann.get('on')} is not in session {sid}"))
    return problems


def validate_path(path: str | Path) -> list[Problem]:
    """Validate a store directory or a single session file."""
    path = Path(path)
    if path.is_dir():
        return validate_store(path)
    return validate_session(path).problems
