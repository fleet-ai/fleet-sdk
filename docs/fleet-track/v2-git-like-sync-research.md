# FleetTrack V2 Git-Like Sync Research

## Summary

FleetTrack v2 should keep the product surface of v1, but replace the storage
protocol with a git-like commit model optimized for append-only agent session
files.

The design should not depend on S3 bucket versioning as product history. S3
versioning can remain a recovery backstop, but FleetTrack history should be
represented explicitly by immutable objects, immutable version manifests, and
mutable refs.

The practical model is:

- content-addressed objects store compressed session byte ranges
- commits/version manifests describe a complete logical session state
- refs point to the latest version for a branch
- branches are per device or per continuation by default
- listing defaults to refs/latest, not every version

## Current V1 Cadence

The current daemon uploads whole changed files, not append segments.

Observed from the SDK implementation:

- A full reconciliation scan runs on startup and every 10 minutes.
- Reconciliation hashes local source files and queues files whose hashes differ
  from the remote manifest.
- The daemon main loop drains the queue every 10 seconds.
- Each queue drain claims up to 32 files.
- Uploads run with 8 worker threads.
- Presigned URL requests are chunked at 100 paths.
- JSONL uploads trim a trailing incomplete line before upload.
- The remote manifest is uploaded after pending and in-flight queue items drain.

The file watcher module still exists, but v1 does not use watcher-driven uploads
by default. This keeps v1 as a simple end-to-end sync path rather than an
aggressive hot-file uploader.

This means changed files are normally picked up by the next reconciliation pass,
or immediately when running the one-shot E2E path.

## Goals

V2 should support:

- efficient backup of long active JSONL sessions
- exact same-tool restore from raw native bytes
- explicit version history without relying on S3 object versions
- latest-only default listing
- opt-in version history and diff views
- local-first validation before orchestrator rollout
- v1 shipping in parallel without shaping the v2 protocol

## Non-Goals For The First V2

Do not implement merge semantics initially.

Do not allow multiple devices to advance the same branch as a normal path. If a
session is restored or continued on another device, create a new branch/ref.

Do not make the canonical Fleet event model the archival source of truth. The raw
native byte archive remains the exact restore source. Canonical events are a
projection for search, inspection, and cross-tool continuation.

## Storage Primitives

### Object

An object is immutable compressed bytes, addressed by hash.

```text
v2/objects/sha256/ab/cd/{object_hash}.zst
```

The object hash should cover the stored bytes. Segment metadata can separately
record the raw uncompressed hash.

### Segment

A segment is a contiguous range of one logical source file.

For JSONL files, segments must only cut at complete JSONL record boundaries. A
trailing partial line is ignored until it becomes complete.

Recommended first policy:

- target compressed size: 1-8 MiB
- hard uncompressed cap: 32 MiB
- max records per segment: 5,000
- max open segment age: 30-120 seconds

### Version

A version is an immutable manifest equivalent to a git commit. It describes a
complete logical session state, not only the delta.

```json
{
  "schema_version": 2,
  "version_id": "sha256(canonical body without version_id)",
  "parent_version_id": "previous version or null",
  "fleet_session_id": "...",
  "branch_id": "...",
  "source": "codex",
  "source_session_id": "...",
  "source_device_id": "...",
  "created_at": "2026-05-05T00:00:00Z",
  "logical_files": [
    {
      "path": ".codex/sessions/2026/05/05/rollout-....jsonl",
      "generation": 1,
      "file_kind": "jsonl",
      "segments": [
        {
          "seq_start": 0,
          "seq_end": 499,
          "record_count": 500,
          "start_offset": 0,
          "end_offset": 812345,
          "raw_sha256": "...",
          "object_hash": "...",
          "compression": "zstd"
        }
      ],
      "file_sha256": "known when complete or fully reassembled"
    }
  ]
}
```

The manifest should be canonical JSON so `version_id` is deterministic and
tamper-evident.

### Ref

A ref is a small mutable pointer to the latest version for a branch.

```json
{
  "schema_version": 1,
  "fleet_session_id": "...",
  "branch_id": "...",
  "latest_version_id": "...",
  "updated_at": "2026-05-05T00:00:00Z"
}
```

Default listing should read refs, not versions. Version history should be
explicit through commands such as `flt track versions <session>` or
`flt track ls --all-versions`.

### Branch

A branch is one append line of history. The initial branch id can be derived from
device, tool, and native source session id.

```text
{source_device_id}:{source}:{source_session_id}
```

If a session is restored and continued on another device, the continuation should
create a new branch. It can have `parent_version_id` pointing at the restored
version, but it should not advance the source device's branch.

This avoids merge/rebase complexity while preserving provenance.

## Local Checkpoints

The SDK should maintain a local checkpoint per logical source file.

```json
{
  "schema_version": 1,
  "source": "codex",
  "path": ".codex/sessions/...",
  "fleet_session_id": "...",
  "branch_id": "...",
  "generation": 1,
  "last_complete_offset": 12345678,
  "last_record_seq": 9182,
  "prefix_sha256": "...",
  "latest_version_id": "..."
}
```

The checkpoint is an optimization, not authority. Reconciliation must be able to
rebuild from local bytes and remote manifests.

If a file shrinks or the known prefix hash no longer matches, increment
`generation` and commit a new lineage for that file path.

## Commit Cadence

Do not commit every event.

Use a bounded policy for active sessions:

- commit when a segment reaches target size
- commit when at least N complete records are available
- commit after an idle window, initially 30-120 seconds
- commit on daemon shutdown when possible
- keep periodic full reconciliation as a backstop

A good first default is:

- `min_records_for_commit = 100`
- `target_compressed_segment_size = 1 MiB`
- `max_open_segment_age = 60 seconds`
- `reconcile_interval = 10 minutes`

The exact numbers can move after local benchmarks. The important property is
that active sessions get near-real-time durability without creating one commit
per JSONL row.

## Orchestrator API

The orchestrator remains the control plane. Large bytes go directly to S3 via
presigned URLs.

Required v2 endpoints:

```text
POST /v2/track/plan
POST /v2/track/commit
GET  /v2/track/sessions
GET  /v2/track/sessions/{session_id}/versions
GET  /v2/track/sessions/{session_id}/versions/{version_id}
POST /v2/track/restore-plan
```

`/plan` accepts candidate object hashes, sizes, and content types. It returns
presigned upload URLs only for missing objects.

`/commit` accepts a version manifest, branch id, and expected parent version. The
server validates that every referenced object exists, writes the immutable
version, and advances the ref only if the expected parent still matches.

Parent mismatches should be rare because branches are per device/continuation. If
they happen, the server should reject the commit. The client can fetch the branch
head and create a new continuation branch rather than attempting a merge.

`/restore-plan` returns a selected version manifest plus presigned download URLs
for required objects.

## SDK Queue Model

Keep the SQLite queue pattern, but change work items.

V1 rows are effectively:

```text
upload_file(path, sha256)
```

V2 rows should be:

```text
upload_object(object_hash, local_spool_path, size, compression)
commit_version(version_id, branch_id, expected_parent_version_id)
```

The commit item must not run until all referenced object upload items have
succeeded.

## Local Test Plan

Build v2 locally before orchestrator changes are required.

Use a filesystem-backed fake object store and fake commit store:

```text
.fleet/track/v2-local/
  objects/sha256/...
  sessions/.../versions/...
  sessions/.../refs/...
```

Required local tests:

- JSONL segmenter never splits records.
- Trailing partial JSONL lines are ignored until complete.
- Append-only update uploads only new segments.
- Reassembly produces byte-identical raw files.
- Object hashes verify before restore.
- Version ids are deterministic for canonical manifests.
- Default list returns only latest refs.
- `--all-versions` or equivalent returns history.
- File truncation/rewrite increments generation.
- Restore writes through temp-file-and-rename.
- Restored Claude/Codex files pass adapter validation in a temp `HOME`.

These tests should run without network and without touching real user session
directories.

## Relationship To V1

V1 can ship now as a bootstrap, but v2 should not be constrained by its storage
shape.

Reusable v1 pieces:

- CLI namespace
- auth
- daemon install/status/logs
- source discovery
- SQLite queue infrastructure
- presigned S3 upload pattern
- periodic reconciliation

Replace for v2:

- whole-file uploads
- flat `manifest.json`
- path-keyed S3 objects as the main version model
- hashes over local bytes that do not match uploaded scrubbed bytes

If v2 is implemented cleanly, existing v1 S3 data can be ignored or imported by a
one-off migration later. V2 should be the long-term restore/version protocol.
