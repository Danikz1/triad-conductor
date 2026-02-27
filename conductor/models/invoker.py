"""Model invocation via CLI tools (claude, codex, gemini)."""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from conductor.cost_tracker import estimate_cost
from conductor.models.parsers import extract_json

log = logging.getLogger(__name__)


def invoke_model(
    model_name: str,
    prompt: str,
    schema_path: Optional[Path] = None,
    cwd: Optional[Path] = None,
    mcp_config_path: Optional[Path] = None,
    dry_run: bool = False,
    dry_run_response: Optional[dict] = None,
) -> dict[str, Any]:
    """Invoke a model CLI and return parsed JSON output.

    Args:
        model_name: One of 'claude', 'codex', 'gemini'.
        prompt: Full prompt text (sent via stdin).
        schema_path: Path to JSON schema file (used by claude/gemini for structured output).
        cwd: Working directory (used by codex for repo access).
        mcp_config_path: Path to MCP config JSON (used by claude builder).
        dry_run: If True, return dry_run_response instead of calling CLI.
        dry_run_response: Canned response for dry-run mode.

    Returns:
        Parsed JSON dict from model output.

    Raises:
        RuntimeError: If invocation fails or output can't be parsed.
    """
    if dry_run:
        log.info("[DRY RUN] Would invoke %s", model_name)
        if dry_run_response is not None:
            return dry_run_response
        return {"kind": "dry_run", "model": model_name}

    cost = estimate_cost(model_name)
    log.info("Invoking %s (est. $%.2f)", model_name, cost)

    if model_name == "claude":
        return _invoke_claude(prompt, schema_path, mcp_config_path), cost
    elif model_name == "codex":
        return _invoke_codex(prompt, cwd), cost
    elif model_name == "gemini":
        return _invoke_gemini(prompt, schema_path), cost
    else:
        raise ValueError(f"Unknown model: {model_name}")


def _invoke_claude(
    prompt: str,
    schema_path: Optional[Path] = None,
    mcp_config_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Invoke Claude CLI: claude -p --output-format json ..."""
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
    ]
    if schema_path:
        cmd += ["--json-schema", str(schema_path)]
    if mcp_config_path:
        cmd += ["--mcp-config", str(mcp_config_path)]

    result = subprocess.run(
        cmd, input=prompt, text=True, capture_output=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed (exit {result.returncode}): {result.stderr[:500]}")

    return extract_json(result.stdout)


def _invoke_codex(prompt: str, cwd: Optional[Path] = None) -> dict[str, Any]:
    """Invoke Codex CLI: codex exec - -C <dir> --full-auto"""
    cmd = ["codex", "exec", "-", "--full-auto"]
    if cwd:
        cmd += ["-C", str(cwd)]

    result = subprocess.run(
        cmd, input=prompt, text=True, capture_output=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Codex CLI failed (exit {result.returncode}): {result.stderr[:500]}")

    return extract_json(result.stdout)


def _invoke_gemini(prompt: str, schema_path: Optional[Path] = None) -> dict[str, Any]:
    """Invoke Gemini CLI: gemini -p '<prompt>' --output-format json --yolo"""
    # Gemini takes prompt as argument, but we use a temp file for long prompts
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    cmd = ["gemini", "-p"]
    # Read prompt from file to avoid ARG_MAX
    with open(prompt_file) as f:
        prompt_text = f.read()

    cmd_args = ["gemini", "-p", "-", "--output-format", "json", "--yolo"]

    result = subprocess.run(
        cmd_args, input=prompt_text, text=True, capture_output=True, timeout=600,
    )

    Path(prompt_file).unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(f"Gemini CLI failed (exit {result.returncode}): {result.stderr[:500]}")

    return extract_json(result.stdout)


def invoke_model_safe(
    model_name: str,
    prompt: str,
    schema_path: Optional[Path] = None,
    cwd: Optional[Path] = None,
    mcp_config_path: Optional[Path] = None,
    dry_run: bool = False,
    dry_run_response: Optional[dict] = None,
) -> tuple[Optional[dict[str, Any]], float, Optional[str]]:
    """Like invoke_model but catches errors. Returns (result, cost, error_msg)."""
    try:
        result = invoke_model(
            model_name, prompt, schema_path, cwd, mcp_config_path,
            dry_run, dry_run_response,
        )
        if isinstance(result, tuple):
            data, cost = result
            return data, cost, None
        return result, estimate_cost(model_name), None
    except Exception as e:
        log.error("Model invocation failed (%s): %s", model_name, e)
        return None, estimate_cost(model_name), str(e)
