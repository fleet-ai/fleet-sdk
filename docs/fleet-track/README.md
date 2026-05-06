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

### Search

`flt track ls` lists deterministic session metadata from the orchestrator's
Postgres store. `flt track search` is Turbopuffer-only and emits JSON by default
for agent workflows.

Search accepts one JSON object and posts it to the orchestrator-managed hybrid
index. Pass inline JSON, `@file`, or `-` for stdin:

```bash
flt track search '{"query":"bugbot local index","top_k":20}'
flt track search @search.json
flt track search -
flt track search --filters
```

The JSON body supports:

```text
query    string   Orchestrator-managed hybrid search: BM25 over search_text
                  plus ANN over vector.
top_k    integer  Maximum ranked results to return. Defaults to 50.
filters  array    Turbopuffer filter expression, forwarded as-is.
rank_by  array    Turbopuffer ranking expression, forwarded as-is.
```

The command posts the body to `POST /v1/track/sessions/search`. Orchestrator
injects the team boundary and hydrates the ranked results back to Fleet session
metadata.

Turbopuffer's query and filter docs are available at
<https://turbopuffer.com/docs/query#filtering>.

Filterable attributes are:

```text
session_id, user_id, device_id, tool, cwd, repo_url, git_branch, model,
forked_from, event_count, started_at, last_active
```

`team_id` is always injected by orchestrator. Filters use Turbopuffer filter
arrays. Common operators include `And`, `Or`, `Not`, `Eq`, `NotEq`, `In`,
`NotIn`, `Lt`, `Lte`, `Gt`, `Gte`, `Contains`, and `ContainsAny`.

Example body:

```json
{
  "query": "deployment debugging",
  "filters": [
    "And",
    [
      ["repo_url", "Eq", "git@github.com:fleet-ai/theseus.git"],
      ["tool", "Eq", "codex"],
      ["last_active", "Gte", "2026-05-01T00:00:00Z"]
    ]
  ],
  "top_k": 25
}
```

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
