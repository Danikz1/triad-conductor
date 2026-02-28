# Triad Conductor
## Comprehensive Project Description (As-Built, Current State)

**Date:** 2026-02-28
**Host:** macOS (Mac mini)
**Primary use:** autonomous multi-model coding orchestration (Claude, Codex, Gemini)
**Current maturity:** v0.1.0 — functional, tested, Telegram bot + Triad Architect refinement layer

---

## 1) Executive Summary

Triad Conductor is a non-LLM Python orchestrator that executes a bounded coding workflow:

```
INTAKE → PROPOSE → SYNTHESIZE → BUILD → CROSS_CHECK → OPTIMIZE → REPORT → DONE
```

Core principles:
- Models generate proposals/plans/updates.
- Conductor enforces reality via real command exit codes, schema gates, git operations, and breaker limits.
- One builder codes by default; others verify/review.
- Hard circuit breakers: time cap, cost cap, tool call cap.

**Triad Architect** is an optional pre-development refinement layer that triangulates 3 LLM perspectives to turn raw ideas into validated specs before development begins:

```
INTAKE → EXPAND_3 → SCORE → SYNTHESIZE → USER_REVIEW → APPROVED → HANDOFF_TO_DEV
```

Primary launch path:
```bash
/Users/daniyarserikson/Projects/triad-conductor/triad-start
```

---

## 2) Current Implemented Scope

### Implemented
- Full phase loop in `conductor/cli.py` (invoked by `conductor.py` wrapper) with persisted `state.json`
- Resumable execution with `--resume` and persisted `context.json`
- Parallel PROPOSE fan-out, arbiter SYNTHESIZE, iterative BUILD, reviewer/QA CROSS_CHECK, optional OPTIMIZE, REPORT
- JSON Schema validation (`schemas/*.schema.json`) on all model outputs
- Circuit breakers: wall time, tool calls, estimated cost, phase loop caps
- Git branch/worktree orchestration per run (`builder` + `integrate` branches)
- Redaction utilities for secrets/tokens in prompts/log fragments
- One-command launcher (`triad-start`) for "new folder + project.md + run", now with environment preflight checks
- Telegram bot integration with `/run`, `/status`, `/stop`, `/refine`, `/approve`, `/reject`, `/history`
- Telegram `/approve` now auto-prepares `/Users/daniyarserikson/Projects/<project-name>/project.md` + git repo bootstrap
- Telegram post-run auto-publish: merge `integrate`→`main` (when successful), update project-scoped comprehensive description, create/push GitHub repo, send publish report message
- **Triad Architect** idea refinement: 3-persona expansion, heuristic scoring, arbiter synthesis, structured user review, handoff to development
- `conductor.py ideate` CLI subcommand for non-Telegram refinement
- Dry-run mode with fixture examples for both conductor and architect pipelines

### Out of Scope (still)
- Billing/subscription and user management
- Web dashboard/GUI
- Persistent run queue with multi-worker scheduling

---

## 3) How Users Run It

### A) One command from any folder (recommended)
1. Create a markdown description (example: `project.md`) in any folder.
2. Run:

```bash
/Users/daniyarserikson/Projects/triad-conductor/triad-start
```

The launcher:
- Auto-detects `project.md` (or uses the file argument you pass)
- Creates or reuses a project folder under `/Users/daniyarserikson/Projects/<project-name>`
- Copies the task file, bootstraps git if needed, creates a run id
- Runs preflight checks for required CLIs plus authentication readiness (`claude`, `codex`, `gemini`)
- Starts `conductor.py run` with that generated folder as `--project-root`

Project name resolution order:
- `--project-name NAME` if provided
- First markdown heading (`# ...`) from task file
- Task filename without `.md`

### B) Explicit CLI invocation

```bash
cd /Users/daniyarserikson/Projects/triad-conductor
./.venv/bin/python conductor.py run \
  --task /ABS/PATH/TO/project.md \
  --config config.yaml \
  --project-root /ABS/PATH/TO/TARGET_PROJECT \
  --run-id run_20260228_001
```

### C) Idea refinement with Triad Architect

```bash
# Interactive CLI
./.venv/bin/python conductor.py ideate \
  --idea "Build a personal finance tracker that syncs with bank APIs" \
  --config config.yaml

# With constraints and auto-approve on convergence
./.venv/bin/python conductor.py ideate \
  --idea tasks/my_idea.md \
  --constraint "Must use Python" \
  --constraint "Single user only" \
  --auto-approve

# Dry-run (uses example fixtures)
./.venv/bin/python conductor.py ideate --idea "any idea" --dry-run
```

On approval, produces `approved_spec.md` + `config_scaled.yaml` ready for:
```bash
python conductor.py run --task <approved_spec.md> --config <config_scaled.yaml>
```

### D) Dry-run

```bash
/Users/daniyarserikson/Projects/triad-conductor/triad-start project.md --dry-run
```

Uses canned JSON examples from `examples/` instead of real model CLIs.

### E) Resume an interrupted run

```bash
./.venv/bin/python conductor.py run \
  --task /ABS/PATH/TO/project.md \
  --config config.yaml \
  --run-id <existing_run_id> \
  --resume
```

### F) Launcher flags

```bash
# Explicit target project folder name
triad-start project.md --project-name Mukhtar.AI

# Override projects root folder
triad-start project.md --projects-home /some/other/root

# Legacy behavior: run in current directory
triad-start project.md --use-current-dir

# Only run environment checks
triad-start --preflight-only

# Skip auth checks (advanced; not recommended)
triad-start --skip-auth-preflight

# Skip checks (not recommended)
triad-start --skip-preflight
```

---

## 4) Architecture: Main Phase Loop

```
INTAKE (0) → PROPOSE (1) → SYNTHESIZE (2) → BUILD (3) → CROSS_CHECK (4) → OPTIMIZE (5) → REPORT (6) → DONE
```

### Phase 0: INTAKE
- **Input:** Task markdown file
- **Action:** Create run directories, copy task, initialize git branches, create builder worktree
- **Output:** Context with task_text, branches, builder_worktree
- **Transition:** → PROPOSE

### Phase 1: PROPOSE (Parallel)
- **Input:** Task text + constraints
- **Action:** Call 3 proposer models (Claude, Codex, Gemini) in parallel via `prompts/proposer.md`
- **Validation:** Each output against `proposal.schema.json`
- **Safety:** If 2/3 models flag same contradiction quote → block
- **Output:** List of proposals
- **Transition:** → SYNTHESIZE or REPORT (blocked)

### Phase 2: SYNTHESIZE
- **Input:** Task text + all proposals
- **Action:** Arbiter model (Claude) merges proposals via `prompts/arbiter.md`
- **Validation:** Output against `master_plan.schema.json`
- **Output:** master_plan.json with milestones, acceptance criteria, test matrix
- **Transition:** → BUILD or REPORT (blocked)

### Phase 3: BUILD (Iterative per milestone)
- **Input:** Master plan, current milestone, test results, diffs
- **Loop:** Builder (Codex) implements → smoke tests → pass: merge & next milestone / fail: stuck detection
- **Recovery:** Replan (1 attempt) → Tournament (2 builders compete) → Block
- **Limits:** Max 5 iterations per milestone
- **Transition:** → CROSS_CHECK or REPORT (blocked)

### Phase 4: CROSS_CHECK (Reviewer + QA)
- **Parallel:** Reviewer (Claude) + QA (Gemini) verify implementation
- **If clean:** → OPTIMIZE (if enabled) or REPORT
- **If issues:** Convert to change_requests, loop back to BUILD (max 3 loops)

### Phase 5: OPTIMIZE (Optional, parallel)
- **Action:** 3 optimizer models suggest improvements in parallel
- **Safety:** Apply non-conflicting patches, run tests, merge only if green
- **Limits:** Max 2 passes
- **Transition:** → REPORT

### Phase 6: REPORT
- **Action:** Generate final_report.json (SUCCESS/PARTIAL) or blocked_report.json (BLOCKED)
- **Transition:** → DONE

---

## 5) Architecture: Triad Architect (Idea Refinement)

```
INTAKE → EXPAND_3 → SCORE → SYNTHESIZE → USER_REVIEW → [loop or] APPROVED → HANDOFF_TO_DEV
```

### Three Expansion Personas
1. **Scope Definer** (Claude) — Requirements, boundaries, MoSCoW prioritisation
2. **Technical Analyst** (Codex) — Feasibility, architecture, risks, tech stack
3. **User Advocate** (Gemini) — UX, user journeys, accessibility, value proposition

### Heuristic Scoring (5 dimensions, weighted)
| Dimension | Weight | What it measures |
|-----------|--------|------------------|
| Clarity | 0.25 | Specificity and unambiguity of requirements |
| Feasibility | 0.25 | Technical realism of the proposal |
| Coverage | 0.20 | Breadth of problem space addressed |
| Consistency | 0.15 | Internal coherence across sections |
| Specificity | 0.15 | Concreteness of success criteria and risks |

Confidence threshold: 5.0 (below → flagged)

### Structured Review Protocol
- `approve` / `lgtm` / `ship it` → Approve spec
- `reject` / `cancel` / `stop` → Reject and clear
- `D1: yes` / `D1: offline only` → Resolve a decision
- `A1: actually multi-user` → Correct an assumption
- Free text → General pushback (triggers re-expansion if >20 chars)

### Convergence
Spec is "converged" when: no remaining `decisions_needed` AND no `assumptions` with `needs_confirmation: true`

### Handoff
On approval:
- Freeze `approved_spec.json`
- Generate `approved_spec.md` (structured task.md for conductor)
- Generate `config_scaled.yaml` (limits scaled by complexity: S/M/L/XL)

### Cost & Iteration Limits
- Ideation cost cap: $5.00 (separate from dev budget)
- Max iterations: 3 feedback rounds before forced approve/reject

---

## 6) Circuit Breakers

Enforced at the start of each phase:

| Breaker | Default | Effect |
|---------|---------|--------|
| Wall time | 90 min | → REPORT (BLOCKED) |
| Total cost | $25.00 | → REPORT (BLOCKED) |
| Tool calls | 200 | → REPORT (BLOCKED) |
| Build iterations/milestone | 5 | Stuck detection |
| Review loops | 3 | → REPORT |
| Optimize passes | 2 | → REPORT |
| Stuck replans | 1 | → Tournament or REPORT |

---

## 7) Stuck Detection & Recovery

**Triggered if:**
- Same failure signature repeats 3 times
- Failing test count doesn't decrease over 3 iterations
- Tiny LOC changes (<10) twice in a row while failing
- External dependency error persists after 1 attempt

**Recovery chain:**
1. **Replan** — Arbiter creates smaller milestone or changes approach (max 1)
2. **Tournament** — Two builders (builderA, builderB) compete for 1-2 iterations; pick winner
3. **Block** — Transition to REPORT with status BLOCKED

---

## 8) Git Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Base branch (configurable) |
| `run/<run_id>` | Anchor from base |
| `run/<run_id>/builder` | Builder implements changes |
| `run/<run_id>/integrate` | Golden branch for the run |
| `run/<run_id>/builderA` | Tournament option A |
| `run/<run_id>/builderB` | Tournament option B |

Worktrees at `worktrees/<run_id>/builder/`, etc.
Only the conductor merges into integrate (no builder push).

---

## 9) Telegram Bot

### Commands
| Command | Action |
|---------|--------|
| `/start`, `/help` | Show usage |
| `/run [--dry-run] [--project-root /path]` | Launch conductor run |
| `/status` | Read state.json, show phase/milestone/cost |
| `/stop` | SIGINT → conductor's clean shutdown |
| `/refine [--dry-run]` | Start Triad Architect on pending task |
| `/approve` | Approve refined spec, trigger handoff, and auto-prepare `/Users/daniyarserikson/Projects/<project-name>` |
| `/reject` | Reject and clear refinement |
| `/history` | Show feedback history for current refinement |
| (text message) | Store as pending task, or feedback if refiner active |
| (upload .md file) | Store as pending task |

### Configuration
- `TELEGRAM_BOT_TOKEN` — Bot token in `.env`
- `TELEGRAM_ALLOWED_USERS` — Comma-separated user IDs (empty = allow all)
- `TRIAD_PROJECTS_HOME` — Override default projects root (`/Users/daniyarserikson/Projects`)
- `TRIAD_GITHUB_AUTO_PUBLISH` — `1` (default) to auto-create/push GitHub repo after run, `0` to disable
- `TRIAD_GITHUB_OWNER` — Optional owner/org for `gh repo create` (otherwise uses authenticated default)
- `TRIAD_GITHUB_VISIBILITY` — `private` (default), `public`, or `internal`

### Architecture
- Subprocess model: bot spawns `conductor.py run` as child process per run
- State polling: reads `state.json` every 2s for phase transitions
- One active run per chat
- Refiner sessions stored in `chat_data` (per-chat, in-memory)
- After `/approve`, bot stores pending task + pending project root and initializes git in that folder
- `/run` uses stored project root by default (unless explicit `--project-root` is provided)
- On completion, bot sends:
  1. final run summary
  2. publish summary (description update + GitHub create/push status + remote URL + errors)
  3. `state.json` attachment

### Auto-generated Project Description File
- File path pattern: `<project-name>_PROJECT_DESCRIPTION.md` in the project root
- Example: `Mukhtar-AI_PROJECT_DESCRIPTION.md`
- Contents include:
  - source project description (`project.md`)
  - latest run status/cost/tool calls
  - final/blocked report snapshot
  - artifact list
  - GitHub remote link (if available)

---

## 10) Model Invocation

### CLI Commands
- **Claude:** `claude -p --output-format json --no-session-persistence [--model <id>] [--json-schema <path>] [--mcp-config <path>] [--dangerously-skip-permissions]`
- **Codex:** primary `codex exec - [--model <id>] -a never --sandbox <workspace-write|danger-full-access> [-C <dir>]`, compatibility fallback to `codex exec - [--model <id>] --full-auto`
- **Gemini:** tries compatibility sequence:
  1. `[--model <id>] --yolo --approval-mode yolo`
  2. `[--model <id>] --approval-mode=yolo`
  3. `[--model <id>] --yolo`

### Permission Toggles (env vars)
- `TRIAD_AUTOMATE_PERMISSIONS=1` (default) — Skip permission prompts
- `TRIAD_DANGEROUS_AUTONOMY=1` — Codex without sandbox (dangerous)

### Model Lifecycle Policy (New Provider Releases)

Goal: keep Triad on the best coding models without silent regressions.

- **Do not rely on blind "latest" aliases in production.**
  Use explicit/pinned model IDs after validation.
- **Evaluate new releases on a scheduled cadence** (recommended: weekly).
  Run a fixed benchmark pack (real repo tasks + tests) and score by:
  1) test pass rate/correctness, 2) reliability/stability, 3) cost, 4) latency.
- **Promote only on evidence.**
  A candidate model replaces the current one only if it beats the active baseline on the benchmark criteria.
- **Keep rollback immediate.**
  Retain the previous known-good model set and revert if failure rate rises after promotion.
- **Current state (important):**
  Triad now supports per-role `model` pinning in `config.yaml`, and forwards those IDs via provider CLIs (`--model` / `-m`) during invocation.
  Authentication preflight is enforced before non-dry runs, so runs fail early if required providers are not logged in.

---

## 11) Schema Validation

Every model output is validated against JSON schema before acceptance:

### Conductor Schemas
| Schema | Purpose |
|--------|---------|
| `proposal.schema.json` | Proposal output structure |
| `master_plan.schema.json` | Master plan with milestones |
| `build_update.schema.json` | Builder status updates |
| `review.schema.json` | Reviewer verdict |
| `qa.schema.json` | QA test results |
| `optimization.schema.json` | Optimizer suggestions |
| `final_report.schema.json` | Success/partial report |
| `blocked_report.schema.json` | Failure/blocked report |

### Architect Schemas
| Schema | Purpose |
|--------|---------|
| `intake.schema.json` | Intake record |
| `expansion.schema.json` | Per-persona expansion output |
| `scored_expansion.schema.json` | Scored expansion with rankings |
| `refined_spec.schema.json` | Unified synthesised spec |
| `revision_request.schema.json` | User feedback structure |
| `approved_spec.schema.json` | Frozen approved spec |

**Failure handling:** First attempt fails → retry with validation errors appended to prompt → still fails → block.

---

## 12) Redaction & Security

### Redaction Patterns (before sending to any model)
- AWS access keys (AKIA...)
- GitHub tokens (ghp_, gho_, ghu_, ghs_, github_pat_)
- Bearer tokens, API keys, secrets, passwords
- PEM-formatted private keys
- Credit card numbers (13-19 digits, Luhn check)

### File Denylist (never attach)
- `.env`, `.env.*`, `*secret*`, `*key*`, `id_rsa*`, `.ssh/**`, `**/Library/Keychains/**`

### Log Truncation
Max 150 lines, keeping head and tail for context.

---

## 13) State Management

### RunState (`runs/<run_id>/state.json`)
```
run_id, started_at, phase, milestone_index, build_iteration,
review_loops_used, optimize_passes_used, tool_calls_used,
approx_cost_usd, fail_signatures, failing_counts, loc_changed,
stuck_replans_used, tournament_used, final_status, breaker_reason
```

### Context (`runs/<run_id>/context.json`)
```
project_root, task_text, branches, builder_worktree,
master_plan, last_test_output, change_requests, proposals,
mcp_config_path
```

Both files use atomic writes (write to .tmp then os.rename) for crash safety.

---

## 14) Repository Structure

```
triad-conductor/
├── conductor.py                    # Entry point wrapper
├── triad-start                     # One-command launcher (executable)
├── telegram_bot.py                 # Telegram bot entry point
├── config.yaml                     # Active configuration
├── config.example.yaml             # Config template
├── pyproject.toml                  # Package metadata & dependencies
├── .env.example                    # Environment template
├── .gitignore
├── INSTRUCTIONS.md
├── Triad_Conductor_Project_Description.md
├── Triad_Forge_Proposal.md
│
├── conductor/
│   ├── cli.py                      # Main CLI: run + ideate subcommands
│   ├── config.py                   # YAML config → Config dataclass
│   ├── state.py                    # RunState, Limits, breakers, atomic persist
│   ├── git_ops.py                  # Git branch/worktree/merge/diff
│   ├── tools.py                    # Local test/lint/typecheck execution
│   ├── stuck.py                    # Stuck detection, tournament, replan
│   ├── cost_tracker.py             # Cost estimation per model
│   ├── redaction.py                # Secret pattern matching
│   ├── logging_setup.py            # Logging configuration
│   ├── prompt_renderer.py          # {{VAR}} template rendering
│   ├── schema_validator.py         # JSON schema validation
│   ├── state_machine.md            # State machine spec
│   │
│   ├── models/
│   │   ├── invoker.py              # CLI invocation for claude/codex/gemini
│   │   └── parsers.py              # JSON extraction from model output
│   │
│   ├── phases/
│   │   ├── intake.py               # Phase 0: Setup dirs, git, worktrees
│   │   ├── propose.py              # Phase 1: Parallel 3-model proposals
│   │   ├── synthesize.py           # Phase 2: Arbiter merges → master_plan
│   │   ├── build.py                # Phase 3: Builder loop + stuck detection
│   │   ├── cross_check.py          # Phase 4: Reviewer + QA
│   │   ├── optimize.py             # Phase 5: Parallel optimisation
│   │   └── report.py               # Phase 6: Final/blocked report
│   │
│   ├── refiner/                    # Triad Architect
│   │   ├── engine.py               # RefinerEngine: full refinement loop
│   │   ├── expanders.py            # Parallel 3-persona expansion
│   │   ├── scorer.py               # Heuristic scoring (5 dimensions)
│   │   ├── synthesizer.py          # Arbiter synthesis → refined_spec
│   │   ├── reviewer.py             # Parse user review, convergence check
│   │   ├── handoff.py              # approved_spec.md + config_scaled.yaml
│   │   └── formatting.py           # Telegram HTML formatting for specs
│   │
│   └── telegram/
│       ├── bot.py                  # Application builder + handler registration
│       ├── handlers.py             # /run /status /stop /refine /approve /reject /history
│       ├── runner.py               # RunnerManager: subprocess + state polling
│       └── formatting.py           # Phase emojis, status, reports
│
├── prompts/
│   ├── proposer.md                 # Proposes implementation plans
│   ├── arbiter.md                  # Merges proposals → master plan
│   ├── builder.md                  # Implements code per milestone
│   ├── reviewer.md                 # Reviews implementation
│   ├── qa.md                       # Quality assurance testing
│   ├── optimizer.md                # Optimisation suggestions
│   ├── reporter.md                 # Final report generation
│   ├── scope_definer.md            # (Architect) Scope/requirements persona
│   ├── technical_analyst.md        # (Architect) Technical analysis persona
│   ├── user_advocate.md            # (Architect) User experience persona
│   └── spec_arbiter.md             # (Architect) Synthesis arbiter
│
├── schemas/                        # JSON Schema files (14 total)
│   ├── proposal.schema.json
│   ├── master_plan.schema.json
│   ├── build_update.schema.json
│   ├── review.schema.json
│   ├── qa.schema.json
│   ├── optimization.schema.json
│   ├── final_report.schema.json
│   ├── blocked_report.schema.json
│   ├── intake.schema.json
│   ├── expansion.schema.json
│   ├── scored_expansion.schema.json
│   ├── refined_spec.schema.json
│   ├── revision_request.schema.json
│   └── approved_spec.schema.json
│
├── examples/                       # Dry-run fixture JSONs
│   ├── proposal.json
│   ├── master_plan.json
│   ├── build_update.json
│   ├── review.json
│   ├── qa.json
│   ├── optimization.json
│   ├── final_report.json
│   ├── blocked_report.json
│   ├── expansion_scope.json
│   ├── expansion_technical.json
│   ├── expansion_advocate.json
│   └── refined_spec.json
│
├── tests/                          # Test suite (128 tests)
│   ├── conftest.py
│   ├── test_cli_context.py
│   ├── test_config.py
│   ├── test_git_ops.py
│   ├── test_build_phase.py
│   ├── test_propose_phase.py
│   ├── test_report_phase.py
│   ├── test_invoker.py
│   ├── test_parsers.py
│   ├── test_schema_validator.py
│   ├── test_mcp_server.py
│   ├── test_redaction.py
│   ├── test_state.py
│   ├── test_stuck.py
│   ├── test_telegram_runner.py
│   ├── test_prompt_renderer.py
│   └── fixtures/sample_task.md
│
├── mcp/
│   ├── devtools_server.py          # MCP DevTools server
│   └── devtools_server_stub.py
│
├── tasks/                          # Task description storage
├── runs/                           # Run output directories (gitignored)
└── worktrees/                      # Git worktrees (gitignored)
```

---

## 15) Configuration (config.yaml)

```yaml
project:
  name: triad-conductor
  base_branch: main

run_limits:
  max_wall_time_minutes: 90
  max_total_cost_usd: 25.0
  max_total_tool_calls: 200

phase_limits:
  propose: { timeout_minutes: 8 }
  build: { max_iterations: 5, max_stuck_replans: 1 }
  cross_check: { max_review_loops: 3 }
  optimize: { enabled: true, max_passes: 2 }

tournament_mode:
  enabled: true
  trigger_if:
    - stuck_detector_fired_once
    - arbiter_requests_tournament
    - two_root_cause_hypotheses

models:
  proposer_models:
    - { name: claude, role: proposer, model: opus }
    - { name: codex, role: proposer, model: gpt-5.3-codex }
    - { name: gemini, role: proposer, model: gemini-2.5-pro }
  arbiter_model: { name: claude, role: arbiter, model: opus }
  builder_model: { name: codex, role: builder, model: gpt-5.3-codex }
  reviewer_model: { name: claude, role: reviewer, model: opus }
  qa_model: { name: gemini, role: qa, model: gemini-2.5-pro }
  optimizer_models:
    - { name: claude, role: optimizer, model: opus }
    - { name: codex, role: optimizer, model: gpt-5.3-codex }
    - { name: gemini, role: optimizer, model: gemini-2.5-pro }

artifacts:
  runs_dir: runs
  redact_before_model: true
```

---

## 16) Dependencies

### Core
- `pyyaml` — Config parsing
- `jsonschema` — Schema validation

### Optional: dev
- `pytest` — Testing

### Optional: telegram
- `python-telegram-bot>=21.0` — Async Telegram bot framework
- `python-dotenv>=1.0` — Environment variable loading

Install: `pip install -e ".[telegram]"`

---

## 17) Quality Status

- **Test suite:** 128 tests passing
- **Schema validation:** All 14 schemas verified with fixture examples
- **Dry-run:** End-to-end verified for both `run` and `ideate` subcommands
- **Telegram bot:** Verified command handling, runner command forwarding, auto-project-root preparation, and post-run publish reporting

---

## 18) Recent Changes

### Telegram deployment/publishing automation
- `/approve` now auto-creates project root under `/Users/daniyarserikson/Projects/<project-name>`
- Approved spec is written into `<project-root>/project.md`
- Git repo bootstrap is automatic for prepared project roots
- `/run` now defaults to the prepared project root (override still possible with `--project-root`)
- Post-run publishing pipeline added:
  - merge `run/<run_id>/integrate` into `main` for successful/partial runs
  - update comprehensive project description file named `<project-name>_PROJECT_DESCRIPTION.md`
  - create GitHub repo via `gh repo create` when missing
  - push `main` to `origin`
  - send Telegram publish report summary message

### Launcher & CLI compatibility
- `triad-start` preflight checks (`--preflight-only`, `--skip-preflight`)
- `triad-start` auth preflight checks (`--skip-auth-preflight` override available)
- `conductor.py run` and `conductor.py ideate` enforce model auth preflight by default (`--skip-auth-preflight` or `TRIAD_SKIP_AUTH_PREFLIGHT=1` to bypass)
- Per-role model pinning added via `model` in config refs, forwarded to all provider CLIs
- Codex invoker fallback handles both unknown-option and unexpected-argument flag errors
- Gemini invoker fallback handles conflicting `--yolo`/`--approval-mode` variants across CLI versions

### Triad Architect (idea refinement system)
- 6 new JSON schemas for the refinement pipeline
- 4 role prompts (scope_definer, technical_analyst, user_advocate, spec_arbiter)
- 7 core modules in `conductor/refiner/`
- `conductor.py ideate` CLI subcommand with interactive review loop
- 4 dry-run fixture examples validated against schemas
- Telegram handlers: `/refine`, `/approve`, `/reject`, `/history`
- Text messages auto-route to refiner when session is active
- Complexity-scaled config generation (S: $10/45min, M: $25/90min, L: $40/120min, XL: $60/180min)

### Previous fixes
- PROPOSE contradiction blocking with quote-consensus normalisation
- CROSS_CHECK → BUILD feedback wiring via CHANGE_REQUESTS
- PARTIAL status distinguished from BLOCKED in REPORT
- Run resumption with `--resume` flag
- Permission automation env toggles in invoker

---

### End
