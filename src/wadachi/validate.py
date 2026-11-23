"""Validation of wadachi files and stores (SPEC.md section 14).

Every problem carries one of the codes in CODES, the same table as SPEC.md
section 14, so tools and the conformance suite can check for exactly the
failure they expect. The validator never raises on bad input: whatever it
reads, it reports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator

from . import FORMAT, schemas
from .canonical import CanonicalError, dumps
from .digest import digests
from .ids import event_id, session_id, split_src
from .times import WADACHI_TIME, instant_ns

CODES = (
    "path",
    "store",
    "compression",
    "encoding",
    "json",
    "canonical",
    "version",
    "schema",
    "header",
    "session-id",
    "seq",
    "turn",
    "time",
    "unknown-source",
    "duplicate-src",
    "id",
    "duplicate-id",
    "dangling-of",
    "of-order",
    "order",
    "annotation-orphan",
    "annotation-layer",
    "annotation-target",
    "digest",
)


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
    return Draft202012Validator(schema)


_HEADER = _validator("record", "header")
_EVENT = _validator("record", "event")
_ANNOTATION = _validator("annotation")


def _read_bytes(path: Path) -> bytes:
    if path.name.endswith(".zst"):
        import zstandard  # optional; the caller reports its absence

        with path.open("rb") as f:
            return zstandard.ZstdDecompressor().stream_reader(f).read()
    return path.read_bytes()


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not a JSON value")


def _has_lone_surrogate(value: object) -> bool:
    if isinstance(value, str):
        return any(0xD800 <= ord(ch) <= 0xDFFF for ch in value)
    if isinstance(value, dict):
        return any(_has_lone_surrogate(k) or _has_lone_surrogate(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_lone_surrogate(v) for v in value)
    return False


def read_lines(path: Path, problems: list[Problem]) -> list[tuple[int, dict]]:
    """Read a .jsonl file, checking encoding, JSON and canonical form."""
    p = str(path)
    try:
        data = _read_bytes(path)
    except ImportError:
        problems.append(Problem("compression", p, 0, "install the zstandard package to read .zst files"))
        return []
    except Exception as err:  # unreadable or corrupt compressed data
        problems.append(Problem("compression" if path.name.endswith(".zst") else "path", p, 0, str(err)))
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
        text = text.replace("\r\n", "\n").replace("\r", "\n")
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
        except (ValueError, RecursionError) as err:
            problems.append(Problem("json", p, n, str(err)))
            continue
        if not isinstance(obj, dict):
            problems.append(Problem("json", p, n, "a line must be a JSON object"))
            continue
        if _has_lone_surrogate(obj):
            problems.append(Problem("encoding", p, n, "a string holds a lone surrogate (SPEC.md section 2)"))
        else:
            try:
                if dumps(obj) != line:
                    problems.append(Problem("canonical", p, n, "not serialised as RFC 8785 defines"))
            except CanonicalError as err:
                problems.append(Problem("canonical", p, n, str(err)))
        out.append((n, obj))
    return out


def _schema_problems(validator: Draft202012Validator, obj: dict, p: str, n: int) -> list[Problem]:
    found = []
    for err in sorted(validator.iter_errors(obj), key=lambda e: [str(x) for x in e.absolute_path]):
        where = "/".join(str(x) for x in err.absolute_path) or "(line)"
        found.append(Problem("schema", p, n, f"{where}: {err.message}"))
    return found


def _time_problems(obj: dict, fields: tuple[str, ...], p: str, n: int) -> list[Problem]:
    found = []
    for name in fields:
        value = obj.get(name)
        if isinstance(value, str) and WADACHI_TIME.match(value):
            try:
                instant_ns(value)
            except ValueError as err:
                found.append(Problem("time", p, n, f"{name}: {err}"))
    return found


def _key_number(key: str) -> int:
    return int(key[1:]) if key[1:].isdigit() else 0


def validate_session(path: str | Path) -> Session:
    """Validate one session file on its own."""
    path = Path(path)
    p = str(path)
    s = Session(p)
    if not path.is_file():
        s.problems.append(Problem("path", p, 0, "no such file"))
        return s
    lines = read_lines(path, s.problems)
    if not lines:
        if not any(pr.code in ("encoding", "compression") for pr in s.problems):
            s.problems.append(Problem("header", p, 0, "the file holds no lines"))
        return s

    first_n, first = lines[0]
    if first.get("type") != "session":
        s.problems.append(Problem("header", p, first_n, "the first line must be the session header"))
        body = lines
        header_ok = False
    else:
        if first.get("format") != FORMAT:
            s.problems.append(
                Problem("version", p, first_n, f"format {first.get('format')!r} is not {FORMAT}; nothing else checked")
            )
            return s
        s.header = first
        header_problems = _schema_problems(_HEADER, first, p, first_n)
        s.problems += header_problems + _time_problems(first, ("started_at", "ended_at"), p, first_n)
        header_ok = not header_problems
        if header_ok:
            files = first["files"]
            expected = session_id(
                first["harness"]["name"], native_id=first.get("native_id"), path=files["f1"]["path"] if "f1" in files else None
            ) if (first.get("native_id") or "f1" in files) else None
            if expected is None:
                s.problems.append(Problem("session-id", p, first_n, "cannot derive the id: no native_id and no f1"))
            elif first["id"] != expected:
                s.problems.append(Problem("session-id", p, first_n, f"id should be {expected}"))
        body = lines[1:]

    files = first.get("files") if header_ok else {}
    sid = first.get("id") if header_ok else None
    seen_ids: set[str] = set()
    seen_src: set[str] = set()
    prompts = 0
    numbered: list[tuple[int, dict]] = []
    for n, ev in body:
        if ev.get("type") == "session":
            s.problems.append(Problem("header", p, n, "a header may appear only on the first line"))
            continue
        i = len(s.events)
        s.events.append(ev)
        numbered.append((n, ev))
        event_problems = _schema_problems(_EVENT, ev, p, n)
        s.problems += event_problems + _time_problems(ev, ("t",), p, n)

        if ev.get("seq") != i:
            s.problems.append(Problem("seq", p, n, f"seq should be {i}"))
        if ev.get("type") == "prompt":
            prompts += 1
        if ev.get("turn") != prompts:
            s.problems.append(Problem("turn", p, n, f"turn should be {prompts}"))

        eid, src = ev.get("id"), ev.get("src")
        if isinstance(eid, str):
            if eid in seen_ids:
                s.problems.append(Problem("duplicate-id", p, n, f"{eid} is already used"))
            seen_ids.add(eid)
        if isinstance(src, str) and ":" in src:
            if src in seen_src:
                s.problems.append(Problem("duplicate-src", p, n, f"{src} is already used"))
            seen_src.add(src)
            key, _ = split_src(src)
            if header_ok and key not in files:
                s.problems.append(Problem("unknown-source", p, n, f"{key} is not in the header's files"))
            elif header_ok and isinstance(eid, str):
                expected = event_id(sid, src)
                if eid != expected:
                    s.problems.append(Problem("id", p, n, f"id should be {expected}"))

    position = {e["id"]: k for k, e in enumerate(s.events) if isinstance(e.get("id"), str)}
    for k, (n, ev) in enumerate(numbered):
        target = ev.get("of")
        if not isinstance(target, str):
            continue
        if target not in position:
            s.problems.append(Problem("dangling-of", p, n, f"{target} is not in this session"))
        elif position[target] >= k:
            s.problems.append(Problem("of-order", p, n, f"{target} must come before the event that refers to it"))

    if header_ok:
        _check_order(s, numbered, files)
    return s


def _check_order(s: Session, numbered: list[tuple[int, dict]], files: dict) -> None:
    """Check SPEC.md section 5: where events from hook and aux sources are placed.

    The order of record events comes from their sources and cannot be checked
    here; the placement of every other event follows from it.
    """

    def key_of(ev: dict) -> str:
        return str(ev.get("src", "")).partition(":")[0]

    def role(ev: dict) -> str | None:
        f = files.get(key_of(ev))
        return f.get("role") if isinstance(f, dict) else None

    if any(role(ev) not in ("record", "hook", "aux") for _, ev in numbered):
        return  # unknown sources are reported elsewhere
    record = [ev for _, ev in numbered if role(ev) == "record"]
    # Secondary events by file key; within one file, in the order they appear,
    # which stands in for source order.
    secondary = sorted((ev for _, ev in numbered if role(ev) != "record"), key=lambda ev: _key_number(key_of(ev)))

    expected = list(record)
    trailing = []
    for ev in secondary:
        target = ev.get("of")
        anchor = None
        if isinstance(target, str):
            for k, other in enumerate(expected):
                if other.get("id") == target or other.get("of") == target:
                    anchor = k
        if anchor is None:
            trailing.append(ev)
        else:
            expected.insert(anchor + 1, ev)
    expected += trailing

    for (n, actual), want in zip(numbered, expected):
        if actual is not want:
            s.problems.append(Problem("order", s.path, n, f"expected {want.get('id')} here (SPEC.md section 5)"))
            return


def _session_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*") if p.is_file() and (p.name.endswith(".jsonl") or p.name.endswith(".jsonl.zst")))


def _stem(path: Path) -> str:
    return path.name.removesuffix(".zst").removesuffix(".jsonl")


def validate_store(root: str | Path) -> list[Problem]:
    """Validate a store: every session, and every annotation layer."""
    root = Path(root)
    problems: list[Problem] = []
    if not root.is_dir():
        return [Problem("path", str(root), 0, "no such directory")]
    if not (root / "sessions").is_dir() and not (root / "annotations").is_dir():
        return [Problem("store", str(root), 0, "not a wadachi store: no sessions/ or annotations/ directory")]

    sessions: dict[str, Session] = {}
    for f in _session_files(root / "sessions"):
        s = validate_session(f)
        problems += s.problems
        name = _stem(f)
        if s.header and s.header.get("id") != name:
            problems.append(Problem("session-id", str(f), 0, f"the file should be named after its id, {s.header.get('id')}"))
        sessions[name] = s

    for layer_dir in sorted(d for d in (root / "annotations").glob("*") if d.is_dir()):
        layer = layer_dir.name
        for f in _session_files(layer_dir):
            sid, p = _stem(f), str(f)
            if sid not in sessions:
                problems.append(Problem("annotation-orphan", p, 0, f"no session {sid} in this store"))
                continue
            session = sessions[sid]
            targets = session.ids | {sid}
            computed = None
            for n, ann in read_lines(f, problems):
                problems += _schema_problems(_ANNOTATION, ann, p, n) + _time_problems(ann, ("at",), p, n)
                if ann.get("layer") != layer:
                    problems.append(Problem("annotation-layer", p, n, f"layer should be {layer!r}, the directory's name"))
                on = ann.get("on")
                if not isinstance(on, str) or on not in targets:
                    problems.append(Problem("annotation-target", p, n, f"{on!r} is not in session {sid}"))
                elif layer == "digest" and ann.get("layer") == "digest":
                    if computed is None:
                        computed = _digests_of(session)
                    if computed is not None:
                        if on not in computed:
                            problems.append(Problem("digest", p, n, f"{on} is not the prompt of a turn"))
                        elif ann.get("v") != computed[on]:
                            problems.append(Problem("digest", p, n, f"the digest of this turn is {computed[on]!r}"))
    return problems


def _digests_of(session: Session) -> dict[str, str] | None:
    """Digests by prompt id, or None if the session is too broken to compute them."""
    if session.problems:
        return None
    try:
        return dict(digests(session.events))
    except (ValueError, TypeError, KeyError):
        return None


def validate_path(path: str | Path) -> list[Problem]:
    """Validate a store directory or a single session file."""
    path = Path(path)
    if path.is_dir():
        return validate_store(path)
    return validate_session(path).problems
