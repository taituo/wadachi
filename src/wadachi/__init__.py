"""Wadachi: a neutral record format for coding agent sessions.

The reference tools: canonical serialisation (RFC 8785), id derivation,
validation and digests. See SPEC.md for the format itself.
"""

__version__ = "0.1.0"
FORMAT = "wadachi/0.1"

from .canonical import dumps  # noqa: E402
from .ids import event_id, session_id  # noqa: E402

__all__ = ["FORMAT", "__version__", "dumps", "event_id", "session_id"]
