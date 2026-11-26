"""Harness converters. Add each finished adapter to REGISTRY."""

from .base import Converter
from . import claude_code, codex, opencode

REGISTRY: dict[str, Converter] = {"claude-code": claude_code, "codex": codex, "opencode": opencode}
