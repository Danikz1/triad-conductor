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


def test_runner_omits_optional_flags_when_not_provided(monkeypatch, tmp_path):
    runner_mod = _import_runner_module(monkeypatch)
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
