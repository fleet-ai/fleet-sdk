# Local Resume Test Plan

## Goal

Prove that FleetTrack can restore and resume sessions without breaking local
agent tools.

Lossy conversion is acceptable for cross-tool continuation. Broken native
session files are not acceptable.

## Test Levels

### Level 1: Raw Reassembly

Input: a native session file.

Steps:

1. Segment the file at valid record boundaries.
2. Compress and hash each segment.
3. Reassemble the file from segments.
4. Verify full-file hash equality.
5. Parse every JSONL record.

Pass condition: reassembled file is byte-identical and parse-valid.

### Level 2: Same-Tool Restore Validation

Input: a real Codex or Claude session file.

Steps:

1. Create a temporary HOME.
2. Recreate only the minimal session directory for the target tool.
3. Restore the reassembled raw file into the temp HOME.
4. Run the target tool's safest available non-mutating resume/list command.
5. Confirm the tool can discover or parse the restored session.

Pass condition: the target tool accepts the restored file without loader errors.

This must not use the user's live `~/.codex`, `~/.claude`, or `~/.cursor`
directories.

### Level 3: Same-Tool Resume Smoke

Input: a small synthetic session created for testing.

Steps:

1. Create a throwaway session in the source tool.
2. Archive it through FleetTrack.
3. Restore it into a temp HOME.
4. Attempt an actual resume in the temp HOME when the tool supports it.

Pass condition: the tool starts from the restored session and can accept a new
message.

### Level 4: Cross-Tool Continuation

Input: raw source session plus canonical projection.

Steps:

1. Project source records into `fleet.session.v1`.
2. Export a conservative target-tool continuation candidate.
3. Validate the candidate using the target adapter.
4. Install into temp HOME only after validation.
5. Attempt target-tool load/resume.

Pass condition: target tool loads the continuation. Content may be summarized or
lossy.

## Local CLI Concepts

Development-only commands:

```text
flt track sessions segment-local <path> --out /tmp/fleettrack-segments
flt track sessions reassemble-local <manifest> --out /tmp/session.jsonl
flt track sessions validate-local <path> --tool codex
flt track sessions restore-local <manifest> --tool codex --home /tmp/fleettrack-home
flt track sessions continue-local <manifest> --from claude --to codex --home /tmp/fleettrack-home
```

Production commands should hide these details behind `restore`, `validate`, and
`continue`.

## Adapter Validation Strategy

Validation should be strict for same-tool restore:

- JSONL must parse fully.
- Required top-level keys must exist for the target tool/version.
- Event ordering must be stable.
- Parent pointers should refer to existing events where the tool expects them.
- Restored files must be written atomically.

Validation should be conservative for cross-tool exports:

- Unknown events are allowed to be dropped or summarized.
- Required target fields must be present.
- No raw source-only objects should be injected into target-native files unless
  the adapter explicitly supports them.
- If the target adapter is uncertain, produce a context bundle instead of a
  native session file.

## Fixtures

Create non-sensitive fixtures for:

- Minimal Codex session.
- Codex session with shell command and tool result.
- Codex session with patch/file edits.
- Minimal Claude session.
- Claude session with tool use and tool result.
- Claude session with subagent records.
- Cursor transcript if available.
- Corrupt JSONL with partial final line.
- Truncated file.
- File rewrite/truncation generation.

Fixtures should be synthetic or scrubbed. Do not commit private user session
content.

## Success Criteria

Before enabling v2 upload by default:

- 100% pass for raw reassembly fixtures.
- 100% pass for same-tool restore validation fixtures.
- At least one real temp-HOME resume smoke for Codex.
- At least one real temp-HOME resume smoke for Claude, if Claude exposes a safe
  way to run it.
- Cross-tool continuation must fail closed: if validation cannot prove safety,
  it emits a context bundle and does not write a native session file.

