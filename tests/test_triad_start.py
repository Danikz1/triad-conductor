"""Tests for triad-start argument parsing edge cases."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_triad_start_does_not_treat_run_id_value_as_task_path(tmp_path):
    script = Path(__file__).resolve().parents[1] / "triad-start"
    result = subprocess.run(
        [str(script), "--run-id", "custom123"],
        cwd=str(tmp_path),
        text=True,
        capture_output=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "Task file not found: custom123" not in output
    assert "Usage:" in output
