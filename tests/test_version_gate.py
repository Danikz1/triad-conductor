"""Tests for provider CLI minimum-version gate."""

from __future__ import annotations

import pytest

from conductor.config import Config
from conductor.models import version_gate


def test_parse_semver_handles_common_version_lines():
    assert version_gate._parse_semver("claude 2.1.63") == (2, 1, 63)
    assert version_gate._parse_semver("codex-cli 0.106.0") == (0, 106, 0)
    assert version_gate._parse_semver("version unknown") is None


def test_run_version_gate_marks_old_version_as_failure(monkeypatch):
    cfg = Config()
    monkeypatch.setattr(version_gate, "required_providers", lambda _cfg: ["codex"])
    monkeypatch.setattr(version_gate, "_get_provider_version", lambda provider: "codex-cli 0.100.0")

    checks = version_gate.run_version_gate(cfg)

    assert len(checks) == 1
    assert checks[0].provider == "codex"
    assert checks[0].ok is False
    assert checks[0].min_version == "0.106.0"


def test_ensure_supported_cli_versions_raises_on_failure(monkeypatch):
    cfg = Config()
    monkeypatch.setattr(version_gate, "required_providers", lambda _cfg: ["gemini"])
    monkeypatch.setattr(version_gate, "_get_provider_version", lambda provider: "gemini 0.20.0")

    with pytest.raises(RuntimeError) as exc:
        version_gate.ensure_supported_cli_versions(cfg)

    assert "version gate failed" in str(exc.value).lower()
    assert "gemini" in str(exc.value).lower()

