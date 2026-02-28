"""Tests for Telegram runner post-run publish behavior."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from pathlib import Path


def _import_runner_module(monkeypatch):
    telegram_stub = types.ModuleType("telegram")
    telegram_stub.Bot = object
    monkeypatch.setitem(sys.modules, "telegram", telegram_stub)
    module = importlib.import_module("conductor.telegram.runner")
    return importlib.reload(module)


class _DummyProcess:
    def poll(self):
        return 0

    def terminate(self):
        return None

    def send_signal(self, sig):
        return None


class _DummyBot:
    def __init__(self):
        self.messages = []
        self.documents = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.messages.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})

    async def send_document(self, chat_id, document, filename=None, caption=None):
        self.documents.append(
            {"chat_id": chat_id, "document": document, "filename": filename, "caption": caption}
        )


def test_write_project_description_uses_project_name_prefix(monkeypatch, tmp_path):
    runner_mod = _import_runner_module(monkeypatch)
    bot = _DummyBot()
    manager = runner_mod.RunnerManager(bot=bot)

    project_root = tmp_path / "project-root"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "project.md").write_text("# Mukhtar AI\n\nBuild a smart assistant.", encoding="utf-8")

    task_file = tmp_path / "task.md"
    task_file.write_text("# fallback\n", encoding="utf-8")

    run = runner_mod.ActiveRun(
        run_id="tg-abc12345",
        chat_id=7,
        process=_DummyProcess(),
        conductor_root=tmp_path,
        task_file=task_file,
        project_root=project_root,
    )

    description_path = manager._write_project_description(
        project_root=project_root,
        run=run,
        state={"phase": "DONE", "approx_cost_usd": 1.2, "tool_calls_used": 5},
        run_status="SUCCESS",
        run_report={"status": "SUCCESS", "summary": "ok"},
        github_url="https://github.com/acme/mukhtar-ai",
        artifacts=["artifacts/final_report.json"],
    )

    assert description_path.name == "Mukhtar-AI_PROJECT_DESCRIPTION.md"
    assert description_path.exists()
    text = description_path.read_text(encoding="utf-8")
    assert "Latest Build Run" in text
    assert "https://github.com/acme/mukhtar-ai" in text


def test_send_completion_sends_publish_report(monkeypatch, tmp_path):
    runner_mod = _import_runner_module(monkeypatch)
    bot = _DummyBot()
    manager = runner_mod.RunnerManager(bot=bot)

    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    task_file = tmp_path / "task.md"
    task_file.write_text("# Task\n", encoding="utf-8")

    run = runner_mod.ActiveRun(
        run_id="tg-finish",
        chat_id=99,
        process=_DummyProcess(),
        conductor_root=tmp_path,
        task_file=task_file,
        project_root=project_root,
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "run_id": run.run_id,
                "phase": "DONE",
                "approx_cost_usd": 2.5,
                "tool_calls_used": 10,
                "started_at": 0,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        manager,
        "_publish_project",
        lambda _run, _state: {
            "project_root": str(project_root),
            "description_path": str(project_root / "Mukhtar-AI_PROJECT_DESCRIPTION.md"),
            "description_updated": True,
            "github_checked": True,
            "github_created": True,
            "github_pushed": True,
            "github_url": "https://github.com/acme/mukhtar-ai",
            "run_status": "SUCCESS",
            "errors": [],
        },
    )
    monkeypatch.setattr(runner_mod, "format_publish_report", lambda report: "PUBLISH-REPORT")

    asyncio.run(manager._send_completion(run, state_path))

    texts = [m["text"] for m in bot.messages]
    assert any("Run complete" in t for t in texts)
    assert "PUBLISH-REPORT" in texts
    assert len(bot.documents) == 1


def test_normalize_github_remote(monkeypatch):
    runner_mod = _import_runner_module(monkeypatch)
    assert (
        runner_mod._normalize_github_remote("git@github.com:owner/repo.git")
        == "https://github.com/owner/repo"
    )
    assert (
        runner_mod._normalize_github_remote("https://github.com/owner/repo.git")
        == "https://github.com/owner/repo"
    )
