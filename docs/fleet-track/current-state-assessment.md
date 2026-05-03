# Current State Assessment

## Bottom Line

Use the current FleetTrack code as a bootstrap, not as the final architecture.

The prototype proves the right shape:

- local daemon
- source discovery
- auth
- queueing
- presigned upload
- S3-backed storage
- basic status CLI

The prototype does not yet prove the hard parts:

- efficient long-session sync
- semantic versioning
- restore safety
- canonical session model
- local resume validation
- cross-tool continuation

## SDK Pieces

| Area | Current State | Keep? | Notes |
| --- | --- | --- | --- |
| CLI | `flt track enable/status/daemon/logs` | Yes | Good namespace and first-run flow. Add `doctor`, `sessions`, `restore`, `validate`, and `continue` later. |
| Auth | Browser/JWT login plus team ID | Yes | Track requires user-scoped credentials; this is correct for per-user isolation. |
| Service install | launchd/systemd user daemon | Yes | Correct product shape. Needs better diagnostics. |
| Source discovery | Claude, Cursor, Codex local paths | Yes | Keep but move source definitions into adapter modules. |
| Watcher | watchdog with 2.5 second debounce | Yes | Useful for low-latency queueing. Not sufficient as the only correctness mechanism. |
| Reconcile | full scan every 10 minutes | Yes | Keep as safety net. Replace whole-file hash diff with segment/version reconciliation. |
| Hash cache | SQLite path/mtime/size cache | Partly | Keep local state pattern. Extend for record offsets, generations, and segment manifests. |
| Queue | SQLite upload queue | Yes | Keep. Change rows from file uploads to object uploads and version commits. |
| Upload | whole scrubbed file via presigned S3 PUT | Replace | This is the main scalability problem. |
| Manifest | flat `path -> sha256` map | Replace | Useful only for prototype diffing. Need version manifests with segments. |
| Scrubbing | local byte scrub before upload | Partly | Keep, but define whether hashes refer to raw, scrubbed, or both. |

## Server Pieces

| Area | Current State | Keep? | Notes |
| --- | --- | --- | --- |
| Router | public `/v1/track` router in Theseus | Yes | Keep v1 for compatibility, add v2 endpoints. |
| Provision | validates device and returns user/team | Yes | No DB write; acceptable. Could add device registry later. |
| Manifest fetch | reads one S3 `manifest.json` | Replace | V2 should fetch session/version manifests and refs. |
| Upload URLs | returns presigned PUT URLs for paths | Replace | V2 should plan missing content-addressed objects. |
| Storage | `fleet-track-sessions/{team}/{user}/{device}/raw/...` | Partly | Keep bucket and isolation. Add `v2/objects` and `v2/sessions`. |
| Metrics | `logfire.info` for provision/upload URLs | Partly | Add explicit endpoint, object, commit, and restore metrics. |

## Main Risks If We Ship V1 As-Is

1. Large active sessions repeatedly upload as full files.
2. S3 versioning can retain many large overwritten object versions.
3. No compression means unnecessary network and storage cost.
4. Hashes are over local bytes, while uploads are scrubbed bytes, so the manifest
   hash is not a checksum of stored object bytes.
5. No explicit commit protocol means the latest state is whatever manifest upload
   wins last.
6. No restore path exists.
7. No validation path exists before writing restored sessions into live tool
   directories.
8. No canonical format exists for unified search or cross-tool continuation.

## Migration Strategy

Do not rewrite everything first. Make incremental replacements behind the same
CLI surface:

1. Keep `flt track enable` and the daemon service.
2. Add local v2 segmenting and reassembly code with tests.
3. Add `validate-local` and temp-HOME restore tests.
4. Add v2 server planning and commit endpoints.
5. Switch upload queue from file-path jobs to object-hash and commit jobs.
6. Keep v1 raw whole-file upload behind a compatibility flag until v2 is stable.
7. Add canonical projection as a separate worker or CLI operation.

## Decision

Do not scrap the branch. Port it and use it as the product skeleton.

Do scrap the storage/sync protocol before relying on it for long sessions or
cross-machine restore.

