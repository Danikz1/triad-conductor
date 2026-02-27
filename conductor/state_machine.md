# Conductor State Machine (v2.1)

This document specifies the minimal behavior of the **non‑LLM conductor**.

## Core responsibilities
1) Owns the run state (phase, iteration counters, budgets).
2) Owns git (branches, worktrees, merges).
3) Runs tools (tests/lint/typecheck/screenshot) and reads real exit codes.
4) Redacts sensitive data before sending any artifacts to models.
5) Enforces circuit breakers and “stuck” detection.

## Suggested directory layout
Repo root:
- `worktrees/<run_id>/builder/`      (builder worktree)
- `worktrees/<run_id>/integrate/`    (integration worktree)
- `runs/<run_id>/state.json`         (authoritative run state)
- `runs/<run_id>/artifacts/...`      (test logs, screenshots, diffs, etc.)

## Git strategy (recommended)
Base branch: `main` (configurable)

For a run_id like `2026-02-26_180530Z_ab12cd`:
- `run/<run_id>`                 (anchor branch from base)
- `run/<run_id>/builder`         (builder branch)
- `run/<run_id>/integrate`       (integration branch, “golden” for the run)
- optional tournament:
  - `run/<run_id>/builderA`
  - `run/<run_id>/builderB`

Only the conductor merges into `integrate`.

## Phases and transitions
### PHASE 0: INTAKE
Input: task text + constraints
Output: `runs/<run_id>/input/task.md`, initial `state.json`
Next: PROPOSE

### PHASE 1: PROPOSE (parallel)
Action: call each proposer model using `prompts/proposer.md`
Validation: each output must validate against `proposal.schema.json`
Spec contradiction rule:
- If **2/3** proposals contain a contradiction with (quote + explanation), transition to PAUSE_BLOCKED (needs human).
Otherwise: SYNTHESIZE

### PHASE 2: SYNTHESIZE
Action: call arbiter using `prompts/arbiter.md` with all proposals JSON
Validation: output must validate `master_plan.schema.json`
If arbiter flags unresolvable contradictions: PAUSE_BLOCKED
Else: BUILD

### PHASE 3: BUILD (single builder loop)
Loop per milestone:
1) Present builder with:
   - master_plan.json
   - current milestone_id
   - latest test results (redacted)
   - current diff summary
2) Builder edits code in builder worktree (or via tools) then emits `build_update` JSON.
3) Conductor runs:
   - smoke tests (from plan.test_matrix.smoke)
   - optional lint/typecheck
4) If pass for the milestone:
   - merge builder → integrate
   - proceed to next milestone
5) If fail:
   - feed redacted failures back to builder
   - increment iteration
   - run stuck detection (see below)
6) If iteration cap hit: STUCK_REPLAN (once) or TOURNAMENT or PAUSE_BLOCKED

Exit: when all milestones done and full tests pass → CROSS_CHECK

### PHASE 4: CROSS_CHECK (Reviewer then QA)
Inputs:
- diff (integrate branch vs base or vs previous checkpoint)
- test results
- screenshot index
Outputs:
- review.json (must validate)
- qa.json (must validate)

If verdicts are clean (APPROVE + PASS): OPTIMIZE (if enabled) else REPORT
If issues:
- convert into concrete change requests
- go back to BUILD (review loop counter increments; cap enforced)

### PHASE 5: OPTIMIZE (optional)
Parallel: call optimizer models → collect optimization JSON
Conductor applies **non-conflicting** patches only:
- apply patch to builder branch (or a temp branch)
- run full tests
- if green, merge into integrate
Cap passes to prevent endless refactors.

### PHASE 6: REPORT
Call reporter to generate final report JSON.
Write a human-friendly message using that JSON.

## Stuck detection (must be deterministic)
Maintain in state:
- `fail_signature_history`: last N failure signatures
- `failing_tests_count_history`
- `loc_changed_history`

Compute failure signature from test output, e.g.:
- first failing test id + first stack line
- or first compiler error line

Trigger stuck if any:
- same signature repeats 3 times
- failing_tests_count does not decrease across 2 iterations
- LOC changed < 10 but failures persist across 2 iterations
- external dependency error persists (network/auth) after 1 attempt

When stuck triggers:
1) If `stuck_replans_used < max_stuck_replans`: go to mini REPLAN (arbiter creates smaller milestone or changes approach) then return to BUILD.
2) Else if tournament enabled and not used: TOURNAMENT
3) Else: PAUSE_BLOCKED

## Tournament mode (bounded)
- Create builderA and builderB branches from integrate.
- Run two builders (sequentially or parallel) for 1–2 iterations max.
- Run smoke tests for each.
- Pick the branch that:
  1) passes more tests
  2) has fewer regressions
  3) has simpler diff
- Merge winner into integrate.
- Return to normal BUILD.

## Circuit breakers
Enforce:
- max_wall_time_minutes
- max_total_cost_usd (approximate; track per model invocation if possible)
- max_total_tool_calls
- per-phase iteration caps

On breaker hit: REPORT with status PARTIAL or BLOCKED and include artifacts.

