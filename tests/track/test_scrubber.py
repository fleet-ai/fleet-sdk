"""Unit tests for scrubber.py — assert specific named rules fire on specific inputs."""

from __future__ import annotations

import re

from fleet.track.scrubber import (
    DEFAULT_RULES,
    Hit,
    Rule,
    scrub,
    scrub_bytes,
)


def _fired(text: str) -> set[str]:
    return scrub(text).fired_rules


# ------------------------------------------------------------------ #
# Per-rule assertions                                                  #
# ------------------------------------------------------------------ #


def test_aws_access_key_id():
    assert "aws_access_key_id" in _fired("My key is AKIAIOSFODNN7EXAMPLE today")


def test_aws_secret_access_key():
    text = 'aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
    assert "aws_secret_access_key" in _fired(text)


def test_anthropic_api_key():
    assert "anthropic_api_key" in _fired("sk-ant-api03-aBcDeFgHiJkLmNoPqRsTuVwXyZ-12345")


def test_openai_api_key():
    assert "openai_api_key" in _fired("sk-abcdef0123456789ABCDEF0123456789")


def test_github_token():
    assert "github_token" in _fired("ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789")


def test_slack_token():
    assert "slack_token" in _fired("xoxb-1234567890-abcdefghijk")


def test_jwt():
    text = "Authorization: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    assert "jwt" in _fired(text)


def test_private_key_block():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    assert "private_key_block" in _fired(text)


def test_connection_string():
    assert "connection_string" in _fired("postgres://user:pass@host:5432/db")


def test_home_path_macos_redacted():
    result = scrub("the path is /Users/alice/Documents/foo")
    assert "home_path_macos" in result.fired_rules
    assert "alice" not in result.text
    assert "/Users/[user]" in result.text


def test_home_path_linux_redacted():
    result = scrub("logs at /home/bob/app.log")
    assert "home_path_linux" in result.fired_rules
    assert "/home/[user]/app.log" in result.text


# ------------------------------------------------------------------ #
# Hit metadata                                                         #
# ------------------------------------------------------------------ #


def test_hits_carry_line_numbers():
    text = "line 1\nline 2 has AKIAIOSFODNN7EXAMPLE\nline 3"
    result = scrub(text)
    assert any(h.rule == "aws_access_key_id" and h.line == 2 for h in result.hits)


def test_hits_record_original_match_text():
    result = scrub("AKIAIOSFODNN7EXAMPLE")
    aws_hits = [h for h in result.hits if h.rule == "aws_access_key_id"]
    assert aws_hits == [Hit(rule="aws_access_key_id", line=1, matched="AKIAIOSFODNN7EXAMPLE")]


def test_no_hits_means_text_unchanged():
    text = '{"hello": "world"}\n'
    result = scrub(text)
    assert result.hits == ()
    assert result.text == text


# ------------------------------------------------------------------ #
# Subsitution behavior                                                 #
# ------------------------------------------------------------------ #


def test_aws_key_is_replaced():
    result = scrub("AKIAIOSFODNN7EXAMPLE")
    assert "AKIA" not in result.text
    assert "[REDACTED_AWS_KEY]" in result.text


def test_jsonl_structure_preserved():
    """Scrubbing must not break JSON parsing of a JSONL line."""
    import json

    text = '{"key": "AKIAIOSFODNN7EXAMPLE", "other": 42}\n'
    result = scrub(text)
    parsed = json.loads(result.text.strip())
    assert parsed["other"] == 42
    assert "[REDACTED" in parsed["key"]


def test_env_assignment_callable_replacement():
    """The env_assignment_long_value rule uses a callable replacement that
    preserves the variable name. Use a name that no other rule matches so the
    substitution actually comes from this rule."""
    text = "MY_LONG_THING=abcdefghij1234567890longvalue"
    result = scrub(text)
    assert "env_assignment_long_value" in result.fired_rules
    assert "MY_LONG_THING=[REDACTED]" in result.text


# ------------------------------------------------------------------ #
# Custom rules                                                         #
# ------------------------------------------------------------------ #


def test_custom_rules_replace_default_set():
    only_aws = (Rule("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}"), "[X]"),)
    result = scrub("AKIAIOSFODNN7EXAMPLE and sk-abcdef0123456789ABCDEF0123456789", rules=only_aws)
    assert "[X]" in result.text
    # OpenAI rule isn't in the custom rule set, so the openai key remains.
    assert "sk-abcdef" in result.text


def test_default_rules_are_a_tuple():
    """Frozen so the production set can't be mutated by an importer."""
    assert isinstance(DEFAULT_RULES, tuple)


# ------------------------------------------------------------------ #
# scrub_bytes backward-compat                                          #
# ------------------------------------------------------------------ #


def test_scrub_bytes_returns_bytes():
    out = scrub_bytes(b'{"key": "AKIAIOSFODNN7EXAMPLE"}\n')
    assert isinstance(out, bytes)
    assert b"AKIA" not in out


def test_scrub_bytes_handles_invalid_utf8():
    # Decoded with errors="replace", scrubbed, re-encoded. Should not raise.
    bad = b"\xff\xfe AKIAIOSFODNN7EXAMPLE \x80"
    out = scrub_bytes(bad)
    assert b"AKIA" not in out
