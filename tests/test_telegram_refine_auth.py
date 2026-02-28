"""Tests for Telegram /refine auth preflight behavior."""

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
        self.replies: list[str] = []

    async def reply_text(self, text: str, parse_mode=None):
        self.replies.append(text)


class _DummyUpdate:
    def __init__(self):
        self.message = _DummyMessage()
        self.effective_user = types.SimpleNamespace(id=1)
        self.effective_chat = types.SimpleNamespace(id=1)


def test_refine_reports_auth_preflight_failure(monkeypatch, tmp_path):
    handlers = _import_handlers_module(monkeypatch)
    monkeypatch.setattr(handlers, "CONDUCTOR_ROOT", tmp_path)
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")

    import conductor.models.preflight as preflight

    def _raise_auth_error(config):
        raise RuntimeError("claude not logged in")

    monkeypatch.setattr(preflight, "ensure_required_auth", _raise_auth_error)

    update = _DummyUpdate()
    context = types.SimpleNamespace(args=[], chat_data={"pending_task": "# Idea"})

    asyncio.run(handlers.refine_cmd(update, context))

    assert update.message.replies
    assert "Model auth preflight failed." in update.message.replies[0]
    assert "/consilium" in update.message.replies[0]
    assert "refiner_engine" not in context.chat_data
