# Artifact expiry and reconciliation

This background workflow is part of the existing once-per-minute
`researchos.expire_artifacts` task. It manages disposable artifacts in the
configured database/bucket; it does not delete retained research originals or
change decisions, evidence, notes or research history.

## Execution and retention boundaries

The cleanup database role holds a singleton advisory lock. It visits up to 20
active workspaces per default cycle, with batches of up to 100 records/objects per
type and 100 temporary filenames per directory. A configurable 20-second budget
is checked between workspaces and before the temporary scan; existing storage timeouts still
bound individual calls and may take longer. This is not a measured latency SLO.
`RESEARCHOS_MAINTENANCE_CYCLE_SECONDS` accepts 1-120 seconds. Capacity under a
large number of tenants/files requires separate measurement.

The database-backed workspace cursor advances even when a workspace is busy or
fails. Scans wrap after the last workspace. Per-workspace object cursors and the
two temporary-directory cursors persist across worker/process restarts. The
cleanup-only `maintenance_checkpoints` table is not an API resource. Application
credentials cannot read it. Workspace deletion cascades its scoped checkpoint
and any global cursor currently pointing at it. Recovery clears all checkpoints
before opening application access, and bucket changes reset scan state.

Before changing a workspace, maintenance tries both the global backup
preservation lock and the workspace exclusive lock. If a read/write worker,
request or backup holds a conflicting lock, it skips that workspace until a later
visit. It does not wait while holding application job leases. Checkpoints and
status writes commit after remote cleanup; request/worker writers participate in
the same workspace locks. No row locks are held across artifact transfers.

## What is removed

Expired successful exports are removed under their exact job prefix and marked
`expired`. Unsubmitted, expired pending uploads without queued/running parsers
lose their staging objects and become `expired`; their failed file marker releases
quota. A pending replacement upload continues reserving quota. Deletion requests
continue consuming their original quota until online bytes are actually erased.
Missing file markers are also omitted from available duplicate-upload suggestions.

Orphan reconciliation uses `RESEARCHOS_ORPHAN_GRACE_HOURS` (default 24 hours,
allowed 2-720). It only considers objects older than this grace cutoff and matching
server-generated key shapes under an active workspace's `final/`, `staging/` or
`exports/` prefix. It preserves:

- Every database-referenced original key, including historical PDF versions and
  recovered-file keys. Corrupt referenced originals remain diagnostic evidence.
- Keys belonging to queued/running parsers or exports, and upload staging needed
  by an active parser/lease or a still-recent validation.
- Current published export keys until the ordinary export-expiry phase removes
  them, fresh objects, unfamiliar names and foreign workspace/database namespaces.

Old completed/failed upload staging and abandoned attempt-specific final/export
copies can be removed after the grace interval. Expired validation sessions with
no remaining active parser are failed instead of indefinitely reserving quota.
These operations keep their status/history rows.

The object scan follows the documented general-purpose S3
[ListObjectsV2](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html)
and [ListObjectVersions](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectVersions.html)
pagination contracts. Versioned buckets are scanned by exact version IDs,
including delete markers. If removal erases the next-page version marker, the
checkpoint retains the preceding stable boundary and revisits the shortened
page. Explicit authorized prefix erasure repeatedly drains the first remaining
page, then verifies no versions/current objects remain. A successful delete reply
that leaves the same page unchanged fails cleanup instead of claiming success.
Directory buckets/S3 Express have different APIs and are not supported here.

Local temporary reconciliation touches only valid UUID job/attempt filenames in
`runtime/pdf-tmp/<database>/` and `runtime/export-tmp/<database>/`. It preserves
queued/running jobs and files younger than the same grace period. It removes aged
terminal/unknown-job remnants within those exact directories. It skips directory
entries, symbolic links/reparse points and paths resolving outside the expected
project namespace. It never follows a link to erase its destination. Local scan
memory is bounded to a page, but directory enumeration time still depends on
total entries and must be measured at production scale.

## Diagnosing and retrying

Only aggregate counts/error codes are emitted as `artifact_expiry` worker events.
No research text, storage keys, credentials or private links are logged. A storage
failure rolls back status and scoped checkpoint changes, reports a failed
workspace and advances the outer rotation so another workspace can run. Already
removed disposable objects are safe to encounter again. Busy/blocked temporary
files remain for a later scan. The task catches unexpected infrastructure errors
as `MAINTENANCE_UNAVAILABLE` without logging sensitive exception values.

Inspect `runtime/worker.stdout.log`, `runtime/worker.stderr.log` and dispatcher
status. Restore failed storage/queue/database services and let the normal task
retry. Do not manually mark work complete or run broad filesystem/bucket deletion
to clear a failure. Repeated failures, unknown objects, or an increasingly old
scan cursor require operator review rather than a shorter grace period.

An operator can inspect checkpoints through the dedicated cleanup/owner account
while keeping their object cursor contents private. Do not grant application
access to the checkpoint table for troubleshooting. The initial schema generator
is now frozen; all ongoing ORM changes require forward Alembic migrations.

## Evidence and remaining boundaries

Tests use real PostgreSQL, the configured private S3 service and Redis. Versioned
pagination is exercised both against local SeaweedFS and Moto. Explicit small-page
erasure covers unversioned, enabled and suspended versioning on the real local
provider; an earlier Moto suspended-version deletion raised an internal emulator
exception, retained in the initial report. Controlled server timestamps avoid
waiting 24 hours in tests; real storage executes every removal. Temporary-file
tests use actual aged files and verify another database's namespace is untouched.

The migration drill reconstructs 27 exported business tables with two original
PDF versions and immutable history into schema `0007`, then upgrades to `0008`
and compares all business rows. Backup recovery verifies that checkpoints are
cleared and application access remains revoked for this table.

Unknown workspace prefixes, unfamiliar names, legacy unnamespaced directories,
operator recovery temporary directories, mail-preview expiry, multipart-upload
remnants and backup sets are outside this automatic janitor. Review these through
their dedicated operational policy. Formal backup retention/key escrow/daily
scheduling, additional providers, large-tenant capacity and production recovery
remain release gates. Logical object removal is not a claim of forensic physical
media erasure or reclaimed disk capacity.
