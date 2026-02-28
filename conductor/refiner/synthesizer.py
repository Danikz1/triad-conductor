"""Phase 3: SYNTHESIZE — arbiter merges scored expansions into refined_spec."""

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

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "refined_spec.schema.json"


def run_synthesize(
    state: RunState,
    config: Config,
    idea_text: str,
    expansions: list[dict],
    scores: list[dict],
    run_dir: Path,
    version: int = 1,
    feedback: str = "",
    dry_run: bool = False,
    dry_run_response: Optional[dict] = None,
) -> dict[str, Any]:
    """Call the arbiter to synthesize expansions into a refined spec.

    Returns {"refined_spec": dict, "blocked": bool, "reason": str | None}.
    """
    log.info("=== TRIAD ARCHITECT: SYNTHESIZE (v%d) ===", version)

    variables = {
        "IDEA": idea_text,
        "EXPANSION_0": json.dumps(expansions[0], indent=2) if len(expansions) > 0 else "{}",
        "EXPANSION_1": json.dumps(expansions[1], indent=2) if len(expansions) > 1 else "{}",
        "EXPANSION_2": json.dumps(expansions[2], indent=2) if len(expansions) > 2 else "{}",
        "SCORES": json.dumps(scores, indent=2),
        "FEEDBACK": feedback or "(none — first iteration)",
        "VERSION": str(version),
    }

    prompt = render_prompt("spec_arbiter", variables)
    if config.redact_before_model:
        prompt = redact(prompt)

    arbiter_model = config.arbiter_model
    result, cost, err = invoke_model_safe(
        model_name=arbiter_model.name,
        prompt=prompt,
        schema_path=_SCHEMA_PATH,
        dry_run=dry_run,
        dry_run_response=dry_run_response,
    )
    state.tool_calls_used += 1
    state.approx_cost_usd += cost

    if err:
        log.error("Arbiter failed: %s", err)
        state.phase = "REPORT"
        state.breaker_reason = f"Arbiter failed: {err}"
        persist_state(state, run_dir / "state.json")
        return {"refined_spec": None, "blocked": True, "reason": state.breaker_reason}

    # Validate
    validation_errors = validate(result, "refined_spec")
    if validation_errors:
        log.warning("Arbiter output failed validation, retrying: %s", validation_errors)
        retry_prompt = prompt + f"\n\n[VALIDATION ERROR — fix and output valid JSON]\nErrors: {json.dumps(validation_errors)}"
        result, cost, err = invoke_model_safe(
            model_name=arbiter_model.name,
            prompt=retry_prompt,
            schema_path=_SCHEMA_PATH,
            dry_run=dry_run,
            dry_run_response=dry_run_response,
        )
        state.tool_calls_used += 1
        state.approx_cost_usd += cost

        if err or validate(result, "refined_spec"):
            reason = f"Arbiter validation failed after retry: {err or validation_errors}"
            state.phase = "REPORT"
            state.breaker_reason = reason
            persist_state(state, run_dir / "state.json")
            return {"refined_spec": None, "blocked": True, "reason": reason}

    # Save
    save_json(run_dir / "artifacts" / f"refined_spec_v{version}.json", result)
    log.info("Refined spec v%d saved (%s, %d milestones)",
             version, result.get("estimated_complexity"), result.get("estimated_milestones", 0))

    return {"refined_spec": result, "blocked": False, "reason": None}
