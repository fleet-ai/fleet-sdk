# FleetTrack

FleetTrack is the SDK feature for syncing local AI coding sessions to Fleet and
resuming them locally or across tools.

## Current Behavior

The SDK scans:

- `~/.claude/projects/**/*.jsonl`
- `~/.cursor/projects/**/agent-transcripts/**/*.jsonl`
- `~/.cursor/projects/**/agent-transcripts/**/*.txt`
- `~/.codex/sessions/**/*.jsonl`
- `~/.codex/archived_sessions/**/*.jsonl`

The v1 syncer uses full reconciliation as the sync trigger. On startup, and then
every 10 minutes, it scans local session files, diffs them against the remote
manifest, queues changed files, uploads complete scrubbed file bodies through
presigned S3 `PUT` URLs, and writes a new manifest after successful uploads. The
file watcher code remains available, but v1 does not use watcher-driven uploads
by default.

The SDK also upserts session metadata after successful uploads so `flt track ls`
and `flt track resume` can use the remote session index.

The public Fleet API currently exposes:

- `POST /v1/track/provision`
- `GET /v1/track/manifest`
- `POST /v1/track/upload-urls`
- `POST /v1/track/sessions/{id}`
- `GET /v1/track/sessions`
- `GET /v1/track/sessions/{id}`
- `GET /v1/track/sessions/{id}/content`

Objects are stored under:

```text
fleet-track-sessions/
  {team_id}/{user_id}/{device_id}/
    manifest.json
    raw/.claude/projects/...
    raw/.cursor/projects/...
    raw/.codex/sessions/...
```

Authentication uses `FLEET_API_KEY`. Track requires an API key that resolves to
a concrete Fleet profile so orchestrator can isolate uploaded sessions by
`team_id`, `user_id`, and `device_id`. The orchestrator remains the control
plane; session bytes go directly to S3 through presigned URLs.

## Commands

```text
flt track enable
flt track disable
flt track status
flt track daemon --once
flt track logs
flt track ls
flt track search
flt track resume
flt track gc
```

### Agent Search

`flt track search <query>` emits JSON by default for agent workflows. For
structured search, agents can pass a Turbopuffer-shaped JSON body through
orchestrator:

```bash
flt track search --tpuf '{"query":"bugbot local index","top_k":20}'
flt track search --tpuf @search.json
flt track search --tpuf -
```

The raw body supports `query`, `rank_by`, `filters`, and `top_k`, matching
`POST /v1/track/sessions/search`. Orchestrator injects the team boundary and
hydrates the ranked results back to Fleet session metadata.

## Design Notes

- Raw native session files remain the restore source of truth.
- The unified event model is a projection for listing, search, compaction, and
  cross-tool continuation.
- Same-tool resume should prefer native tool resume when the source session is
  available locally.
- Cross-tool resume may be lossy, but must create valid target-tool session
  state or fail closed.
- Bulk session bytes should keep going directly to object storage; orchestrator
  should not proxy large payloads.

See [Goals](./goals.md) for the organized remaining work.
