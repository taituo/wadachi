"""Harness converters. Add each finished adapter to REGISTRY."""

from .base import Converter
from . import codex, opencode

REGISTRY: dict[str, Converter] = {"codex": codex, "opencode": opencode}
