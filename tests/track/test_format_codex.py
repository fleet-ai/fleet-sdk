"""CodexSource.parse tests — every payload type, robustness corpus."""

from __future__ import annotations

import json
from pathlib import Path

from fleet.track.sources import CodexSource


def _write(tmp_path: Path, lines: list[dict]) -> Path:
    f = tmp_path / "session.jsonl"
    f.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return f


def _parse(tmp_path: Path, lines: list[dict]):
    f = _write(tmp_path, lines)
    return list(CodexSource(home=tmp_path).parse(f))


def _evt(timestamp="2026-04-30T00:00:00Z", **kw):
    return {"timestamp": timestamp, **kw}


# ------------------------------------------------------------------ #
# Top-level types                                                      #
# ------------------------------------------------------------------ #


def test_session_meta_becomes_session_start(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="session_meta",
        payload={"id": "sess1", "cwd": "/tmp", "cli_version": "0.5", "base_instructions": "you are codex"},
    )])
    assert events[0].type == "session_start"
    # id is the row-unique synthetic id (used for serializer dedup);
    # the codex session id lives in raw.
    assert events[0].raw["payload"]["id"] == "sess1"
    assert events[0].cwd == "/tmp"
    assert events[0].agent_version == "0.5"
    assert events[0].user_instructions == "you are codex"


def test_session_meta_with_dict_base_instructions(tmp_path: Path):
    """codex sometimes wraps base_instructions as {text: '...'}."""
    events = _parse(tmp_path, [_evt(
        type="session_meta",
        payload={"id": "s", "base_instructions": {"text": "hi"}},
    )])
    assert events[0].user_instructions == "hi"


def test_turn_context_becomes_turn_start(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="turn_context",
        payload={"turn_id": "t1", "cwd": "/x", "model": "gpt-5", "approval_policy": "never"},
    )])
    assert events[0].type == "turn_start"
    assert events[0].turn_id == "t1"
    assert events[0].cwd == "/x"
    assert events[0].model == "gpt-5"


# ------------------------------------------------------------------ #
# response_item                                                        #
# ------------------------------------------------------------------ #


def test_response_item_message_user(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "hi"}]},
    )])
    msgs = [e for e in events if e.type == "user_message"]
    assert msgs[0].text == "hi"


def test_response_item_message_developer_treated_as_user(tmp_path: Path):
    """developer-role messages are system instructions; we map them to user_message
    so the unified stream is monotonic (codex injects them mid-conversation)."""
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "message", "role": "developer",
                 "content": [{"type": "input_text", "text": "<perms>do this</perms>"}]},
    )])
    assert events[0].type == "user_message"


def test_response_item_message_assistant(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "answer"}]},
    )])
    msgs = [e for e in events if e.type == "assistant_message"]
    assert msgs[0].text == "answer"


def test_response_item_function_call(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "function_call", "call_id": "c1", "name": "exec_command",
                 "arguments": json.dumps({"cmd": "ls", "workdir": "/"})},
    )])
    calls = [e for e in events if e.type == "tool_call"]
    assert calls[0].tool_call_id == "c1"
    assert calls[0].name == "exec_command"
    assert calls[0].input == {"cmd": "ls", "workdir": "/"}


def test_response_item_function_call_with_malformed_args(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "function_call", "call_id": "c1", "name": "n", "arguments": "{not json"},
    )])
    assert events[0].input == {}  # tolerated


def test_response_item_function_call_output(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "function_call_output", "call_id": "c1", "output": "OK\n"},
    )])
    assert events[0].type == "tool_result"
    assert events[0].tool_call_id == "c1"
    assert events[0].output == "OK\n"


def test_response_item_reasoning_encrypted(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "reasoning", "summary": [], "encrypted_content": "abc=="},
    )])
    r = events[0]
    assert r.type == "assistant_reasoning"
    assert r.encrypted is True
    assert r.encrypted_content == "abc=="
    assert r.text is None


def test_response_item_reasoning_with_summary(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "reasoning",
                 "summary": [{"type": "summary_text", "text": "checking foo"}]},
    )])
    assert events[0].text == "checking foo"


def test_response_item_compacted_is_lifecycle(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item", payload={"type": "compacted"}
    )])
    assert events[0].type == "lifecycle"
    assert events[0].name == "context_compacted"


def test_response_item_custom_tool_call(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "custom_tool_call", "id": "c1", "name": "my_tool",
                 "input": json.dumps({"x": 1})},
    )])
    assert events[0].type == "tool_call"
    assert events[0].name == "my_tool"
    assert events[0].input == {"x": 1}


def test_response_item_web_search_call(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "web_search_call", "id": "w1",
                 "action": {"query": "fleet sdk", "num": 5}},
    )])
    assert events[0].type == "tool_call"
    assert events[0].input == {"query": "fleet sdk", "num": 5}


def test_response_item_tool_search_call(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "tool_search_call", "call_id": "ts1",
                 "arguments": {"query": "github"}},
    )])
    assert events[0].type == "tool_call"
    assert events[0].input == {"query": "github"}


def test_response_item_tool_search_output(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "tool_search_output", "call_id": "ts1",
                 "tools": [{"type": "function", "name": "github_get"}]},
    )])
    assert events[0].type == "tool_result"
    assert events[0].tool_call_id == "ts1"
    assert "github_get" in events[0].output


# ------------------------------------------------------------------ #
# event_msg                                                            #
# ------------------------------------------------------------------ #


def test_event_msg_user_message(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="event_msg",
        payload={"type": "user_message", "message": "hi"},
    )])
    assert events[0].type == "user_message"
    assert events[0].text == "hi"


def test_event_msg_user_message_with_inline_image(tmp_path: Path):
    """codex inline image in `images` becomes an Attachment event."""
    events = _parse(tmp_path, [_evt(
        type="event_msg",
        payload={"type": "user_message", "message": "look",
                 "images": ["BASE64_INLINE_IMAGE"],
                 "local_image_paths": ["/tmp/x.png"]},
    )])
    by_type = {e.type for e in events}
    assert "user_message" in by_type
    atts = [e for e in events if e.type == "attachment"]
    assert len(atts) == 2
    inline = next(a for a in atts if a.content)
    ref = next(a for a in atts if a.ref)
    assert inline.content == "BASE64_INLINE_IMAGE"
    assert ref.ref == "/tmp/x.png"
    assert ref.media_type == "image/png"


def test_event_msg_agent_message_with_phase(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="event_msg",
        payload={"type": "agent_message", "message": "OK", "phase": "commentary"},
    )])
    assert events[0].type == "assistant_message"
    assert events[0].phase == "commentary"


def test_event_msg_agent_reasoning(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="event_msg",
        payload={"type": "agent_reasoning", "text": "thinking"},
    )])
    assert events[0].type == "assistant_reasoning"
    assert events[0].text == "thinking"
    assert events[0].encrypted is False


def test_event_msg_task_lifecycle(tmp_path: Path):
    events = _parse(tmp_path, [
        _evt(type="event_msg", payload={"type": "task_started", "turn_id": "t1"}),
        _evt(type="event_msg", payload={"type": "task_complete", "turn_id": "t1"}),
        _evt(type="event_msg", payload={"type": "turn_aborted", "turn_id": "t2"}),
    ])
    assert events[0].type == "turn_start"
    assert events[1].type == "turn_end"
    assert events[1].aborted is False
    assert events[2].type == "turn_end"
    assert events[2].aborted is True


def test_event_msg_token_count(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="event_msg",
        payload={"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 100, "output_tokens": 50,
                                 "cached_input_tokens": 80, "total_tokens": 150}
        }},
    )])
    e = events[0]
    assert e.type == "token_usage"
    assert e.input_tokens == 100
    assert e.output_tokens == 50
    assert e.cache_read_tokens == 80
    assert e.total_tokens == 150
    assert e.provider == "openai"  # default when session_meta hasn't set one


def test_token_count_provider_from_session_meta(tmp_path: Path):
    """A session_meta row carrying `model_provider` should propagate to
    subsequent token_count events."""
    events = _parse(tmp_path, [
        _evt(type="session_meta",
             payload={"id": "s", "cwd": "/x", "model_provider": "azure-openai"}),
        _evt(type="event_msg",
             payload={"type": "token_count",
                      "info": {"last_token_usage":
                                   {"input_tokens": 1, "output_tokens": 2}}}),
    ])
    usage = next(e for e in events if e.type == "token_usage")
    assert usage.provider == "azure-openai"


def test_assistant_message_model_tracked_from_turn_context(tmp_path: Path):
    """A turn_context with `model: gpt-5` should make later AssistantMessages
    in the same span carry that model."""
    events = _parse(tmp_path, [
        _evt(type="turn_context",
             payload={"turn_id": "t1", "cwd": "/x", "model": "gpt-5",
                      "approval_policy": "never"}),
        _evt(type="response_item",
             payload={"type": "message", "role": "assistant",
                      "content": [{"type": "output_text", "text": "answer"}]}),
        _evt(type="event_msg",
             payload={"type": "agent_message", "message": "answer", "phase": "final"}),
    ])
    asst = [e for e in events if e.type == "assistant_message"]
    assert len(asst) == 2
    assert all(a.model == "gpt-5" for a in asst)


def test_approval_policy_change_emits_operator(tmp_path: Path):
    """Mid-session approval_policy toggles surface as Operator events."""
    events = _parse(tmp_path, [
        _evt(type="turn_context",
             payload={"turn_id": "t1", "approval_policy": "never"}),
        _evt(type="turn_context",
             payload={"turn_id": "t2", "approval_policy": "on-request"}),
    ])
    ops = [e for e in events if e.type == "operator"]
    assert len(ops) == 1
    assert ops[0].action == "approval_policy"
    assert ops[0].detail == "on-request"
    assert ops[0].metadata == {"previous": "never", "current": "on-request"}


def test_no_operator_event_on_first_turn_context(tmp_path: Path):
    """First turn_context establishes baseline; should NOT emit an Operator."""
    events = _parse(tmp_path, [
        _evt(type="turn_context",
             payload={"turn_id": "t1", "approval_policy": "never"}),
    ])
    assert not any(e.type == "operator" for e in events)


def test_event_msg_exec_command_end(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="event_msg",
        payload={"type": "exec_command_end", "call_id": "c1",
                 "formatted_output": "files\n", "exit_code": 0,
                 "duration": {"secs": 1, "nanos": 500000000}},
    )])
    e = events[0]
    assert e.type == "tool_result"
    assert e.tool_call_id == "c1"
    assert e.output == "files\n"
    assert e.exit_code == 0
    assert e.duration_ms == 1500


def test_event_msg_mcp_tool_call_end(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="event_msg",
        payload={"type": "mcp_tool_call_end", "call_id": "c1",
                 "invocation": {"server": "github", "tool": "get_pr", "arguments": {"n": 1}},
                 "duration": {"secs": 0, "nanos": 700000000},
                 "result": {"Ok": {"content": [{"type": "text", "text": "PR data"}]}}},
    )])
    e = events[0]
    assert e.type == "tool_result"
    assert e.tool_call_id == "c1"
    assert "PR data" in e.output
    assert e.is_error is False
    assert e.duration_ms == 700


def test_event_msg_mcp_tool_call_end_with_error(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="event_msg",
        payload={"type": "mcp_tool_call_end", "call_id": "c1",
                 "result": {"Err": {"reason": "timeout"}}},
    )])
    assert events[0].type == "tool_result"
    assert events[0].is_error is True


def test_event_msg_collab_agent_spawn_end(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="event_msg",
        payload={"type": "collab_agent_spawn_end", "call_id": "c1",
                 "new_thread_id": "thread2", "new_agent_nickname": "Zeno",
                 "new_agent_role": "default", "prompt": "do work"},
    )])
    e = events[0]
    assert e.type == "tool_call"
    assert e.tool_call_id == "c1"
    assert e.name == "collab_agent.default"
    assert e.input["agent_nickname"] == "Zeno"
    assert e.input["prompt"] == "do work"


def test_event_msg_collab_close_end(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="event_msg",
        payload={"type": "collab_close_end", "call_id": "c1",
                 "status": {"completed": "all done"}},
    )])
    assert events[0].type == "tool_result"
    assert events[0].output == "all done"


def test_event_msg_lifecycle_types(tmp_path: Path):
    cases = [
        ("thread_name_updated", "thread_name_updated"),
        ("error", "error"),
        ("context_compacted", "context_compacted"),
        ("patch_apply_end", "patch_apply_end"),
    ]
    for raw, expected_name in cases:
        events = _parse(tmp_path, [_evt(type="event_msg", payload={"type": raw})])
        assert events[0].type == "lifecycle"
        assert events[0].name == expected_name, f"raw={raw}"


# ------------------------------------------------------------------ #
# Top-level compacted                                                  #
# ------------------------------------------------------------------ #


def test_top_level_compacted_is_lifecycle(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="compacted",
        payload={"message": "", "replacement_history": [{"type": "message"}]},
    )])
    assert events[0].type == "lifecycle"
    assert events[0].name == "context_compacted"


# ------------------------------------------------------------------ #
# Robustness                                                           #
# ------------------------------------------------------------------ #


def test_unknown_response_item_payload_is_opaque(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="response_item",
        payload={"type": "future_payload_type", "stuff": 1},
    )])
    assert events[0].type == "opaque"
    assert "future_payload_type" in events[0].original_type


def test_unknown_event_msg_payload_is_opaque(tmp_path: Path):
    events = _parse(tmp_path, [_evt(
        type="event_msg",
        payload={"type": "future_event"},
    )])
    assert events[0].type == "opaque"


def test_unknown_top_level_type_is_opaque(tmp_path: Path):
    events = _parse(tmp_path, [_evt(type="future_top_level", payload={})])
    assert events[0].type == "opaque"


def test_malformed_json_lines_are_skipped(tmp_path: Path):
    f = tmp_path / "session.jsonl"
    f.write_text(
        json.dumps(_evt(type="event_msg", payload={"type": "user_message", "message": "a"})) + "\n"
        + "garbage line not json\n"
        + json.dumps(_evt(type="event_msg", payload={"type": "agent_message", "message": "b"})) + "\n"
    )
    events = list(CodexSource(home=tmp_path).parse(f))
    msgs = [e.text for e in events if e.type in ("user_message", "assistant_message")]
    assert msgs == ["a", "b"]


def test_empty_payload_does_not_raise(tmp_path: Path):
    """Some rows may have payload=null."""
    events = _parse(tmp_path, [{"type": "response_item", "timestamp": "t", "payload": None}])
    # payload becomes {}, ptype is None, falls through to OpaqueEvent.
    assert events[0].type == "opaque"
