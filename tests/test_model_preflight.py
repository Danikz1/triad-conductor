"""Tests for model authentication preflight checks."""

from __future__ import annotations

import subprocess

import pytest

from conductor.config import Config, ModelRef
from conductor.models import preflight


def _cp(args: list[str], code: int = 0, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=code, stdout=out, stderr=err)


def test_required_providers_deduplicates_and_sorts():
    cfg = Config(
        proposer_models=[
            ModelRef("claude", "proposer"),
            ModelRef("claude", "proposer"),
        ],
        arbiter_model=ModelRef("codex", "arbiter"),
        builder_model=ModelRef("codex", "builder"),
        reviewer_model=ModelRef("gemini", "reviewer"),
        qa_model=ModelRef("gemini", "qa"),
        optimizer_models=[],
    )

    assert preflight.required_providers(cfg) == ["claude", "codex", "gemini"]


def test_run_auth_preflight_detects_logged_out_claude(monkeypatch):
    def fake_run(cmd, text, capture_output, timeout):
        if cmd[:3] == ["claude", "auth", "status"]:
            return _cp(cmd, out='{"loggedIn": false, "authMethod": "none"}')
        if cmd[:3] == ["codex", "login", "status"]:
            return _cp(cmd, out="Logged in using ChatGPT")
        if cmd[0] == "gemini":
            return _cp(cmd, out='{"text":"OK"}')
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    checks = preflight.run_auth_preflight(Config(), timeout_seconds=5)
    by_provider = {c.provider: c for c in checks}
    assert by_provider["claude"].ok is False
    assert by_provider["codex"].ok is True
    assert by_provider["gemini"].ok is True


def test_ensure_required_auth_raises_with_login_hints(monkeypatch):
    def fake_run(cmd, text, capture_output, timeout):
        if cmd[:3] == ["claude", "auth", "status"]:
            return _cp(cmd, out='{"loggedIn": false}')
        if cmd[:3] == ["codex", "login", "status"]:
            return _cp(cmd, out="Not logged in")
        if cmd[0] == "gemini":
            return _cp(cmd, code=41, err="Interactive consent could not be obtained.")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc:
        preflight.ensure_required_auth(Config(), timeout_seconds=5)

    message = str(exc.value)
    assert "claude auth login" in message
    assert "codex login" in message
    assert "gemini" in message


def test_gemini_fallback_from_approval_mode_to_yolo(monkeypatch):
    gemini_calls: list[list[str]] = []

    def fake_run(cmd, text, capture_output, timeout):
        if cmd[:3] == ["claude", "auth", "status"]:
            return _cp(cmd, out='{"loggedIn": true}')
        if cmd[:3] == ["codex", "login", "status"]:
            return _cp(cmd, out="Logged in using ChatGPT")
        if cmd[0] == "gemini":
            gemini_calls.append(cmd)
            if "--approval-mode=yolo" in cmd:
                return _cp(cmd, code=1, err="unknown option: --approval-mode=yolo")
            return _cp(cmd, out='{"text":"OK"}')
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    checks = preflight.run_auth_preflight(Config(), timeout_seconds=5)
    by_provider = {c.provider: c for c in checks}
    assert by_provider["gemini"].ok is True
    assert len(gemini_calls) == 2
