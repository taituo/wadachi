"""The JSON Schemas, shipped with the package so the tools and the spec share one source."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files


@cache
def load(name: str) -> dict:
    """Load `record` or `annotation`."""
    return json.loads(files(__package__).joinpath(f"{name}.schema.json").read_text("utf-8"))
