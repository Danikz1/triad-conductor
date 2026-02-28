"""CLI version checks for model providers used by Triad."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from conductor.config import Config
from conductor.models.preflight import required_providers

MIN_PROVIDER_VERSIONS: dict[str, str] = {
    "claude": "2.0.0",
    "codex": "0.106.0",
    "gemini": "0.30.0",
}

VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class VersionCheck:
    provider: str
    ok: bool
    min_version: str
    found_version: str
    details: str


def _parse_semver(text: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.search(text or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _compare_semver(found: tuple[int, int, int], minimum: tuple[int, int, int]) -> bool:
    return found >= minimum


def _get_provider_version(provider: str) -> str:
    result = subprocess.run(
        [provider, "--version"],
        text=True,
        capture_output=True,
        timeout=20,
    )
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if result.returncode != 0:
        raise RuntimeError(f"`{provider} --version` failed (exit {result.returncode}): {output[:240]}")
    if not output:
        return "unknown"
    return output.splitlines()[0].strip()


def run_version_gate(config: Config) -> list[VersionCheck]:
    checks: list[VersionCheck] = []
    for provider in required_providers(config):
        min_version = MIN_PROVIDER_VERSIONS.get(provider, "")
        if not min_version:
            checks.append(
                VersionCheck(
                    provider=provider,
                    ok=True,
                    min_version="n/a",
                    found_version="n/a",
                    details="No minimum version policy for this provider.",
                )
            )
            continue

        try:
            version_line = _get_provider_version(provider)
        except FileNotFoundError:
            checks.append(
                VersionCheck(
                    provider=provider,
                    ok=False,
                    min_version=min_version,
                    found_version="not installed",
                    details="CLI not found in PATH.",
                )
            )
            continue
        except RuntimeError as exc:
            checks.append(
                VersionCheck(
                    provider=provider,
                    ok=False,
                    min_version=min_version,
                    found_version="unknown",
                    details=str(exc),
                )
            )
            continue

        found = _parse_semver(version_line)
        minimum = _parse_semver(min_version)
        if found is None or minimum is None:
            checks.append(
                VersionCheck(
                    provider=provider,
                    ok=False,
                    min_version=min_version,
                    found_version=version_line,
                    details="Could not parse semantic version.",
                )
            )
            continue

        ok = _compare_semver(found, minimum)
        checks.append(
            VersionCheck(
                provider=provider,
                ok=ok,
                min_version=min_version,
                found_version=version_line,
                details="OK" if ok else f"Upgrade required (minimum {min_version}).",
            )
        )
    return checks


def ensure_supported_cli_versions(config: Config) -> None:
    checks = run_version_gate(config)
    failures = [c for c in checks if not c.ok]
    if not failures:
        return
    lines = ["Model CLI version gate failed:"]
    for check in failures:
        lines.append(
            f"- {check.provider}: found `{check.found_version}`, minimum `{check.min_version}`. {check.details}"
        )
    lines.append("Install/upgrade CLIs, then retry.")
    raise RuntimeError("\n".join(lines))

