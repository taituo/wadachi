"""Harness converters. Add each finished adapter to REGISTRY."""

from .base import Converter
from . import antigravity, claude_code, codex, opencode

REGISTRY: dict[str, Converter] = {"antigravity": antigravity, "claude-code": claude_code, "codex": codex, "opencode": opencode}
