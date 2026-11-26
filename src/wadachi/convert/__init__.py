"""Harness converters. Add each finished adapter to REGISTRY."""

from .base import Converter

REGISTRY: dict[str, Converter] = {}
