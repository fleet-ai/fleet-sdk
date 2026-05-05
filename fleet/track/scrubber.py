"""Client-side PII / secret scrubbing before upload.

Pure regex replacement. No parsing, no models. Structure-preserving:
scrubbing a JSONL line still produces valid JSON.

Each rule has a name. `scrub` returns a `ScrubResult` carrying both the
scrubbed text and a list of `Hit` records — tests assert "the AWS rule
fired on this input" instead of fragile substring matches, and the
future `flt track inspect <file>` command formats the hits per line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence, Union

Replacement = Union[str, Callable[[re.Match], str]]


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern
    replacement: Replacement


@dataclass(frozen=True)
class Hit:
    """One match of a rule. Line is 1-indexed for human-readable output."""

    rule: str
    line: int
    matched: str


@dataclass(frozen=True)
class ScrubResult:
    text: str
    hits: tuple[Hit, ...] = field(default_factory=tuple)

    @property
    def fired_rules(self) -> set[str]:
        return {h.rule for h in self.hits}


# Order matters: more-specific rules run first so that, e.g. AKIA keys
# aren't first redacted by the generic API-key rule and lose their name.
DEFAULT_RULES: tuple[Rule, ...] = (
    Rule("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    Rule(
        "aws_secret_access_key",
        re.compile(r"(?i)(aws_secret_access_key|aws_secret)\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}"),
        "[REDACTED_AWS_SECRET]",
    ),
    Rule(
        "anthropic_api_key",
        re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}"),
        "[REDACTED_ANTHROPIC_KEY]",
    ),
    Rule(
        "openai_api_key",
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        "[REDACTED_OPENAI_KEY]",
    ),
    Rule(
        "github_token",
        re.compile(r"ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82}"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    Rule(
        "slack_token",
        re.compile(r"xox[bpras]-[A-Za-z0-9\-]{10,}"),
        "[REDACTED_SLACK_TOKEN]",
    ),
    Rule(
        "jwt",
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_\-]{10,}"),
        "[REDACTED_JWT]",
    ),
    Rule(
        "private_key_block",
        re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    Rule(
        "connection_string",
        re.compile(r"(?i)(postgres|mysql|mongodb(\+srv)?|redis|amqp)://[^\s'\"]+"),
        "[REDACTED_CONNECTION_STRING]",
    ),
    Rule(
        "ssh_public_key",
        re.compile(r"(?i)(ssh-rsa|ssh-ed25519)\s+[A-Za-z0-9+/=]{40,}"),
        "[REDACTED_SSH_KEY]",
    ),
    Rule(
        "generic_api_key_assignment",
        re.compile(
            r"(?i)(api[_-]?key|apikey|api[_-]?token|auth[_-]?token|secret[_-]?key|access[_-]?token)"
            r"\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{20,}"
        ),
        "[REDACTED_API_KEY]",
    ),
    Rule(
        "bearer_token",
        re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}"),
        "Bearer [REDACTED_TOKEN]",
    ),
    Rule(
        "env_assignment_long_value",
        re.compile(r"(?m)^[A-Z_]{2,}=(?!.*REDACTED)[^\n]{20,}$"),
        lambda m: m.group(0).split("=")[0] + "=[REDACTED]",
    ),
    Rule("home_path_macos", re.compile(r"/Users/[a-zA-Z0-9._-]+"), "/Users/[user]"),
    Rule("home_path_linux", re.compile(r"/home/[a-zA-Z0-9._-]+"), "/home/[user]"),
)


def scrub(text: str, rules: Iterable[Rule] = DEFAULT_RULES) -> ScrubResult:
    """Apply rules in order. Returns scrubbed text + per-hit metadata.

    Hits are recorded against the *original* text's line numbers so that
    `flt track inspect` can point at the line the user can find in their
    on-disk session file.
    """
    rule_list: Sequence[Rule] = tuple(rules)
    hits: list[Hit] = []

    # First pass: enumerate hits against the *original* text so line
    # numbers don't shift when subsequent rules rewrite content.
    for rule in rule_list:
        for m in rule.pattern.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append(Hit(rule=rule.name, line=line, matched=m.group(0)))

    # Second pass: actual substitution. We re-run regexes here rather than
    # building offsets, because subs in earlier rules can change later
    # rules' match positions (e.g. a long secret becoming "[REDACTED]"
    # could expose a substring that looks like another secret).
    for rule in rule_list:
        text = rule.pattern.sub(rule.replacement, text)

    return ScrubResult(text=text, hits=tuple(hits))


def scrub_bytes(data: bytes, rules: Iterable[Rule] = DEFAULT_RULES) -> bytes:
    """Scrub raw bytes (decoded as UTF-8, re-encoded). Backward-compatible
    wrapper for the upload path that just wants the scrubbed payload."""
    try:
        text = data.decode("utf-8", errors="replace")
        return scrub(text, rules).text.encode("utf-8")
    except Exception:
        return data
