"""Tests for conductor.state module."""

import time
from pathlib import Path

from conductor.state import (
    RunState, Limits, PhaseLimits,
    check_breakers, persist_state, load_state, save_json, load_json, now_ts,
)


def test_runstate_defaults():
    s = RunState(run_id="test-1", started_at=1000.0, phase="INTAKE")
    assert s.milestone_index == 0
    assert s.fail_signatures == []
    assert s.failing_counts == []
    assert s.loc_changed == []


def test_runstate_to_dict_from_dict():
    s = RunState(run_id="test-1", started_at=1000.0, phase="BUILD", milestone_index=2)
    d = s.to_dict()
    assert d["run_id"] == "test-1"
    assert d["phase"] == "BUILD"
    s2 = RunState.from_dict(d)
    assert s2.run_id == s.run_id
    assert s2.milestone_index == 2


def test_check_breakers_none():
    s = RunState(run_id="test", started_at=now_ts(), phase="BUILD")
    limits = Limits()
    assert check_breakers(s, limits) is None


def test_check_breakers_wall_time():
    s = RunState(run_id="test", started_at=now_ts() - 6000, phase="BUILD")
    limits = Limits(max_wall_time_minutes=1)
    result = check_breakers(s, limits)
    assert result is not None
    assert "Wall-time" in result


def test_check_breakers_tool_calls():
    s = RunState(run_id="test", started_at=now_ts(), phase="BUILD", tool_calls_used=300)
    limits = Limits(max_total_tool_calls=200)
    result = check_breakers(s, limits)
    assert "Tool calls" in result


def test_check_breakers_cost():
    s = RunState(run_id="test", started_at=now_ts(), phase="BUILD", approx_cost_usd=30.0)
    limits = Limits(max_total_cost_usd=25.0)
    result = check_breakers(s, limits)
    assert "Cost" in result


def test_persist_and_load(tmp_dir):
    path = tmp_dir / "state.json"
    s = RunState(run_id="test-persist", started_at=1234.0, phase="PROPOSE")
    persist_state(s, path)
    assert path.exists()
    s2 = load_state(path)
    assert s2.run_id == "test-persist"
    assert s2.phase == "PROPOSE"


def test_save_load_json(tmp_dir):
    path = tmp_dir / "data.json"
    data = {"key": "value", "num": 42}
    save_json(path, data)
    loaded = load_json(path)
    assert loaded == data
