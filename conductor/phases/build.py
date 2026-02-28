"""Phase 3: BUILD - Builder loop per milestone with test/stuck detection."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from conductor.config import Config
from conductor.git_ops import (
    merge_builder_to_integrate, get_diff, get_loc_changed,
    create_tournament_worktrees, commit_all,
)
from conductor.models.invoker import invoke_model_safe
from conductor.prompt_renderer import render_prompt
from conductor.redaction import redact, truncate_log
from conductor.schema_validator import validate
from conductor.state import RunState, PhaseLimits, persist_state, save_json, check_breakers, Limits
from conductor.stuck import stuck_detector, handle_stuck, pick_tournament_winner
from conductor.tools import run_tests, count_failing_tests, compute_failure_signature

log = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "build_update.schema.json"


def run_build(
    state: RunState,
    config: Config,
    master_plan: dict[str, Any],
    context: dict[str, Any],
    run_dir: Path,
    limits: Limits,
    phase_limits: PhaseLimits,
    dry_run: bool = False,
    dry_run_response: Optional[dict] = None,
) -> dict:
    """Execute the BUILD phase.

    Loops through milestones. For each milestone, iterates:
    invoke builder → conductor runs tests → pass (merge) or fail (feedback, stuck detect).
    """
    log.info("=== PHASE 3: BUILD ===")

    milestones = master_plan.get("milestones", [])
    test_matrix = master_plan.get("test_matrix", {})
    smoke_cmds = test_matrix.get("smoke", ["python -m pytest -q -k smoke"])
    full_cmds = test_matrix.get("full", ["python -m pytest -q"])

    builder_wt = context["builder_worktree"]
    branches = context["branches"]
    project_root = context.get("project_root", Path.cwd())
    mcp_config_path = context.get("mcp_config_path")

    while state.milestone_index < len(milestones):
        milestone = milestones[state.milestone_index]
        milestone_id = milestone["id"]
        log.info("--- Milestone %s: %s ---", milestone_id, milestone.get("title", ""))

        state.build_iteration = 0
        state.fail_signatures = []
        state.failing_counts = []
        state.loc_changed = []

        while state.build_iteration < phase_limits.max_build_iterations:
            # Check circuit breakers
            breaker = check_breakers(state, limits)
            if breaker:
                state.breaker_reason = breaker
                state.phase = "REPORT"
                persist_state(state, run_dir / "state.json")
                return {"completed": False, "reason": breaker}

            state.build_iteration += 1
            log.info("Build iteration %d/%d for %s",
                     state.build_iteration, phase_limits.max_build_iterations, milestone_id)

            # Prepare builder prompt
            diff = get_diff(project_root, branches["integrate"], branches["builder"])
            test_results_text = "(no previous test results)" if state.build_iteration == 1 else context.get("last_test_output", "")
            change_requests = context.get("change_requests", [])
            if change_requests:
                change_requests_text = "\n".join(f"- {item}" for item in change_requests)
            else:
                change_requests_text = "(none)"
            if config.redact_before_model:
                test_results_text = redact(truncate_log(test_results_text))
                diff = redact(diff)
                change_requests_text = redact(change_requests_text)

            variables = {
                "TASK": context.get("task_text", ""),
                "MASTER_PLAN_JSON": json.dumps(master_plan, indent=2),
                "CURRENT_STATE": json.dumps({
                    "milestone_id": milestone_id,
                    "iteration": state.build_iteration,
                    "phase": "BUILD",
                }),
                "CHANGE_REQUESTS": change_requests_text,
                "TEST_RESULTS": test_results_text,
                "DIFF": diff,
            }
            prompt = render_prompt("builder", variables)
            if config.redact_before_model:
                prompt = redact(prompt)

            # Invoke builder
            result, cost, err = invoke_model_safe(
                model_name=config.builder_model.name,
                model_id=config.builder_model.model,
                prompt=prompt,
                schema_path=_SCHEMA_PATH,
                cwd=builder_wt,
                mcp_config_path=mcp_config_path,
                dry_run=dry_run,
                dry_run_response=dry_run_response,
            )
            state.tool_calls_used += 1
            state.approx_cost_usd += cost

            if err:
                log.error("Builder invocation failed: %s", err)
                context["last_test_output"] = f"Builder error: {err}"
                continue

            # Validate build_update
            if result:
                val_errors = validate(result, "build_update")
                if val_errors:
                    log.warning("Build update schema validation failed: %s", val_errors)

            # Run smoke tests
            all_passed = True
            test_output = ""
            for cmd_str in smoke_cmds:
                cmd = cmd_str.split()
                passed, output = run_tests(cmd, cwd=builder_wt)
                state.tool_calls_used += 1
                test_output += output + "\n"
                if not passed:
                    all_passed = False

            # Save test output
            test_log_path = run_dir / "artifacts" / "tests" / f"build_{milestone_id}_iter{state.build_iteration}.log"
            test_log_path.parent.mkdir(parents=True, exist_ok=True)
            test_log_path.write_text(test_output, encoding="utf-8")
            context["last_test_output"] = test_output

            if all_passed:
                log.info("Milestone %s passed smoke tests on iteration %d", milestone_id, state.build_iteration)
                # Commit and merge
                committed = commit_all(builder_wt, f"Complete milestone {milestone_id}")
                if not committed:
                    state.phase = "REPORT"
                    state.breaker_reason = f"Git commit failed for milestone {milestone_id}"
                    persist_state(state, run_dir / "state.json")
                    return {"completed": False, "reason": state.breaker_reason}

                merged = merge_builder_to_integrate(project_root, branches["builder"], branches["integrate"])
                if not merged:
                    state.phase = "REPORT"
                    state.breaker_reason = f"Git merge failed for milestone {milestone_id}"
                    persist_state(state, run_dir / "state.json")
                    return {"completed": False, "reason": state.breaker_reason}

                state.milestone_index += 1
                persist_state(state, run_dir / "state.json")
                break
            else:
                # Track for stuck detection
                sig = compute_failure_signature(test_output)
                fail_count = count_failing_tests(test_output)
                loc = get_loc_changed(project_root, branches["integrate"], branches["builder"])
                state.fail_signatures.append(sig)
                state.failing_counts.append(fail_count if fail_count >= 0 else 999)
                state.loc_changed.append(loc)

                log.info("Tests failed (sig=%s, count=%d, loc=%d)", sig[:60], fail_count, loc)

                # Check stuck
                if stuck_detector(state):
                    action = handle_stuck(state, phase_limits, config.tournament_enabled)
                    if action == "replan":
                        log.info("Stuck → replan (not yet re-invoking arbiter in this loop)")
                        # In a real implementation, we'd invoke arbiter for a mini-replan
                        # For now, reset iteration and continue
                        state.build_iteration = 0
                        state.fail_signatures = []
                        state.failing_counts = []
                        state.loc_changed = []
                        continue
                    elif action == "tournament":
                        winner = _run_tournament(
                            state, config, master_plan, milestone, context,
                            run_dir, limits, phase_limits, dry_run, dry_run_response,
                        )
                        if winner:
                            state.milestone_index += 1
                            persist_state(state, run_dir / "state.json")
                            break
                        else:
                            state.phase = "REPORT"
                            state.breaker_reason = "Tournament failed to resolve stuck"
                            persist_state(state, run_dir / "state.json")
                            return {"completed": False, "reason": state.breaker_reason}
                    else:  # blocked
                        state.phase = "REPORT"
                        state.breaker_reason = f"Stuck on milestone {milestone_id}, no recovery options"
                        persist_state(state, run_dir / "state.json")
                        return {"completed": False, "reason": state.breaker_reason}

                persist_state(state, run_dir / "state.json")
        else:
            # Iteration cap hit without passing
            state.phase = "REPORT"
            state.breaker_reason = f"Build iteration cap hit for milestone {milestone_id}"
            persist_state(state, run_dir / "state.json")
            return {"completed": False, "reason": state.breaker_reason}

    # All milestones done — run full tests
    log.info("All milestones complete, running full test suite")
    full_passed = True
    full_output = ""
    for cmd_str in full_cmds:
        cmd = cmd_str.split()
        passed, output = run_tests(cmd, cwd=builder_wt)
        state.tool_calls_used += 1
        full_output += output + "\n"
        if not passed:
            full_passed = False

    full_log_path = run_dir / "artifacts" / "tests" / "full_tests.log"
    full_log_path.write_text(full_output, encoding="utf-8")
    context["last_test_output"] = full_output

    if full_passed:
        state.phase = "CROSS_CHECK"
    else:
        state.phase = "REPORT"
        state.breaker_reason = "Full test suite failed after all milestones"

    persist_state(state, run_dir / "state.json")
    return {"completed": full_passed, "reason": state.breaker_reason}


def _run_tournament(
    state: RunState,
    config: Config,
    master_plan: dict,
    milestone: dict,
    context: dict,
    run_dir: Path,
    limits: Limits,
    phase_limits: PhaseLimits,
    dry_run: bool,
    dry_run_response: Optional[dict],
) -> bool:
    """Run tournament mode: two builders compete, pick winner. Returns True if winner found."""
    log.info("=== TOURNAMENT MODE ===")
    project_root = context.get("project_root", Path.cwd())
    branches = context["branches"]
    worktrees_dir = project_root / config.worktrees_dir

    path_a, path_b, branch_a, branch_b = create_tournament_worktrees(
        repo_dir=project_root,
        worktrees_dir=worktrees_dir,
        run_id=state.run_id,
        integrate_branch=branches["integrate"],
        branch_prefix=config.branch_prefix,
    )

    smoke_cmds = master_plan.get("test_matrix", {}).get("smoke", ["python -m pytest -q -k smoke"])
    results = []

    for path, branch, label in [(path_a, branch_a, "A"), (path_b, branch_b, "B")]:
        log.info("Tournament builder %s on branch %s", label, branch)
        # Invoke builder (simplified — 1 iteration each)
        variables = {
            "TASK": context.get("task_text", ""),
            "MASTER_PLAN_JSON": json.dumps(master_plan, indent=2),
            "CURRENT_STATE": json.dumps({
                "milestone_id": milestone["id"],
                "iteration": 1,
                "phase": "BUILD_TOURNAMENT",
                "label": label,
            }),
            "TEST_RESULTS": "(tournament start)",
            "DIFF": "",
        }
        prompt = render_prompt("builder", variables)
        result, cost, err = invoke_model_safe(
            model_name=config.builder_model.name,
            model_id=config.builder_model.model,
            prompt=prompt, schema_path=_SCHEMA_PATH,
            cwd=path, dry_run=dry_run, dry_run_response=dry_run_response,
        )
        state.tool_calls_used += 1
        state.approx_cost_usd += cost

        # Run tests
        test_passed = True
        test_output = ""
        for cmd_str in smoke_cmds:
            cmd = cmd_str.split()
            passed, output = run_tests(cmd, cwd=path)
            state.tool_calls_used += 1
            test_output += output + "\n"
            if not passed:
                test_passed = False

        fail_count = count_failing_tests(test_output)
        loc = get_loc_changed(project_root, branches["integrate"], branch)

        results.append({
            "passed": test_passed,
            "fail_count": fail_count if fail_count >= 0 else 999,
            "loc": loc,
            "branch": branch,
            "path": path,
        })

    winner_idx = pick_tournament_winner(results)
    if winner_idx is not None:
        winner = results[winner_idx]
        log.info("Tournament winner: %s (branch %s)", chr(65 + winner_idx), winner["branch"])
        committed = commit_all(winner["path"], f"Tournament winner for milestone {milestone['id']}")
        if not committed:
            log.warning("Tournament winner commit failed for milestone %s", milestone["id"])
            return False

        merged = merge_builder_to_integrate(project_root, winner["branch"], branches["integrate"])
        if not merged:
            log.warning("Tournament winner merge failed for milestone %s", milestone["id"])
            return False

        return True
    else:
        log.warning("Tournament: no clear winner")
        return False
