"""Triad Architect engine — orchestrates INTAKE → EXPAND → SCORE → SYNTHESIZE → REVIEW loop."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from conductor.config import Config, load_config
from conductor.state import RunState, persist_state, save_json, load_json, now_ts

from .expanders import run_expand
from .scorer import run_score
from .synthesizer import run_synthesize
from .reviewer import (
    ReviewResponse, parse_review, build_revision_request,
    needs_re_expand, is_converged,
)
from .handoff import run_handoff

log = logging.getLogger(__name__)

MAX_ITERATIONS = 3
IDEATION_COST_CAP = 5.0  # Separate from dev budget


class RefinerEngine:
    """Manages the stateful refinement loop for one idea.

    This is designed to be driven step-by-step from the Telegram bot (async)
    or all-at-once from the CLI (sync).
    """

    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        config: Config,
        idea_text: str,
        constraints: list[str] | None = None,
        dry_run: bool = False,
    ):
        self.run_id = run_id
        self.run_dir = run_dir
        self.config = config
        self.idea_text = idea_text
        self.constraints = constraints or []
        self.dry_run = dry_run

        self.state = RunState(run_id=run_id, started_at=now_ts(), phase="INTAKE")
        self.state_path = run_dir / "state.json"

        self.version = 0
        self.expansions: list[dict] = []
        self.scores: list[dict] = []
        self.refined_spec: Optional[dict] = None
        self.feedback_history: list[str] = []
        self.resolved_decisions: dict[str, str] = {}
        self.corrected_assumptions: dict[str, str] = {}

        # Persist initial state
        run_dir.mkdir(parents=True, exist_ok=True)
        persist_state(self.state, self.state_path)

        # Save raw idea
        (run_dir / "raw_idea.md").write_text(idea_text, encoding="utf-8")

    def run_intake(self) -> dict:
        """Phase 0: parse and store the intake record."""
        log.info("=== TRIAD ARCHITECT: INTAKE ===")
        self.state.phase = "EXPAND_3"
        persist_state(self.state, self.state_path)

        intake = {
            "raw_text": self.idea_text,
            "detected_constraints": self.constraints,
            "domain_hints": [],
            "ambiguity_level": "high" if len(self.idea_text) < 200 else "medium",
        }
        save_json(self.run_dir / "artifacts" / "intake.json", intake)
        return intake

    def run_expand_and_score(
        self,
        dry_run_responses: Optional[list[dict]] = None,
    ) -> dict:
        """Phases 1+2: expand then score."""
        self.state.phase = "EXPAND_3"
        persist_state(self.state, self.state_path)

        feedback_str = "\n".join(self.feedback_history) if self.feedback_history else ""

        result = run_expand(
            state=self.state,
            config=self.config,
            idea_text=self.idea_text,
            constraints=self.constraints,
            run_dir=self.run_dir,
            feedback=feedback_str,
            dry_run=self.dry_run,
            dry_run_responses=dry_run_responses,
        )

        if result["blocked"]:
            return result

        self.expansions = result["expansions"]

        # Score
        self.state.phase = "SCORE"
        persist_state(self.state, self.state_path)
        self.scores = run_score(self.expansions, self.run_dir)

        return {"expansions": self.expansions, "scores": self.scores, "blocked": False}

    def run_synthesize(
        self,
        dry_run_response: Optional[dict] = None,
    ) -> dict:
        """Phase 3: synthesize expansions into refined spec."""
        self.version += 1
        self.state.phase = "SYNTHESIZE"
        persist_state(self.state, self.state_path)

        feedback_str = "\n".join(self.feedback_history) if self.feedback_history else ""

        result = run_synthesize(
            state=self.state,
            config=self.config,
            idea_text=self.idea_text,
            expansions=self.expansions,
            scores=self.scores,
            run_dir=self.run_dir,
            version=self.version,
            feedback=feedback_str,
            dry_run=self.dry_run,
            dry_run_response=dry_run_response,
        )

        if result["blocked"]:
            return result

        self.refined_spec = result["refined_spec"]

        self.state.phase = "USER_REVIEW"
        persist_state(self.state, self.state_path)

        return {"refined_spec": self.refined_spec, "blocked": False, "converged": is_converged(self.refined_spec)}

    def handle_review(self, user_text: str) -> dict:
        """Process a user review response. Returns action info."""
        response = parse_review(user_text)

        if response.action == ReviewResponse.APPROVE:
            self.state.phase = "APPROVED"
            persist_state(self.state, self.state_path)
            return {"action": "approved"}

        if response.action == ReviewResponse.REJECT:
            self.state.phase = "STOPPED_BY_USER"
            persist_state(self.state, self.state_path)
            return {"action": "rejected"}

        # Accumulate feedback
        if response.action == ReviewResponse.DECISION:
            self.resolved_decisions[response.decision_id] = response.decision_answer
            self.feedback_history.append(f"Decision {response.decision_id}: {response.decision_answer}")
        elif response.action == ReviewResponse.ASSUMPTION:
            self.corrected_assumptions[response.assumption_id] = response.assumption_correction
            self.constraints.append(f"{response.assumption_id} correction: {response.assumption_correction}")
            self.feedback_history.append(f"Assumption {response.assumption_id}: {response.assumption_correction}")
        else:
            self.feedback_history.append(response.raw_text)

        revision = build_revision_request(self.version, [response])

        if self.version >= MAX_ITERATIONS:
            return {
                "action": "max_iterations",
                "message": "Max iterations reached. Reply 'approve' to proceed with current spec, or 'reject' to stop.",
            }

        return {
            "action": "revise",
            "needs_re_expand": needs_re_expand(revision),
            "revision": revision,
        }

    def run_handoff(self, user_id: int, base_config_path: Path) -> dict:
        """Phase 5: generate approved spec + task.md + config."""
        self.state.phase = "HANDOFF_TO_DEV"
        persist_state(self.state, self.state_path)

        result = run_handoff(
            refined_spec=self.refined_spec,
            user_id=user_id,
            run_dir=self.run_dir,
            base_config_path=base_config_path,
            resolved_decisions=self.resolved_decisions,
        )

        self.state.phase = "DONE"
        persist_state(self.state, self.state_path)

        return result

    def check_cost_cap(self) -> Optional[str]:
        """Check if ideation cost cap is exceeded."""
        if self.state.approx_cost_usd > IDEATION_COST_CAP:
            return f"Ideation cost exceeded: ${self.state.approx_cost_usd:.2f} > ${IDEATION_COST_CAP}"
        return None
