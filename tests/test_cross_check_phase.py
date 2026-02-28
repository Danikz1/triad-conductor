"""Tests for CROSS_CHECK re-entry behavior."""

from __future__ import annotations

import conductor.phases.cross_check as cross_check_phase
from conductor.config import Config
from conductor.state import Limits, PhaseLimits, RunState, now_ts


def test_cross_check_rewinds_milestone_index_for_rework(tmp_path, monkeypatch):
    monkeypatch.setattr(cross_check_phase, "get_diff", lambda *args, **kwargs: "diff")
    monkeypatch.setattr(cross_check_phase, "render_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(cross_check_phase, "validate", lambda *args, **kwargs: [])

    calls = {"count": 0}

    def fake_invoke_model_safe(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return (
                {
                    "kind": "review",
                    "verdict": "REQUEST_CHANGES",
                    "requested_changes": ["Fix edge case in auth"],
                    "blockers": [],
                },
                0.0,
                None,
            )
        return (
            {
                "kind": "qa",
                "verdict": "FAIL",
                "concerns": [
                    {
                        "severity": "high",
                        "title": "Missing regression test",
                        "suggested_test_or_fix": "Add test for auth edge case",
                    }
                ],
            },
            0.0,
            None,
        )

    monkeypatch.setattr(cross_check_phase, "invoke_model_safe", fake_invoke_model_safe)

    state = RunState(
        run_id="run-cc-rework",
        started_at=now_ts(),
        phase="CROSS_CHECK",
        milestone_index=3,
    )
    master_plan = {
        "milestones": [
            {"id": "M1"},
            {"id": "M2"},
            {"id": "M3"},
        ]
    }
    context = {
        "project_root": tmp_path,
        "branches": {"anchor": "main", "integrate": "run/int"},
        "last_test_output": "ok",
    }

    result = cross_check_phase.run_cross_check(
        state=state,
        config=Config(),
        master_plan=master_plan,
        context=context,
        run_dir=tmp_path / "run",
        limits=Limits(),
        phase_limits=PhaseLimits(max_review_loops=3),
    )

    assert result["clean"] is False
    assert state.phase == "BUILD"
    assert state.build_iteration == 0
    assert state.milestone_index == 2
    assert "change_requests" in context
    assert any("Fix edge case in auth" in item for item in context["change_requests"])
