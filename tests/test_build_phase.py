"""Tests for BUILD phase prompt wiring and feedback carryover."""

from pathlib import Path

import conductor.phases.build as build_phase
from conductor.config import Config
from conductor.state import Limits, PhaseLimits, RunState, now_ts


def _minimal_master_plan() -> dict:
    return {
        "milestones": [{"id": "M1", "title": "Do the thing"}],
        "test_matrix": {
            "smoke": ["pytest"],
            "full": ["pytest"],
        },
    }


def _minimal_context(tmp_path: Path) -> dict:
    return {
        "project_root": tmp_path,
        "task_text": "task text",
        "branches": {"integrate": "int", "builder": "bld"},
        "builder_worktree": tmp_path / "wt",
        "master_plan": None,
        "last_test_output": "",
    }


def _patch_success_path(monkeypatch):
    monkeypatch.setattr(build_phase, "get_diff", lambda *args, **kwargs: "diff")
    monkeypatch.setattr(build_phase, "invoke_model_safe", lambda **kwargs: ({"kind": "build_update"}, 0.0, None))
    monkeypatch.setattr(build_phase, "validate", lambda data, schema: [])
    monkeypatch.setattr(build_phase, "run_tests", lambda cmd, cwd: (True, "ok"))
    monkeypatch.setattr(build_phase, "commit_all", lambda cwd, msg: True)
    monkeypatch.setattr(build_phase, "merge_builder_to_integrate", lambda *args, **kwargs: True)


def test_run_build_includes_change_requests_in_prompt(tmp_path, monkeypatch):
    captured = {}
    _patch_success_path(monkeypatch)

    def fake_render_prompt(name: str, variables: dict) -> str:
        captured["variables"] = variables
        return "prompt"

    monkeypatch.setattr(build_phase, "render_prompt", fake_render_prompt)

    state = RunState(run_id="run-build-1", started_at=now_ts(), phase="BUILD")
    context = _minimal_context(tmp_path)
    context["change_requests"] = ["[BLOCKER] fix auth flow", "[QA-HIGH] add missing test"]

    result = build_phase.run_build(
        state=state,
        config=Config(),
        master_plan=_minimal_master_plan(),
        context=context,
        run_dir=tmp_path / "run",
        limits=Limits(),
        phase_limits=PhaseLimits(max_build_iterations=2),
    )

    assert result["completed"] is True
    assert state.phase == "CROSS_CHECK"
    assert "CHANGE_REQUESTS" in captured["variables"]
    assert "fix auth flow" in captured["variables"]["CHANGE_REQUESTS"]
    assert "add missing test" in captured["variables"]["CHANGE_REQUESTS"]


def test_run_build_defaults_change_requests_to_none(tmp_path, monkeypatch):
    captured = {}
    _patch_success_path(monkeypatch)

    def fake_render_prompt(name: str, variables: dict) -> str:
        captured["variables"] = variables
        return "prompt"

    monkeypatch.setattr(build_phase, "render_prompt", fake_render_prompt)

    state = RunState(run_id="run-build-2", started_at=now_ts(), phase="BUILD")
    context = _minimal_context(tmp_path)

    result = build_phase.run_build(
        state=state,
        config=Config(),
        master_plan=_minimal_master_plan(),
        context=context,
        run_dir=tmp_path / "run",
        limits=Limits(),
        phase_limits=PhaseLimits(max_build_iterations=2),
    )

    assert result["completed"] is True
    assert captured["variables"]["CHANGE_REQUESTS"] == "(none)"


def test_run_build_blocks_when_commit_fails(tmp_path, monkeypatch):
    _patch_success_path(monkeypatch)
    monkeypatch.setattr(build_phase, "commit_all", lambda cwd, msg: False)

    state = RunState(run_id="run-build-commit-fail", started_at=now_ts(), phase="BUILD")
    context = _minimal_context(tmp_path)

    result = build_phase.run_build(
        state=state,
        config=Config(),
        master_plan=_minimal_master_plan(),
        context=context,
        run_dir=tmp_path / "run",
        limits=Limits(),
        phase_limits=PhaseLimits(max_build_iterations=2),
    )

    assert result["completed"] is False
    assert state.phase == "REPORT"
    assert state.breaker_reason == "Git commit failed for milestone M1"


def test_run_build_blocks_when_merge_fails(tmp_path, monkeypatch):
    _patch_success_path(monkeypatch)
    monkeypatch.setattr(build_phase, "merge_builder_to_integrate", lambda *args, **kwargs: False)

    state = RunState(run_id="run-build-merge-fail", started_at=now_ts(), phase="BUILD")
    context = _minimal_context(tmp_path)

    result = build_phase.run_build(
        state=state,
        config=Config(),
        master_plan=_minimal_master_plan(),
        context=context,
        run_dir=tmp_path / "run",
        limits=Limits(),
        phase_limits=PhaseLimits(max_build_iterations=2),
    )

    assert result["completed"] is False
    assert state.phase == "REPORT"
    assert state.breaker_reason == "Git merge failed for milestone M1"
