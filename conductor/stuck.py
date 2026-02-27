"""Stuck detection, tournament mode, and replan logic."""

from __future__ import annotations

import logging
from typing import Any, Optional

from conductor.state import RunState, PhaseLimits

log = logging.getLogger(__name__)


def stuck_detector(state: RunState) -> bool:
    """Deterministic stuck detection based on state history.
    Returns True if the builder appears stuck."""
    # Same failure signature 3 times in a row
    if len(state.fail_signatures) >= 3 and len(set(state.fail_signatures[-3:])) == 1:
        log.info("Stuck: same failure signature 3 times: %s", state.fail_signatures[-1])
        return True
    # Failing count not decreasing over 3 iterations
    if (len(state.failing_counts) >= 3
            and state.failing_counts[-1] >= state.failing_counts[-2] >= state.failing_counts[-3]):
        log.info("Stuck: failing test count not decreasing: %s", state.failing_counts[-3:])
        return True
    # Small diffs twice in a row while still failing
    if len(state.loc_changed) >= 2 and state.loc_changed[-1] < 10 and state.loc_changed[-2] < 10:
        log.info("Stuck: tiny LOC changes: %s", state.loc_changed[-2:])
        return True
    return False


def handle_stuck(
    state: RunState,
    phase_limits: PhaseLimits,
    tournament_enabled: bool,
) -> str:
    """Decide what to do when stuck. Returns one of:
    'replan', 'tournament', 'blocked'."""
    if state.stuck_replans_used < phase_limits.max_stuck_replans:
        state.stuck_replans_used += 1
        log.info("Stuck: attempting replan (%d/%d)", state.stuck_replans_used, phase_limits.max_stuck_replans)
        return "replan"
    if tournament_enabled and not state.tournament_used:
        state.tournament_used = True
        log.info("Stuck: triggering tournament mode")
        return "tournament"
    log.info("Stuck: no recovery options left, blocking")
    return "blocked"


def pick_tournament_winner(
    results: list[dict[str, Any]],
) -> Optional[int]:
    """Given tournament results [{passed: bool, fail_count: int, loc: int, branch: str}, ...],
    pick the winner index. Returns None if both fail equally."""
    if not results:
        return None

    # Sort by: passes_tests desc, fewer failures, simpler diff (less LOC)
    scored = []
    for i, r in enumerate(results):
        score = (
            1 if r.get("passed") else 0,
            -r.get("fail_count", 999),
            -r.get("loc", 99999),
        )
        scored.append((score, i))

    scored.sort(reverse=True)

    # If both fail with same count, no clear winner
    if len(scored) >= 2 and scored[0][0] == scored[1][0] and not results[scored[0][1]].get("passed"):
        return None

    return scored[0][1]
