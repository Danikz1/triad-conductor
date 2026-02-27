"""Phase 2: SYNTHESIZE - Arbiter merges proposals into master_plan."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from conductor.config import Config
from conductor.models.invoker import invoke_model_safe
from conductor.prompt_renderer import render_prompt
from conductor.redaction import redact
from conductor.schema_validator import validate
from conductor.state import RunState, persist_state, save_json

log = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "master_plan.schema.json"


def run_synthesize(
    state: RunState,
    config: Config,
    task_text: str,
    proposals: list[dict[str, Any]],
    run_dir: Path,
    dry_run: bool = False,
    dry_run_response: Optional[dict] = None,
) -> dict:
    """Execute the SYNTHESIZE phase.

    Calls the arbiter model with all proposals to produce a master_plan.
    Validates output against master_plan.schema.json.
    """
    log.info("=== PHASE 2: SYNTHESIZE ===")

    variables = {
        "TASK": task_text,
        "CONSTRAINTS": "See task description.",
        "PROPOSALS_JSON": json.dumps(proposals, indent=2),
    }
    prompt = render_prompt("arbiter", variables)
    if config.redact_before_model:
        prompt = redact(prompt)

    result, cost, err = invoke_model_safe(
        model_name=config.arbiter_model.name,
        prompt=prompt,
        schema_path=_SCHEMA_PATH,
        dry_run=dry_run,
        dry_run_response=dry_run_response,
    )
    state.tool_calls_used += 1
    state.approx_cost_usd += cost

    if err:
        state.phase = "REPORT"
        state.breaker_reason = f"Arbiter failed: {err}"
        persist_state(state, run_dir / "state.json")
        return {"master_plan": None, "blocked": True, "reason": state.breaker_reason}

    # Validate
    validation_errors = validate(result, "master_plan")
    if validation_errors:
        # One retry
        log.warning("Arbiter schema validation failed, retrying: %s", validation_errors)
        retry_prompt = prompt + f"\n\n[VALIDATION ERROR]\nErrors: {json.dumps(validation_errors)}"
        result, cost, err = invoke_model_safe(
            model_name=config.arbiter_model.name, prompt=retry_prompt,
            schema_path=_SCHEMA_PATH, dry_run=dry_run, dry_run_response=dry_run_response,
        )
        state.tool_calls_used += 1
        state.approx_cost_usd += cost
        if err or validate(result, "master_plan"):
            state.phase = "REPORT"
            state.breaker_reason = "Arbiter output failed schema validation"
            persist_state(state, run_dir / "state.json")
            return {"master_plan": None, "blocked": True, "reason": state.breaker_reason}

    # Ensure run_id is set
    if result.get("run_id") != state.run_id:
        result["run_id"] = state.run_id

    # Save master plan
    save_json(run_dir / "artifacts" / "master_plan.json", result)
    log.info("Master plan saved with %d milestones", len(result.get("milestones", [])))

    # Transition
    state.phase = "BUILD"
    persist_state(state, run_dir / "state.json")

    return {"master_plan": result, "blocked": False}
