"""Template loading and {{PLACEHOLDER}} substitution for prompt files."""

from __future__ import annotations

import re
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt template by name (e.g. 'proposer' loads prompts/proposer.md)."""
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def render(template: str, variables: dict[str, str]) -> str:
    """Replace all {{VAR}} placeholders in the template with values from variables.
    Missing variables are left as-is."""
    def _replace(m: re.Match) -> str:
        key = m.group(1)
        return variables.get(key, m.group(0))
    return re.sub(r"\{\{(\w+)\}\}", _replace, template)


def render_prompt(name: str, variables: dict[str, str]) -> str:
    """Load a named prompt and substitute variables."""
    template = load_prompt(name)
    return render(template, variables)
