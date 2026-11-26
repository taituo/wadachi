"""Dump discovered sessions. Console output contains counts, never content."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from . import FORMAT, session_id
from .convert import REGISTRY
from .convert import base


class DumpError(ValueError):
    pass


INPUT_ERRORS = (OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error)


def default_store() -> Path:
    return Path(os.environ.get("WADACHI_STORE", str(Path.home() / ".wadachi/store"))).expanduser()


def guard_store(store: Path, allow_inside_git: bool) -> None:
    if allow_inside_git:
        return
    # Resolve symlinks before checking ancestors. A git worktree has a .git file.
    for target in (store, store / "sessions", store / "raw"):
        resolved = target.expanduser().resolve()
        if any((p / ".git").is_file() or (p / ".git" / "HEAD").is_file()
               for p in (resolved, *resolved.parents)):
            raise DumpError("refusing to write a store inside a git working tree; use --allow-inside-git")


def herdr_sessions(pane_id: str | None = None) -> dict[str, set[str]]:
    try:
        run = subprocess.run(["herdr", "api", "snapshot"], capture_output=True, text=True, check=True, timeout=15)
        data = json.loads(run.stdout)["result"]["snapshot"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        raise DumpError("cannot read Herdr's session snapshot") from None
    aliases = {"claude": "claude-code", "agy": "antigravity"}
    selected = {}
    for pane in data.get("panes", []):
        if pane_id is not None and pane.get("pane_id") != pane_id:
            continue
        if pane.get("agent_status") in ("stopped", "exited"):
            continue
        session = pane.get("agent_session") or {}
        agent = session.get("agent", pane.get("agent"))
        agent = aliases.get(agent, agent)
        if session.get("kind") == "id" and isinstance(session.get("value"), str):
            selected.setdefault(agent, set()).add(session["value"])
    return selected


def _freeze(inp):
    """Read each source once. Conversion and raw retention use those same bytes."""
    loaded = [(s, s.reader(s.path)) for s in inp.sources]
    sources = [replace(s, reader=lambda path, snapshot=snap: snapshot) for s, snap in loaded]
    return replace(inp, sources=sources), loaded


def _identity(converter, inp, loaded):
    nid = inp.native_id
    if not nid:
        records = [(pos, base.section_2(rec)) for src, snap in loaded if src.role == "record" and src.events
                   for pos, rec in snap.records]
        nid = converter.native_id(records)
    nid = base.section_2(nid)
    main = next(s for s in inp.sources if s.key == "f1")
    return session_id(converter.HARNESS, native_id=nid, path=base.display_path(main.path))


def _unchanged(path, converter, loaded, unread=()):
    try:
        with path.open(encoding="utf-8") as stream:
            header = json.loads(stream.readline())
    except (OSError, ValueError):
        return False
    if not isinstance(header, dict):
        return False
    hashes = {src.key: hashlib.sha256(snap.data).hexdigest() for src, snap in loaded}
    files = header.get("files", {})
    try:
        listed = base.unread_entries(unread)
    except OSError:
        return False
    return (header.get("type") == "session" and header.get("format") == FORMAT
            and header.get("converter") == converter.CONVERTER and isinstance(files, dict)
            and hashes == {k: v.get("sha256") for k, v in files.items() if isinstance(v, dict)}
            and header.get("unread", []) == listed)


def _keep_raw(store, loaded, unread=()):
    blobs = [snapshot.data for _, snapshot in loaded] + [p.read_bytes() for p in unread]
    for data in blobs:
        digest = hashlib.sha256(data).hexdigest()
        out = store / "raw" / digest
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            out.write_bytes(data)
        elif hashlib.sha256(out.read_bytes()).hexdigest() != digest:
            raise DumpError("a retained raw source has the wrong hash")


def _self_sessions(converter, discovered):
    nid = converter.self_id() if hasattr(converter, "self_id") else None
    matches = [s for s in discovered if nid and s.native_id == nid]
    if matches:
        return matches
    if getattr(converter, "SELF_FROM_HERDR", False) and os.environ.get("HERDR_PANE_ID"):
        try:
            ids = herdr_sessions(os.environ["HERDR_PANE_ID"]).get(converter.HARNESS, set())
            matches = [s for s in discovered if s.native_id in ids]
            if matches:
                return matches
        except DumpError:
            pass
    if hasattr(converter, "select_self"):
        matches = converter.select_self(discovered, str(Path.cwd()))
        if matches:
            print(f"{converter.HARNESS}: --self fallback: newest session with recorded cwd equal to current directory", file=sys.stderr)
        return matches
    # Select on recorded cwd, never the converter's guessed or completed path.
    candidates = []
    cwd = str(Path.cwd())
    for found in discovered:
        try:
            snapshot = base.read_jsonl(found.path)
            meta = next((r.get("payload", {}) for _, r in snapshot.records if r.get("type") == "session_meta"), {})
            if meta.get("cwd") == cwd:
                candidates.append((found.path.stat().st_mtime_ns, str(found.path), found))
        except (OSError, ValueError):
            continue
    if candidates:
        print(f"{converter.HARNESS}: --self fallback: newest session with recorded cwd equal to current directory", file=sys.stderr)
        return [max(candidates, key=lambda item: item[:2])[2]]
    return []


def _calling_harness():
    exact = [name for name, converter in REGISTRY.items()
             if hasattr(converter, "self_id") and converter.self_id()]
    if len(exact) == 1:
        return exact[0]
    present = [name for name, converter in REGISTRY.items()
               if hasattr(converter, "caller_present") and converter.caller_present()]
    if not exact and len(present) == 1:
        return present[0]
    if not exact and os.environ.get("HERDR_PANE_ID"):
        try:
            names = set(herdr_sessions(os.environ["HERDR_PANE_ID"])) & REGISTRY.keys()
            if len(names) == 1:
                return next(iter(names))
        except DumpError:
            pass
    if len(REGISTRY) == 1:
        return next(iter(REGISTRY))
    raise DumpError("cannot identify one calling harness; use --harness NAME with --self")


def dump(store: Path, harness: str | None = None, self_only: bool = False,
         from_herdr: bool = False, keep_raw: bool = False, allow_inside_git: bool = False) -> int:
    store = store.expanduser()
    guard_store(store, allow_inside_git)
    if self_only and harness is None:
        harness = _calling_harness()
    selection = herdr_sessions() if from_herdr else None
    failed_any = False
    for name, converter in sorted(REGISTRY.items()):
        if harness is not None and name != harness:
            continue
        converted = skipped = failed = unmeasured = 0
        try:
            discovered = list(converter.discover())
            if self_only:
                chosen = _self_sessions(converter, discovered)
                if not chosen:
                    failed += 1
            elif selection is not None:
                ids = selection.get(name, set())
                chosen = [s for s in discovered if s.native_id in ids]
                failed += len(ids - {s.native_id for s in discovered})
            else:
                chosen = discovered
            # Empty paths must not trigger an adapter's discover-all fallback.
            if chosen and hasattr(converter, "selected_sessions"):
                inputs = iter(converter.selected_sessions(chosen))
            else:
                inputs = iter(base.sessions(converter, [s.path for s in chosen])) if chosen else iter(())
            while True:
                try:
                    inp = next(inputs)
                except StopIteration:
                    break
                except INPUT_ERRORS:
                    failed += 1
                    break
                try:
                    frozen, loaded = _freeze(inp)
                    sid = _identity(converter, frozen, loaded)
                    out = store / "sessions" / f"{sid}.jsonl"
                    guard_store(out, allow_inside_git)
                    unchanged = _unchanged(out, converter, loaded, frozen.unread)
                    if keep_raw:
                        _keep_raw(store, loaded, frozen.unread)
                    if unchanged:
                        skipped += 1
                    else:
                        lines = base.convert(converter, frozen)
                        base.write_session(lines, store)
                        converted += 1
                        measured = converter.CONVERTER.get("measured")
                        if measured is not None and lines[0]["harness"].get("version") not in measured:
                            unmeasured += 1
                except DumpError:
                    raise
                except INPUT_ERRORS:
                    failed += 1
        except DumpError:
            raise
        except INPUT_ERRORS:
            failed += 1
        # Sessions from harness versions the converter was not checked against (SPEC.md 3.4).
        extra = f" unmeasured={unmeasured}" if unmeasured else ""
        print(f"{name}: converted={converted} skipped={skipped} failed={failed}{extra}")
        failed_any |= failed > 0
    return int(failed_any)
