"""Tests for CLI run command behavior."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import conductor.cli as cli
from conductor.state import RunState, persist_state, now_ts


class _DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def exception(self, *args, **kwargs):
        return None


def test_resume_done_run_exits_success(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "setup_logging", lambda run_dir: _DummyLogger())
    monkeypatch.setattr(cli.signal, "signal", lambda *args, **kwargs: None)

    run_id = "resume-done"
    task_path = tmp_path / "task.md"
    task_path.write_text("# Task\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")

    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(
        run_id=run_id,
        started_at=now_ts(),
        phase="DONE",
    )
    persist_state(state, run_dir / "state.json")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "conductor.py",
            "run",
            "--task",
            str(task_path),
            "--config",
            str(config_path),
            "--run-id",
            run_id,
            "--resume",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0


def test_done_state_exit_code_mapping():
    success = RunState(run_id="r1", started_at=now_ts(), phase="DONE", final_status="SUCCESS")
    blocked = RunState(run_id="r2", started_at=now_ts(), phase="DONE", final_status="BLOCKED")
    partial = RunState(run_id="r3", started_at=now_ts(), phase="DONE", final_status="PARTIAL")
    implicit_blocked = RunState(
        run_id="r4",
        started_at=now_ts(),
        phase="DONE",
        final_status=None,
        breaker_reason="some error",
    )

    assert cli._exit_code_for_done_state(success) == 0
    assert cli._exit_code_for_done_state(blocked) == 1
    assert cli._exit_code_for_done_state(partial) == 2
    assert cli._exit_code_for_done_state(implicit_blocked) == 1


def test_run_exits_when_auth_preflight_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "setup_logging", lambda run_dir: _DummyLogger())
    monkeypatch.setattr(cli.signal, "signal", lambda *args, **kwargs: None)
    def _raise_auth_error(config):
        raise RuntimeError("auth failed")
    monkeypatch.setattr(cli, "ensure_required_auth", _raise_auth_error)

    run_id = "auth-preflight-fail"
    task_path = tmp_path / "task.md"
    task_path.write_text("# Task\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "conductor.py",
            "run",
            "--task",
            str(task_path),
            "--config",
            str(config_path),
            "--run-id",
            run_id,
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 3
