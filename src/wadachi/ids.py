"""Session and event ids, derived as SPEC.md section 7 defines."""

from __future__ import annotations

import hashlib


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def session_id(harness: str, native_id: str | None = None, path: str | None = None) -> str:
    """The id of a session.

    From the harness's own session id when it has one; otherwise from the path
    of the session's first record source, as written in the header's files.
    """
    if native_id:
        return "s_" + _h(harness + "\n" + native_id)
    if path:
        return "s_" + _h(harness + "\n" + "path:" + path)
    raise ValueError("a session id needs a native id or a record path")


def event_id(session: str, source_path: str, position: str, event_type: str) -> str:
    """The id of an event.

    `position` is the part of `src` after the file key and colon, including
    any JSON Pointer: for `f1:@abc#/message/content/2` it is
    `@abc#/message/content/2`.
    """
    return "e_" + _h(session + "\n" + source_path + "\n" + position + "\n" + event_type)


def split_src(src: str) -> tuple[str, str]:
    """Split `f1:88123#/a` into (`f1`, `88123#/a`)."""
    key, sep, position = src.partition(":")
    if not sep:
        raise ValueError(f"src {src!r} has no colon")
    return key, position
