"""Tests for Telegram /health and /logs handlers."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types


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


class _DummyMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text: str, parse_mode=None):
        self.replies.append(text)


class _DummyUpdate:
    def __init__(self):
        self.message = _DummyMessage()
        self.effective_user = types.SimpleNamespace(id=1)
        self.effective_chat = types.SimpleNamespace(id=77)


class _DummyRunner:
    def __init__(self, *, health=None, logs=None, active_run_id="tg-abc", queue_depth=0):
        self._health = health
        self._logs = logs
        self._run_id = active_run_id
        self._queue_depth = queue_depth

    def get_health(self, chat_id):
        return self._health

    def get_recent_logs(self, chat_id, lines=20):
        return self._logs

    def active_run_id(self, chat_id):
        return self._run_id

    def queue_depth(self, chat_id):
        return self._queue_depth


def test_health_cmd_returns_formatted_health(monkeypatch):
    handlers = _import_handlers_module(monkeypatch)
    update = _DummyUpdate()
    runner = _DummyRunner(
        health={
            "run_id": "tg-health1",
            "phase": "PROPOSE",
            "phase_age_seconds": 120.0,
            "state_age_seconds": 8.0,
            "last_activity": "still proposing",
            "queue_depth": 1,
            "stuck_threshold_seconds": 600.0,
            "is_stuck": False,
        }
    )
    context = types.SimpleNamespace(args=[], bot_data={"runner": runner}, chat_data={})

    asyncio.run(handlers.health_cmd(update, context))

    assert update.message.replies
    assert "Health" in update.message.replies[0]
    assert "tg-health1" in update.message.replies[0]


def test_logs_cmd_returns_tail(monkeypatch):
    handlers = _import_handlers_module(monkeypatch)
    update = _DummyUpdate()
    runner = _DummyRunner(logs=["line 1", "line 2"], active_run_id="tg-logs1")
    context = types.SimpleNamespace(args=["2"], bot_data={"runner": runner}, chat_data={})

    asyncio.run(handlers.logs_cmd(update, context))

    assert update.message.replies
    assert "Recent Logs" in update.message.replies[0]
    assert "line 2" in update.message.replies[0]


def test_logs_cmd_without_active_run(monkeypatch):
    handlers = _import_handlers_module(monkeypatch)
    update = _DummyUpdate()
    runner = _DummyRunner(logs=None, active_run_id=None)
    context = types.SimpleNamespace(args=[], bot_data={"runner": runner}, chat_data={})

    asyncio.run(handlers.logs_cmd(update, context))

    assert update.message.replies
    assert update.message.replies[0] == "No active run."

