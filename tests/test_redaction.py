"""Tests for conductor.redaction module."""

from conductor.redaction import redact, is_denied, truncate_log


def test_redact_aws_key():
    text = "key=AKIAIOSFODNN7EXAMPLE"
    result = redact(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in result
    assert "[REDACTED]" in result


def test_redact_github_token():
    text = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
    result = redact(text)
    assert "ghp_" not in result
    assert "[REDACTED]" in result


def test_redact_bearer():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.something"
    result = redact(text)
    assert "eyJ" not in result
    assert "Authorization: Bearer [REDACTED]" in result


def test_redact_password():
    text = "password=SuperSecret123!"
    result = redact(text)
    assert "SuperSecret123" not in result
    assert "[REDACTED]" in result


def test_redact_private_key():
    text = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Z1x...
-----END RSA PRIVATE KEY-----"""
    result = redact(text)
    assert "BEGIN RSA PRIVATE KEY" not in result
    assert "[REDACTED]" in result


def test_redact_credit_card():
    # Valid Visa test card (passes Luhn)
    text = "card: 4111 1111 1111 1111"
    result = redact(text)
    assert "4111" not in result
    assert "[REDACTED]" in result


def test_redact_preserves_normal_text():
    text = "This is normal log output\nNo secrets here\nLine 3"
    assert redact(text) == text


def test_is_denied():
    globs = ["**/.env", "**/.env.*", "**/*secret*", "**/id_rsa*"]
    assert is_denied("project/.env", globs)
    assert is_denied("project/.env.local", globs)
    assert is_denied("config/my_secret.yaml", globs)
    assert is_denied("~/.ssh/id_rsa", globs)
    assert not is_denied("src/main.py", globs)
    assert not is_denied("README.md", globs)


def test_truncate_log():
    lines = "\n".join(f"line {i}" for i in range(300))
    result = truncate_log(lines, max_lines=100)
    assert "truncated" in result
    assert len(result.splitlines()) < 300


def test_truncate_short_log():
    text = "short\nlog"
    assert truncate_log(text) == text
