# FleetTrack

FleetTrack is the SDK feature for syncing local AI coding sessions to Fleet and
resuming them locally or across tools.

## Current Behavior

The SDK scans:

- `~/.claude/projects/**/*.jsonl`
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
- `POST /v1/track/sessions/search`
- `POST /v1/track/sessions/aggregate`
- `GET /v1/track/sessions/{id}`
- `GET /v1/track/sessions/{id}/content`

Objects are stored under:

```text
fleet-track-sessions/
  {team_id}/{user_id}/{device_id}/
    manifest.json
    raw/.claude/projects/...
    raw/.codex/sessions/...
```

Cursor transcript syncing is intentionally disabled for now. `CursorSource`
still exists for future parser work, but Cursor files are not included in the
default daemon scan until the SDK can extract stable metadata and replay events.

Authentication prefers `FLEET_API_KEY` when set and otherwise uses stored
`flt login` browser credentials. Track requires credentials that resolve to a
concrete Fleet user/profile so orchestrator can isolate uploaded sessions by
`team_id`, `user_id`, and `device_id`. The orchestrator remains the control
plane; session bytes go directly to S3 through presigned URLs.

For local use:

```bash
flt login
flt track enable
```

For non-interactive use:

```bash
export FLEET_API_KEY="sk_your_key_here"
flt track enable
```

## Commands

```text
flt track enable
flt track disable
flt track status
flt track daemon --once
flt track logs
flt track ls
flt track search
flt track aggregate
flt track download
flt track resume
flt track gc
```

### Search

`flt track ls` lists deterministic session metadata from the orchestrator's
Postgres store. `flt track search` uses the orchestrator-managed Turbopuffer
session index for ranked session discovery and emits JSON by default for agent
workflows.

Search accepts one structured JSON object. Pass inline JSON, `@file`, or `-` for
stdin:

```bash
flt track search '{"query":"bugbot local index","limit":20}'
flt track search '{"mode":"keyword","query":"schema error","filters":{"tool":"codex"}}'
flt track search @search.json
flt track search -
flt track search --filters
```

The JSON body supports:

```text
query    string   Natural-language search text.
mode     string   hybrid (default), keyword, semantic, or recent.
limit    integer  Maximum ranked results to return. Defaults to 50.
filters  object   Mongo-style exact/range/boolean filters.
time     object   Shared time filter, e.g. {"field":"last_active","since":"7d"}.
```

The command posts the body to `POST /v1/track/sessions/search`. Orchestrator
injects the team boundary, compiles structured filters to Turbopuffer, and
hydrates ranked results back to Fleet session metadata.

Filterable attributes are:

```text
session_id, user_id, device_id, tool, cwd, repo_url, git_branch, model,
forked_from, event_count, started_at, last_active
```

`team_id` is always injected by orchestrator. Filters support direct equality,
Mongo-style field operators, and boolean operators:

```json
{"tool": "codex"}
{"event_count": {"$gte": 1000}}
{"$or": [{"repo_url": {"$contains": "theseus"}}, {"repo_url": {"$contains": "fleet-sdk"}}]}
```

Supported field operators are `eq/$eq`, `ne/$ne`, `in/$in`, `nin/$nin`,
`gt/$gt`, `gte/$gte`, `lt/$lt`, `lte/$lte`, `contains/$contains`,
`glob/$glob`, and `regex/$regex`. Supported boolean operators are `$and`,
`$or`, `$not`, and `$nor`.

Example body:

```json
{
  "query": "deployment debugging",
  "filters": {
    "repo_url": {"$contains": "theseus"},
    "tool": {"$in": ["codex", "claude"]},
    "event_count": {"$gte": 1000}
  },
  "time": {"field": "last_active", "gte": "2026-05-01T00:00:00Z"},
  "limit": 25
}
```

### Aggregate

`flt track aggregate` runs structured Postgres-backed aggregate queries. It does not
accept raw SQL.

```bash
flt track aggregate '{"group_by":["repo_url","tool"],"metrics":["count","sum_event_count"]}'
flt track aggregate '{"time":{"field":"last_active","since":"30d"},"group_by":["tool"]}'
flt track aggregate '{"group_by":["repo_url"],"time_bucket":{"field":"last_active","interval":"day"},"having":{"count":{"$gte":5}},"order_by":[{"field":"count","direction":"desc"}]}'
```

Supported metrics:

```text
count, sum_event_count, min_event_count, max_event_count, avg_event_count,
distinct_user_count, distinct_device_count, distinct_repo_count,
distinct_model_count
```

Aggregate bodies also support:

- `time_bucket`: `{"field":"last_active","interval":"hour|day|week|month"}`.
- `order_by`: list of `{"field":"count","direction":"desc"}` entries. Fields
  may be metrics or grouped key fields.
- `having`: metric filters after grouping, for example `{"count":{"$gte":5}}`.

### Download For Intra-Session Analysis

`flt track download <session_id>` downloads the session into the local cache and
prints the canonical JSONL path. This is the intended primitive for
intra-session agentic search. After downloading, use local tools:

```bash
flt track download 019dfbd6-0600-70b1-8a0b-c6f4cdbf1c57
rg "started_at schema" ~/.fleet/track/cache/sessions/019dfbd6-0600-70b1-8a0b-c6f4cdbf1c57/session.jsonl
jq 'select(.type=="message")' ~/.fleet/track/cache/sessions/019dfbd6-0600-70b1-8a0b-c6f4cdbf1c57/session.jsonl
```

Download behavior:

- Orchestrator authorizes and returns a presigned S3 URL plus content metadata.
- The SDK downloads directly from S3 and caches under
  `~/.fleet/track/cache/sessions/<session_id>/`.
- If the S3 object is stored as gzip, the SDK writes decompressed canonical JSONL
  locally.
- Repeated downloads are cache hits unless metadata such as `last_active`,
  `event_count`, `content_codec`, or byte sizes changes.

### FleetCode MCP Connector

The SDK ships FleetCode, a small stdio MCP server for connector hosts that have
the Fleet SDK installed. It exposes the same three agent-facing operations as
the CLI:

- `fleetcode_search_sessions` for structured session search.
- `fleetcode_aggregate_sessions` for grouped metadata metrics.
- `fleetcode_download_session` for local cached JSONL downloads.

It also exposes `fleetcode_query_help`, which returns filterable fields, operators,
metrics, and examples so agents can construct valid queries.

The MCP server requires Python 3.10+. If the connector machine already installs
the SDK as `fleet-python[cli]`, the MCP dependency is included. Otherwise,
install the smaller FleetCode extra in the environment that runs the connector:

```bash
pip install 'fleet-python[fleetcode]'
```

Then configure the connector to run:

```json
{
  "command": "fleetcode-mcp",
  "env": {
    "FLEET_TRACK_BASE_URL": "https://us-west-1.fleetai.com"
  }
}
```

Authentication is the same as `flt track`: `FLEET_API_KEY` is preferred when
set, otherwise the MCP process uses stored `flt login` credentials from the
same OS user. For a connector running under a different user or on a different
machine, either run `flt login` in that connector environment or pass
`FLEET_API_KEY` in `env`.

`FLEET_TRACK_BASE_URL` is optional; the normal Fleet default is used when it is
omitted. The MCP process keeps orchestrator as the auth boundary and downloads
session bytes directly to the same local cache as `flt track download`.

### Compression

Uploads are raw by default for safe rollout. To store new uploaded session blobs
compressed in S3, set one of:

```bash
export FLEET_TRACK_UPLOAD_CODEC=gzip
# or
export FLEET_TRACK_COMPRESS_UPLOADS=1
```

Compression happens after local scrubbing. Metadata upserts include
`content_codec`, `raw_bytes`, and `stored_bytes`, and downloads decode based on
that metadata. Existing raw S3 objects remain readable because missing codec
metadata defaults to `raw`.

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
