"""Phase 1: PROPOSE - Parallel 3-model fan-out for proposals."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from conductor.config import Config
from conductor.cost_tracker import estimate_cost
from conductor.models.invoker import invoke_model_safe
from conductor.prompt_renderer import render_prompt
from conductor.redaction import redact
from conductor.schema_validator import validate
from conductor.state import RunState, persist_state, save_json

log = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "proposal.schema.json"


def _normalize_contradiction_quote(quote: str) -> str:
    """Normalize contradiction quotes for consensus matching."""
    return " ".join(quote.split()).casefold()


def _find_contradiction_consensus(
    records: list[tuple[str, dict]],
    required_count: int = 2,
) -> Optional[dict]:
    """Check if ``required_count`` proposers flag the same spec contradiction.

    *records* is a list of ``(model_name, proposal_dict)`` tuples.
    Returns a dict with the shared quote and contributing models, or ``None``.
    """
    quote_models: dict[str, set[str]] = {}
    display_quotes: dict[str, str] = {}
    for model_name, proposal in records:
        for c in proposal.get("spec_contradictions") or []:
            raw_quote = c.get("quote", "")
            if not raw_quote:
                continue
            normalized = _normalize_contradiction_quote(raw_quote)
            if not normalized:
                continue
            quote_models.setdefault(normalized, set()).add(model_name)
            display_quotes.setdefault(normalized, " ".join(raw_quote.split()))

    for normalized, models in quote_models.items():
        if len(models) >= required_count:
            return {"quote": display_quotes[normalized], "models": sorted(models)}
    return None


def run_propose(
    state: RunState,
    config: Config,
    task_text: str,
    run_dir: Path,
    dry_run: bool = False,
    dry_run_responses: Optional[list[dict]] = None,
) -> dict:
    """Execute the PROPOSE phase.

    Calls each proposer model in parallel, validates proposals against schema,
    checks for spec contradictions (2/3 = PAUSE_BLOCKED).

    Returns context dict with proposals list.
    """
    log.info("=== PHASE 1: PROPOSE ===")

    constraints = "See task description for constraints."
    variables = {
        "TASK": task_text,
        "CONSTRAINTS": constraints,
        "REPO_SUMMARY": "(not available)",
    }
    prompt = render_prompt("proposer", variables)
    if config.redact_before_model:
        prompt = redact(prompt)

    proposals: list[dict[str, Any]] = []
    proposal_records: list[tuple[str, dict[str, Any]]] = []
    errors: list[str] = []
    state_lock = Lock()

    def _record_usage(cost: float) -> None:
        with state_lock:
            state.tool_calls_used += 1
            state.approx_cost_usd += cost

    def _call_proposer(i: int, model_ref):
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

    # Parallel invocation
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_call_proposer, i, m)
            for i, m in enumerate(config.proposer_models)
        ]
        for future in as_completed(futures):
            i, name, result, err = future.result()
            if err:
                errors.append(f"{name}: {err}")
                log.error("Proposer %s failed: %s", name, err)
                continue

            # Validate against schema
            validation_errors = validate(result, "proposal")
            if validation_errors:
                # One retry with error feedback
                log.warning("Proposer %s schema validation failed, retrying: %s", name, validation_errors)
                retry_prompt = prompt + f"\n\n[VALIDATION ERROR - please fix and output valid JSON]\nErrors: {json.dumps(validation_errors)}"
                dr_resp = dry_run_responses[i] if dry_run_responses and i < len(dry_run_responses) else None
                result, cost, err = invoke_model_safe(
                    model_name=name, prompt=retry_prompt,
                    schema_path=_SCHEMA_PATH, dry_run=dry_run, dry_run_response=dr_resp,
                )
                _record_usage(cost)
                if err:
                    errors.append(f"{name} (retry): {err}")
                    continue
                validation_errors = validate(result, "proposal")
                if validation_errors:
                    errors.append(f"{name}: schema validation failed after retry")
                    continue

            proposals.append(result)
            proposal_records.append((name, result))
            log.info("Proposer %s succeeded", name)

    # Save proposals
    proposals_dir = run_dir / "artifacts" / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(proposals):
        save_json(proposals_dir / f"proposal_{i}.json", p)

    if len(proposals) == 0:
        state.phase = "REPORT"
        state.breaker_reason = f"All proposers failed: {'; '.join(errors)}"
        persist_state(state, run_dir / "state.json")
        return {"proposals": [], "blocked": True, "reason": state.breaker_reason}

    # Contradiction check: block only when 2+ proposers flag the same contradiction quote.
    consensus = _find_contradiction_consensus(proposal_records, required_count=2)
    if consensus is not None:
        log.warning(
            "Spec contradiction consensus detected by %s on quote: %s",
            ",".join(consensus["models"]),
            consensus["quote"],
        )
        state.phase = "REPORT"
        state.breaker_reason = (
            "Spec contradiction consensus detected "
            f"({','.join(consensus['models'])}) on quote: {consensus['quote']}"
        )
        persist_state(state, run_dir / "state.json")
        return {"proposals": proposals, "blocked": True, "reason": state.breaker_reason}

    # Transition to SYNTHESIZE
    state.phase = "SYNTHESIZE"
    persist_state(state, run_dir / "state.json")

    return {"proposals": proposals, "blocked": False}
