# FleetTrack Goals

## Product Goals

FleetTrack should make local AI coding sessions durable, searchable, restorable,
and eventually portable across agent tools.

The first useful product outcome is reliable backup and restore:

- A user can enable FleetTrack and forget about it.
- The daemon uploads session history without noticeably disrupting local work.
- A user can restore sessions onto a new machine.
- Restored same-tool sessions load cleanly.
- If a restore cannot be validated, FleetTrack refuses to install a broken
  session file.

The second product outcome is cross-tool continuity:

- A user can continue a Claude session in Codex, or a Codex session in Claude,
  with a useful context bundle.
- The converted session may be lossy.
- The converted session must not corrupt or break the target tool's session
  loader.

The third product outcome is a Fleet-native session corpus:

- Sessions can be indexed and searched across tools.
- Tool calls, shell commands, patches, assistant messages, user messages,
  reasoning summaries, attachments, and environment context can be queried using
  one Fleet schema.
- The canonical model preserves provenance back to raw records.

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

## Rollout Goals

Phase 0: Document and assess the prototype.

Phase 1: Implement local segmenter, manifest writer, and restore validator
without changing the server.

Phase 2: Add v2 server control-plane endpoints for missing-object planning and
version commits.

Phase 3: Add same-tool restore for Codex and Claude using temporary HOME-based
validation.

Phase 4: Add canonical session projection and read-only CLI inspection.

Phase 5: Add conservative cross-tool continuation export.

