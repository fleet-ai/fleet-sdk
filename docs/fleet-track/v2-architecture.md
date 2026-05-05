# FleetTrack V2 Architecture

## Summary

FleetTrack v2 should be a content-addressed session archive with explicit
version commits.

The current implementation uploads whole changed files. That is simple, but it
does not scale for long hot JSONL sessions. A single large transcript that
changes frequently can be re-uploaded many times, and the S3 bucket currently has
versioning enabled.

V2 should upload immutable compressed segments and advance a session ref only
after all required objects are present.

## Storage Model

Use immutable objects for data and small mutable refs for latest state.

```text
fleet-track-sessions/
  v2/
    objects/
      sha256/
        ab/cd/{object_hash}.zst
    sessions/
      {team_id}/{user_id}/{source}/{source_session_id}/
        versions/{version_id}.json
        refs/latest.json
        raw-paths/{path_hash}.json
```

`objects/` are content-addressed and immutable. They can be shared by multiple
versions, devices, or restored sessions if hashes match.

`versions/` are immutable manifests.

`refs/latest.json` is the only mutable pointer. It should be updated by the
server with parent-version checks.

## Segment Boundaries

For JSONL sources, the segmenter must cut only at complete JSONL record
boundaries. It must ignore a trailing incomplete line until the next pass.

Segment cut policy:

- target compressed size: 1-8 MiB
- hard uncompressed cap: configurable, initially 32 MiB
- max records per segment: configurable, initially 5,000
- max open time for active files: 30-120 seconds
- boundary rule: complete JSONL records only

If a single JSONL record exceeds the hard cap, store it as a one-record segment.
Do not split the record.

For plain text transcripts, use line boundaries if possible. For unknown binary
or opaque files, either store whole-file objects or use fixed-size chunks with a
separate "opaque" file type. Opaque files are restorable but not canonicalized.

## Local Checkpoints

The daemon should keep a checkpoint per logical source file:

```json
{
  "schema_version": 1,
  "source": "codex",
  "path": ".codex/sessions/2026/04/session.jsonl",
  "file_id": "stable id derived from source metadata or path",
  "generation": 3,
  "last_complete_offset": 12345678,
  "last_record_seq": 9182,
  "prefix_sha256": "...",
  "latest_version_id": "..."
}
```

The checkpoint is an optimization, not trust. Reconciliation can rebuild state
from local records and remote manifests.

Detect file rewrite/truncation by comparing size, mtime, and prefix hash. If a
file shrinks or its known prefix no longer matches, increment `generation` and
commit a new version lineage for that path.

## Version Manifest

Each version is an immutable commit:

```json
{
  "schema_version": 2,
  "version_id": "sha256 of canonical manifest body",
  "parent_version_id": "...",
  "source": "codex",
  "source_session_id": "...",
  "device_id": "...",
  "created_at": "2026-04-29T00:00:00Z",
  "logical_files": [
    {
      "path": ".codex/sessions/...",
      "generation": 3,
      "file_kind": "jsonl",
      "segments": [
        {
          "seq_start": 0,
          "seq_end": 999,
          "record_count": 1000,
          "start_offset": 0,
          "end_offset": 881231,
          "raw_sha256": "...",
          "object_hash": "...",
          "compression": "zstd"
        }
      ],
      "file_sha256": "sha256 of full reassembled file when known"
    }
  ],
  "canonical_projection": {
    "schema": "fleet.session.v1",
    "adapter": "codex@0.1.0",
    "status": "pending"
  }
}
```

`version_id` should be content-derived from a canonical JSON body so commits are
deduplicable and tamper-evident.

## Server API

The v1 API can remain for compatibility. Add v2 endpoints:

```text
POST /v2/track/plan
POST /v2/track/commit
GET  /v2/track/sessions
GET  /v2/track/sessions/{session_id}/manifest
POST /v2/track/restore-plan
```

`/plan` accepts candidate object hashes and returns presigned upload URLs only
for missing objects.

`/commit` accepts a version manifest and an expected parent ref. The server
checks that all referenced objects exist, writes the immutable version, then
conditionally advances `refs/latest.json`.

`/restore-plan` returns a manifest and presigned download URLs for required
objects.

## CLI Surface

Keep `flt track` as the product namespace.

Initial commands:

```text
flt track enable
flt track status
flt track doctor
flt track sessions list
flt track sessions inspect <session-id>
flt track sessions validate <session-id>
flt track sessions restore <session-id> --tool codex --dry-run
flt track sessions restore <session-id> --tool codex
flt track sessions export <session-id> --format markdown
```

Later commands:

```text
flt track sessions continue <session-id> --from claude --to codex
flt track sessions canonicalize <session-id>
flt track sessions diff <session-id> --version A..B
```

`restore` defaults to dry-run validation unless `--yes` or an interactive prompt
confirms writing into the live session directory.

## Current Prototype Reuse

Use the current daemon as the scaffolding for v2:

- Replace file upload work items with segment upload work items.
- Replace `manifest.json` flat map with version manifests.
- Keep the SQLite queue, but make queue rows object/commit oriented.
- Keep the presigned URL pattern, but make the server return URLs for missing
  object hashes.
- Keep full reconciliation, but compare logical session versions rather than
  whole-file hashes.

