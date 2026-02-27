# Triad Conductor Template (v2.1)

This repo is a **template** for a multi-model coding workflow run by a **non-LLM conductor**.

It implements the workflow:
0) Intake → 1) Propose (parallel) → 2) Synthesize → 3) Build → 4) Cross-check → 5) Optimize (optional) → 6) Report

Core rules:
- **Exit codes are truth.** Never accept “the model says tests passed”.
- **One Builder codes** by default; other models verify/review.
- **Hard circuit breakers**: iteration caps, time cap, cost cap.
- **Git isolation**: builder & integrator branches/worktrees.
- **Redaction layer**: redact secrets before sending logs to any model.

## What you get in this template
- `schemas/` JSON Schemas for every LLM output the conductor expects
- `prompts/` role prompts (Proposer, Arbiter, Builder, Reviewer, QA, Optimizer, Reporter)
- `conductor/state_machine.md` implementation spec (states, transitions, stuck detector, tournament trigger)
- `conductor/redaction.md` redaction rules
- `config.example.yaml` knobs for budgets & iteration limits
- `examples/` example JSON outputs for each schema

## How to use
1) Copy this folder onto your Mac mini.
2) Implement the conductor using `conductor/state_machine.md`.
3) Use the prompts in `prompts/` when invoking each model CLI.
4) Validate every model response against the schema in `schemas/` before proceeding.
