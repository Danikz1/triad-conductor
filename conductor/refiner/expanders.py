"""Phase 1: EXPAND — parallel 3-role expansion of a raw idea."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from conductor.config import Config
from conductor.cost_tracker import estimate_cost
from conductor.models.invoker import invoke_model_safe
from conductor.prompt_renderer import render_prompt
from conductor.redaction import redact
from conductor.schema_validator import validate
from conductor.state import RunState, persist_state, save_json

log = logging.getLogger(__name__)

ROLES = ["scope_definer", "technical_analyst", "user_advocate"]

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "expansion.schema.json"


def run_expand(
    state: RunState,
    config: Config,
    idea_text: str,
    constraints: list[str],
    run_dir: Path,
    feedback: str = "",
    dry_run: bool = False,
    dry_run_responses: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Run all three expanders in parallel.

    Returns {"expansions": [...], "blocked": bool, "reason": str | None}.
    """
    log.info("=== TRIAD ARCHITECT: EXPAND (3 roles) ===")

    variables = {
        "IDEA": idea_text,
        "CONSTRAINTS": json.dumps(constraints) if constraints else "(none)",
        "FEEDBACK": feedback or "(none — first iteration)",
    }

    model_map = {
        "scope_definer": config.proposer_models[0] if len(config.proposer_models) > 0 else config.proposer_models[0],
        "technical_analyst": config.proposer_models[1] if len(config.proposer_models) > 1 else config.proposer_models[0],
        "user_advocate": config.proposer_models[2] if len(config.proposer_models) > 2 else config.proposer_models[0],
    }

    expansions: list[dict[str, Any]] = []
    errors: list[str] = []

    def _call_expander(i: int, role: str):
        prompt = render_prompt(role, variables)
        if config.redact_before_model:
            prompt = redact(prompt)

        model_ref = model_map[role]
        dr_resp = dry_run_responses[i] if dry_run_responses and i < len(dry_run_responses) else None

        result, cost, err = invoke_model_safe(
            model_name=model_ref.name,
            prompt=prompt,
            schema_path=_SCHEMA_PATH,
            dry_run=dry_run,
            dry_run_response=dr_resp,
        )
        state.tool_calls_used += 1
        state.approx_cost_usd += cost
        return i, role, model_ref.name, result, err

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_call_expander, i, role)
            for i, role in enumerate(ROLES)
        ]
        for future in as_completed(futures):
            i, role, name, result, err = future.result()
            if err:
                errors.append(f"{role} ({name}): {err}")
                log.error("Expander %s (%s) failed: %s", role, name, err)
                continue

            validation_errors = validate(result, "expansion")
            if validation_errors:
                log.warning("Expander %s schema validation failed: %s", role, validation_errors)
                errors.append(f"{role}: schema validation failed")
                continue

            expansions.append(result)
            log.info("Expander %s (%s) succeeded", role, name)

    # Save expansions
    expansions_dir = run_dir / "artifacts" / "expansions"
    expansions_dir.mkdir(parents=True, exist_ok=True)
    for i, exp in enumerate(expansions):
        save_json(expansions_dir / f"expansion_{i}.json", exp)

    if len(expansions) == 0:
        state.phase = "REPORT"
        state.breaker_reason = f"All expanders failed: {'; '.join(errors)}"
        persist_state(state, run_dir / "state.json")
        return {"expansions": [], "blocked": True, "reason": state.breaker_reason}

    return {"expansions": expansions, "blocked": False, "reason": None}
