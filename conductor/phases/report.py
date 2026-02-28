"""Phase 6: REPORT - Generate final or blocked report."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from conductor.config import Config
from conductor.models.invoker import invoke_model_safe
from conductor.prompt_renderer import render_prompt
from conductor.redaction import redact, truncate_log
from conductor.schema_validator import validate
from conductor.state import RunState, persist_state, save_json

log = logging.getLogger(__name__)

_FINAL_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "final_report.schema.json"
_BLOCKED_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "blocked_report.schema.json"


def run_report(
    state: RunState,
    config: Config,
    master_plan: Optional[dict[str, Any]],
    context: dict[str, Any],
    run_dir: Path,
    dry_run: bool = False,
    dry_run_response: Optional[dict] = None,
) -> dict:
    """Execute the REPORT phase.

    Generates final_report (SUCCESS/PARTIAL) or blocked_report depending on state.
    """
    log.info("=== PHASE 6: REPORT ===")

    # Determine status first so PARTIAL and BLOCKED can diverge cleanly.
    if state.final_status in {"SUCCESS", "PARTIAL", "BLOCKED"}:
        status = state.final_status
    elif state.breaker_reason:
        status = "BLOCKED"
    else:
        status = "SUCCESS"

    is_blocked = status == "BLOCKED"
    schema_name = "blocked_report" if is_blocked else "final_report"
    schema_path = _BLOCKED_SCHEMA if is_blocked else _FINAL_SCHEMA

    test_results = context.get("last_test_output", "(no test output)")
    if config.redact_before_model:
        test_results = redact(truncate_log(test_results))

    # Collect artifact links
    artifacts_dir = run_dir / "artifacts"
    artifact_links = []
    if artifacts_dir.exists():
        for p in sorted(artifacts_dir.rglob("*")):
            if p.is_file():
                artifact_links.append(str(p.relative_to(run_dir)))

    variables = {
        "RUN_ID": state.run_id,
        "MASTER_PLAN_JSON": json.dumps(master_plan, indent=2) if master_plan else "(no master plan)",
        "CURRENT_STATE": json.dumps({
            "status": status,
            "phase": state.phase,
            "breaker_reason": state.breaker_reason,
            "milestones_completed": state.milestone_index,
            "build_iterations_used": state.build_iteration,
            "review_loops_used": state.review_loops_used,
            "cost_usd": round(state.approx_cost_usd, 2),
        }),
        "TEST_RESULTS": test_results,
        "ARTIFACT_LINKS": json.dumps(artifact_links),
    }
    prompt = render_prompt("reporter", variables)

    result, cost, err = invoke_model_safe(
        model_name=config.reviewer_model.name,  # Use reviewer model for reporting
        prompt=prompt,
        schema_path=schema_path,
        dry_run=dry_run,
        dry_run_response=dry_run_response,
    )
    state.tool_calls_used += 1
    state.approx_cost_usd += cost

    if err or result is None:
        log.error("Reporter failed: %s", err)
        # Generate a minimal report ourselves
        if is_blocked:
            result = {
                "kind": "blocked_report",
                "run_id": state.run_id,
                "status": "BLOCKED",
                "block_reason": state.breaker_reason or "Unknown",
                "evidence": [state.breaker_reason or "No evidence available"],
                "what_was_tried": ["Automated build pipeline"],
                "spec_change_options": [{
                    "option": "Review and retry with adjusted parameters",
                    "pros": ["May resolve the issue"],
                    "cons": ["Requires manual intervention"],
                    "impact": "Depends on root cause",
                }],
            }
        else:
            result = {
                "kind": "final_report",
                "run_id": state.run_id,
                "status": status,
                "summary": f"Run {state.run_id} completed with status {status}.",
                "how_to_run": ["See artifacts for details"],
                "tests_ran": ["See test logs"],
                "artifacts": {
                    "screenshots": [],
                    "logs": [str(p) for p in (run_dir / "artifacts" / "logs").glob("*")] if (run_dir / "artifacts" / "logs").exists() else [],
                    "test_reports": [str(p) for p in (run_dir / "artifacts" / "tests").glob("*")] if (run_dir / "artifacts" / "tests").exists() else [],
                    "branches": [],
                },
                "known_limitations": [],
                "next_steps": [],
            }

    # Save report
    report_filename = "blocked_report.json" if is_blocked else "final_report.json"
    save_json(run_dir / "artifacts" / report_filename, result)
    log.info("Report saved: %s (status=%s)", report_filename, status)

    # Print human-friendly summary
    if is_blocked:
        print(f"\n{'='*60}")
        print(f"RUN BLOCKED: {state.run_id}")
        print(f"Reason: {result.get('block_reason', 'unknown')}")
        print(f"{'='*60}\n")
    else:
        print(f"\n{'='*60}")
        print(f"RUN COMPLETE: {state.run_id} — {status}")
        print(f"Summary: {result.get('summary', 'N/A')}")
        print(f"{'='*60}\n")

    state.phase = "DONE"
    persist_state(state, run_dir / "state.json")

    return {"report": result, "status": status}
