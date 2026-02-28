"""Phase 5: HANDOFF — convert approved spec to task.md + config.yaml for Conductor."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from conductor.state import save_json

log = logging.getLogger(__name__)

# Complexity-scaled config limits
COMPLEXITY_LIMITS = {
    "S":  {"max_wall_time_minutes": 45,  "max_total_cost_usd": 10, "max_total_tool_calls": 100},
    "M":  {"max_wall_time_minutes": 90,  "max_total_cost_usd": 25, "max_total_tool_calls": 200},
    "L":  {"max_wall_time_minutes": 120, "max_total_cost_usd": 40, "max_total_tool_calls": 300},
    "XL": {"max_wall_time_minutes": 180, "max_total_cost_usd": 60, "max_total_tool_calls": 400},
}


def generate_task_md(spec: dict) -> str:
    """Convert a refined/approved spec into a structured task.md for conductor."""
    lines = [
        f"# {spec.get('project_name', 'Untitled Project')}",
        "",
        f"> {spec.get('one_liner', '')}",
        "",
        "## Problem",
        spec.get("problem_statement", "(not specified)"),
        "",
        "## Requirements",
        "",
        "### MUST",
    ]

    reqs = spec.get("requirements", {})
    for r in reqs.get("must", []):
        lines.append(f"- **{r.get('id', '?')}**: {r.get('text', r.get('requirement', ''))}")
    lines.append("")

    if reqs.get("should"):
        lines.append("### SHOULD")
        for r in reqs["should"]:
            lines.append(f"- **{r.get('id', '?')}**: {r.get('text', r.get('requirement', ''))}")
        lines.append("")

    if reqs.get("could"):
        lines.append("### COULD")
        for r in reqs["could"]:
            lines.append(f"- **{r.get('id', '?')}**: {r.get('text', r.get('requirement', ''))}")
        lines.append("")

    if reqs.get("wont"):
        lines.append("### WON'T (out of scope)")
        for r in reqs["wont"]:
            lines.append(f"- **{r.get('id', '?')}**: {r.get('text', r.get('requirement', ''))}")
        lines.append("")

    lines.append("## Success Criteria")
    for c in spec.get("success_criteria", []):
        lines.append(f"- {c}")
    lines.append("")

    lines.append("## Risks")
    for r in spec.get("risks", []):
        lines.append(f"- [{r.get('severity', '?')}] {r.get('risk', '')}: {r.get('mitigation', '')}")
    lines.append("")

    tech = spec.get("suggested_tech_stack")
    if tech:
        lines.append("## Tech Stack")
        lines.append(f"- Language: {tech.get('language', '?')}")
        if tech.get("key_libraries"):
            lines.append(f"- Libraries: {', '.join(tech['key_libraries'])}")
        lines.append("")

    lines.append(f"## Estimated Complexity: {spec.get('estimated_complexity', '?')}")
    lines.append(f"## Estimated Milestones: {spec.get('estimated_milestones', '?')}")
    lines.append("")

    return "\n".join(lines)


def generate_config_yaml(spec: dict, base_config_path: Path) -> str:
    """Generate a config YAML scaled to the spec's estimated complexity."""
    import yaml

    complexity = spec.get("estimated_complexity", "M")
    limits = COMPLEXITY_LIMITS.get(complexity, COMPLEXITY_LIMITS["M"])

    # Read base config and override limits
    if base_config_path.exists():
        base = yaml.safe_load(base_config_path.read_text(encoding="utf-8"))
    else:
        base = {}

    if "run_limits" not in base:
        base["run_limits"] = {}
    base["run_limits"].update(limits)

    return yaml.dump(base, default_flow_style=False, sort_keys=False)


def create_approved_spec(
    refined_spec: dict,
    user_id: int,
    resolved_decisions: dict[str, str] | None = None,
    confirmed_assumptions: list[dict] | None = None,
) -> dict[str, Any]:
    """Freeze a refined spec into an approved_spec."""
    return {
        "kind": "approved_spec",
        "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "approved_by_user_id": user_id,
        "spec_version": refined_spec.get("version", 1),
        "project_name": refined_spec.get("project_name", "Untitled"),
        "one_liner": refined_spec.get("one_liner", ""),
        "problem_statement": refined_spec.get("problem_statement", ""),
        "requirements": refined_spec.get("requirements", {}),
        "resolved_decisions": resolved_decisions or {},
        "confirmed_assumptions": confirmed_assumptions or [],
        "success_criteria": refined_spec.get("success_criteria", []),
        "risks": refined_spec.get("risks", []),
        "estimated_complexity": refined_spec.get("estimated_complexity", "M"),
        "estimated_milestones": refined_spec.get("estimated_milestones", 1),
        "suggested_tech_stack": refined_spec.get("suggested_tech_stack"),
    }


def run_handoff(
    refined_spec: dict,
    user_id: int,
    run_dir: Path,
    base_config_path: Path,
    resolved_decisions: dict[str, str] | None = None,
    confirmed_assumptions: list[dict] | None = None,
) -> dict[str, Any]:
    """Execute the handoff: freeze spec, generate task.md + config.yaml.

    Returns {"task_path": Path, "config_path": Path, "approved_spec": dict}.
    """
    log.info("=== TRIAD ARCHITECT: HANDOFF ===")

    # Create approved spec
    approved = create_approved_spec(
        refined_spec, user_id, resolved_decisions, confirmed_assumptions,
    )
    save_json(run_dir / "artifacts" / "approved_spec.json", approved)

    # Generate task.md
    task_md = generate_task_md(approved)
    task_path = run_dir / "artifacts" / "approved_spec.md"
    task_path.write_text(task_md, encoding="utf-8")
    log.info("Generated task.md: %s", task_path)

    # Generate config
    config_yaml = generate_config_yaml(refined_spec, base_config_path)
    config_path = run_dir / "artifacts" / "config_scaled.yaml"
    config_path.write_text(config_yaml, encoding="utf-8")
    log.info("Generated config: %s", config_path)

    return {
        "task_path": task_path,
        "config_path": config_path,
        "approved_spec": approved,
    }
