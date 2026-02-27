"""JSON Schema validation for model outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

_SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"
_schema_cache: dict[str, dict] = {}


def _load_schema(schema_name: str) -> dict:
    """Load and cache a JSON schema by name (e.g. 'proposal')."""
    if schema_name not in _schema_cache:
        path = _SCHEMAS_DIR / f"{schema_name}.schema.json"
        _schema_cache[schema_name] = json.loads(path.read_text(encoding="utf-8"))
    return _schema_cache[schema_name]


def validate(data: Any, schema_name: str) -> list[str]:
    """Validate data against a named schema. Returns list of error messages (empty = valid)."""
    schema = _load_schema(schema_name)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    return [f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in errors]


def validate_or_raise(data: Any, schema_name: str) -> None:
    """Validate data against a named schema, raising ValueError on failure."""
    errors = validate(data, schema_name)
    if errors:
        raise ValueError(f"Schema validation failed for '{schema_name}':\n" + "\n".join(errors))
