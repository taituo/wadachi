"""Harness converters. Add each finished adapter to REGISTRY."""

from .base import Converter
from . import codex

REGISTRY: dict[str, Converter] = {"codex": codex}
