"""Tests for OPTIMIZE phase failure handling and patch revert cleanup."""

from __future__ import annotations

import subprocess
from pathlib import Path

import conductor.phases.optimize as optimize_phase
from conductor.config import Config, ModelRef
from conductor.state import Limits, PhaseLimits, RunState, now_ts


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True)


def test_revert_failed_patch_restores_tracked_and_cleans_untracked(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)

    tracked = repo / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    _run(["git", "add", "tracked.txt"], cwd=repo)
    _run(["git", "commit", "-m", "init"], cwd=repo)

    before_untracked = optimize_phase._list_untracked_files(repo)
    tracked.write_text("modified\n", encoding="utf-8")
    (repo / "new_file.txt").write_text("temp\n", encoding="utf-8")

    optimize_phase._revert_failed_patch(repo, before_untracked)

    assert tracked.read_text(encoding="utf-8") == "original\n"
    assert not (repo / "new_file.txt").exists()


def test_run_optimize_blocks_when_commit_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(optimize_phase, "get_diff", lambda *args, **kwargs: "diff")
    monkeypatch.setattr(optimize_phase, "render_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(optimize_phase, "validate", lambda *args, **kwargs: [])
    monkeypatch.setattr(optimize_phase, "run_tests", lambda cmd, cwd: (True, "ok"))
    monkeypatch.setattr(optimize_phase, "commit_all", lambda cwd, msg: False)
    monkeypatch.setattr(optimize_phase, "merge_builder_to_integrate", lambda *args, **kwargs: True)
    monkeypatch.setattr(optimize_phase, "_list_untracked_files", lambda cwd: set())
    monkeypatch.setattr(optimize_phase, "_revert_failed_patch", lambda cwd, before: None)

    def fake_invoke_model_safe(**kwargs):
        return (
            {
                "kind": "optimization",
                "suggestions": [
                    {
                        "title": "Speed up hot path",
                        "patch_unified_diff": (
                            "diff --git a/app.py b/app.py\n"
                            "--- a/app.py\n"
                            "+++ b/app.py\n"
                            "@@ -1 +1 @@\n"
                            "-print('slow')\n"
                            "+print('fast')\n"
                        ),
                    }
                ],
            },
            0.0,
            None,
        )

    monkeypatch.setattr(optimize_phase, "invoke_model_safe", fake_invoke_model_safe)

    def fake_subprocess_run(cmd, **kwargs):
        if cmd[:2] == ["git", "apply"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(optimize_phase.subprocess, "run", fake_subprocess_run)

    state = RunState(run_id="run-opt-commit-fail", started_at=now_ts(), phase="OPTIMIZE")
    context = {
        "branches": {"anchor": "main", "integrate": "run/int", "builder": "run/bld"},
        "project_root": tmp_path,
        "builder_worktree": tmp_path / "wt",
        "last_test_output": "",
    }
    context["builder_worktree"].mkdir(parents=True, exist_ok=True)
    master_plan = {"test_matrix": {"full": ["pytest"]}}

    result = optimize_phase.run_optimize(
        state=state,
        config=Config(optimizer_models=[ModelRef(name="codex", role="optimizer")]),
        master_plan=master_plan,
        context=context,
        run_dir=tmp_path / "run",
        limits=Limits(),
        phase_limits=PhaseLimits(max_optimize_passes=2),
    )

    assert result["applied"] == []
    assert state.phase == "REPORT"
    assert state.breaker_reason == "Git commit failed for optimization: Speed up hot path"
