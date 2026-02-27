"""Redaction of secrets and sensitive data before sending to models."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

REDACTED = "[REDACTED]"

# Regex patterns for common secrets
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # AWS access keys
    (re.compile(r"AKIA[0-9A-Z]{16}"), REDACTED),
    # GitHub tokens
    (re.compile(r"ghp_[A-Za-z0-9]{36,}"), REDACTED),
    (re.compile(r"gho_[A-Za-z0-9]{36,}"), REDACTED),
    (re.compile(r"ghu_[A-Za-z0-9]{36,}"), REDACTED),
    (re.compile(r"ghs_[A-Za-z0-9]{36,}"), REDACTED),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    # Bearer tokens
    (re.compile(r"(Authorization:\s*Bearer\s+)\S+", re.IGNORECASE), rf"\1{REDACTED}"),
    # Generic api_key / token / secret / password in key=value or key: value
    (re.compile(r"((?:api_key|api[-_]?secret|token|secret|password|passwd|access_token|refresh_token)\s*[=:]\s*)\S+", re.IGNORECASE), rf"\1{REDACTED}"),
    # Private keys (PEM blocks)
    (re.compile(r"-----BEGIN\s+[\w\s]*PRIVATE\s+KEY-----[\s\S]*?-----END\s+[\w\s]*PRIVATE\s+KEY-----"), REDACTED),
    # AWS secret access key patterns (40-char base64)
    (re.compile(r"(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[=:]\s*\S+", re.IGNORECASE), rf"aws_secret_access_key={REDACTED}"),
]


def _luhn_check(digits: str) -> bool:
    """Validate a digit string using the Luhn algorithm."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _redact_credit_cards(text: str) -> str:
    """Redact 13-19 digit sequences (with optional spaces/dashes) that pass Luhn."""
    def _replace(m: re.Match) -> str:
        raw = m.group(0)
        digits = re.sub(r"[\s\-]", "", raw)
        if 13 <= len(digits) <= 19 and digits.isdigit() and _luhn_check(digits):
            return REDACTED
        return raw
    return re.sub(r"\b[\d][\d \-]{11,22}[\d]\b", _replace, text)


def redact(text: str) -> str:
    """Apply all redaction patterns to text."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    text = _redact_credit_cards(text)
    return text


def is_denied(filepath: str, denylist_globs: list[str]) -> bool:
    """Check if a filepath matches any denylist glob pattern."""
    for glob in denylist_globs:
        if fnmatch.fnmatch(filepath, glob):
            return True
        # Also check just the filename component
        if fnmatch.fnmatch(Path(filepath).name, glob.split("/")[-1]):
            return True
    return False


def truncate_log(text: str, max_lines: int = 150) -> str:
    """Truncate text to a maximum number of lines, keeping first and last portions."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    keep = max_lines // 2
    return "\n".join(
        lines[:keep]
        + [f"... ({len(lines) - max_lines} lines truncated) ..."]
        + lines[-keep:]
    )
