# Daily backup operator and retention

This component runs separately from Celery and the web/API. All source, catalog,
containers and working files remain under `<checkout>`. It is a
tested local implementation; production activation, key custody, monitoring and
recovery service levels are separate release gates.

## Provisioning and defaults

Migration `0009` grants SELECT to the cluster-provisioned `researchos_backup`
principal. `tools/init_database.py` creates its local credential without printing
it and sets default transactions read-only. The account is neither an owner nor
a superuser and cannot change domain rows, histories or schema. It can read the
entire private database to back it up, including credential hashes, so restrict
access to this credential and encrypted output.

`RESEARCHOS_BACKUP_DATABASE_URL` must match the application's host, port and
database and use `researchos_backup`. Restore uses the separate migration/cleanup
credentials, never this reader. The local `.env` still contains several service
credentials for development; production must inject separate secrets and use
appropriate operating-system accounts/ACLs. A separate process alone does not
establish that security boundary.

Default settings are:

| Setting | Default / requirement |
| --- | --- |
| `RESEARCHOS_BACKUP_SCHEDULE_ENABLED` | false |
| `RESEARCHOS_BACKUP_DAILY_HOUR_UTC` | 19, equivalent to 03:00 Asia/Hong_Kong |
| `RESEARCHOS_BACKUP_RETENTION_DAYS` | unset; range 1-3650 if configured |
| `RESEARCHOS_BACKUP_RETENTION_APPROVED` | false; must accompany a retention interval |
| `RESEARCHOS_BACKUP_CATALOG_DIRECTORY` | `runtime/backups/<database>/`; overrides must remain inside the project |
| `RESEARCHOS_BACKUP_KEY` | base64 encoded 32 random bytes; external secret injection required in production |

The proposed 30-day policy in the design is not approved by a successful test.
No formal development key or live retention policy was initialized by automated
tests. Their keys/catalogs are temporary test fixtures, not an established backup
service or separately escrowed recovery material.

## Key preparation and activation

Development operators can explicitly run `tools/backup.py init-key` to create
`runtime/backup-key.json`. It refuses an existing file and refuses production.
Production accepts the key through the environment rather than that local file.
Keep every retained backup's key available; the signed catalog records only its
SHA-256 fingerprint. A new key does not re-encrypt or remove older backups.
Escrow and independently retrieve both encryption keys and the control secret
used for catalog/deletion-ledger signatures before activation. That custody
workflow and control-secret rotation have not been certified.

After provisioning the reader, retrieving the key and reviewing the daily time,
set `RESEARCHOS_BACKUP_SCHEDULE_ENABLED=true` in the operator's private
configuration. Then run:

```powershell
./tools/start-backups.ps1
```

The normal service launcher also checks this setting. It launches a hidden
independent Python operator process only when enabled and its inputs validate.
It avoids duplicate local starts using the verified process identity and uses a
database advisory lock to serialize actual backup/retention operations. The
operator's logs/PID are `runtime/backup-scheduler.{stdout,stderr}.log` and
`runtime/backup-scheduler.pid`. `tools/stop.ps1` includes this operator before
stopping PostgreSQL; a forced interruption still requires reconciliation.

One-off commands, all from the project root:

```powershell
./runtime/venv/Scripts/python.exe ./tools/backup.py create
./runtime/venv/Scripts/python.exe ./tools/backup.py schedule-once
./runtime/venv/Scripts/python.exe ./tools/backup.py status --verify
```

`create` makes an additional backup. `schedule-once` performs only currently due
work. The process entry point `python -m app.recovery.scheduler --once` is useful
for an external service controller from `backend/`; it still respects enablement.
Do not put credentials or keys on command lines or into shared diagnostics.

## Durable daily behavior

The operator polls once per minute. It computes the latest due UTC daily slot,
catches up after downtime and uses a signed successful run for that slot to
avoid repeating work after restart. It does not enqueue one historical backup
for every missed date. A snapshot predating the requested slot cannot count as
success. Missing/size-changed successful files permit a replacement attempt.
This does not establish a measured RPO of 24 hours: outages, clock skew, polling,
backup duration and restoration capacity still require operational evaluation.

Failures retain a machine-readable failed record and retry with exponential
delay from one minute up to one hour. A live database lock takes precedence over
any stale-looking file record. Only after acquiring that lock can the next
operator mark unfinished runs interrupted, remove their own partial/working
files and retry. Database/object snapshot and source hash checks use the same
recovery implementation described in [recovery-runbook.md](recovery-runbook.md).

The catalog layout is:

- `records/<run-id>.json`: atomically replaced, signed status/slot/key fingerprint,
  source context, checksums and summary counts. It contains no research text.
- `files/<run-id>.rosbak`: completed encrypted container, promoted from `.part`
  only after encryption finishes. Its ciphertext SHA-256 and size are recorded.
- `work/<run-id>/`: temporary unencrypted dump/ZIP, scoped to that signed run.
  Ordinary completion/failure removes it. Link/reparse-point paths are refused.

Only generated UUID paths within the checked catalog are disposable. Unknown
files and legacy backups outside this namespace are not erased automatically.
The signatures bind the database, endpoint fingerprint, bucket and run ID; they
detect alteration and cross-context reuse. They do not prove inventory
completeness or protection against filesystem rollback/omitted files. Keep the
catalog and current independent deletion ledger outside database snapshots and
review their inventories separately.

`status` checks signed metadata and file presence/size. `status --verify` also
rehashes ciphertext and reports damaged IDs without credentials/private text.
Hash verification does not prove key availability or a successful SQL/object
restore; perform the actual isolated restore drill as well. Monitor any failed
run, file error, unregistered artifact or missing daily slot. Alert transport and
production on-call ownership have not been integrated.

## Review and apply retention

Preview the concrete interval without needing an encryption key:

```powershell
./runtime/venv/Scripts/python.exe ./tools/backup.py prune --days 30
```

After the policy owner approves the interval, configure both retention settings
above. The apply command requires an exact match with that approved configuration:

```powershell
./runtime/venv/Scripts/python.exe ./tools/backup.py prune --days 30 --apply
```

The same approved policy runs during normal operator ticks. Successful/unfinished
expiry records age from the snapshot time; failed run artifacts age from their
start time. Retention verifies registered ciphertext checksums before erasure,
writes durable `expiring` intent, removes the exact file and then records
`expired`. A retry after interruption between removal/record completion is safe.
It never uses a broad filesystem glob as deletion authorization.

The approved interval is a maximum retention window. It can remove the last old
backup; the output flags `backup_window_empty` instead of silently retaining data
beyond policy or claiming recovery protection. Restore backup creation immediately
if this occurs. A changed checksum, catalog error, missing source lock/key/service
or interrupted cleanup must be investigated. Expiry is not claimed completed
when a stage fails. Deletion receipts show a target expiry time that still needs
operational verification, not a certificate that all backup copies have vanished.
Legacy/provider/off-host copies and unregistered artifacts require their own
inventory and retention controls. Logical file deletion is not forensic media
erasure or proof of recovered physical disk space.

## Evidence and deployment limits

Tests perform real read-only PostgreSQL dumps, private-object copies, encrypted
backup restoration and original SHA-256/history/task checks. They exercise daily
boundaries, persisted restart state in separate actual Python processes, missed
slots, key fingerprints, failure backoff, a live lock versus unfinished work,
signed catalog tampering, expiry preview/apply and changed ciphertext rejection.
Controlled timestamps avoid waiting days; no production-scale RPO/RTO is claimed.

This operator currently assumes one host/catalog volume. Multi-host catalog
coherence, off-host disaster recovery, power-loss durability, actual forced
process-tree termination (including pg_dump children), key/control-secret
rotation, complete inventory, provider outages, capacity and production OS
permissions remain release gates. A failed ordinary run and a synthesized stale
record are not proof that every possible crash has been rehearsed.
