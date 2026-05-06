# FleetTrack Goals

## Current Status

FleetTrack now has a usable v1 product path:

- Authentication through `FLEET_API_KEY` or stored `flt login` credentials.
- `flt track enable/status/daemon/logs/ls/resume/gc`.
- Local source discovery and raw-byte sync for Claude, Claude Desktop
  local-agent, Codex, and Cursor. Cursor replay remains disabled until metadata
  extraction and event replay are implemented.
- Periodic full reconciliation into a SQLite upload queue.
- Scrubbed whole-file uploads to S3 through orchestrator-issued presigned URLs.
- Remote session metadata indexing for listing/search/resume.
- A shared unified event model used by local and remote session stores.
- Conservative cross-tool resume via generated target-tool checkout files.

## Product Goals

FleetTrack should make local AI coding sessions durable, searchable, restorable,
and portable across agent tools.

The first product goal is reliable backup:

- A user can enable FleetTrack and forget about it.
- The daemon uploads session history without noticeably disrupting local work.
- Session metadata is searchable from another machine.
- Uploaded bytes are associated with the right user, team, device, tool, repo,
  and source path.

The second product goal is reliable resume:

- A user can resume an uploaded session from another machine.
- Restored same-tool sessions load cleanly.
- If local repo state is required, FleetTrack resolves the matching local repo
  or fails with a clear recovery path.
- FleetTrack never writes an invalid native session file into a live tool
  directory.

The third product goal is cross-tool continuity:

- A user can continue a Claude session in Codex, or a Codex session in Claude,
  with a useful context bundle.
- The converted session may be lossy.
- The converted session must not corrupt or break the target tool's session
  loader.

The fourth product goal is a Fleet-native session corpus:

- Sessions can be indexed and searched across tools.
- Tool calls, shell commands, patches, assistant messages, user messages,
  reasoning summaries, attachments, and environment context can be queried using
  one Fleet schema.
- The canonical model preserves provenance back to raw records.

## Remaining Work

### V1 Hardening

- Add a `flt track doctor` command for auth, daemon, queue, source, and remote
  endpoint diagnostics.
- Add an explicit E2E smoke test path for dev/staging after the Theseus migration
  is applied.
- Improve resume failure messages for missing repos, missing tools, and
  unsupported source/target pairs.
- Keep metadata indexing best-effort: file upload success must not be rolled
  back just because metadata upsert failed.
- Keep API-key behavior explicit for Track. The key must resolve to a concrete
  user/profile identity.

### Restore Safety

- Validate same-tool restored session files in a temporary `HOME` before writing
  into live tool directories.
- Write restored files atomically through temp-file-and-rename.
- Never mutate an active session file in place.
- Refuse to install reconstructed files when hashes or adapter validation fail.
- Add synthetic fixtures for Claude, Codex, Cursor, truncation, partial JSONL,
  tool calls, patches, and shell output.

### Sync Efficiency

- Replace repeated whole-file uploads for large hot JSONL files with safe
  record-boundary segment uploads.
- Compress uploaded session payloads.
- Add explicit version/commit manifests rather than relying on a flat
  `path -> sha256` manifest as product history.
- Treat local checkpoints as an optimization only; reconciliation must be able to
  rebuild from local bytes and remote manifests.

### Search And Corpus

- Continue using the unified event model as a projection, not the archival source
  of truth.
- Preserve unknown native fields so adapters can improve later.
- Index title, cwd, repo identity, branch lineage, tool calls, file changes,
  shell commands, and assistant/user messages.
- Keep provenance from every indexed event back to the raw native source.

## Non-Goals

FleetTrack does not need perfect cross-tool replay in the first version.

It should not try to synthesize private tool internals that are not understood.
If a target tool needs hidden fields or opaque state to resume exactly, the
adapter should fall back to creating a fresh valid continuation with a summary
and transcript.

FleetTrack should not write unvalidated synthetic records into live session
directories.

FleetTrack should not make orchestrator proxy large session payloads. The
orchestrator should remain the control plane; bulk bytes should go directly to
object storage.

## Safety Invariants

- Never split a JSON record inside a storage segment.
- Never restore a partial session file.
- Never install a reconstructed file unless all segment hashes verify.
- Never install a native-format conversion unless the target adapter validator
  accepts it.
- Never mutate an active session file in place.
- Always write restored files atomically through temp-file-and-rename.
- Preserve unknown raw fields so adapters can improve later.
- Treat raw native records as the archival source of truth.
