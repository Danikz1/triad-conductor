"""Auth preflight checks for model CLIs used by Triad."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Iterable

from conductor.config import Config, ModelRef


@dataclass(frozen=True)
class AuthCheck:
    provider: str
    ok: bool
    details: str


def _all_model_refs(config: Config) -> Iterable[ModelRef]:
    yield from config.proposer_models
    yield config.arbiter_model
    yield config.builder_model
    yield config.reviewer_model
    yield config.qa_model
    yield from config.optimizer_models


def required_providers(config: Config) -> list[str]:
    providers = {m.name.strip().lower() for m in _all_model_refs(config) if m.name}
    return sorted(providers)


def _first_model_id(config: Config, provider: str) -> str | None:
    for model_ref in _all_model_refs(config):
        if model_ref.name.strip().lower() == provider and model_ref.model:
            return model_ref.model
    return None


def _run(cmd: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_seconds)


def _unknown_flag(text: str) -> bool:
    s = text.lower()
    return "unknown option" in s or "unrecognized option" in s or "unknown flag" in s


def _conflicting_gemini_flags(text: str) -> bool:
    s = text.lower()
    return "cannot use both" in s and "--yolo" in s and "--approval-mode" in s


def _check_claude_headless(timeout_seconds: int, model_id: str | None) -> AuthCheck:
    cmd = [
        "claude",
        "-p",
        "Reply exactly: OK",
        "--output-format",
        "text",
        "--no-session-persistence",
    ]
    if model_id:
        cmd += ["--model", model_id]

    try:
        result = _run(cmd, timeout_seconds)
    except FileNotFoundError:
        return AuthCheck("claude", False, "CLI not found (install `claude` first).")
    except subprocess.TimeoutExpired:
        return AuthCheck("claude", False, "Timed out during Claude headless auth probe.")

    combined = f"{result.stdout}\n{result.stderr}".strip()
    lowered = combined.lower()
    if result.returncode == 0:
        return AuthCheck("claude", True, "Authenticated (headless probe succeeded).")
    if "not logged in" in lowered or "please run /login" in lowered:
        return AuthCheck("claude", False, "Not authenticated for headless mode (run `claude` then `/login`).")
    return AuthCheck(
        "claude",
        False,
        f"Claude headless auth probe failed (exit {result.returncode}): {combined[:240]}",
    )


def _check_claude(timeout_seconds: int, model_id: str | None) -> AuthCheck:
    try:
        result = _run(["claude", "auth", "status"], timeout_seconds)
    except FileNotFoundError:
        return AuthCheck("claude", False, "CLI not found (install `claude` first).")
    except subprocess.TimeoutExpired:
        return AuthCheck("claude", False, "Timed out while checking `claude auth status`.")

    combined = f"{result.stdout}\n{result.stderr}".strip()
    payload_text = (result.stdout or "").strip()
    if payload_text:
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            if payload.get("loggedIn") is True:
                return AuthCheck("claude", True, "Authenticated.")
            method = payload.get("authMethod", "unknown")
            # Some environments can report false negatives in auth status.
            # Fall back to a lightweight headless probe, which matches Triad runtime.
            probe = _check_claude_headless(timeout_seconds, model_id=model_id)
            if probe.ok:
                return probe
            return AuthCheck("claude", False, f"Not authenticated (authMethod={method}).")

    if result.returncode != 0:
        probe = _check_claude_headless(timeout_seconds, model_id=model_id)
        if probe.ok:
            return probe
        return AuthCheck(
            "claude",
            False,
            f"`claude auth status` failed (exit {result.returncode}): {combined[:240]}",
        )

    lowered = combined.lower()
    if "logged in" in lowered and "not logged" not in lowered:
        return AuthCheck("claude", True, "Authenticated.")
    probe = _check_claude_headless(timeout_seconds, model_id=model_id)
    if probe.ok:
        return probe
    return AuthCheck("claude", False, f"Unable to verify authentication: {combined[:240]}")


def _check_codex(timeout_seconds: int) -> AuthCheck:
    try:
        result = _run(["codex", "login", "status"], timeout_seconds)
    except FileNotFoundError:
        return AuthCheck("codex", False, "CLI not found (install `codex` first).")
    except subprocess.TimeoutExpired:
        return AuthCheck("codex", False, "Timed out while checking `codex login status`.")

    combined = f"{result.stdout}\n{result.stderr}".strip()
    lowered = combined.lower()
    if result.returncode == 0 and "logged in" in lowered and "not logged" not in lowered:
        return AuthCheck("codex", True, "Authenticated.")

    if "not logged" in lowered:
        return AuthCheck("codex", False, "Not authenticated.")

    return AuthCheck(
        "codex",
        False,
        f"Unable to verify authentication (exit {result.returncode}): {combined[:240]}",
    )


def _check_gemini(timeout_seconds: int, model_id: str | None) -> AuthCheck:
    base = ["gemini", "-p", "Reply with OK", "--output-format", "json"]
    if model_id:
        base += ["--model", model_id]

    attempts = [
        base + ["--approval-mode=yolo"],
        base + ["--yolo"],
    ]
    last_details = "Unknown Gemini authentication failure."

    for cmd in attempts:
        try:
            result = _run(cmd, timeout_seconds)
        except FileNotFoundError:
            return AuthCheck("gemini", False, "CLI not found (install `gemini` first).")
        except subprocess.TimeoutExpired:
            return AuthCheck("gemini", False, "Timed out while checking Gemini authentication.")

        if result.returncode == 0:
            return AuthCheck("gemini", True, "Authenticated.")

        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        combined = f"{stdout}\n{stderr}".strip()
        lowered = combined.lower()

        if _unknown_flag(lowered) or _conflicting_gemini_flags(lowered):
            last_details = f"Flag compatibility issue: {combined[:240]}"
            continue

        if (
            "error authenticating" in lowered
            or "interactive consent could not be obtained" in lowered
            or "fatalauthenticationerror" in lowered
        ):
            return AuthCheck("gemini", False, "Not authenticated (run `gemini` interactively to log in).")

        last_details = f"Auth probe failed (exit {result.returncode}): {combined[:240]}"

    return AuthCheck("gemini", False, last_details)


def run_auth_preflight(config: Config, timeout_seconds: int = 30) -> list[AuthCheck]:
    checks: list[AuthCheck] = []
    for provider in required_providers(config):
        if provider == "claude":
            checks.append(_check_claude(timeout_seconds, model_id=_first_model_id(config, "claude")))
            continue
        if provider == "codex":
            checks.append(_check_codex(timeout_seconds))
            continue
        if provider == "gemini":
            checks.append(_check_gemini(timeout_seconds, model_id=_first_model_id(config, "gemini")))
            continue
        checks.append(AuthCheck(provider, True, "Auth preflight skipped for custom provider."))
    return checks


def ensure_required_auth(config: Config, timeout_seconds: int = 30) -> None:
    checks = run_auth_preflight(config, timeout_seconds=timeout_seconds)
    failures = [c for c in checks if not c.ok]
    if not failures:
        return

    lines = ["Model auth preflight failed:"]
    for check in failures:
        lines.append(f"- {check.provider}: {check.details}")
    lines.append("Login commands:")
    lines.append("  claude auth login")
    lines.append("  codex login")
    lines.append("  gemini  # run once interactively to complete OAuth")
    raise RuntimeError("\n".join(lines))
