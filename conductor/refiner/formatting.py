"""Telegram message formatting for Triad Architect specs."""

from __future__ import annotations

from typing import Any


def format_refined_spec(spec: dict[str, Any]) -> str:
    """Format a refined_spec for Telegram (HTML)."""
    lines = [
        f"<b>Refined Spec v{spec.get('version', '?')}: \"{spec.get('project_name', '?')}\"</b>",
        "",
        f"<i>{spec.get('one_liner', '')}</i>",
        "",
    ]

    # Requirements
    reqs = spec.get("requirements", {})

    must = reqs.get("must", [])
    if must:
        consensus_label = ""
        lines.append("<b>--- Requirements ---</b>")
        lines.append("<b>MUST:</b>")
        for r in must:
            c = r.get("consensus", "")
            tag = f" ({c})" if c else ""
            lines.append(f"  {r.get('id', '?')}: {r.get('text', '')}{tag}")

    should = reqs.get("should", [])
    if should:
        lines.append("<b>SHOULD:</b>")
        for r in should:
            lines.append(f"  {r.get('id', '?')}: {r.get('text', '')}")

    could = reqs.get("could", [])
    if could:
        lines.append("<b>COULD:</b>")
        for r in could:
            lines.append(f"  {r.get('id', '?')}: {r.get('text', '')}")

    wont = reqs.get("wont", [])
    if wont:
        lines.append("<b>WON'T:</b>")
        for r in wont:
            lines.append(f"  {r.get('id', '?')}: {r.get('text', '')}")

    lines.append("")

    # Decisions needed
    decisions = spec.get("decisions_needed", [])
    if decisions:
        lines.append("<b>--- Decisions Needed ---</b>")
        for d in decisions:
            lines.append(f"  {d['id']}: {d['question']}")
            lines.append(f"   Recommendation: {d.get('recommendation', '?')}")
            lines.append(f"   Reply \"{d['id']}: yes\" or \"{d['id']}: no\" or \"{d['id']}: &lt;your answer&gt;\"")
        lines.append("")

    # Assumptions
    assumptions = [a for a in spec.get("assumptions", []) if a.get("needs_confirmation")]
    if assumptions:
        lines.append("<b>--- Assumptions ---</b>")
        for a in assumptions:
            lines.append(f"  {a['id']}: {a['assumption']} (needs confirmation)")
            lines.append(f"   Reply \"{a['id']}: correct\" or \"{a['id']}: &lt;correction&gt;\"")
        lines.append("")

    # Estimate
    lines.append("<b>--- Estimate ---</b>")
    lines.append(
        f"Complexity: {spec.get('estimated_complexity', '?')} | "
        f"Milestones: {spec.get('estimated_milestones', '?')}"
    )
    lines.append("")

    # Convergence hint
    if not decisions and not assumptions:
        lines.append("Spec looks converged. Reply <code>approve</code> to start development.")
    else:
        lines.append("Reply <code>approve</code> to proceed, or send feedback.")

    return "\n".join(lines)


def format_approval_confirmation(spec: dict[str, Any], dev_run_id: str | None = None) -> str:
    """Format the approval + handoff confirmation message."""
    lines = [
        f"<b>Spec approved: \"{spec.get('project_name', '?')}\"</b>",
        "",
        f"Complexity: {spec.get('estimated_complexity', '?')}",
        f"Milestones: {spec.get('estimated_milestones', '?')}",
    ]
    if dev_run_id:
        lines.append(f"Development run: <code>{dev_run_id}</code>")
        lines.append("I'll send phase transition updates as the conductor progresses.")
    else:
        lines.append("Use /run to start development.")
    return "\n".join(lines)


def format_refiner_status(state: dict[str, Any], phase: str, version: int) -> str:
    """Format current refiner status."""
    return (
        f"<b>Triad Architect Status</b>\n"
        f"Phase: {phase}\n"
        f"Spec version: v{version}\n"
        f"Cost so far: ${state.get('approx_cost_usd', 0):.2f}\n"
        f"Tool calls: {state.get('tool_calls_used', 0)}"
    )
