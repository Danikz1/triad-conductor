"""Tests for `conductor doctor` CLI subcommand."""

from __future__ import annotations

import sys

import pytest

import conductor.cli as cli
import conductor.doctor as doctor


def test_doctor_command_exits_zero_on_ok(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        doctor,
        "run_doctor",
        lambda **kwargs: {
            "ok": True,
            "command_checks": [],
            "version_checks": [],
            "auth_checks": [],
        },
    )
    monkeypatch.setattr(doctor, "format_doctor_report", lambda report: "REPORT-OK")
    monkeypatch.setattr(
        sys,
        "argv",
        ["conductor.py", "doctor", "--config", str(cfg)],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "REPORT-OK" in out


def test_doctor_command_json_output_exits_nonzero_on_fail(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        doctor,
        "run_doctor",
        lambda **kwargs: {
            "ok": False,
            "command_checks": [],
            "version_checks": [],
            "auth_checks": [],
        },
    )
    monkeypatch.setattr(doctor, "doctor_json", lambda report: '{"ok": false}')
    monkeypatch.setattr(
        sys,
        "argv",
        ["conductor.py", "doctor", "--config", str(cfg), "--json"],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    out = capsys.readouterr().out
    assert exc.value.code == 3
    assert '{"ok": false}' in out

