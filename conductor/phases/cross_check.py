"""Phase 4: CROSS_CHECK - Reviewer + QA, loop back if issues."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from conductor.config import Config
from conductor.git_ops import get_diff
from conductor.models.invoker import invoke_model_safe
from conductor.prompt_renderer import render_prompt
from conductor.redaction import redact, truncate_log
from conductor.schema_validator import validate
from conductor.state import RunState, PhaseLimits, Limits, persist_state, save_json, check_breakers

log = logging.getLogger(__name__)

_REVIEW_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "review.schema.json"
_QA_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "qa.schema.json"


def run_cross_check(
    state: RunState,
    config: Config,
    master_plan: dict[str, Any],
    context: dict[str, Any],
    run_dir: Path,
    limits: Limits,
    phase_limits: PhaseLimits,
    dry_run: bool = False,
    dry_run_review: Optional[dict] = None,
    dry_run_qa: Optional[dict] = None,
) -> dict:
    """Execute the CROSS_CHECK phase.

    Invokes reviewer and QA models. If verdicts are clean → OPTIMIZE/REPORT.
    If issues → loop back to BUILD (up to max_review_loops).
    """
    log.info("=== PHASE 4: CROSS_CHECK ===")

    branches = context["branches"]
    project_root = context.get("project_root", Path.cwd())
    diff = get_diff(project_root, branches["anchor"], branches["integrate"])
    test_results = context.get("last_test_output", "(no test output)")

    if config.redact_before_model:
        diff = redact(diff)
        test_results = redact(truncate_log(test_results))

    # --- Reviewer ---
    review_vars = {
        "MASTER_PLAN_JSON": json.dumps(master_plan, indent=2),
        "DIFF": diff,
        "TEST_RESULTS": test_results,
        "SCREENSHOT_INDEX": "(none)",
    }
    review_prompt = render_prompt("reviewer", review_vars)

    review_result, cost, err = invoke_model_safe(
        model_name=config.reviewer_model.name,
        prompt=review_prompt,
        schema_path=_REVIEW_SCHEMA,
        dry_run=dry_run,
        dry_run_response=dry_run_review,
    )
    state.tool_calls_used += 1
    state.approx_cost_usd += cost

    if err:
        log.error("Reviewer failed: %s", err)
        review_result = None

    if review_result:
        val_errors = validate(review_result, "review")
        if val_errors:
            log.warning("Review schema validation errors: %s", val_errors)
        save_json(run_dir / "artifacts" / "review.json", review_result)

    # --- QA ---
    qa_vars = {
        "MASTER_PLAN_JSON": json.dumps(master_plan, indent=2),
        "DIFF": diff,
        "TEST_RESULTS": test_results,
        "SCREENSHOT_INDEX": "(none)",
    }
    qa_prompt = render_prompt("qa", qa_vars)

    qa_result, cost, err = invoke_model_safe(
        model_name=config.qa_model.name,
        prompt=qa_prompt,
        schema_path=_QA_SCHEMA,
        dry_run=dry_run,
        dry_run_response=dry_run_qa,
    )
    state.tool_calls_used += 1
    state.approx_cost_usd += cost

    if err:
        log.error("QA failed: %s", err)
        qa_result = None

    if qa_result:
        val_errors = validate(qa_result, "qa")
        if val_errors:
            log.warning("QA schema validation errors: %s", val_errors)
        save_json(run_dir / "artifacts" / "qa.json", qa_result)

    # Evaluate verdicts
    review_verdict = review_result.get("verdict", "BLOCKED") if review_result else "BLOCKED"
    qa_verdict = qa_result.get("verdict", "BLOCKED") if qa_result else "BLOCKED"

    log.info("Review verdict: %s, QA verdict: %s", review_verdict, qa_verdict)

    if review_verdict == "APPROVE" and qa_verdict == "PASS":
        # Clean — proceed to optimize or report
        state.final_status = None
        if config.optimize_enabled:
            state.phase = "OPTIMIZE"
        else:
            state.phase = "REPORT"
        persist_state(state, run_dir / "state.json")
        return {
            "review": review_result,
            "qa": qa_result,
            "clean": True,
        }

    # Issues found — loop back to BUILD
    state.review_loops_used += 1
    if state.review_loops_used >= phase_limits.max_review_loops:
        log.warning("Review loop cap reached (%d)", phase_limits.max_review_loops)
        # Proceed anyway with partial status
        state.final_status = "PARTIAL"
        state.phase = "REPORT"
        state.breaker_reason = "Review loop cap reached with unresolved issues"
        persist_state(state, run_dir / "state.json")
        return {
            "review": review_result,
            "qa": qa_result,
            "clean": False,
            "capped": True,
        }

    # Collect change requests for builder
    change_requests = []
    if review_result and review_result.get("requested_changes"):
        change_requests.extend(review_result["requested_changes"])
    if review_result and review_result.get("blockers"):
        for b in review_result["blockers"]:
            change_requests.append(f"[BLOCKER] {b['title']}: {b['suggested_fix']}")
    if qa_result and qa_result.get("concerns"):
        for c in qa_result["concerns"]:
            if c.get("severity") in ("high", "medium"):
                change_requests.append(f"[QA-{c['severity'].upper()}] {c['title']}: {c['suggested_test_or_fix']}")

    context["change_requests"] = change_requests
    state.final_status = None
    state.phase = "BUILD"
    state.build_iteration = 0  # Reset for the rework
    persist_state(state, run_dir / "state.json")

    return {
        "review": review_result,
        "qa": qa_result,
        "clean": False,
        "change_requests": change_requests,
    }
