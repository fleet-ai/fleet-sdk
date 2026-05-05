"""Round-trip and cross-format tests for the unified format.

These tests use small synthetic fixtures to lock in invariants:
  - parse → serialize → parse-again preserves the kernel events
  - cross-format conversion never crashes
  - structural events (turn boundaries, lifecycles) survive

Real-world corpus tests (massive sample sweeps) live in scripts the dev
runs locally, not in pytest — they take seconds and depend on the dev's
own ~/.claude and ~/.codex contents.
"""

from __future__ import annotations

import json
from pathlib import Path

from fleet.track.sources import ClaudeSource, CodexSource


# ------------------------------------------------------------------ #
# Synthetic fixtures                                                   #
# ------------------------------------------------------------------ #


def _make_claude_session(tmp_path: Path) -> Path:
    """A diverse claude session with every event class we model."""
    rows = [
        # SessionStart-eligible row
        {"type": "user", "uuid": "u1", "parentUuid": None,
         "sessionId": "s1", "cwd": "/tmp", "gitBranch": "main", "version": "0.5",
         "timestamp": "2026-04-30T00:00:00Z",
         "message": {"role": "user", "content": "hello, claude"}},
        # Assistant with all three block types in one row
        {"type": "assistant", "uuid": "a1", "parentUuid": "u1",
         "timestamp": "2026-04-30T00:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "thinking", "thinking": "I should look at the file"},
             {"type": "text", "text": "Sure. Let me check."},
             {"type": "tool_use", "id": "tu1", "name": "Read",
              "input": {"file_path": "/etc/hosts"}},
         ]}},
        # User tool_result
        {"type": "user", "uuid": "u2", "parentUuid": "a1",
         "timestamp": "2026-04-30T00:00:02Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "tu1",
              "content": "127.0.0.1 localhost\n", "is_error": False}
         ]}},
        # Assistant final text
        {"type": "assistant", "uuid": "a2", "parentUuid": "u2",
         "timestamp": "2026-04-30T00:00:03Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "Found localhost in there."}
         ]}},
        # Lifecycle row types
        {"type": "system", "uuid": "sys1"},
        {"type": "permission-mode"},  # no uuid → uses synthetic L{n}
        {"type": "attachment"},
        {"type": "file-history-snapshot",
         "snapshot": [{"path": "/x.py", "post": "new"}]},
    ]
    f = tmp_path / "claude.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return f


def _make_codex_session(tmp_path: Path) -> Path:
    """A diverse codex session covering session_meta + all major payloads."""
    rows = [
        {"timestamp": "2026-04-30T00:00:00Z", "type": "session_meta",
         "payload": {"id": "s1", "cwd": "/tmp", "cli_version": "0.5",
                     "base_instructions": "you are codex"}},
        {"timestamp": "2026-04-30T00:00:01Z", "type": "turn_context",
         "payload": {"turn_id": "t1", "cwd": "/tmp", "model": "gpt-5"}},
        {"timestamp": "2026-04-30T00:00:02Z", "type": "event_msg",
         "payload": {"type": "task_started", "turn_id": "t1"}},
        {"timestamp": "2026-04-30T00:00:03Z", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "list files"}]}},
        {"timestamp": "2026-04-30T00:00:04Z", "type": "response_item",
         "payload": {"type": "reasoning", "summary": [],
                     "encrypted_content": "AAAA=="}},
        {"timestamp": "2026-04-30T00:00:05Z", "type": "response_item",
         "payload": {"type": "function_call", "call_id": "c1", "name": "exec_command",
                     "arguments": json.dumps({"cmd": "ls"})}},
        {"timestamp": "2026-04-30T00:00:06Z", "type": "event_msg",
         "payload": {"type": "exec_command_end", "call_id": "c1",
                     "formatted_output": "a\nb\n", "exit_code": 0,
                     "duration": {"secs": 0, "nanos": 100000000}}},
        {"timestamp": "2026-04-30T00:00:07Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "two files"}]}},
        {"timestamp": "2026-04-30T00:00:08Z", "type": "event_msg",
         "payload": {"type": "token_count",
                     "info": {"last_token_usage": {"input_tokens": 100,
                                                    "output_tokens": 50}}}},
        {"timestamp": "2026-04-30T00:00:09Z", "type": "event_msg",
         "payload": {"type": "task_complete", "turn_id": "t1"}},
    ]
    f = tmp_path / "codex.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return f


# ------------------------------------------------------------------ #
# Self-format roundtrip — byte-equal on synthetic fixtures             #
# ------------------------------------------------------------------ #


def _roundtrip_lines(src, f: Path) -> tuple[list[dict], list[dict]]:
    """Return (orig_lines_parsed, rt_lines_parsed)."""
    orig = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    events = list(src.parse(f))
    out = src.serialize(events).decode("utf-8")
    rt = [json.loads(l) for l in out.splitlines() if l.strip()]
    return orig, rt


def test_claude_self_roundtrip_byte_equal(tmp_path: Path):
    f = _make_claude_session(tmp_path)
    orig, rt = _roundtrip_lines(ClaudeSource(home=tmp_path), f)
    assert len(orig) == len(rt)
    for i, (o, r) in enumerate(zip(orig, rt)):
        assert o == r, f"diff at line {i}: {o} != {r}"


def test_codex_self_roundtrip_byte_equal(tmp_path: Path):
    f = _make_codex_session(tmp_path)
    orig, rt = _roundtrip_lines(CodexSource(home=tmp_path), f)
    assert len(orig) == len(rt)
    for i, (o, r) in enumerate(zip(orig, rt)):
        assert o == r, f"diff at line {i}: {o} != {r}"


# ------------------------------------------------------------------ #
# Cross-format viability                                               #
# ------------------------------------------------------------------ #


def test_claude_to_codex_does_not_crash(tmp_path: Path):
    f = _make_claude_session(tmp_path)
    claude = ClaudeSource(home=tmp_path)
    codex = CodexSource(home=tmp_path)
    events = list(claude.parse(f))
    out = codex.serialize(events)
    assert out  # non-empty
    # Re-parse via codex; must yield events.
    out_path = tmp_path / "converted.jsonl"
    out_path.write_bytes(out)
    re_events = list(codex.parse(out_path))
    assert len(re_events) > 0


def test_codex_to_claude_does_not_crash(tmp_path: Path):
    f = _make_codex_session(tmp_path)
    claude = ClaudeSource(home=tmp_path)
    codex = CodexSource(home=tmp_path)
    events = list(codex.parse(f))
    out = claude.serialize(events)
    assert out
    out_path = tmp_path / "converted.jsonl"
    out_path.write_bytes(out)
    re_events = list(claude.parse(out_path))
    assert len(re_events) > 0


def test_claude_to_codex_preserves_kernel_events(tmp_path: Path):
    """Every kernel-modeled event class on the claude side must survive
    cross-format conversion to codex."""
    f = _make_claude_session(tmp_path)
    claude = ClaudeSource(home=tmp_path)
    codex = CodexSource(home=tmp_path)

    in_events = list(claude.parse(f))
    out_path = tmp_path / "converted.jsonl"
    out_path.write_bytes(codex.serialize(in_events))
    re_events = list(codex.parse(out_path))

    # Kernel types we expect to still be present (lifecycle becomes
    # codex's event_msg.thread_name_updated which re-parses as Lifecycle).
    in_kernel = {e.type for e in in_events
                 if e.type in {"user_message", "assistant_message",
                               "assistant_reasoning", "tool_call",
                               "tool_result", "session_start"}}
    out_kernel = {e.type for e in re_events}

    for kind in in_kernel:
        assert kind in out_kernel, f"{kind} lost in claude→codex conversion"


def test_codex_to_claude_preserves_kernel_events(tmp_path: Path):
    f = _make_codex_session(tmp_path)
    claude = ClaudeSource(home=tmp_path)
    codex = CodexSource(home=tmp_path)

    in_events = list(codex.parse(f))
    out_path = tmp_path / "converted.jsonl"
    out_path.write_bytes(claude.serialize(in_events))
    re_events = list(claude.parse(out_path))

    in_kernel = {e.type for e in in_events
                 if e.type in {"user_message", "assistant_message",
                               "assistant_reasoning", "tool_call",
                               "tool_result"}}
    out_kernel = {e.type for e in re_events}

    for kind in in_kernel:
        assert kind in out_kernel, f"{kind} lost in codex→claude conversion"


# ------------------------------------------------------------------ #
# Lossiness invariants                                                 #
# ------------------------------------------------------------------ #


def test_claude_branch_structure_preserved_within_unified(tmp_path: Path):
    """parent_id chain survives parse round-trip, even though codex output
    won't preserve the tree structure."""
    f = _make_claude_session(tmp_path)
    src = ClaudeSource(home=tmp_path)
    events = list(src.parse(f))

    # Find the assistant event derived from u1
    a1_events = [e for e in events if e.parent_id == "u1"]
    assert a1_events  # something was parented under u1


def test_event_count_consistent_across_self_roundtrip(tmp_path: Path):
    """Same source → unified → same source → unified gives the same event count."""
    for source_factory, fixture_factory in [
        (lambda: ClaudeSource(home=tmp_path), _make_claude_session),
        (lambda: CodexSource(home=tmp_path), _make_codex_session),
    ]:
        f = fixture_factory(tmp_path)
        src = source_factory()
        events1 = list(src.parse(f))
        out = src.serialize(events1)
        out_path = tmp_path / "out.jsonl"
        out_path.write_bytes(out)
        events2 = list(src.parse(out_path))
        assert len(events1) == len(events2), \
            f"{src.name}: {len(events1)} ≠ {len(events2)}"


# ------------------------------------------------------------------ #
# Robustness                                                           #
# ------------------------------------------------------------------ #


def test_claude_serialize_empty_event_list(tmp_path: Path):
    src = ClaudeSource(home=tmp_path)
    assert src.serialize([]) == b""


def test_codex_serialize_empty_event_list(tmp_path: Path):
    src = CodexSource(home=tmp_path)
    assert src.serialize([]) == b""


def test_serialize_handles_synthesized_session_start(tmp_path: Path):
    """Parser-synthesized SessionStart has empty raw; codex serializer
    should still emit it as a session_meta row."""
    from fleet.track.unified import SessionStart

    src = CodexSource(home=tmp_path)
    out = src.serialize([
        SessionStart(source="claude", id="s1", cwd="/tmp", agent_version="0.5",
                     timestamp="2026-04-30T00:00:00Z"),
    ])
    line = json.loads(out.decode("utf-8").strip())
    assert line["type"] == "session_meta"
    assert line["payload"]["cwd"] == "/tmp"
