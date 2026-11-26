"""The `wadachi` command.

    wadachi validate PATH...            check session files or stores; exit 1 on any problem
    wadachi digest SESSION [--annotate] print each turn's digest, or digest annotations
    wadachi canonical [FILE]            rewrite JSON lines canonically (RFC 8785)
    wadachi convert HARNESS [PATH...] --store DIR [--hooks LOG]
    wadachi convert HARNESS --list      list discovered native ids, paths and sizes
    wadachi id session HARNESS (--native-id ID | --path PATH)
    wadachi id event SESSION_ID SRC
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .canonical import CanonicalError, dumps
from .convert import REGISTRY
from .convert.base import convert, display_path, sessions, write_session
from .digest import annotations, digests
from .ids import event_id, session_id
from .validate import validate_path, validate_session


def _validate(args: argparse.Namespace) -> int:
    problems = []
    for path in args.paths:
        problems += validate_path(path)
    for problem in problems:
        print(problem)
    if not args.quiet:
        print(f"{len(problems)} problem(s)" if problems else "ok", file=sys.stderr)
    return 1 if problems else 0


def _digest(args: argparse.Namespace) -> int:
    session = validate_session(args.session)
    if session.problems and not args.force:
        for problem in session.problems:
            print(problem, file=sys.stderr)
        print("the session is not valid; use --force to digest it anyway", file=sys.stderr)
        return 1
    try:
        if args.annotate:
            for ann in annotations(session.events):
                print(dumps(ann))
        else:
            for _, line in digests(session.events):
                print(line)
    except (ValueError, TypeError, KeyError) as err:
        print(f"cannot digest this session: {err}", file=sys.stderr)
        return 1
    return 0


def _canonical(args: argparse.Namespace) -> int:
    try:
        stream = open(args.file, encoding="utf-8") if args.file else sys.stdin
    except OSError as err:
        print(err, file=sys.stderr)
        return 1
    status = 0
    with stream:
        for n, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                sys.stdout.write(dumps(json.loads(line)) + "\n")
            except (ValueError, TypeError, CanonicalError) as err:
                print(f"line {n}: {err}", file=sys.stderr)
                status = 1
    return status


def _id(args: argparse.Namespace) -> int:
    try:
        if args.what == "session":
            print(session_id(args.harness, native_id=args.native_id, path=args.path))
        else:
            print(event_id(args.session_id, args.src))
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    return 0


def _convert(args: argparse.Namespace) -> int:
    converter = REGISTRY[args.harness]
    try:
        if args.list:
            for session in converter.discover():
                print(f"{session.native_id or ''}\t{display_path(session.path)}\t{session.size}")
        else:
            for session in sessions(converter, args.paths):
                print(write_session(convert(converter, session, args.hooks), args.store))
    except (OSError, ValueError, TypeError, sqlite3.Error) as err:
        print(f"cannot convert {args.harness}: {err}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wadachi", description="Tools for wadachi session records.")
    parser.add_argument("--version", action="version", version=f"wadachi {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check session files or stores")
    p.add_argument("paths", nargs="+")
    p.add_argument("-q", "--quiet", action="store_true", help="print problems only")
    p.set_defaults(func=_validate)

    p = sub.add_parser("digest", help="one counted line per turn")
    p.add_argument("session")
    p.add_argument("--annotate", action="store_true", help="print digest annotations as JSON lines")
    p.add_argument("--force", action="store_true", help="digest even if the session is not valid")
    p.set_defaults(func=_digest)

    p = sub.add_parser("canonical", help="rewrite JSON lines canonically")
    p.add_argument("file", nargs="?")
    p.set_defaults(func=_canonical)

    p = sub.add_parser("convert", help="convert harness records to wadachi")
    p.add_argument("harness")
    p.add_argument("paths", type=Path, nargs="*")
    p.add_argument("--store", type=Path)
    p.add_argument("--hooks", type=Path)
    p.add_argument("--list", action="store_true", help="list discovered native ids, paths and sizes")
    p.set_defaults(func=_convert)

    p = sub.add_parser("id", help="derive a session or event id")
    ids = p.add_subparsers(dest="what", required=True)
    q = ids.add_parser("session")
    q.add_argument("harness")
    group = q.add_mutually_exclusive_group(required=True)
    group.add_argument("--native-id")
    group.add_argument("--path")
    q = ids.add_parser("event")
    q.add_argument("session_id")
    q.add_argument("src", help="the event's src, such as f1:@abc#/content/2")
    p.set_defaults(func=_id)

    args = parser.parse_args(argv)
    if args.command == "convert":
        if args.harness not in REGISTRY:
            parser.error(f"unknown harness: {args.harness}")
        if args.list and (args.paths or args.store is not None or args.hooks is not None):
            parser.error("--list cannot be combined with paths, --store or --hooks")
        if not args.list and args.store is None:
            parser.error("convert requires --store DIR")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
