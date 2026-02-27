# Redaction Rules

Goal: ensure the conductor **never** sends secrets or sensitive personal data to any model.

## Rule 1: denylist files
Never attach file contents that match denylist globs (see config):
- .env, .ssh, keychains, private keys, “secret” files, etc.

## Rule 2: redact common secret patterns in logs/diffs
Before sending any text to a model, run a redaction pass that:
- replaces matches with `[REDACTED]`
- keeps line structure where possible (so stack traces remain useful)

Suggested patterns to redact (examples):
- API keys/tokens:
  - AWS access keys (AKIA…)
  - GitHub tokens (ghp_…)
  - Bearer tokens: `Authorization: Bearer ...`
  - generic `api_key=...`, `token=...`, `secret=...`
- Private keys: `-----BEGIN ... PRIVATE KEY-----`
- Password fields: `password=...`, `passwd: ...`
- OTP/2FA codes if present in logs

## Rule 3: credit card & CVV-like content
If your project may touch messages/financial data:
- redact any 13–19 digit sequences (with spaces/dashes) that pass Luhn check
- redact standalone 3–4 digit sequences when adjacent to keywords like:
  - cvv, cvc, security code

## Rule 4: screenshots
Screenshots can contain secrets.
Options:
- Store screenshots locally, but do not attach them to models unless required.
- If you attach screenshots, prefer screenshots of UI output only (not password managers, terminals with env vars, etc.).

## Rule 5: “minimum necessary”
Only include:
- the failing test name(s)
- the first ~50–150 relevant lines of stack trace
- the minimal diff context
Avoid attaching full logs or full repository contents.

