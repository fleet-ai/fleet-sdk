"""Client-side PII/secret scrubbing before upload.

Pure function: scrub(text) -> text.
Regex string replacement only — no parsing, no models.
Structure-preserving: scrubbing a JSONL line produces valid JSON.
"""

from __future__ import annotations

import re

_RULES: list[tuple[re.Pattern, str]] = [
    # AWS
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"(?i)(aws_secret_access_key|aws_secret)\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}"), "[REDACTED_AWS_SECRET]"),
    # Generic API key assignments
    (re.compile(r"(?i)(api[_-]?key|apikey|api[_-]?token|auth[_-]?token|secret[_-]?key|access[_-]?token)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{20,}"), "[REDACTED_API_KEY]"),
    # Bearer tokens
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}"), "Bearer [REDACTED_TOKEN]"),
    # JWTs
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[REDACTED_JWT]"),
    # Private key blocks
    (re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    # Connection strings
    (re.compile(r"(?i)(postgres|mysql|mongodb(\+srv)?|redis|amqp)://[^\s'\"]+"), "[REDACTED_CONNECTION_STRING]"),
    # GitHub PAT
    (re.compile(r"ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82}"), "[REDACTED_GITHUB_TOKEN]"),
    # Slack
    (re.compile(r"xox[bpras]-[A-Za-z0-9\-]{10,}"), "[REDACTED_SLACK_TOKEN]"),
    # Anthropic
    (re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}"), "[REDACTED_ANTHROPIC_KEY]"),
    # OpenAI
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED_OPENAI_KEY]"),
    # SSH public key content
    (re.compile(r"(?i)(ssh-rsa|ssh-ed25519)\s+[A-Za-z0-9+/=]{40,}"), "[REDACTED_SSH_KEY]"),
    # .env style assignments with long values
    (re.compile(r"(?m)^[A-Z_]{2,}=(?!.*REDACTED)[^\n]{20,}$"), lambda m: m.group(0).split("=")[0] + "=[REDACTED]"),
    # Home directory paths
    (re.compile(r"/Users/[a-zA-Z0-9._-]+"), "/Users/[user]"),
    (re.compile(r"/home/[a-zA-Z0-9._-]+"), "/home/[user]"),
]


def scrub(text: str) -> str:
    """Apply all redaction rules to text. Returns scrubbed string."""
    for pattern, replacement in _RULES:
        if callable(replacement):
            text = pattern.sub(replacement, text)
        else:
            text = pattern.sub(replacement, text)
    return text


def scrub_bytes(data: bytes) -> bytes:
    """Scrub raw bytes (decoded as UTF-8, re-encoded)."""
    try:
        text = data.decode("utf-8", errors="replace")
        return scrub(text).encode("utf-8")
    except Exception:
        return data
