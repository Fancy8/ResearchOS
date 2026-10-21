# Isolated backup recovery operator runbook

This is a tested local operator workflow, not production recovery certification.
All paths are relative to `<checkout>`. The operator owns the local
drill; assign a production recovery owner and independent reviewer before release.
No live database is overwritten by these tools.

## Create a formal backup

Use the dedicated read-only backup database credential and private S3 credential.
The bootstrap superuser is for cluster provisioning only. Backup data includes
credential hashes and private research data; restrict access to containers and
runtime. Supply `RESEARCHOS_BACKUP_KEY` as base64 encoded 32 random bytes from the
approved secret store in production. Development can initialize a local key:

```powershell
./runtime/venv/Scripts/python.exe ./tools/backup.py init-key
./runtime/venv/Scripts/python.exe ./tools/backup.py create
```

`init-key` refuses production and an existing key file. Creation writes a new
encrypted file under `runtime/backups/<database>/files/`; JSON reports run status,
snapshot time and relative output path, with counts/duration in the signed catalog.
See [backup-schedule-runbook.md](backup-schedule-runbook.md) for daily scheduling
and reviewed retention. Escrow the key separately
from the container and prove retrieval in an isolated drill. Retained backup keys
must remain available through rotation. Tests use ephemeral keys: their `.rosbak`
files are evidence, not formal recoverable backups. Formal key initialization,
escrow and a live daily backup policy have not been activated by development tests.

## Prepare a restore

1. Record incident/release ID, backup path and trusted checksum, source
   database/bucket, expected schema head and operator. Stop writes in the intended
   recovery environment; prevent applications/workers from connecting to it.
2. Provision a different **empty** database owned by the migration role and a
   different empty private bucket. Do not migrate the raw physical restore target:
   `pg_restore` recreates its schema. No other target sessions may exist.
3. Set `RESEARCHOS_RECOVERY_DATABASE_URL` and
   `RESEARCHOS_RECOVERY_CLEANUP_URL` privately. Cleanup must use
   `researchos_cleanup` at exactly the target host/port/database; both URLs use
   `postgresql+psycopg`. Never copy URLs or keys into diagnostics.
4. Connect `RESEARCHOS_LEDGER_READER_URL`/`RESEARCHOS_LEDGER_WRITER_URL` to the
   authoritative **current** independent PostgreSQL journal and retrieve its
   matching control/signing secret. Reader and writer must address the same
   authority with their dedicated roles. Never restore an old authority alongside
   the business dump. The journal verifies complete chains, current heads,
   reviewed activation and the backup's minimum checkpoint; absent/inactive or
   truncated inventories fail closed. Local legacy files are diagnostic mirrors.
   Check the signed recovery floor: the development inventory has five
   unreconstructible historical receipts, so snapshots before its reviewed
   2026-10-15 cutover are refused. See [deletion-journal-runbook.md](deletion-journal-runbook.md).
5. Retrieve the matching encryption key. Do not reuse old application sessions,
   upload URLs or exported download URLs in the recovered service.

## Execute and inspect

```powershell
./runtime/venv/Scripts/python.exe ./tools/backup.py restore ./runtime/backups/<backup>.rosbak --target-bucket <isolated-bucket> --maintenance-ack
```

The acknowledgement asserts the target is offline. The tool rejects live-name,
nonempty, mismatched-credential and connected targets. It authenticates the
container, dump and original hashes before SQL, revokes runtime target CONNECT,
restores SQL in one transaction, copies/rehashes originals and checks table counts
and schema head.

Before granting application CONNECT it replays signed deletion requests and
finishes queued/running/failed deletion jobs in the dump. Account cleanup also
completes pending file receipts. Receipts retain the opaque access hash while
removing identities, targets, errors and leases. Cleanup receives the explicit
target bucket without changing process-wide source configuration. Invalid frozen
spaces fail recovery.

The final stage revokes sessions/tokens, removes stale outbox/idempotency records,
fails interrupted processing/uploads, expires exports and randomizes remaining
password hashes. Users must recover passwords through the new mail channel.
Research history for accounts that were not deleted is retained.

The final sanitation and CONNECT grants commit in one transaction while the
journal replay gate is still held. A failure of the last grant cannot leave an
application-open target. The result supplies the original logical journal source
ID/database; after fencing the old writers, configure these on the replacement
deployment so physical database/bucket renaming does not reset deletion history.

Record actual JSON output, timings and failure classes. Through the restored API
validate current/historical PDF bytes, evidence pages, decision snapshots, task
source revisions, notes/formulas and associations. Verify removed identities and
files cannot be retrieved and old sessions cannot authenticate. Test recovery
mail before user handoff. Only after these checks and independent ledger review
may the operator repoint the service. This CLI does not perform deployment/DNS
cutover. Small-fixture results do not meet proposed production RPO/RTO gates.

## Failure and retry

After the target is closed, SQL restore, object hash/copy or ledger signature
failure leaves application CONNECT revoked. Copied destination objects are
removed where storage remains available. Keep the target offline, retain evidence
and inspect sanitized error classes and project-local logs. Do not bypass failed
stages by manually granting CONNECT. A storage outage may also prevent disposal
of copied objects; verify those separately before declaring cleanup complete.

A failed target is diagnostic evidence, not an empty retry target. Provision a
new isolated database/bucket and repeat after correcting the cause. Any disposal
must name and verify the exact isolated targets. Never delete source storage or
broad runtime directories as a retry shortcut.

Evidence: `artifacts/backend-all.xml`, `artifacts/recovery-lock-routing.xml` and
`artifacts/backup-recovery-proof.json`. Tests cover synthetic small data, real
PostgreSQL/S3/Redis, original/history API reads, pending deletions, destination
corruption, SQL failure, invalid signatures and backup/cleanup lock contention.
Provider outages, large backups, key escrow, independent-authority owner rollback/
fresh witness, retention and production cutover remain release gates. The local
journal shares a cluster with the development business database; this does not
prove a production failure domain or off-host disaster recovery.
