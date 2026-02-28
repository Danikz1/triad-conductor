"""Tests for Telegram handler project-root preparation helpers."""

from __future__ import annotations

import importlib
import subprocess
import sys
import types
from pathlib import Path


def _import_handlers_module(monkeypatch):
    telegram_stub = types.ModuleType("telegram")
    telegram_stub.Update = object
    monkeypatch.setitem(sys.modules, "telegram", telegram_stub)

    telegram_ext_stub = types.ModuleType("telegram.ext")
    telegram_ext_stub.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
    monkeypatch.setitem(sys.modules, "telegram.ext", telegram_ext_stub)

    runner_stub = types.ModuleType("conductor.telegram.runner")
    runner_stub.RunnerManager = object
    monkeypatch.setitem(sys.modules, "conductor.telegram.runner", runner_stub)

    module = importlib.import_module("conductor.telegram.handlers")
    return importlib.reload(module)


def _git(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)


def test_prepare_project_root_writes_project_md(monkeypatch, tmp_path):
    handlers = _import_handlers_module(monkeypatch)
    monkeypatch.setenv("TRIAD_PROJECTS_HOME", str(tmp_path))

    task = "# Mukhtar.AI\n\nBuild it."
    root = handlers._prepare_project_root("Mukhtar.AI", task)

    assert root == tmp_path / "Mukhtar.AI"
    assert (root / "project.md").read_text(encoding="utf-8") == task

    root2 = handlers._prepare_project_root("A/B Test", task)
    assert root2.name == "A-B-Test"


def test_ensure_git_repo_bootstraps_main_and_head(monkeypatch, tmp_path):
    handlers = _import_handlers_module(monkeypatch)
    project_root = tmp_path / "fresh-project"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "project.md").write_text("# Test\n", encoding="utf-8")

    handlers._ensure_git_repo(project_root)

    head = _git(["git", "rev-parse", "HEAD"], cwd=project_root)
    main_ref = _git(["git", "show-ref", "--verify", "--quiet", "refs/heads/main"], cwd=project_root)
    assert head.returncode == 0
    assert main_ref.returncode == 0


def test_clear_pending_task_also_clears_project_root(monkeypatch):
    handlers = _import_handlers_module(monkeypatch)
    context = types.SimpleNamespace(chat_data={})
    handlers._set_pending_task(context, "task text")
    handlers._set_pending_project_root(context, Path("/tmp/example"))

    handlers._clear_pending_task(context)

    assert handlers._get_pending_task(context) is None
    assert handlers._get_pending_project_root(context) is None
