"""Environment diagnostics for Triad Conductor."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import Any

from conductor.config import Config
from conductor.models.preflight import run_auth_preflight
from conductor.models.version_gate import run_version_gate


def _probe_command(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    if not path:
        return {"name": name, "ok": False, "details": "not found in PATH"}

    try:
        result = subprocess.run(
            [name, "--version"],
            text=True,
            capture_output=True,
            timeout=10,
        )
    except Exception as exc:
        return {"name": name, "ok": False, "details": f"version probe failed: {exc}"}

    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip().splitlines()
    line = output[0] if output else "version unknown"
    if result.returncode != 0:
        return {"name": name, "ok": False, "details": f"`{name} --version` failed: {line}"}
    return {"name": name, "ok": True, "details": line}


def run_doctor(
    *,
    config: Config,
    check_auth: bool,
    check_versions: bool,
) -> dict[str, Any]:
    command_checks = [
        {"name": "python", "ok": True, "details": sys.version.splitlines()[0]},
        _probe_command("git"),
        _probe_command("claude"),
        _probe_command("codex"),
        _probe_command("gemini"),
    ]

    auth_checks: list[dict[str, Any]] = []
    if check_auth:
        for check in run_auth_preflight(config):
            auth_checks.append(
                {"provider": check.provider, "ok": check.ok, "details": check.details}
            )

    version_checks: list[dict[str, Any]] = []
    if check_versions:
        for check in run_version_gate(config):
            version_checks.append(
                {
                    "provider": check.provider,
                    "ok": check.ok,
                    "minimum": check.min_version,
                    "found": check.found_version,
                    "details": check.details,
                }
            )

    ok = all(c["ok"] for c in command_checks)
    if auth_checks:
        ok = ok and all(c["ok"] for c in auth_checks)
    if version_checks:
        ok = ok and all(c["ok"] for c in version_checks)

    return {
        "ok": ok,
        "command_checks": command_checks,
        "version_checks": version_checks,
        "auth_checks": auth_checks,
    }


def format_doctor_report(report: dict[str, Any]) -> str:
    lines = ["Triad Doctor", ""]

    lines.append("Commands:")
    for check in report.get("command_checks", []):
        status = "OK" if check.get("ok") else "FAIL"
        lines.append(f"- [{status}] {check.get('name')}: {check.get('details')}")

    versions = report.get("version_checks", [])
    if versions:
        lines.append("")
        lines.append("Version Gate:")
        for check in versions:
            status = "OK" if check.get("ok") else "FAIL"
            lines.append(
                f"- [{status}] {check.get('provider')}: found `{check.get('found')}` "
                f"(min `{check.get('minimum')}`) — {check.get('details')}"
            )

    auth = report.get("auth_checks", [])
    if auth:
        lines.append("")
        lines.append("Auth:")
        for check in auth:
            status = "OK" if check.get("ok") else "FAIL"
            lines.append(f"- [{status}] {check.get('provider')}: {check.get('details')}")

    lines.append("")
    lines.append("Overall: " + ("PASS" if report.get("ok") else "FAIL"))
    return "\n".join(lines)


def doctor_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)

