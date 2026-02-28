"""Phase 2: SCORE — heuristic scoring of expansions."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from conductor.state import save_json

log = logging.getLogger(__name__)

# Scoring weights (from final spec)
WEIGHTS = {
    "clarity": 0.25,
    "feasibility": 0.25,
    "coverage": 0.20,
    "consistency": 0.15,
    "specificity": 0.15,
}

# Minimum score threshold — below this, flag the section
CONFIDENCE_THRESHOLD = 5.0


def _score_clarity(exp: dict) -> float:
    """Score based on how specific and testable requirements are."""
    reqs = exp.get("requirements", {})
    must = reqs.get("must", [])
    # Penalize vague words
    vague_words = {"support", "handle", "manage", "various", "etc", "stuff", "things"}
    total_words = 0
    vague_count = 0
    for r in must:
        words = r.lower().split()
        total_words += len(words)
        vague_count += sum(1 for w in words if w in vague_words)

    if total_words == 0:
        return 2.0
    vague_ratio = vague_count / total_words
    base = 8.0 - (vague_ratio * 15)
    # Bonus for longer, more specific requirements
    avg_len = total_words / max(len(must), 1)
    if avg_len > 8:
        base += 1.0
    return max(1.0, min(10.0, base))


def _score_feasibility(exp: dict) -> float:
    """Score based on risk identification quality."""
    risks = exp.get("risks", [])
    if not risks:
        return 3.0
    score = 5.0
    for r in risks:
        if r.get("severity") in ("high", "medium"):
            score += 0.8
        if len(r.get("suggestion", "")) > 10:
            score += 0.5
    return min(10.0, score)


def _score_coverage(exp: dict) -> float:
    """Score based on field completeness."""
    required_sections = [
        "interpretation", "requirements", "assumptions",
        "open_questions", "risks", "success_criteria",
    ]
    filled = 0
    for section in required_sections:
        val = exp.get(section)
        if val and (isinstance(val, str) and len(val) > 5 or isinstance(val, (list, dict)) and len(val) > 0):
            filled += 1

    base = (filled / len(required_sections)) * 10

    # Check sub-fields in requirements
    reqs = exp.get("requirements", {})
    for key in ("must", "should", "could", "wont"):
        if reqs.get(key):
            base += 0.3

    return min(10.0, base)


def _score_consistency(exp: dict) -> float:
    """Score based on internal consistency (no contradictions)."""
    must = set(r.lower() for r in exp.get("requirements", {}).get("must", []))
    wont = set(r.lower() for r in exp.get("requirements", {}).get("wont", []))
    # If must and wont overlap, that's a contradiction
    overlap = must & wont
    if overlap:
        return 3.0
    return 8.0


def _score_specificity(exp: dict) -> float:
    """Score based on concrete success criteria."""
    criteria = exp.get("success_criteria", [])
    if not criteria:
        return 2.0

    score = 5.0
    for c in criteria:
        # Bonus for measurable criteria (contains numbers, "under X", "< X", etc.)
        if re.search(r"\d+", c):
            score += 1.5
        elif len(c) > 20:
            score += 0.5
    return min(10.0, score)


def score_expansion(expansion: dict, expansion_id: int) -> dict[str, Any]:
    """Score a single expansion using heuristics. Returns scored_expansion dict."""
    scores = {
        "clarity": round(_score_clarity(expansion), 1),
        "feasibility": round(_score_feasibility(expansion), 1),
        "coverage": round(_score_coverage(expansion), 1),
        "consistency": round(_score_consistency(expansion), 1),
        "specificity": round(_score_specificity(expansion), 1),
    }

    weighted_total = round(
        sum(scores[k] * WEIGHTS[k] for k in WEIGHTS), 2
    )

    flags = []
    for criterion, score in scores.items():
        if score < CONFIDENCE_THRESHOLD:
            flags.append(f"low_{criterion}")

    return {
        "expansion_id": expansion_id,
        "role": expansion.get("role", "unknown"),
        "scores": scores,
        "weighted_total": weighted_total,
        "section_rankings": {},  # Filled in by rank_expansions
        "flags": flags,
    }


def rank_expansions(scored: list[dict]) -> list[dict]:
    """Assign section_rankings across all scored expansions."""
    sections = ["requirements", "risks", "success_criteria", "assumptions", "open_questions"]

    # For each section, rank by weighted_total (simplification — full version would
    # score per section, but heuristic MVP uses overall score as proxy)
    sorted_by_score = sorted(scored, key=lambda s: s["weighted_total"], reverse=True)
    for rank, s in enumerate(sorted_by_score, 1):
        for section in sections:
            s["section_rankings"][section] = rank

    return scored


def run_score(
    expansions: list[dict],
    run_dir: Path,
) -> list[dict]:
    """Score all expansions and return ranked scored_expansion list."""
    log.info("=== TRIAD ARCHITECT: SCORE ===")

    scored = [score_expansion(exp, i) for i, exp in enumerate(expansions)]
    scored = rank_expansions(scored)

    # Save
    scores_dir = run_dir / "artifacts" / "scores"
    scores_dir.mkdir(parents=True, exist_ok=True)
    for s in scored:
        save_json(scores_dir / f"scored_expansion_{s['expansion_id']}.json", s)

    for s in scored:
        log.info(
            "  %s: %.2f (flags: %s)",
            s["role"], s["weighted_total"],
            ", ".join(s["flags"]) or "none",
        )

    return scored
