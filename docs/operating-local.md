# Local development operations

All commands start in `<checkout>`. Runtime, credentials, caches,
mail previews, deletion ledger and test reports remain inside this root.

## Start and verify

Run `tools/setup.ps1` for dependency/runtime setup, then `tools/start-services.ps1`
and `tools/start.ps1`. The web app is `http://localhost:3000/login`; API docs are
`http://127.0.0.1:58000/api/docs`. The launcher now waits for both HTTP endpoints
to become ready and fails if startup is unsuccessful.

Setup first installs hash-pinned pip 26.2.1 from
`backend/bootstrap-requirements.lock.txt`, then the application lock. Setup and
verification run `tools/check_python_dependencies.py` against both files: pip
is not silently omitted by the usual freeze inventory. The check is local;
time-bound advisory audits and their limits are in dependency-security.md.

The application and audit locks now pin reviewed CPython 3.12 / Windows x64 wheels
and SHA-256 hashes. Setup reuses `tools/install-python-dependencies.ps1`; verified
application wheels install from the project cache with no index/source fallback.
Run `tools/audit-dependencies.ps1` for complete runtime/tooling advisory reports.
Commands, failure behavior, fresh-environment evidence and platform limits are in
[python-dependency-delivery.md](python-dependency-delivery.md).

`tools/verify.ps1` runs lint, deterministic OpenAPI/TypeScript drift checks,
Alembic metadata checks, real PostgreSQL/API tests, frontend checks/build and
browser acceptance. Test data uses the separate `researchos_test` database;
browser cases create their own invited development accounts. Browser account
deletion cases remove only those synthetic accounts.

The deletion authority has separate `researchos_ledger` / `researchos_ledger_test`
databases, credentials and `l0004` migration head. Normal startup/verification
checks its active inventory. Existing installations must run `tools/setup_ledger.py`
and review/import legacy records; a clean new installation can initialize an
explicit empty source. Do not initialize an empty replacement to bypass missing
records. Commands, historical limits and recovery continuity are in
[deletion-journal-runbook.md](deletion-journal-runbook.md).

The GitHub workflow is provided but has not been executed on a remote runner.
The local checks are not evidence that hosted CI or production deployment works.

The dispatcher also runs bounded independent Redis visibility recovery. It shares
the application's configured visibility timeout and must use an application-owned
broker DB/keyprefix. `runtime/venv/Scripts/python.exe tools/broker_status.py` reads
counts/ages only and redacts configuration/connection failures. Mechanism, exact
local crash evidence and production limits are in
[broker-recovery-runbook.md](broker-recovery-runbook.md).

The daily backup operator has its own optional process and read-only database
credential. It is disabled unless configured; ordinary service startup checks the
setting without initializing keys. Activation, catch-up, signed catalogs and
retention commands are documented in [backup-schedule-runbook.md](backup-schedule-runbook.md).

## Invitations and account recovery

Create a local invitation with `runtime/venv/Scripts/python.exe tools/invite.py
<email>`. Invitation tokens are credentials; do not place them in issue text or
logs. Registration schedules a verification email through the transactional
outbox. Password recovery has the same public reply for known and unknown email.
Verification/reset tokens are purpose-separated, expire and are single-use;
password reset revokes previous sessions.

Development sends `.eml` previews to `runtime/mail-preview/researchos/development/<space>/`.
`tools/mail_preview.py --workspace <uuid>` lists message IDs and subjects without
printing the tokens. Add `--message <uuid> --open` to open a selected local link.
Preview files must remain private. Production refuses preview mode and requires
configured SMTP with TLS. Real SMTP/provider delivery has not been tested.

Outbound tokens are hashed for verification and separately encrypted for queued
delivery. Outbox payloads contain IDs only. The encrypted envelope is removed
after acceptance; delivery failures retain the envelope for bounded retries.
SMTP is at-least-once: a crash after provider acceptance can cause duplicate
messages with the same Message-ID, while the action token remains single-use.

## Controlled deletion

Deletion requires a ten-minute, identity/scope/impact-bound preview, explicit
confirmation, CSRF and password reauthentication. Redis-backed limits apply to
login, registration, verification/recovery and deletion reauthentication.
Unavailable rate-limit infrastructure rejects authentication attempts.

Files referenced by evidence or required by an active export cannot be removed.
For an unreferenced file version, cleanup erases bytes/pages/jobs/uploads and
retains an unavailable version marker. Account deletion freezes the workspace,
revokes sessions, waits for writers, cleans original files and business/history
records, and removes identity and local mail previews using a separate database
role. An opaque receipt allows progress checks after sessions are revoked.

Keep the receipt private. Cleanup failures do not report success and remain
retryable. Completed jobs contain no raw user/workspace/file identifiers.
The independent ledger contains keyed identifier hashes and a signature, not
emails or research text. Back up this ledger and its control secret separately
from database snapshots. Never expose a restored service before replaying it:

`runtime/venv/Scripts/python.exe tools/replay_deletions.py --source-database
researchos --maintenance-ack`

Configure the dedicated cleanup URL for the isolated restored database first.
The CLI refuses to proceed without the maintenance acknowledgement. Small-fixture
tests now perform actual encrypted PostgreSQL/object backup and isolated restore.
See [recovery-runbook.md](recovery-runbook.md) for operator preconditions, key
handling, failure isolation and the remaining production gates.
Unsigned ledgers from early development are retained as prototype evidence and
must be reviewed before a restore. The restore gate refuses unsigned ledgers.

No backup retention is configured by default. The app therefore reports online
deletion separately and does not claim backup erasure. A retention period may be
configured only with a matching operational policy and tested expiry process.

## Diagnosing local failures

Inspect `runtime/api.stderr.log`, `runtime/web.stderr.log`,
`runtime/worker.stderr.log` and `runtime/dispatcher.stdout.log`. Never copy
credentials or mail links into shared diagnostics. A parser/worker crash leaves
its lease recoverable; a stale attempt cannot publish another attempt's result.
For broker/storage outages, restore the project services and restart the worker
and dispatcher with `tools/restart-workers.ps1`. Recover frozen deletion jobs
before reopening the affected account; do not manually unfreeze data mid-cleanup.

The full production incident, recovery and deployment runbooks remain a release
gate in docs/07-quality-and-operations.md.

## Expired disposable artifacts

The dispatcher queues `researchos.expire_artifacts` at startup and nominally once
per minute. The registered worker uses the dedicated cleanup role and a singleton
database lock; duplicate ticks are harmless. It removes expired
successful exports (including abandoned attempts for that job), then marks their
jobs expired. It also removes staging bytes of expired pending uploads without a
queued/running parser, marks the upload expired and releases the failed file's
quota. Status/history rows and all retained original PDF versions remain.
The ordinary expiry phase skips unexpired artifacts and validating uploads;
reconciliation can later fail an abandoned, aged validation with no active parser.

Nonblocking workspace/backup preservation locks defer busy spaces until another
tick. Storage failures roll back status changes and never count work as completed;
another workspace can still be processed. Worker output contains only expiry
counts, without keys, credentials or research text. Real queue-worker execution
and controlled-clock scheduler behavior have separate tests.

The same task now reconciles aged orphan objects, completed/failed staging
remnants and domain-worker temporary files with durable fair scan checkpoints.
See [maintenance-runbook.md](maintenance-runbook.md) for grace periods, source
protection, pagination, failures and manual-review scopes. Backup retention and
live activation of daily encrypted backup scheduling remain outstanding. The
backup operator now supplies policy-controlled expiry for its signed catalog;
no live backup retention deletion is enabled by development tests.
