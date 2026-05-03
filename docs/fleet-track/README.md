# FleetTrack Planning

FleetTrack currently exists as a passive local-session sync daemon in the SDK plus
thin server support in Theseus. This directory captures the plan for turning that
prototype into a durable session archive and migration system.

## Current Decision

Do not scrap everything. Keep the current implementation as a useful bootstrap,
but do not ship the current sync protocol as the long-term design.

Keep:

- Browser/JWT login flow and team/user-scoped auth.
- `flt track enable/status/daemon` product surface.
- OS service installation through launchd/systemd.
- Source discovery for Claude, Codex, and Cursor local session stores.
- Local SQLite queue and background daemon shape.
- Orchestrator-as-control-plane model with presigned S3 uploads.
- S3 tenant isolation by `team_id/user_id/device_id`.
- Client and server-side path blocklists.

Replace before scale:

- Whole-file uploads for every changed transcript.
- Flat "Merkle" manifest that only maps `path -> sha256`.
- Raw-only storage with no semantic session/version model.
- Lack of compression.
- Lack of explicit commit protocol and conflict detection.
- Reliance on S3 versioning as the only version history.
- No local restore/resume validation before writing into live tool stores.

## Existing Behavior

The SDK watches:

- `~/.claude/projects/**/*.jsonl`
- `~/.cursor/projects/**/agent-transcripts/**/*.jsonl`
- `~/.cursor/projects/**/agent-transcripts/**/*.txt`
- `~/.codex/sessions/**/*.jsonl`
- `~/.codex/archived_sessions/**/*.jsonl`

The daemon reacts to file events after a 2.5 second debounce, drains the upload
queue every 10 seconds, and runs a full reconciliation every 10 minutes. Changed
files are uploaded as complete scrubbed file bodies through presigned S3 `PUT`
URLs. There is no chunking or compression.

Theseus currently exposes:

- `POST /v1/track/provision`
- `GET /v1/track/manifest`
- `POST /v1/track/upload-urls`

Objects are stored under:

```text
fleet-track-sessions/
  {team_id}/{user_id}/{device_id}/
    manifest.json
    raw/.claude/projects/...
    raw/.cursor/projects/...
    raw/.codex/sessions/...
```

## Target Direction

FleetTrack v2 should store immutable, compressed, content-addressed session
segments plus explicit version manifests. The raw source archive remains the
source of truth. A Fleet-owned canonical session model is a versioned projection
over the raw archive, not a replacement for it.

The core invariant is:

```text
raw restore must be byte-identical and load-safe; cross-tool conversion may be
lossy, but must never write invalid native session files.
```

See:

- [Current State Assessment](./current-state-assessment.md)
- [Goals](./goals.md)
- [V2 Architecture](./v2-architecture.md)
- [Unified Session Format](./unified-session-format.md)
- [Local Resume Test Plan](./local-resume-test-plan.md)
