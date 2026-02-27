"""Tests for conductor.stuck module."""

from conductor.state import RunState, PhaseLimits
from conductor.stuck import stuck_detector, handle_stuck, pick_tournament_winner


def _make_state(**kwargs):
    defaults = {"run_id": "test", "started_at": 1000.0, "phase": "BUILD"}
    defaults.update(kwargs)
    return RunState(**defaults)


def test_stuck_same_signature_3x():
    s = _make_state(fail_signatures=["sig_a", "sig_a", "sig_a"])
    assert stuck_detector(s) is True


def test_stuck_different_signatures():
    s = _make_state(fail_signatures=["sig_a", "sig_b", "sig_c"])
    assert stuck_detector(s) is False


def test_stuck_failing_count_not_decreasing():
    s = _make_state(failing_counts=[3, 3, 3])
    assert stuck_detector(s) is True


def test_stuck_failing_count_decreasing():
    s = _make_state(failing_counts=[5, 3, 1])
    assert stuck_detector(s) is False


def test_stuck_small_loc_changes():
    s = _make_state(loc_changed=[5, 3])
    assert stuck_detector(s) is True


def test_stuck_large_loc_changes():
    s = _make_state(loc_changed=[50, 30])
    assert stuck_detector(s) is False


def test_handle_stuck_replan():
    s = _make_state(stuck_replans_used=0)
    pl = PhaseLimits(max_stuck_replans=1)
    result = handle_stuck(s, pl, tournament_enabled=True)
    assert result == "replan"
    assert s.stuck_replans_used == 1


def test_handle_stuck_tournament():
    s = _make_state(stuck_replans_used=1, tournament_used=False)
    pl = PhaseLimits(max_stuck_replans=1)
    result = handle_stuck(s, pl, tournament_enabled=True)
    assert result == "tournament"
    assert s.tournament_used is True


def test_handle_stuck_blocked():
    s = _make_state(stuck_replans_used=1, tournament_used=True)
    pl = PhaseLimits(max_stuck_replans=1)
    result = handle_stuck(s, pl, tournament_enabled=True)
    assert result == "blocked"


def test_handle_stuck_no_tournament():
    s = _make_state(stuck_replans_used=1)
    pl = PhaseLimits(max_stuck_replans=1)
    result = handle_stuck(s, pl, tournament_enabled=False)
    assert result == "blocked"


def test_pick_tournament_winner_one_passes():
    results = [
        {"passed": True, "fail_count": 0, "loc": 50, "branch": "A"},
        {"passed": False, "fail_count": 3, "loc": 30, "branch": "B"},
    ]
    assert pick_tournament_winner(results) == 0


def test_pick_tournament_winner_both_pass():
    results = [
        {"passed": True, "fail_count": 0, "loc": 100, "branch": "A"},
        {"passed": True, "fail_count": 0, "loc": 50, "branch": "B"},
    ]
    # Simpler diff (less LOC) wins
    assert pick_tournament_winner(results) == 1


def test_pick_tournament_winner_both_fail_equally():
    results = [
        {"passed": False, "fail_count": 3, "loc": 50, "branch": "A"},
        {"passed": False, "fail_count": 3, "loc": 50, "branch": "B"},
    ]
    assert pick_tournament_winner(results) is None


def test_pick_tournament_winner_empty():
    assert pick_tournament_winner([]) is None
