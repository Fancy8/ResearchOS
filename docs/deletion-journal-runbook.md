# Independent deletion journal

The business database dump is not the deletion authority. Current requests live
in a separate PostgreSQL database, with its own Alembic chain (`l0001`–`l0004`),
owner, append-only writer and read-only recovery reader. In local development
these databases share the project-local PostgreSQL cluster. That does **not**
certify independent disaster recovery: production settings require a different
PostgreSQL endpoint; operators must prove a separate failure/backup domain.

## Invariants and trust boundary

- `ledger_entries` contains individually signed anonymized requests in a
  source-specific, contiguous hash chain. A protected `ledger_heads` row records
  the current sequence/hash and signature. An AFTER INSERT trigger serializes
  appends and advances the head in the same transaction; `ON CONFLICT DO NOTHING`
  cannot advance a head without an entry.
- Writer/reader credentials cannot UPDATE, DELETE, TRUNCATE, disable triggers,
  create objects or activate an inventory. A separate migration owner signs and
  records the reviewed initial inventory. An absent source/activation is a failed
  gate, never evidence of an empty journal. The business migration owner and
  runtime principals cannot connect to this authority database.
- Live requests persist their business intent/outbox first. A 202 acknowledgement
  requires the independent journal append too, before physical cleanup. A failed
  preflight returns 503 without accepting the request. An outage after the
  business commit returns `DELETION_JOURNAL_PENDING` with the opaque receipt;
  the browser retains it and opens progress. Worker retry must write/confirm the
  journal before removing data. No cross-database atomic commit is claimed.
- New backups record a signed minimum journal checkpoint. Recovery verifies the
  entire current sequence against its head, activation and backup checkpoint;
  whole missing entries, missing tails, changed bodies/signatures and a head
  behind the backup fail closed. Records stream through server-side cursors.
- Restoration registers authenticated legacy pending jobs before taking its
  final journal read lock. It then holds that lock through replay, target cleanup
  and application CONNECT grant. New journal appends wait for this boundary.
  Actual cutover still requires fencing old application writers; this tool does
  not support two simultaneously writable production deployments.
- `runtime/deletion-ledger/<origin>/` files are legacy/diagnostic mirrors, not the
  authority. Losing a mirror cannot silently remove an authoritative request.
  A mirror write outage logs a sanitized event; once the authority append has
  succeeded, that diagnostic outage does not block acknowledgement or cleanup.

The independent PostgreSQL service and its privileged administrators remain a
trust boundary. A malicious authority owner with signing-key access, or rollback
of the entire authority to an internally consistent state newer than a backup's
minimum checkpoint, needs an independently escrowed current witness/administrative
audit. Local chain tests do not certify that production control. Availability,
key rotation, off-host recovery, monitoring and the authority's own retention/
backup policy remain release gates. Never restore its old database alongside a
business backup and call that the current deletion authority.

Implementation follows PostgreSQL's documented
[advisory-lock semantics](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS)
and [SECURITY DEFINER search-path guidance](https://www.postgresql.org/docs/16/sql-createfunction.html).

## Local provisioning and initial inventory

All commands run from the project root and keep files there. Do not print `.env`
or credential JSON. `tools/setup_ledger.py` is development provisioning only;
production uses separately managed roles, migrations and secret injection.

```powershell
./runtime/venv/Scripts/python.exe tools/setup_ledger.py
./runtime/venv/Scripts/python.exe tools/ledger.py inventory
```

Stop old application writers/workers before final review/import. Inventory first
validates all legacy signatures and pending business jobs, and writes
`artifacts/ledger-inventory-<database>-<digest>.json` without overwriting earlier
inventories. Review counts, each receipt without
an individual record, and the report digest. On a genuinely new deployment:

```powershell
./runtime/venv/Scripts/python.exe tools/ledger.py init-empty --maintenance-ack
```

For legacy data, pass the **reviewed current** digest, not a copied example:

```powershell
./runtime/venv/Scripts/python.exe tools/ledger.py migrate-legacy --inventory-sha256 <reviewed-digest> --maintenance-ack
```

If completed anonymized receipts have no reconstructible tombstone, migration
requires the explicit `--deny-pre-migration-backups` flag. The signed activation
then sets an earliest permissible snapshot time; older business backups remain
retained but recovery is rejected. This prevents inventing identities or quietly
claiming legacy completeness. Do not remove the floor to make an old backup pass.

On 2026-10-15 the local development inventory contained 12 completed account
receipts but seven legacy request files. Five anonymous receipts could not be
reconstructed. The seven verified records were imported with a recovery floor
of **2026-10-15 04:32:42.840342 UTC** (12:32:42.840342 Hong Kong). This is an explicit
historical limitation, not a claim that all 12 legacy requests were reconstructed.
Only development/test records were migrated; production operation was not enabled.

```powershell
./runtime/venv/Scripts/python.exe tools/ledger.py status
./runtime/venv/Scripts/python.exe -m alembic -c backend/ledger-alembic.ini current --check-heads
```

Status reports the head, reviewed count and recovery floor. Normal startup and
verification refuse a missing, stale-schema, invalid or inactive inventory.

## Recovery and continued operation

The independent reader/writer URLs must address the same authority with their
distinct roles. Recovery must retrieve the correct control/signing secret and
connect to the authoritative current journal, not a snapshot copy. If it cannot,
leave the recovery target offline.

After restore, the result includes `ledger_configuration.source_id` and
`ledger_configuration.origin_database`. For an actual replacement deployment,
fence the old writers and configure both `RESEARCHOS_LEDGER_SOURCE_ID` and
`RESEARCHOS_LEDGER_ORIGIN_DATABASE` with these original logical values. Preserve
the signing secret and authority endpoint. This preserves the journal across
physical database/bucket renaming. Do not initialize a new empty authority just
because the restored physical database has a new name.

Isolated drills must not expose writable user traffic or feed test deletions
into a production authority. Use an isolated authority copy for write testing;
that copy is not an authoritative witness for production cutover.

Targeted reports are under `artifacts/deletion-journal-targeted.xml`,
`artifacts/journal-floor-targeted.xml` and `artifacts/journal-recovery-targeted.xml`.
Some early reports include failures corrected later; use the final aggregate
reports and implementation status for current verification results.
