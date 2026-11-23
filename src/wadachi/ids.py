"""Session and event ids (SPEC.md section 7), and the key escaping of section 6."""

from __future__ import annotations

import hashlib
import unicodedata


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def session_id(harness: str, native_id: str | None = None, path: str | None = None) -> str:
    """The id of a session.

    From the harness's own session id when it has one; otherwise from the path
    of the session's `f1` source, as written in the header's files.
    """
    if not harness:
        raise ValueError("a session id needs the harness's name")
    if native_id:
        return "s_" + _h(harness + "\n" + native_id)
    if path:
        return "s_" + _h(harness + "\n" + "path:" + path)
    raise ValueError("a session id needs a native id or the path of f1")


def event_id(session: str, src: str) -> str:
    """The id of an event: from its session's id and its `src`, such as `f1:@abc#/content/2`."""
    return "e_" + _h(session + "\n" + src)


def escape_key(key: str) -> str:
    """Write a source's record key for use after `@` in `src` (SPEC.md section 6)."""
    out = []
    for ch in key:
        if ch in "%#" or ch.isspace() or unicodedata.category(ch) == "Cc":
            out.append("".join(f"%{b:02X}" for b in ch.encode("utf-8")))
        else:
            out.append(ch)
    return "".join(out)


def split_src(src: str) -> tuple[str, str]:
    """Split `f1:88123#/a` into (`f1`, `88123#/a`)."""
    key, sep, position = src.partition(":")
    if not sep:
        raise ValueError(f"src {src!r} has no colon")
    return key, position
