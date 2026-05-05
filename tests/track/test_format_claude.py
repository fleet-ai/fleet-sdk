"""ClaudeSource.parse tests — every row type, every content block, robustness corpus."""

from __future__ import annotations

import json
from pathlib import Path

from fleet.track.sources import ClaudeSource


def _write(tmp_path: Path, lines: list[dict]) -> Path:
    f = tmp_path / "session.jsonl"
    f.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return f


def _parse(tmp_path: Path, lines: list[dict]):
    f = _write(tmp_path, lines)
    return list(ClaudeSource(home=tmp_path).parse(f))


# ------------------------------------------------------------------ #
# SessionStart synthesis                                               #
# ------------------------------------------------------------------ #


def test_first_row_synthesizes_session_start(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "user", "uuid": "u1", "sessionId": "s1", "cwd": "/tmp", "gitBranch": "main",
         "version": "0.5", "message": {"role": "user", "content": "hi"}, "timestamp": "2026-04-30T00:00:00Z"},
    ])
    assert events[0].type == "session_start"
    assert events[0].cwd == "/tmp"
    assert events[0].agent_version == "0.5"
    assert events[0].git_branch == "main"
    assert events[1].type == "user_message"
    assert events[1].text == "hi"


def test_no_session_start_when_metadata_missing(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "system", "uuid": "x", "message": "boot"},
    ])
    assert events[0].type == "lifecycle"
    assert events[0].name == "system"


# ------------------------------------------------------------------ #
# user content shapes                                                  #
# ------------------------------------------------------------------ #


def test_user_string_content(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "hello"}},
    ])
    user_msgs = [e for e in events if e.type == "user_message"]
    assert len(user_msgs) == 1
    assert user_msgs[0].text == "hello"


def test_user_text_block(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "user", "uuid": "u1", "message": {"role": "user",
            "content": [{"type": "text", "text": "wrapped"}]}},
    ])
    msgs = [e for e in events if e.type == "user_message"]
    assert len(msgs) == 1
    assert msgs[0].text == "wrapped"


def test_user_tool_result_block(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "user", "uuid": "u1", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tc1",
             "content": "exit code 0", "is_error": False}
        ]}},
    ])
    results = [e for e in events if e.type == "tool_result"]
    assert len(results) == 1
    assert results[0].tool_call_id == "tc1"
    assert results[0].output == "exit code 0"
    assert results[0].is_error is False


def test_user_tool_result_with_block_content(tmp_path: Path):
    """tool_result.content can be a list of typed blocks (text, image)."""
    events = _parse(tmp_path, [
        {"type": "user", "uuid": "u1", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tc1", "content": [
                {"type": "text", "text": "line one"},
                {"type": "image", "source": {"data": "..."}}
            ]}
        ]}},
    ])
    results = [e for e in events if e.type == "tool_result"]
    assert len(results) == 1
    assert "line one" in results[0].output
    assert "[image]" in results[0].output


def test_user_image_block_becomes_attachment(tmp_path: Path):
    """User-attached image surfaces as a first-class Attachment event."""
    events = _parse(tmp_path, [
        {"type": "user", "uuid": "u1", "message": {"role": "user", "content": [
            {"type": "image", "source": {"data": "BASE64_DATA",
                                         "media_type": "image/png"}}
        ]}},
    ])
    atts = [e for e in events if e.type == "attachment"]
    assert len(atts) == 1
    assert atts[0].media_type == "image/png"
    assert atts[0].content == "BASE64_DATA"


def test_user_with_multiple_blocks_yields_multiple_events(tmp_path: Path):
    """One row, three blocks → three events with sub-id suffixes."""
    events = _parse(tmp_path, [
        {"type": "user", "uuid": "u1", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tc1", "content": "ok"},
            {"type": "tool_result", "tool_use_id": "tc2", "content": "ok"},
            {"type": "text", "text": "trailing note"},
        ]}},
    ])
    derived = [e for e in events if e.type in ("tool_result", "user_message")]
    assert len(derived) == 3
    # First sub-event keeps the row's uuid; rest are suffixed.
    assert derived[0].id == "u1"
    assert derived[1].id == "u1#1"
    assert derived[2].id == "u1#2"


# ------------------------------------------------------------------ #
# assistant content shapes                                             #
# ------------------------------------------------------------------ #


def test_assistant_text_block(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "assistant", "uuid": "a1", "message": {"role": "assistant",
            "content": [{"type": "text", "text": "answer"}]}},
    ])
    msgs = [e for e in events if e.type == "assistant_message"]
    assert len(msgs) == 1
    assert msgs[0].text == "answer"


def test_assistant_thinking_block(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "assistant", "uuid": "a1", "message": {"role": "assistant",
            "content": [{"type": "thinking", "thinking": "let me reason..."}]}},
    ])
    reasoning = [e for e in events if e.type == "assistant_reasoning"]
    assert len(reasoning) == 1
    assert reasoning[0].text == "let me reason..."


def test_assistant_tool_use_block(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "assistant", "uuid": "a1", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_01", "name": "Bash",
             "input": {"command": "ls", "description": "list"}}
        ]}},
    ])
    calls = [e for e in events if e.type == "tool_call"]
    assert len(calls) == 1
    assert calls[0].tool_call_id == "toolu_01"
    assert calls[0].name == "Bash"
    assert calls[0].input == {"command": "ls", "description": "list"}


def test_assistant_with_thinking_text_and_tool_use(tmp_path: Path):
    """Real claude assistant rows often interleave all three block types."""
    events = _parse(tmp_path, [
        {"type": "assistant", "uuid": "a1", "message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "I should..."},
            {"type": "text", "text": "OK, running:"},
            {"type": "tool_use", "id": "tu1", "name": "Bash", "input": {"command": "ls"}},
        ]}},
    ])
    derived = [e for e in events if e.type in ("assistant_reasoning", "assistant_message", "tool_call")]
    assert [e.type for e in derived] == ["assistant_reasoning", "assistant_message", "tool_call"]
    assert derived[0].id == "a1"
    assert derived[1].id == "a1#1"
    assert derived[2].id == "a1#2"


# ------------------------------------------------------------------ #
# Lifecycle row types                                                  #
# ------------------------------------------------------------------ #


def test_lifecycle_row_types_all_named_correctly(tmp_path: Path):
    """Pure-lifecycle row types (no kernel-level meaning) round-trip
    through Lifecycle. permission-mode and attachment are now
    promoted to Operator and Attachment respectively — see their
    own tests below."""
    cases = [
        ("system", "system"),
        ("last-prompt", "last_prompt"),
        ("ai-title", "ai_title"),
        ("custom-title", "custom_title"),
        ("agent-name", "agent_name"),
        ("queue-operation", "queue_operation"),
        ("pr-link", "pr_link"),
        ("progress", "progress"),
    ]
    for raw_type, expected_name in cases:
        events = _parse(tmp_path, [{"type": raw_type, "uuid": "x"}])
        assert events[0].type == "lifecycle"
        assert events[0].name == expected_name, f"raw={raw_type}"


def test_permission_mode_row_becomes_operator(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "permission-mode", "uuid": "x", "permissionMode": "acceptEdits"},
    ])
    assert events[0].type == "operator"
    assert events[0].action == "permission_mode"
    assert events[0].detail == "acceptEdits"


def test_attachment_row_becomes_attachment_event(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "attachment", "uuid": "x",
         "attachment": {"type": "image/png", "name": "diagram.png",
                        "path": "/tmp/diagram.png"}},
    ])
    assert events[0].type == "attachment"
    assert events[0].media_type == "image/png"
    assert events[0].name == "diagram.png"
    assert events[0].ref == "/tmp/diagram.png"


def test_assistant_message_carries_model(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "assistant", "uuid": "a1",
         "message": {"role": "assistant", "model": "claude-opus-4-7",
                     "content": [{"type": "text", "text": "hi"}]}},
    ])
    msgs = [e for e in events if e.type == "assistant_message"]
    assert msgs[0].model == "claude-opus-4-7"


# ------------------------------------------------------------------ #
# file-history-snapshot                                                #
# ------------------------------------------------------------------ #


def test_file_history_snapshot_single_file(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "file-history-snapshot", "uuid": "fh1",
         "snapshot": {"path": "src/foo.py", "diff": "@@ -1 +1 @@", "pre": "old", "post": "new"}},
    ])
    edits = [e for e in events if e.type == "file_edit"]
    assert len(edits) == 1
    assert edits[0].path == "src/foo.py"
    assert edits[0].diff == "@@ -1 +1 @@"


def test_file_history_snapshot_list(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "file-history-snapshot", "uuid": "fh1", "snapshot": [
            {"path": "a.py", "post": "x"},
            {"path": "b.py", "post": "y"},
        ]},
    ])
    edits = [e for e in events if e.type == "file_edit"]
    assert [e.path for e in edits] == ["a.py", "b.py"]


def test_file_history_snapshot_no_snapshot_falls_back_to_lifecycle(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "file-history-snapshot", "uuid": "fh1"},
    ])
    assert events[0].type == "lifecycle"
    assert events[0].name == "file_history_snapshot"


# ------------------------------------------------------------------ #
# parent_id / tree                                                     #
# ------------------------------------------------------------------ #


def test_parent_id_propagates_from_parent_uuid(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "user", "uuid": "u1", "parentUuid": None,
         "message": {"role": "user", "content": "first"}},
        {"type": "assistant", "uuid": "a1", "parentUuid": "u1",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}},
    ])
    msgs = [e for e in events if e.type in ("user_message", "assistant_message")]
    assert msgs[0].id == "u1"
    assert msgs[0].parent_id is None
    assert msgs[1].id == "a1"
    assert msgs[1].parent_id == "u1"


# ------------------------------------------------------------------ #
# Robustness                                                           #
# ------------------------------------------------------------------ #


def test_malformed_line_is_skipped(tmp_path: Path):
    f = tmp_path / "session.jsonl"
    f.write_text(
        json.dumps({"type": "user", "uuid": "u1", "message": {"content": "good"}}) + "\n"
        + "this is not json\n"
        + json.dumps({"type": "assistant", "uuid": "a1",
                      "message": {"content": [{"type": "text", "text": "after"}]}}) + "\n"
    )
    events = list(ClaudeSource(home=tmp_path).parse(f))
    msgs = [e for e in events if e.type in ("user_message", "assistant_message")]
    assert len(msgs) == 2


def test_unknown_top_level_type_is_opaque(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "totally-new-event-type", "uuid": "x"},
    ])
    op = [e for e in events if e.type == "opaque"]
    assert len(op) == 1
    assert op[0].original_type == "totally-new-event-type"


def test_unknown_assistant_block_is_opaque(tmp_path: Path):
    events = _parse(tmp_path, [
        {"type": "assistant", "uuid": "a1", "message": {"role": "assistant",
            "content": [{"type": "future_block", "data": 1}]}},
    ])
    op = [e for e in events if e.type == "opaque"]
    assert len(op) == 1
    assert "future_block" in op[0].original_type


def test_empty_file_yields_no_events(tmp_path: Path):
    f = tmp_path / "empty.jsonl"
    f.write_text("")
    events = list(ClaudeSource(home=tmp_path).parse(f))
    assert events == []


def test_missing_file_yields_no_events_and_no_raise(tmp_path: Path):
    """Parse on a path that doesn't exist must not raise."""
    src = ClaudeSource(home=tmp_path)
    events = list(src.parse(tmp_path / "ghost.jsonl"))
    assert events == []


def test_assistant_with_string_content_not_list(tmp_path: Path):
    """If claude ever emits string content for assistant — surface as opaque, no crash."""
    events = _parse(tmp_path, [
        {"type": "assistant", "uuid": "a1", "message": {"role": "assistant", "content": "weird"}},
    ])
    op = [e for e in events if e.type == "opaque"]
    assert len(op) == 1
    assert op[0].original_type == "assistant_unknown_content_shape"
