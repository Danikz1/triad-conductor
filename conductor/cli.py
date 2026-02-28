"""Triad Conductor — Entry point and phase loop.

Usage:
    python conductor.py run --task <path> --config <path> [--run-id <id>] [--dry-run]
    python conductor.py run --task tasks/my_task.md --config config.yaml
    python conductor.py ideate --idea <path-or-text> --config <path> [--dry-run]

Exit codes:
    0 = SUCCESS
    1 = BLOCKED
    2 = PARTIAL
    3 = ERROR
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

from conductor.config import Config, load_config
from conductor.logging_setup import setup_logging
from conductor.models.preflight import ensure_required_auth
from conductor.state import (
    RunState, Limits, PhaseLimits, check_breakers,
    persist_state, load_state, load_json, now_ts,
)

ROOT = Path(__file__).resolve().parents[1]
_CONTEXT_SENTINEL = "__triad_path__"


def _context_default(project_root: Path) -> dict:
    return {
        "project_root": project_root,
        "task_text": "",
        "branches": {},
        "builder_worktree": None,
        "master_plan": None,
        "last_test_output": "",
    }


def _context_path(run_dir: Path) -> Path:
    return run_dir / "context.json"


def _serialize_context_value(value):
    if isinstance(value, Path):
        return {_CONTEXT_SENTINEL: str(value)}
    if isinstance(value, dict):
        return {k: _serialize_context_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_context_value(v) for v in value]
    return value


def _deserialize_context_value(value):
    if isinstance(value, dict):
        if set(value.keys()) == {_CONTEXT_SENTINEL}:
            return Path(value[_CONTEXT_SENTINEL])
        return {k: _deserialize_context_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deserialize_context_value(v) for v in value]
    return value


def persist_context(context: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    serialized = _serialize_context_value(context)
    tmp.write_text(json.dumps(serialized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.rename(str(tmp), str(path))


def load_context(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _deserialize_context_value(data)


def _generate_run_id() -> str:
    """Generate a run ID like 2026-02-27_143000Z_a1b2c3."""
    import hashlib
    ts = time.strftime("%Y-%m-%d_%H%M%SZ", time.gmtime())
    suffix = hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:6]
    return f"{ts}_{suffix}"


def _env_flag_enabled(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _should_skip_auth_preflight(cli_skip_flag: bool) -> bool:
    return cli_skip_flag or _env_flag_enabled("TRIAD_SKIP_AUTH_PREFLIGHT", False)


def _exit_code_for_status(status: str) -> int:
    if status == "SUCCESS":
        return 0
    if status == "BLOCKED":
        return 1
    if status == "PARTIAL":
        return 2
    return 3


def _exit_code_for_done_state(state: RunState) -> int:
    if state.final_status in {"SUCCESS", "BLOCKED", "PARTIAL"}:
        return _exit_code_for_status(state.final_status)
    if state.breaker_reason:
        return 1
    return 0


def _load_dry_run_examples(run_dir: Path) -> dict:
    """Load example JSONs for dry-run mode."""
    examples_dir = ROOT / "examples"
    examples = {}
    for p in examples_dir.glob("*.json"):
        examples[p.stem] = load_json(p)
    return examples


def _run_ideate(args):
    """Run the Triad Architect ideation/refinement loop (CLI mode)."""
    from conductor.refiner.engine import RefinerEngine
    from conductor.refiner.formatting import format_refined_spec

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(3)
    config = load_config(config_path)

    # Read idea text
    idea_path = Path(args.idea)
    if idea_path.exists():
        idea_text = idea_path.read_text(encoding="utf-8").strip()
    else:
        idea_text = args.idea.strip()

    if not idea_text:
        print("Idea text is empty.", file=sys.stderr)
        sys.exit(3)

    # Setup run
    run_id = args.run_id or f"ideate-{_generate_run_id()}"
    runs_dir = ROOT / config.runs_dir
    run_dir = runs_dir / run_id

    # Setup logging
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(run_dir)
    logger.info("Starting ideation run %s (dry_run=%s)", run_id, args.dry_run)

    if not args.dry_run and not _should_skip_auth_preflight(args.skip_auth_preflight):
        try:
            ensure_required_auth(config)
        except RuntimeError as exc:
            logger.error("%s", exc)
            print(str(exc), file=sys.stderr)
            sys.exit(3)

    engine = RefinerEngine(
        run_id=run_id,
        run_dir=run_dir,
        config=config,
        idea_text=idea_text,
        constraints=args.constraint,
        dry_run=args.dry_run,
    )

    # Load dry-run fixtures if applicable
    dry_expand = None
    dry_synth = None
    if args.dry_run:
        examples_dir = ROOT / "examples"
        import json as _json
        _exp_files = ["expansion_scope.json", "expansion_technical.json", "expansion_advocate.json"]
        dry_expand = []
        for f in _exp_files:
            p = examples_dir / f
            if p.exists():
                dry_expand.append(_json.loads(p.read_text(encoding="utf-8")))
        _synth_path = examples_dir / "refined_spec.json"
        if _synth_path.exists():
            dry_synth = _json.loads(_synth_path.read_text(encoding="utf-8"))

    # Phase 0: Intake
    print(f"\n=== Triad Architect: {run_id} ===\n")
    engine.run_intake()

    iteration = 0
    while True:
        iteration += 1
        print(f"--- Iteration {iteration} ---")

        # Expand + Score
        print("Running EXPAND (3 perspectives) + SCORE...")
        expand_result = engine.run_expand_and_score(dry_run_responses=dry_expand)
        if expand_result.get("blocked"):
            print(f"BLOCKED: {expand_result.get('reason', 'unknown')}", file=sys.stderr)
            sys.exit(1)

        # Synthesize
        print("Running SYNTHESIZE...")
        synth_result = engine.run_synthesize(dry_run_response=dry_synth)
        if synth_result.get("blocked"):
            print(f"BLOCKED: {synth_result.get('reason', 'unknown')}", file=sys.stderr)
            sys.exit(1)

        # Display spec
        spec = synth_result["refined_spec"]
        print("\n" + _format_spec_cli(spec) + "\n")

        # Cost check
        cost_warning = engine.check_cost_cap()
        if cost_warning:
            print(f"WARNING: {cost_warning}")

        # Auto-approve if converged and flag set
        from conductor.refiner.reviewer import is_converged
        if args.auto_approve and is_converged(spec):
            print("Spec converged — auto-approving.")
            user_text = "approve"
        else:
            # Interactive review
            print("Options: 'approve', 'reject', or send feedback (D1: answer / A1: correction / free text)")
            try:
                user_text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                sys.exit(3)

        if not user_text:
            continue

        result = engine.handle_review(user_text)
        action = result.get("action")

        if action == "approved":
            print("\nSpec approved! Running handoff...")
            config_path_abs = Path(args.config).resolve()
            handoff = engine.run_handoff(user_id=0, base_config_path=config_path_abs)
            print(f"Task spec: {handoff['task_path']}")
            print(f"Scaled config: {handoff['config_path']}")
            print(f"\nTo start development:\n  python conductor.py run --task {handoff['task_path']} --config {handoff['config_path']}")
            sys.exit(0)

        if action == "rejected":
            print("Refinement rejected.")
            sys.exit(0)

        if action == "max_iterations":
            print(result["message"])
            continue

        if action == "revise":
            needs_re_expand = result.get("needs_re_expand", False)
            if not needs_re_expand:
                print("Minor feedback — re-synthesizing only...")
                # Skip expand, go straight to synthesize on next loop body
                print("Running SYNTHESIZE...")
                synth_result = engine.run_synthesize(dry_run_response=dry_synth)
                if synth_result.get("blocked"):
                    print(f"BLOCKED: {synth_result.get('reason', 'unknown')}", file=sys.stderr)
                    sys.exit(1)
                spec = synth_result["refined_spec"]
                print("\n" + _format_spec_cli(spec) + "\n")
                continue
            # else: needs re-expand, loop will handle it


def _format_spec_cli(spec: dict) -> str:
    """Format a refined spec for CLI display (plain text)."""
    lines = [
        f"=== Refined Spec v{spec.get('version', '?')}: \"{spec.get('project_name', '?')}\" ===",
        f"  {spec.get('one_liner', '')}",
        "",
    ]
    reqs = spec.get("requirements", {})
    for priority in ("must", "should", "could", "wont"):
        items = reqs.get(priority, [])
        if items:
            lines.append(f"  {priority.upper()}:")
            for r in items:
                lines.append(f"    {r.get('id', '?')}: {r.get('text', '')}")

    decisions = spec.get("decisions_needed", [])
    if decisions:
        lines.append("\n  DECISIONS NEEDED:")
        for d in decisions:
            lines.append(f"    {d['id']}: {d['question']}")
            lines.append(f"      Recommendation: {d.get('recommendation', '?')}")

    assumptions = [a for a in spec.get("assumptions", []) if a.get("needs_confirmation")]
    if assumptions:
        lines.append("\n  ASSUMPTIONS (need confirmation):")
        for a in assumptions:
            lines.append(f"    {a['id']}: {a['assumption']}")

    lines.append(f"\n  Complexity: {spec.get('estimated_complexity', '?')} | Milestones: {spec.get('estimated_milestones', '?')}")

    if not decisions and not assumptions:
        lines.append("  [CONVERGED — ready to approve]")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Triad Conductor — Multi-model coding workflow")
    sub = ap.add_subparsers(dest="cmd")

    run_parser = sub.add_parser("run", help="Execute a full conductor run")
    run_parser.add_argument("--task", required=True, help="Path to task.md file")
    run_parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    run_parser.add_argument("--run-id", default=None, help="Explicit run ID (auto-generated if omitted)")
    run_parser.add_argument("--dry-run", action="store_true", help="Use canned example responses instead of calling models")
    run_parser.add_argument("--project-root", default=None, help="Target project root (for git operations)")
    run_parser.add_argument("--resume", action="store_true", help="Resume an existing run from state.json/context.json")
    run_parser.add_argument("--skip-auth-preflight", action="store_true", help="Skip model authentication checks")

    ideate_parser = sub.add_parser("ideate", help="Refine an idea with Triad Architect before development")
    ideate_parser.add_argument("--idea", required=True, help="Path to idea file (.md/.txt) or inline text")
    ideate_parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    ideate_parser.add_argument("--run-id", default=None, help="Explicit run ID (auto-generated if omitted)")
    ideate_parser.add_argument("--dry-run", action="store_true", help="Use canned example responses instead of calling models")
    ideate_parser.add_argument("--constraint", action="append", default=[], help="Add a constraint (repeatable)")
    ideate_parser.add_argument("--auto-approve", action="store_true", help="Auto-approve on convergence (no user interaction)")
    ideate_parser.add_argument("--skip-auth-preflight", action="store_true", help="Skip model authentication checks")

    args = ap.parse_args()
    if args.cmd == "ideate":
        return _run_ideate(args)
    if args.cmd != "run":
        ap.print_help()
        sys.exit(3)

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(3)
    config = load_config(config_path)

    # Setup run
    run_id = args.run_id or _generate_run_id()
    runs_dir = ROOT / config.runs_dir
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "state.json"
    context_state_path = _context_path(run_dir)

    task_path = Path(args.task)
    if not task_path.exists():
        print(f"Task file not found: {task_path}", file=sys.stderr)
        sys.exit(3)

    # Setup logging
    logger = setup_logging(run_dir)
    logger.info("Starting run %s (dry_run=%s, resume=%s)", run_id, args.dry_run, args.resume)

    # Initialize or resume state/context
    if args.resume:
        if not state_path.exists():
            logger.error("Cannot resume: state file not found at %s", state_path)
            sys.exit(3)
        state = load_state(state_path)
        if state.run_id != run_id:
            logger.warning("Resumed state run_id (%s) differs from requested run_id (%s)", state.run_id, run_id)
        if context_state_path.exists():
            context = load_context(context_state_path)
        else:
            fallback_root = Path(args.project_root) if args.project_root else ROOT
            context = _context_default(fallback_root)
        if args.project_root:
            context["project_root"] = Path(args.project_root)
        context.setdefault("project_root", Path(args.project_root) if args.project_root else ROOT)
        context.setdefault("task_text", "")
        context.setdefault("branches", {})
        context.setdefault("builder_worktree", None)
        context.setdefault("master_plan", None)
        context.setdefault("last_test_output", "")
        logger.info("Resuming run %s from phase %s", run_id, state.phase)
    else:
        state = RunState(run_id=run_id, started_at=now_ts(), phase="INTAKE")
        project_root = Path(args.project_root) if args.project_root else ROOT
        context = _context_default(project_root)
        persist_state(state, state_path)
        persist_context(context, context_state_path)

    project_root = context.get("project_root", Path(args.project_root) if args.project_root else ROOT)

    if (
        state.phase != "DONE"
        and not args.dry_run
        and not _should_skip_auth_preflight(args.skip_auth_preflight)
    ):
        try:
            ensure_required_auth(config)
        except RuntimeError as exc:
            logger.error("%s", exc)
            print(str(exc), file=sys.stderr)
            sys.exit(3)

    # Limits
    limits = Limits(
        max_wall_time_minutes=config.max_wall_time_minutes,
        max_total_tool_calls=config.max_total_tool_calls,
        max_total_cost_usd=config.max_total_cost_usd,
    )
    phase_limits = PhaseLimits(
        max_build_iterations=config.max_build_iterations,
        max_review_loops=config.max_review_loops,
        max_optimize_passes=config.max_optimize_passes,
        max_stuck_replans=config.max_stuck_replans,
    )

    # Dry-run examples
    examples = _load_dry_run_examples(run_dir) if args.dry_run else {}

    # Signal handling: persist state on SIGINT
    def _handle_sigint(signum, frame):
        logger.warning("SIGINT received, persisting state and exiting")
        persist_state(state, state_path)
        persist_context(context, context_state_path)
        sys.exit(3)
    signal.signal(signal.SIGINT, _handle_sigint)

    # Phase loop
    exit_code = _exit_code_for_done_state(state) if state.phase == "DONE" else 3
    try:
        while state.phase != "DONE":
            # Check breakers before each phase
            breaker = check_breakers(state, limits)
            if breaker:
                logger.warning("Circuit breaker: %s", breaker)
                state.breaker_reason = breaker
                state.phase = "REPORT"
                persist_state(state, state_path)

            match state.phase:
                case "INTAKE":
                    from conductor.phases.intake import run_intake
                    result = run_intake(state, config, task_path, project_root, run_dir)
                    context.update({
                        "task_text": result["task_text"],
                        "branches": result["branches"],
                        "builder_worktree": result["builder_worktree"],
                    })

                case "PROPOSE":
                    from conductor.phases.propose import run_propose
                    dr = [examples.get("proposal")] * 3 if args.dry_run else None
                    result = run_propose(state, config, context["task_text"], run_dir,
                                         dry_run=args.dry_run, dry_run_responses=dr)
                    if result.get("blocked"):
                        state.phase = "REPORT"
                        persist_state(state, state_path)
                    else:
                        context["proposals"] = result["proposals"]

                case "SYNTHESIZE":
                    from conductor.phases.synthesize import run_synthesize
                    dr = examples.get("master_plan") if args.dry_run else None
                    result = run_synthesize(
                        state, config, context["task_text"],
                        context.get("proposals", []), run_dir,
                        dry_run=args.dry_run, dry_run_response=dr,
                    )
                    if result.get("blocked"):
                        state.phase = "REPORT"
                        persist_state(state, state_path)
                    else:
                        context["master_plan"] = result["master_plan"]

                case "BUILD":
                    from conductor.phases.build import run_build
                    dr = examples.get("build_update") if args.dry_run else None
                    result = run_build(
                        state, config, context["master_plan"], context,
                        run_dir, limits, phase_limits,
                        dry_run=args.dry_run, dry_run_response=dr,
                    )

                case "CROSS_CHECK":
                    from conductor.phases.cross_check import run_cross_check
                    dr_review = examples.get("review") if args.dry_run else None
                    dr_qa = examples.get("qa") if args.dry_run else None
                    result = run_cross_check(
                        state, config, context["master_plan"], context,
                        run_dir, limits, phase_limits,
                        dry_run=args.dry_run, dry_run_review=dr_review, dry_run_qa=dr_qa,
                    )

                case "OPTIMIZE":
                    from conductor.phases.optimize import run_optimize
                    dr = [examples.get("optimization")] * 3 if args.dry_run else None
                    result = run_optimize(
                        state, config, context["master_plan"], context,
                        run_dir, limits, phase_limits,
                        dry_run=args.dry_run, dry_run_responses=dr,
                    )

                case "REPORT":
                    from conductor.phases.report import run_report
                    is_blocked_for_schema = (
                        state.breaker_reason is not None and state.final_status != "PARTIAL"
                    )
                    schema_key = "blocked_report" if is_blocked_for_schema else "final_report"
                    dr = examples.get(schema_key) if args.dry_run else None
                    result = run_report(
                        state, config, context.get("master_plan"), context,
                        run_dir, dry_run=args.dry_run, dry_run_response=dr,
                    )
                    status = result.get("status", "ERROR")
                    exit_code = _exit_code_for_status(status)

                case _:
                    logger.error("Unknown phase: %s", state.phase)
                    break

            persist_state(state, state_path)
            persist_context(context, context_state_path)

    except Exception:
        logger.exception("Unhandled exception in conductor")
        persist_state(state, state_path)
        persist_context(context, context_state_path)
        exit_code = 3

    logger.info("Run %s finished (exit_code=%d, cost=$%.2f, tool_calls=%d)",
                run_id, exit_code, state.approx_cost_usd, state.tool_calls_used)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
