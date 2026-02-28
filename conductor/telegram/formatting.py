"""Phase emojis, status formatting, and report formatting for Telegram messages."""

from __future__ import annotations

import html
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


def format_heartbeat(
    state: Dict[str, Any],
    *,
    last_activity: str = "",
    state_age_seconds: Optional[float] = None,
) -> str:
    """Format periodic heartbeat while run stays in same phase."""
    run_id = state.get("run_id", "?")
    phase = state.get("phase", "UNKNOWN")
    cost = state.get("approx_cost_usd", 0.0)
    tool_calls = state.get("tool_calls_used", 0)
    started_at = state.get("started_at", 0)

    import time
    elapsed_s = time.time() - started_at if started_at else 0
    elapsed_min = elapsed_s / 60.0

    lines = [
        "\u23f1\ufe0f <b>Heartbeat</b>",
        f"<b>Run:</b> <code>{html.escape(str(run_id))}</code>",
        f"<b>Phase:</b> {phase_label(str(phase))}",
        f"<b>Cost so far:</b> ${float(cost):.2f}",
        f"<b>Tool calls:</b> {int(tool_calls)}",
        f"<b>Elapsed:</b> {elapsed_min:.1f} min",
    ]

    if state_age_seconds is not None:
        lines.append(f"<b>State age:</b> {max(0.0, state_age_seconds):.0f}s")

    if last_activity:
        lines.append(f"<b>Latest activity:</b> <code>{html.escape(last_activity)}</code>")

    return "\n".join(lines)


def format_publish_report(report: Dict[str, Any]) -> str:
    """Format post-run publishing results (description update + GitHub push)."""
    project_root = html.escape(str(report.get("project_root") or "n/a"))
    description_path = html.escape(str(report.get("description_path") or "n/a"))
    status = html.escape(str(report.get("run_status") or "UNKNOWN"))
    github_url = html.escape(str(report.get("github_url") or "n/a"))

    lines = [
        "\U0001f4e6 <b>Project Publish Report</b>",
        f"<b>Status:</b> <code>{status}</code>",
        f"<b>Project root:</b> <code>{project_root}</code>",
        f"<b>Description:</b> <code>{description_path}</code>",
    ]

    if report.get("description_updated"):
        lines.append("<b>Description update:</b> ✅ updated")
    else:
        lines.append("<b>Description update:</b> ⚠️ skipped")

    if report.get("github_created"):
        lines.append("<b>GitHub repo:</b> ✅ created")
    elif report.get("github_checked"):
        lines.append("<b>GitHub repo:</b> ✅ already exists")
    else:
        lines.append("<b>GitHub repo:</b> ⚠️ not created")

    if report.get("github_pushed"):
        lines.append("<b>Git push:</b> ✅ pushed")
    else:
        lines.append("<b>Git push:</b> ⚠️ not pushed")

    if github_url != "n/a":
        lines.append(f"<b>Remote:</b> {github_url}")

    errors = report.get("errors") or []
    if errors:
        lines.append("")
        lines.append("<b>Notes:</b>")
        for err in errors[:5]:
            lines.append(f"- {html.escape(str(err))}")

    return "\n".join(lines)


def format_stuck_alert(
    state: Dict[str, Any],
    *,
    phase_age_seconds: float,
    state_age_seconds: Optional[float],
    last_activity: str,
) -> str:
    """Format alert for prolonged phase/no fresh state updates."""
    run_id = html.escape(str(state.get("run_id", "?")))
    phase = html.escape(str(state.get("phase", "UNKNOWN")))
    lines = [
        "\u26a0\ufe0f <b>Stuck Alert</b>",
        f"<b>Run:</b> <code>{run_id}</code>",
        f"<b>Phase:</b> {phase_label(phase)}",
        f"<b>Time in phase:</b> {max(0.0, phase_age_seconds):.0f}s",
    ]
    if state_age_seconds is not None:
        lines.append(f"<b>State age:</b> {max(0.0, state_age_seconds):.0f}s")
    if last_activity:
        lines.append(f"<b>Latest activity:</b> <code>{html.escape(last_activity)}</code>")
    return "\n".join(lines)


def format_health_report(health: Dict[str, Any]) -> str:
    """Format a /health snapshot."""
    run_id = html.escape(str(health.get("run_id") or "?"))
    phase = html.escape(str(health.get("phase") or "UNKNOWN"))
    queue_depth = int(health.get("queue_depth", 0))
    phase_age = float(health.get("phase_age_seconds", 0.0))
    state_age = health.get("state_age_seconds")
    stuck = bool(health.get("is_stuck", False))
    threshold = float(health.get("stuck_threshold_seconds", 0.0))

    lines = [
        "\U0001fa7a <b>Health</b>",
        f"<b>Run:</b> <code>{run_id}</code>",
        f"<b>Phase:</b> {phase_label(phase)}",
        f"<b>Phase age:</b> {max(0.0, phase_age):.0f}s",
        f"<b>Queue depth:</b> {queue_depth}",
        f"<b>Stuck threshold:</b> {max(0.0, threshold):.0f}s",
        f"<b>Stuck:</b> {'yes' if stuck else 'no'}",
    ]
    if state_age is not None:
        lines.append(f"<b>State age:</b> {max(0.0, float(state_age)):.0f}s")
    last_activity = str(health.get("last_activity") or "")
    if last_activity:
        lines.append(f"<b>Latest activity:</b> <code>{html.escape(last_activity)}</code>")
    return "\n".join(lines)


def format_logs_report(run_id: str, lines: list[str]) -> str:
    """Format /logs output with a bounded <pre> block."""
    escaped_lines = [html.escape(line) for line in lines]
    payload = "\n".join(escaped_lines).strip()
    if not payload:
        payload = "(no logs yet)"
    # Keep comfortably below Telegram's 4096 message limit.
    payload = payload[-3200:]
    return (
        "\U0001f4dc <b>Recent Logs</b>\n"
        f"<b>Run:</b> <code>{html.escape(run_id)}</code>\n"
        f"<pre>{payload}</pre>"
    )
