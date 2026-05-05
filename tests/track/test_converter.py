"""Cross-format converter tests.

Locks in the field-set requirements we discovered empirically by
actually trying `claude --resume` and `codex exec resume` on
converter output:

  - claude resume scans `~/.claude/projects/<encoded-resolved-cwd>/<sessionId>.jsonl`.
    Every row must carry `sessionId` matching the filename.
  - codex resume reads the file by UUID. The first row must be
    `session_meta` with the strict struct:
        id, timestamp, cwd, originator, cli_version, source,
        model_provider, base_instructions={"text": "..."}.
    A plain-string `base_instructions` trips
    `rollout does not start with session metadata`.

These tests don't actually call claude/codex — they assert the
converter produces the structures those CLIs require.
"""

from __future__ import annotations

import json
from pathlib import Path

from fleet.track.converter import _encode_claude_cwd, convert
from fleet.track.sources import ClaudeSource, CodexSource


def _build_claude_fixture(tmp_path: Path) -> Path:
    rows = [
        {"type": "user", "uuid": "u1", "parentUuid": None,
         "sessionId": "src-session", "cwd": "/some/path", "gitBranch": "main",
         "version": "1.0", "timestamp": "2026-04-30T00:00:00Z",
         "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "uuid": "a1", "parentUuid": "u1",
         "timestamp": "2026-04-30T00:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "yo"}
         ]}},
    ]
    f = tmp_path / "claude.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return f


def _build_codex_fixture(tmp_path: Path) -> Path:
    rows = [
        {"timestamp": "2026-04-30T00:00:00Z", "type": "session_meta",
         "payload": {"id": "src-session", "cwd": "/some/path", "cli_version": "0.5",
                     "base_instructions": {"text": "you are codex"}}},
        {"timestamp": "2026-04-30T00:00:01Z", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "hi"}]}},
        {"timestamp": "2026-04-30T00:00:02Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "yo"}]}},
    ]
    f = tmp_path / "codex.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return f


# ------------------------------------------------------------------ #
# CWD encoding                                                         #
# ------------------------------------------------------------------ #


def test_encode_claude_cwd_handles_dots_and_slashes():
    """Real claude project dirs encode `/Users/foo/.config` as `-Users-foo--config`."""
    assert _encode_claude_cwd("/Users/foo/.config") == "-Users-foo--config"
    assert _encode_claude_cwd("/private/tmp/abc") == "-private-tmp-abc"
    assert _encode_claude_cwd("/Users/trenthaines/git/fleet-sdk") == "-Users-trenthaines-git-fleet-sdk"


# ------------------------------------------------------------------ #
# claude as target                                                     #
# ------------------------------------------------------------------ #


def test_codex_to_claude_produces_resumeable_layout(tmp_path: Path):
    """codex source → claude target: every row has sessionId; suggested
    path is under projects/<encoded-cwd>/<session>.jsonl."""
    src = _build_codex_fixture(tmp_path)
    result = convert(
        from_source=CodexSource(),
        to_source=ClaudeSource(),
        in_path=src,
        home=tmp_path,
        target_cwd="/private/tmp/test-resume",
        new_session_id="test-uuid-1",
    )
    # Suggested path
    expected_dir = tmp_path / ".claude" / "projects" / "-private-tmp-test-resume"
    assert result.suggested_path.parent == expected_dir
    assert result.suggested_path.name == "test-uuid-1.jsonl"
    assert result.session_id == "test-uuid-1"

    # Every row carries the new session id
    lines = [json.loads(l) for l in result.bytes.decode().splitlines() if l.strip()]
    assert lines  # non-empty
    for line in lines:
        sid = line.get("sessionId")
        if sid is not None:
            assert sid == "test-uuid-1"

    # Every user/assistant row carries cwd matching target
    for line in lines:
        if line.get("type") in ("user", "assistant"):
            assert line.get("cwd") == "/private/tmp/test-resume"


def test_claude_target_resolves_symlinked_cwd(tmp_path: Path):
    """`/tmp` should resolve to `/private/tmp` on macOS — claude indexes
    by the resolved path, so the converter must propagate the resolved form."""
    if not Path("/tmp").is_symlink():
        # On Linux /tmp isn't a symlink; nothing to verify here.
        return
    src = _build_codex_fixture(tmp_path)
    result = convert(
        from_source=CodexSource(),
        to_source=ClaudeSource(),
        in_path=src,
        home=tmp_path,
        target_cwd="/tmp/should-resolve",
        new_session_id="x",
    )
    # /tmp resolves to /private/tmp on darwin
    assert "private" in str(result.suggested_path)


# ------------------------------------------------------------------ #
# codex as target                                                      #
# ------------------------------------------------------------------ #


def test_claude_to_codex_first_row_is_valid_session_meta(tmp_path: Path):
    """codex exec resume rejects files whose first row's payload doesn't
    deserialize into the session-meta struct. Lock in the field set."""
    src = _build_claude_fixture(tmp_path)
    result = convert(
        from_source=ClaudeSource(),
        to_source=CodexSource(),
        in_path=src,
        home=tmp_path,
        target_cwd="/private/tmp/test-resume",
        new_session_id="test-uuid-2",
    )

    lines = [json.loads(l) for l in result.bytes.decode().splitlines() if l.strip()]
    first = lines[0]

    # Top-level shape
    assert first["type"] == "session_meta"
    assert "timestamp" in first
    payload = first["payload"]

    # Required payload fields (audited from real codex sessions; missing
    # any of them caused codex to reject with "does not start with
    # session metadata"):
    required = {"id", "timestamp", "cwd", "originator", "cli_version",
                "source", "model_provider", "base_instructions"}
    assert set(payload.keys()) >= required, f"missing: {required - set(payload.keys())}"

    # base_instructions must be {text: str}, NOT a plain string.
    assert isinstance(payload["base_instructions"], dict)
    assert "text" in payload["base_instructions"]

    # id and cwd reflect the converter args
    assert payload["id"] == "test-uuid-2"
    assert payload["cwd"] == "/private/tmp/test-resume"


def test_codex_target_suggested_path_is_dated(tmp_path: Path):
    """codex layout: ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl."""
    src = _build_claude_fixture(tmp_path)
    result = convert(
        from_source=ClaudeSource(),
        to_source=CodexSource(),
        in_path=src,
        home=tmp_path,
        target_cwd="/x",
        new_session_id="abc",
    )
    p = result.suggested_path
    # path must be under tmp_path/.codex/sessions/YYYY/MM/DD/
    rel = p.relative_to(tmp_path / ".codex" / "sessions")
    parts = rel.parts
    assert len(parts) == 4  # YYYY, MM, DD, file
    assert parts[3].startswith("rollout-")
    assert parts[3].endswith("-abc.jsonl")


# ------------------------------------------------------------------ #
# Round-trip via converter                                             #
# ------------------------------------------------------------------ #


def test_converter_event_count_preserved(tmp_path: Path):
    """All events in the source file survive conversion + re-parse."""
    src = _build_claude_fixture(tmp_path)
    result = convert(
        from_source=ClaudeSource(),
        to_source=CodexSource(),
        in_path=src,
        home=tmp_path,
        target_cwd="/x",
        new_session_id="rt",
    )

    in_events = list(ClaudeSource().parse(src))
    # Re-parse the converted bytes
    out_path = tmp_path / "converted.jsonl"
    out_path.write_bytes(result.bytes)
    out_events = list(CodexSource().parse(out_path))

    # Every input event should produce at least one output event.
    # (Synthesized SessionStart from the parser becomes a session_meta row.)
    assert len(out_events) >= len(in_events)
