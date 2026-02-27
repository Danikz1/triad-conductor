"""Local tool execution: tests, lint, typecheck."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _run(cmd: list[str], cwd: Optional[Path] = None, timeout: int = 300) -> subprocess.CompletedProcess:
    log.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    try:
        return subprocess.run(
            cmd, cwd=str(cwd) if cwd else None,
            text=True, capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log.warning("Command timed out after %ds: %s", timeout, " ".join(cmd))
        return subprocess.CompletedProcess(cmd, returncode=-1, stdout="", stderr=f"Timeout after {timeout}s")


def run_tests(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[bool, str]:
    """Run a test command. Returns (passed, output)."""
    result = _run(cmd, cwd=cwd, timeout=timeout)
    output = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, output


def run_lint(cwd: Path, cmd: Optional[list[str]] = None, timeout: int = 120) -> tuple[bool, str]:
    """Run linter. Returns (passed, output)."""
    if cmd is None:
        cmd = ["python", "-m", "flake8", "--max-line-length=120", "."]
    result = _run(cmd, cwd=cwd, timeout=timeout)
    output = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, output


def run_typecheck(cwd: Path, cmd: Optional[list[str]] = None, timeout: int = 120) -> tuple[bool, str]:
    """Run type checker. Returns (passed, output)."""
    if cmd is None:
        cmd = ["python", "-m", "mypy", "."]
    result = _run(cmd, cwd=cwd, timeout=timeout)
    output = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, output


def count_failing_tests(output: str) -> int:
    """Extract number of failing tests from pytest output."""
    # pytest format: "X failed, Y passed"
    m = re.search(r"(\d+)\s+failed", output)
    if m:
        return int(m.group(1))
    # If there's an error but no "failed" count, check for error exit
    if "error" in output.lower() or "ERRORS" in output:
        return -1  # Unknown failure count
    return 0


def compute_failure_signature(test_output: str) -> str:
    """Extract a stable signature from test failures for stuck detection."""
    lines = [ln.strip() for ln in test_output.splitlines() if ln.strip()]
    # Look for FAILED lines first (pytest)
    failed_lines = [ln for ln in lines if ln.startswith("FAILED") or "FAILED" in ln]
    if failed_lines:
        return failed_lines[0][:200]
    # Look for Error lines
    error_lines = [ln for ln in lines if "Error" in ln or "error" in ln.lower()]
    if error_lines:
        return error_lines[0][:200]
    return lines[0][:200] if lines else "NO_OUTPUT"
