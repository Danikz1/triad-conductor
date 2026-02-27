"""Phase emojis, status formatting, and report formatting for Telegram messages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


PHASE_EMOJI: Dict[str, str] = {
    "INTAKE": "\u2709\ufe0f",       # envelope
    "PROPOSE": "\U0001f4a1",        # lightbulb
    "SYNTHESIZE": "\U0001f9e9",     # puzzle
    "BUILD": "\U0001f528",          # hammer
    "CROSS_CHECK": "\U0001f50d",    # magnifying glass
    "OPTIMIZE": "\u26a1",           # lightning
    "REPORT": "\U0001f4cb",         # clipboard
    "DONE": "\u2705",               # check mark
    "PAUSE_BLOCKED": "\u23f8\ufe0f", # pause
    "STUCK_REPLAN": "\U0001f504",   # arrows
    "TOURNAMENT": "\u2694\ufe0f",   # swords
}


def phase_label(phase: str) -> str:
    """Return emoji + phase name."""
    emoji = PHASE_EMOJI.get(phase, "\u2753")
    return f"{emoji} {phase}"


def format_status(state: Dict[str, Any]) -> str:
    """Format a state dict into a readable Telegram status message."""
    phase = state.get("phase", "UNKNOWN")
    run_id = state.get("run_id", "?")
    milestone = state.get("milestone_index", 0)
    build_iter = state.get("build_iteration", 0)
    cost = state.get("approx_cost_usd", 0.0)
    tool_calls = state.get("tool_calls_used", 0)
    started_at = state.get("started_at", 0)

    import time
    elapsed_s = time.time() - started_at if started_at else 0
    elapsed_min = elapsed_s / 60.0

    lines = [
        f"<b>Run:</b> <code>{run_id}</code>",
        f"<b>Phase:</b> {phase_label(phase)}",
        f"<b>Milestone:</b> {milestone}",
        f"<b>Build iteration:</b> {build_iter}",
        f"<b>Tool calls:</b> {tool_calls}",
        f"<b>Cost:</b> ${cost:.2f}",
        f"<b>Elapsed:</b> {elapsed_min:.1f} min",
    ]
    return "\n".join(lines)


def format_phase_change(old_phase: str, new_phase: str, state: Dict[str, Any]) -> str:
    """Format a phase transition notification."""
    cost = state.get("approx_cost_usd", 0.0)
    return (
        f"{phase_label(old_phase)} \u2192 {phase_label(new_phase)}\n"
        f"Cost so far: ${cost:.2f}"
    )


def format_final_report(state: Dict[str, Any]) -> str:
    """Format the final completion message."""
    run_id = state.get("run_id", "?")
    phase = state.get("phase", "?")
    cost = state.get("approx_cost_usd", 0.0)
    tool_calls = state.get("tool_calls_used", 0)

    import time
    started_at = state.get("started_at", 0)
    elapsed_s = time.time() - started_at if started_at else 0
    elapsed_min = elapsed_s / 60.0

    lines = [
        f"\u2705 <b>Run complete!</b>",
        f"",
        f"<b>Run ID:</b> <code>{run_id}</code>",
        f"<b>Final phase:</b> {phase_label(phase)}",
        f"<b>Total cost:</b> ${cost:.2f}",
        f"<b>Tool calls:</b> {tool_calls}",
        f"<b>Duration:</b> {elapsed_min:.1f} min",
    ]
    return "\n".join(lines)
