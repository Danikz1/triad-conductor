"""Tests for conductor.models.parsers module."""

import pytest

from conductor.models.parsers import extract_json


def test_extract_json_direct():
    text = '{"kind": "proposal", "value": 42}'
    result = extract_json(text)
    assert result == {"kind": "proposal", "value": 42}


def test_extract_json_code_fence():
    text = """Here is my response:
```json
{"kind": "test", "data": true}
```
Done."""
    result = extract_json(text)
    assert result == {"kind": "test", "data": True}


def test_extract_json_embedded_object():
    text = """Some preamble text
{"kind": "build_update", "iteration": 1, "milestone_id": "M1", "summary": "Did stuff", "changes_made": ["x"], "next_actions": ["y"], "self_reported_risks": []}
trailing text"""
    result = extract_json(text)
    assert result["kind"] == "build_update"


def test_extract_json_with_whitespace():
    text = """
    {
        "kind": "review",
        "value": 123
    }
    """
    result = extract_json(text)
    assert result["kind"] == "review"


def test_extract_json_array():
    text = '[{"a": 1}, {"b": 2}]'
    result = extract_json(text)
    assert isinstance(result, list)
    assert len(result) == 2


def test_extract_json_failure():
    with pytest.raises(ValueError, match="Could not extract JSON"):
        extract_json("This is not JSON at all")


def test_extract_json_nested_braces():
    text = '{"outer": {"inner": {"deep": true}}, "list": [1, 2, 3]}'
    result = extract_json(text)
    assert result["outer"]["inner"]["deep"] is True
