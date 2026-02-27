"""Approximate per-invocation cost estimates."""

from __future__ import annotations

# Rough cost estimates per invocation by model name (USD)
# These are approximations; real cost depends on token usage.
_COST_PER_INVOCATION: dict[str, float] = {
    "claude": 0.50,
    "codex": 0.30,
    "gemini": 0.20,
}

_DEFAULT_COST = 0.40


def estimate_cost(model_name: str) -> float:
    """Return approximate cost in USD for one model invocation."""
    return _COST_PER_INVOCATION.get(model_name, _DEFAULT_COST)
