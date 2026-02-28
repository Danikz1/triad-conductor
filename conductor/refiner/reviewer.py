"""Phase 4: USER REVIEW — parse user responses and classify feedback type."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

log = logging.getLogger(__name__)


class ReviewResponse:
    """Parsed result of a user's review message."""

    APPROVE = "approve"
    REJECT = "reject"
    DECISION = "decision"
    ASSUMPTION = "assumption"
    PUSHBACK = "pushback"

    def __init__(
        self,
        action: str,
        decision_id: Optional[str] = None,
        decision_answer: Optional[str] = None,
        assumption_id: Optional[str] = None,
        assumption_correction: Optional[str] = None,
        raw_text: str = "",
    ):
        self.action = action
        self.decision_id = decision_id
        self.decision_answer = decision_answer
        self.assumption_id = assumption_id
        self.assumption_correction = assumption_correction
        self.raw_text = raw_text


_APPROVE_WORDS = {"approve", "approved", "lgtm", "ship it", "ship", "yes", "ok", "go"}
_REJECT_WORDS = {"reject", "rejected", "cancel", "stop", "no", "abort"}

_DECISION_RE = re.compile(r"^(D\d+)\s*:\s*(.+)$", re.IGNORECASE)
_ASSUMPTION_RE = re.compile(r"^(A\d+)\s*:\s*(.+)$", re.IGNORECASE)


def parse_review(text: str) -> ReviewResponse:
    """Classify a user message into a ReviewResponse."""
    stripped = text.strip()
    lower = stripped.lower()

    # Check approval
    if lower in _APPROVE_WORDS:
        return ReviewResponse(action=ReviewResponse.APPROVE, raw_text=stripped)

    # Check rejection
    if lower in _REJECT_WORDS:
        return ReviewResponse(action=ReviewResponse.REJECT, raw_text=stripped)

    # Check decision answer: "D1: yes" or "D1: offline only"
    m = _DECISION_RE.match(stripped)
    if m:
        return ReviewResponse(
            action=ReviewResponse.DECISION,
            decision_id=m.group(1).upper(),
            decision_answer=m.group(2).strip(),
            raw_text=stripped,
        )

    # Check assumption correction: "A1: actually multi-user"
    m = _ASSUMPTION_RE.match(stripped)
    if m:
        return ReviewResponse(
            action=ReviewResponse.ASSUMPTION,
            assumption_id=m.group(1).upper(),
            assumption_correction=m.group(2).strip(),
            raw_text=stripped,
        )

    # Everything else is pushback
    return ReviewResponse(action=ReviewResponse.PUSHBACK, raw_text=stripped)


def build_revision_request(
    version: int,
    responses: list[ReviewResponse],
) -> dict[str, Any]:
    """Accumulate multiple user responses into a revision_request dict."""
    resolved_decisions: dict[str, str] = {}
    corrected_assumptions: dict[str, str] = {}
    raw_parts: list[str] = []

    for r in responses:
        if r.action == ReviewResponse.DECISION and r.decision_id and r.decision_answer:
            resolved_decisions[r.decision_id] = r.decision_answer
        elif r.action == ReviewResponse.ASSUMPTION and r.assumption_id and r.assumption_correction:
            corrected_assumptions[r.assumption_id] = r.assumption_correction
        elif r.action == ReviewResponse.PUSHBACK:
            raw_parts.append(r.raw_text)

    return {
        "version": version,
        "resolved_decisions": resolved_decisions,
        "corrected_assumptions": corrected_assumptions,
        "raw_feedback": "\n".join(raw_parts),
    }


def needs_re_expand(revision: dict) -> bool:
    """Determine if feedback is significant enough to re-run EXPAND.

    Re-expand if there are assumption corrections or substantive pushback.
    Simple decision answers only need re-synthesis.
    """
    if revision.get("corrected_assumptions"):
        return True
    raw = revision.get("raw_feedback", "").strip()
    if len(raw) > 20:
        return True
    return False


def is_converged(spec: dict) -> bool:
    """Check if the spec has no remaining open items."""
    decisions = spec.get("decisions_needed", [])
    assumptions = [a for a in spec.get("assumptions", []) if a.get("needs_confirmation")]
    return len(decisions) == 0 and len(assumptions) == 0
