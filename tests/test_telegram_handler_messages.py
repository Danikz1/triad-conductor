"""Tests for Telegram handler help/intake prompt text."""

from __future__ import annotations

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


def test_help_message_lists_consilium_and_develop(monkeypatch):
    handlers = _import_handlers_module(monkeypatch)
    text = handlers._help_message()
    assert "/consilium" in text
    assert "/refine" in text
    assert "/run" in text
    assert "/develop" in text
    assert "/health" in text
    assert "/logs" in text
    assert "/approve" in text


def test_next_step_prompt_offers_two_paths(monkeypatch):
    handlers = _import_handlers_module(monkeypatch)
    text = handlers._next_step_prompt("preview text", source_name="project.md")
    assert "Task stored from" in text
    assert "/consilium" in text
    assert "/run" in text
