"""JSON extraction from model stdout with fallback strategies."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from model output text.

    Tries multiple strategies:
    1. Direct JSON parse of the full text
    2. Extract from code fences (```json ... ```)
    3. Find outermost { ... } pair
    4. Find outermost [ ... ] pair (for arrays)

    Raises ValueError if no JSON can be extracted.
    """
    text = text.strip()

    # Strategy 1: Direct parse
    try:
        result = json.loads(text)
        if isinstance(result, (dict, list)):
            return result
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from code fences
    fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
    if fence_match:
        try:
            result = json.loads(fence_match.group(1).strip())
            if isinstance(result, (dict, list)):
                return result
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find outermost { ... }
    obj = _find_balanced(text, "{", "}")
    if obj is not None:
        try:
            result = json.loads(obj)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Strategy 4: Find outermost [ ... ]
    arr = _find_balanced(text, "[", "]")
    if arr is not None:
        try:
            result = json.loads(arr)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from model output (first 200 chars): {text[:200]}")


def _find_balanced(text: str, open_ch: str, close_ch: str) -> str | None:
    """Find the outermost balanced pair of open/close characters."""
    start = text.find(open_ch)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None
