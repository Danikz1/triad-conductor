"""Tests for Telegram RunnerManager command construction."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path


def _import_runner_module(monkeypatch):
    # Keep tests independent from optional telegram dependency installation.
    telegram_stub = types.ModuleType("telegram")
    telegram_stub.Bot = object
    monkeypatch.setitem(sys.modules, "telegram", telegram_stub)
    module = importlib.import_module("conductor.telegram.runner")
    return importlib.reload(module)


class _DummyProcess:
    def __init__(self):
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self._alive = False

    def send_signal(self, sig):
        self._alive = False


class _DummyTask:
    def done(self):
        return True

    def cancel(self):
        return None


def test_runner_forwards_project_root_and_dry_run(monkeypatch, tmp_path):
    runner_mod = _import_runner_module(monkeypatch)
    monkeypatch.setenv("TRIAD_TELEGRAM_AUTO_OPEN_MONITOR", "0")
    conductor_root = tmp_path / "triad-conductor"
    conductor_root.mkdir()
    (conductor_root / "conductor.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (conductor_root / "config.yaml").write_text("project:\n  name: test\n", encoding="utf-8")

    monkeypatch.setattr(runner_mod, "CONDUCTOR_ROOT", conductor_root)
    monkeypatch.setattr(runner_mod.uuid, "uuid4", lambda: types.SimpleNamespace(hex="abcdef1234567890"))

    captured = {}

    def fake_popen(cmd, cwd, stdout, stderr, text):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return _DummyProcess()

    def fake_create_task(coro):
        coro.close()
        return _DummyTask()

    monkeypatch.setattr(runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_mod.asyncio, "create_task", fake_create_task)

    manager = runner_mod.RunnerManager(bot=object())
    target_root = Path("/tmp/target-project")
    run_id = asyncio.run(
        manager.start_run(
            chat_id=1,
            task_text="build stuff",
            dry_run=True,
            project_root=target_root,
        )
    )

    assert run_id == "tg-abcdef12"
    cmd = captured["cmd"]
    assert "--dry-run" in cmd
    assert "--project-root" in cmd
    idx = cmd.index("--project-root")
    assert cmd[idx + 1] == str(target_root)
    assert captured["cwd"] == str(conductor_root)
    assert manager._runs[1].project_root == target_root


def test_runner_omits_optional_flags_when_not_provided(monkeypatch, tmp_path):
    runner_mod = _import_runner_module(monkeypatch)
    monkeypatch.setenv("TRIAD_TELEGRAM_AUTO_OPEN_MONITOR", "0")
    conductor_root = tmp_path / "triad-conductor"
    conductor_root.mkdir()
    (conductor_root / "conductor.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (conductor_root / "config.yaml").write_text("project:\n  name: test\n", encoding="utf-8")

    monkeypatch.setattr(runner_mod, "CONDUCTOR_ROOT", conductor_root)
    monkeypatch.setattr(runner_mod.uuid, "uuid4", lambda: types.SimpleNamespace(hex="0123456789abcdef"))

    captured = {}

    def fake_popen(cmd, cwd, stdout, stderr, text):
        captured["cmd"] = cmd
        return _DummyProcess()

    def fake_create_task(coro):
        coro.close()
        return _DummyTask()

    monkeypatch.setattr(runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_mod.asyncio, "create_task", fake_create_task)

    manager = runner_mod.RunnerManager(bot=object())
    run_id = asyncio.run(manager.start_run(chat_id=2, task_text="hello", dry_run=False, project_root=None))

    assert run_id == "tg-01234567"
    cmd = captured["cmd"]
    assert "--dry-run" not in cmd
    assert "--project-root" not in cmd
    assert manager._runs[2].project_root is None


def test_local_monitor_command_contains_expected_args(monkeypatch, tmp_path):
    runner_mod = _import_runner_module(monkeypatch)
    conductor_root = tmp_path / "triad-conductor"
    conductor_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(runner_mod, "CONDUCTOR_ROOT", conductor_root)
    manager = runner_mod.RunnerManager(bot=object())

    cmd = manager.local_monitor_command("tg-abc12345", Path("/tmp/project"))
    assert "conductor.telegram.live_monitor" in cmd
    assert "--run-id" in cmd
    assert "tg-abc12345" in cmd
    assert "--project-root" in cmd
    assert "/tmp/project" in cmd


def test_start_run_auto_opens_monitor_when_enabled(monkeypatch, tmp_path):
    runner_mod = _import_runner_module(monkeypatch)
    monkeypatch.setenv("TRIAD_TELEGRAM_AUTO_OPEN_MONITOR", "1")
    conductor_root = tmp_path / "triad-conductor"
    conductor_root.mkdir()
    (conductor_root / "conductor.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (conductor_root / "config.yaml").write_text("project:\n  name: test\n", encoding="utf-8")
    monkeypatch.setattr(runner_mod, "CONDUCTOR_ROOT", conductor_root)
    monkeypatch.setattr(runner_mod.uuid, "uuid4", lambda: types.SimpleNamespace(hex="facefeed12345678"))
    monkeypatch.setattr(runner_mod.sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(runner_mod.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None)

    captured = {"osascript_cmd": None}

    def fake_popen(cmd, cwd, stdout, stderr, text):
        return _DummyProcess()

    def fake_run(cmd, text, capture_output):
        captured["osascript_cmd"] = cmd
        return runner_mod.subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_create_task(coro):
        coro.close()
        return _DummyTask()

    monkeypatch.setattr(runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(runner_mod.asyncio, "create_task", fake_create_task)

    manager = runner_mod.RunnerManager(bot=object())
    asyncio.run(
        manager.start_run(
            chat_id=3,
            task_text="build",
            dry_run=False,
            project_root=Path("/tmp/project"),
        )
    )

    assert captured["osascript_cmd"] is not None
    assert captured["osascript_cmd"][0] == "osascript"


def test_queue_run_persists_in_store(monkeypatch, tmp_path):
    runner_mod = _import_runner_module(monkeypatch)
    store = runner_mod.TelegramStateStore(tmp_path / "telegram_state.db")
    manager = runner_mod.RunnerManager(bot=object(), store=store)

    queue_id = manager.queue_run(
        chat_id=9,
        task_text="# queued task",
        dry_run=True,
        project_root=Path("/tmp/project"),
    )

    assert queue_id > 0
    assert manager.queue_depth(9) == 1


def test_stuck_alert_respects_threshold_and_cooldown(monkeypatch, tmp_path):
    runner_mod = _import_runner_module(monkeypatch)
    monkeypatch.setenv("TRIAD_TELEGRAM_STUCK_ALERT_SECONDS", "5")
    monkeypatch.setenv("TRIAD_TELEGRAM_STUCK_ALERT_COOLDOWN_SECONDS", "60")

    manager = runner_mod.RunnerManager(bot=object())
    run = runner_mod.ActiveRun(
        run_id="tg-stuck",
        chat_id=1,
        process=_DummyProcess(),
        conductor_root=tmp_path,
        task_file=tmp_path / "task.md",
        project_root=tmp_path / "project",
    )
    run.last_phase_change_at = runner_mod.time.time() - 10
    state_path = tmp_path / "state.json"

    assert manager._should_send_stuck_alert(run, "PROPOSE", state_path) is True
    assert manager._should_send_stuck_alert(run, "PROPOSE", state_path) is False
