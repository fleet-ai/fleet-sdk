# Unified Session Format

## Purpose

The unified format is a Fleet-owned projection over raw session records. It is
for search, analysis, rendering, and best-effort continuation across tools.

It is not the only source of truth. The raw native records remain archived so we
can restore same-tool sessions exactly and improve adapters later.

## Design Principle

The unified model should be conservative:

- Preserve provenance for every canonical event.
- Preserve unknown source fields.
- Prefer an explicit `unknown` event over dropping data.
- Do not claim a cross-tool export is exact unless the target adapter validates
  it.

## Top-Level Objects

```json
{
  "schema": "fleet.session.v1",
  "session": {
    "id": "...",
    "source": "codex",
    "source_session_id": "...",
    "workspace": {
      "cwd": "...",
      "git_branch": "...",
      "repo_hint": "..."
    },
    "started_at": "...",
    "ended_at": null
  },
  "events": []
}
```

## Event Envelope

Every canonical event uses one envelope:

```json
{
  "id": "stable event id",
  "seq": 123,
  "time": "2026-04-29T00:00:00Z",
  "kind": "message",
  "role": "assistant",
  "parent_id": "...",
  "turn_id": "...",
  "source": {
    "tool": "claude",
    "path": ".claude/projects/...jsonl",
    "record_seq": 456,
    "record_sha256": "...",
    "raw_object_hash": "...",
    "adapter": "claude@0.1.0"
  },
  "body": {},
  "unknown": {}
}
```

`source` is mandatory. `unknown` is where adapter-preserved fields live when the
canonical schema does not have a first-class representation.

## Core Event Kinds

- `session_meta`
- `turn_start`
- `turn_end`
- `message`
- `reasoning`
- `tool_call`
- `tool_result`
- `shell_command`
- `shell_result`
- `file_patch`
- `file_snapshot`
- `attachment`
- `permission_request`
- `permission_result`
- `environment_context`
- `error`
- `unknown`

## Message Body

```json
{
  "kind": "message",
  "role": "user|assistant|system",
  "body": {
    "content": [
      {"type": "text", "text": "..."},
      {"type": "image_ref", "uri": "..."},
      {"type": "file_ref", "path": "..."}
    ]
  }
}
```

## Tool Call Body

```json
{
  "kind": "tool_call",
  "body": {
    "call_id": "...",
    "tool_name": "exec_command",
    "arguments": {},
    "status": "started|completed|failed"
  }
}
```

Tool results should preserve raw output references. Large outputs should be
stored as separate content-addressed objects rather than embedded directly.

## Same-Tool Restore

Same-tool restore does not require the unified model. It reassembles raw native
segments, verifies hashes, validates the file, and writes it into the target
tool's session directory.

This path should be exact.

## Cross-Tool Continuation

Cross-tool continuation uses the unified model to produce a valid target
session or import bundle.

Rules:

- Prefer creating a new target session over modifying an existing one.
- Include a summary, recent transcript, important tool calls/results, file
  changes, and environment context.
- Use only fields the target adapter is known to accept.
- Validate before install.
- If validation fails, output a markdown/context bundle instead.

## Adapter Contract

Each adapter should implement:

```text
detect(paths) -> source sessions
parse(raw records) -> canonical events
validate_raw_restore(file) -> ok/errors
write_same_tool_restore(raw file, destination) -> result
export_continuation(canonical session, destination tool) -> candidate
validate_export(candidate) -> ok/errors
```

Adapters are versioned independently because Claude, Codex, and Cursor formats
can change without notice.

