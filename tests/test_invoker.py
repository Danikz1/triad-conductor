"""Tests for conductor.models.invoker module (mocked subprocess)."""

import subprocess
from unittest.mock import patch, MagicMock

from conductor.models.invoker import (
    _invoke_claude,
    _invoke_codex,
    _invoke_gemini,
    invoke_model,
    invoke_model_safe,
)


def test_invoke_model_dry_run():
    canned = {"kind": "proposal", "data": "test"}
    result = invoke_model("claude", "prompt", dry_run=True, dry_run_response=canned)
    assert result == canned


def test_invoke_model_dry_run_default():
    result = invoke_model("gemini", "prompt", dry_run=True)
    assert result["kind"] == "dry_run"
    assert result["model"] == "gemini"


def test_invoke_model_safe_dry_run():
    canned = {"kind": "test"}
    result, cost, err = invoke_model_safe("claude", "p", dry_run=True, dry_run_response=canned)
    assert result == canned
    assert err is None


def test_invoke_model_safe_error():
    with patch("conductor.models.invoker.invoke_model", side_effect=RuntimeError("fail")):
        result, cost, err = invoke_model_safe("claude", "prompt")
        assert result is None
        assert err is not None
        assert "fail" in err


def test_invoke_model_unknown():
    try:
        invoke_model("unknown_model", "prompt")
        assert False, "Should have raised"
    except ValueError as e:
        assert "Unknown model" in str(e)


def test_invoke_claude_respects_automation_toggle(monkeypatch):
    monkeypatch.setenv("TRIAD_AUTOMATE_PERMISSIONS", "0")
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout="{}", stderr=""
        )
        _invoke_claude("prompt")
        cmd = mock_run.call_args.args[0]
        assert "--dangerously-skip-permissions" not in cmd

    monkeypatch.setenv("TRIAD_AUTOMATE_PERMISSIONS", "1")
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout="{}", stderr=""
        )
        _invoke_claude("prompt")
        cmd = mock_run.call_args.args[0]
        assert "--dangerously-skip-permissions" in cmd


def test_invoke_claude_includes_model_flag():
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout="{}", stderr=""
        )
        _invoke_claude("prompt", model_id="opus")
        cmd = mock_run.call_args.args[0]
        assert "--model" in cmd
        assert "opus" in cmd


def test_invoke_codex_uses_full_auto_by_default(monkeypatch):
    monkeypatch.setenv("TRIAD_AUTOMATE_PERMISSIONS", "1")
    monkeypatch.setenv("TRIAD_DANGEROUS_AUTONOMY", "0")
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["codex"], returncode=0, stdout="{}", stderr=""
        )
        _invoke_codex("prompt")
        cmd = mock_run.call_args.args[0]
        assert "--full-auto" in cmd


def test_invoke_codex_uses_dangerous_bypass_when_enabled(monkeypatch):
    monkeypatch.setenv("TRIAD_AUTOMATE_PERMISSIONS", "1")
    monkeypatch.setenv("TRIAD_DANGEROUS_AUTONOMY", "1")
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["codex"], returncode=0, stdout="{}", stderr=""
        )
        _invoke_codex("prompt")
        cmd = mock_run.call_args.args[0]
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd


def test_invoke_codex_includes_model_flag(monkeypatch):
    monkeypatch.setenv("TRIAD_AUTOMATE_PERMISSIONS", "0")
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["codex"], returncode=0, stdout="{}", stderr=""
        )
        _invoke_codex("prompt", model_id="gpt-5.3-codex")
        cmd = mock_run.call_args.args[0]
        assert "--model" in cmd
        assert "gpt-5.3-codex" in cmd


def test_invoke_codex_falls_back_to_full_auto_on_unknown_option(monkeypatch):
    monkeypatch.setenv("TRIAD_AUTOMATE_PERMISSIONS", "1")
    monkeypatch.setenv("TRIAD_DANGEROUS_AUTONOMY", "0")
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["codex"], returncode=2, stdout="", stderr="unknown option: --full-auto"
            ),
            subprocess.CompletedProcess(
                args=["codex"], returncode=0, stdout="{}", stderr=""
            ),
        ]
        _invoke_codex("prompt")
        first_cmd = mock_run.call_args_list[0].args[0]
        second_cmd = mock_run.call_args_list[1].args[0]
        assert "--full-auto" in first_cmd
        assert "--full-auto" in second_cmd


def test_invoke_codex_fallback_preserves_model(monkeypatch):
    monkeypatch.setenv("TRIAD_AUTOMATE_PERMISSIONS", "1")
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["codex"], returncode=2, stdout="", stderr="unknown option: --full-auto"
            ),
            subprocess.CompletedProcess(
                args=["codex"], returncode=0, stdout="{}", stderr=""
            ),
        ]
        _invoke_codex("prompt", model_id="gpt-5.3-codex")
        second_cmd = mock_run.call_args_list[1].args[0]
        assert "--model" in second_cmd
        assert "gpt-5.3-codex" in second_cmd


def test_invoke_codex_falls_back_to_full_auto_on_unexpected_argument(monkeypatch):
    monkeypatch.setenv("TRIAD_AUTOMATE_PERMISSIONS", "1")
    monkeypatch.setenv("TRIAD_DANGEROUS_AUTONOMY", "0")
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["codex"], returncode=2, stdout="", stderr="error: unexpected argument found"
            ),
            subprocess.CompletedProcess(
                args=["codex"], returncode=0, stdout="{}", stderr=""
            ),
        ]
        _invoke_codex("prompt")
        first_cmd = mock_run.call_args_list[0].args[0]
        second_cmd = mock_run.call_args_list[1].args[0]
        assert "--full-auto" in first_cmd
        assert "--full-auto" in second_cmd


def test_invoke_gemini_falls_back_to_yolo_when_approval_mode_unknown(monkeypatch):
    monkeypatch.setenv("TRIAD_AUTOMATE_PERMISSIONS", "1")
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["gemini"],
                returncode=1,
                stdout="",
                stderr="unknown option: --approval-mode=yolo",
            ),
            subprocess.CompletedProcess(
                args=["gemini"], returncode=0, stdout="{}", stderr=""
            ),
        ]
        _invoke_gemini("prompt")
        first_cmd = mock_run.call_args_list[0].args[0]
        second_cmd = mock_run.call_args_list[1].args[0]
        assert "--approval-mode=yolo" in first_cmd
        assert "--yolo" in second_cmd


def test_invoke_gemini_includes_model_flag(monkeypatch):
    monkeypatch.setenv("TRIAD_AUTOMATE_PERMISSIONS", "0")
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["gemini"], returncode=0, stdout="{}", stderr=""
        )
        _invoke_gemini("prompt", model_id="gemini-2.5-pro")
        cmd = mock_run.call_args.args[0]
        assert "--model" in cmd
        assert "gemini-2.5-pro" in cmd


def test_invoke_gemini_falls_back_to_yolo_when_approval_unknown(monkeypatch):
    monkeypatch.setenv("TRIAD_AUTOMATE_PERMISSIONS", "1")
    with patch("conductor.models.invoker.subprocess.run") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["gemini"],
                returncode=1,
                stdout="",
                stderr="unknown option: --approval-mode=yolo",
            ),
            subprocess.CompletedProcess(
                args=["gemini"], returncode=0, stdout="{}", stderr=""
            ),
        ]
        _invoke_gemini("prompt")
        second_cmd = mock_run.call_args_list[1].args[0]
        assert "--yolo" in second_cmd
        assert "--approval-mode" not in " ".join(second_cmd)
