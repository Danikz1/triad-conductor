"""Phase 5: OPTIMIZE - Parallel optimizers, patch-then-test."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from conductor.config import Config
from conductor.git_ops import get_diff, merge_builder_to_integrate, commit_all
from conductor.models.invoker import invoke_model_safe
from conductor.prompt_renderer import render_prompt
from conductor.redaction import redact, truncate_log
from conductor.schema_validator import validate
from conductor.state import RunState, PhaseLimits, Limits, persist_state, save_json, check_breakers
from conductor.tools import run_tests

log = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "optimization.schema.json"


def _list_untracked_files(cwd: Path) -> set[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return set()
    return {cwd / line.strip() for line in result.stdout.splitlines() if line.strip()}


def _revert_failed_patch(cwd: Path, before_untracked: set[Path]) -> None:
    subprocess.run(
        ["git", "checkout", "."],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    after_untracked = _list_untracked_files(cwd)
    created_untracked = sorted(
        after_untracked - before_untracked,
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for path in created_untracked:
        try:
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        except OSError as exc:
            log.debug("Failed to clean untracked path %s: %s", path, exc)


def run_optimize(
    state: RunState,
    config: Config,
    master_plan: dict[str, Any],
    context: dict[str, Any],
    run_dir: Path,
    limits: Limits,
    phase_limits: PhaseLimits,
    dry_run: bool = False,
    dry_run_responses: Optional[list[dict]] = None,
) -> dict:
    """Execute the OPTIMIZE phase.

    Calls optimizer models in parallel, applies non-conflicting patches one-by-one,
    tests each, merges if green.
    """
    log.info("=== PHASE 5: OPTIMIZE ===")

    if state.optimize_passes_used >= phase_limits.max_optimize_passes:
        log.info("Optimize pass cap already reached")
        state.phase = "REPORT"
        persist_state(state, run_dir / "state.json")
        return {"applied": []}

    branches = context["branches"]
    project_root = context.get("project_root", Path.cwd())
    builder_wt = context["builder_worktree"]

    diff = get_diff(project_root, branches["anchor"], branches["integrate"])
    test_results = context.get("last_test_output", "")
    if config.redact_before_model:
        diff = redact(diff)
        test_results = redact(truncate_log(test_results))

    variables = {
        "MASTER_PLAN_JSON": json.dumps(master_plan, indent=2),
        "DIFF": diff,
        "CURRENT_STATE": json.dumps({"phase": "OPTIMIZE", "pass": state.optimize_passes_used + 1}),
        "TEST_RESULTS": test_results,
    }
    prompt = render_prompt("optimizer", variables)

    # Parallel optimizer invocations
    all_suggestions: list[dict] = []
    state_lock = Lock()

    def _record_usage(cost: float) -> None:
        with state_lock:
            state.tool_calls_used += 1
            state.approx_cost_usd += cost

    def _call_optimizer(i: int, model_ref):
        dr_resp = dry_run_responses[i] if dry_run_responses and i < len(dry_run_responses) else None
        result, cost, err = invoke_model_safe(
            model_name=model_ref.name,
            prompt=prompt,
            schema_path=_SCHEMA_PATH,
            dry_run=dry_run,
            dry_run_response=dr_resp,
        )
        _record_usage(cost)
        return i, model_ref.name, result, err

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_call_optimizer, i, m)
            for i, m in enumerate(config.optimizer_models)
        ]
        for future in as_completed(futures):
            i, name, result, err = future.result()
            if err:
                log.warning("Optimizer %s failed: %s", name, err)
                continue
            if result:
                val_errors = validate(result, "optimization")
                if not val_errors:
                    for s in result.get("suggestions", []):
                        s["_source"] = name
                        all_suggestions.append(s)
                else:
                    log.warning("Optimizer %s schema errors: %s", name, val_errors)

    # Apply patches one-by-one, test, merge if green
    applied = []
    test_cmds = master_plan.get("test_matrix", {}).get("full", ["python -m pytest -q"])

    for suggestion in all_suggestions:
        breaker = check_breakers(state, limits)
        if breaker:
            break

        patch = suggestion.get("patch_unified_diff", "")
        if not patch or len(patch.strip()) < 10:
            continue

        log.info("Trying optimization: %s", suggestion.get("title", "unknown"))
        before_untracked = _list_untracked_files(builder_wt)

        # Try applying the patch in the builder worktree
        try:
            result = subprocess.run(
                ["git", "apply", "--check", "-"],
                input=patch, text=True, capture_output=True,
                cwd=str(builder_wt),
            )
            if result.returncode != 0:
                log.info("Patch doesn't apply cleanly, skipping: %s", suggestion.get("title"))
                continue

            apply_result = subprocess.run(
                ["git", "apply", "-"],
                input=patch, text=True, capture_output=True,
                cwd=str(builder_wt),
            )
            if apply_result.returncode != 0:
                log.info("Patch failed to apply, skipping: %s", suggestion.get("title"))
                _revert_failed_patch(builder_wt, before_untracked)
                continue
        except Exception as e:
            log.warning("Failed to apply patch: %s", e)
            _revert_failed_patch(builder_wt, before_untracked)
            continue

        # Test
        all_passed = True
        for cmd_str in test_cmds:
            cmd = cmd_str.split()
            passed, output = run_tests(cmd, cwd=builder_wt)
            state.tool_calls_used += 1
            if not passed:
                all_passed = False
                break

        if all_passed:
            committed = commit_all(builder_wt, f"Optimization: {suggestion.get('title', 'improvement')}")
            if not committed:
                state.phase = "REPORT"
                state.breaker_reason = f"Git commit failed for optimization: {suggestion.get('title', 'unknown')}"
                persist_state(state, run_dir / "state.json")
                return {"applied": applied}

            merged = merge_builder_to_integrate(project_root, branches["builder"], branches["integrate"])
            if not merged:
                state.phase = "REPORT"
                state.breaker_reason = f"Git merge failed for optimization: {suggestion.get('title', 'unknown')}"
                persist_state(state, run_dir / "state.json")
                return {"applied": applied}

            applied.append(suggestion.get("title", "unknown"))
            log.info("Applied optimization: %s", suggestion.get("title"))
        else:
            # Revert
            _revert_failed_patch(builder_wt, before_untracked)
            log.info("Optimization failed tests, reverted: %s", suggestion.get("title"))

    state.optimize_passes_used += 1
    save_json(run_dir / "artifacts" / "optimizations.json", {"applied": applied, "total_suggested": len(all_suggestions)})

    state.phase = "REPORT"
    persist_state(state, run_dir / "state.json")

    return {"applied": applied}
