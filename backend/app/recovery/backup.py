"""Consistent PostgreSQL/original-object backup and isolated, gated restoration."""

import hashlib
import json
import os
import secrets
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, make_url

from app.core.config import ROOT
from app.core.processes import (
    ProcessGuardError,
    ProcessOutputLimit,
    ProcessTimeout,
    process_environment,
    run_contained,
)
from app.core.security import hasher
from app.recovery.crypto import decrypt_file, encrypt_file
from app.recovery.journal import current_checkpoint, frozen_journal, origin_database, source_identity


def local_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT) or path == ROOT:
        raise ValueError("BACKUP_PATH_MUST_BE_PROJECT_LOCAL")
    return path


def pg_environment(url):
    value = make_url(url)
    return {
        **process_environment(ROOT / "runtime/tmp"),
        "PGHOST": value.host or "127.0.0.1",
        "PGPORT": str(value.port or 5432),
        "PGDATABASE": value.database,
        "PGUSER": value.username,
        "PGPASSWORD": value.password or "",
        "TEMP": str(ROOT / "runtime/tmp"),
        "TMP": str(ROOT / "runtime/tmp"),
    }


def pg_tool(name, arguments, url, timeout=600, on_started=None):
    if name not in {"pg_dump", "pg_restore"}:
        raise ValueError("POSTGRESQL_TOOL_NOT_ALLOWED")
    if name == "pg_restore":
        arguments = [f"--dbname={make_url(url).database}", *arguments]
    executable = ROOT / f"runtime/postgresql/pgsql/bin/{name}{'.exe' if os.name == 'nt' else ''}"
    if not executable.exists():
        raise RuntimeError("PROJECT_POSTGRESQL_TOOL_NOT_AVAILABLE")
    try:
        result = run_contained(
            [str(executable), *arguments],
            env={**pg_environment(url), "PGAPPNAME": f"researchos-{name}-{os.getpid()}"},
            cwd=ROOT,
            timeout=timeout,
            output_limit=256 * 1024,
            memory_limit=512 * 1024 * 1024,
            on_started=on_started,
        )
    except ProcessTimeout:
        raise RuntimeError(f"{name.upper()}_TIMEOUT") from None
    except ProcessOutputLimit:
        raise RuntimeError(f"{name.upper()}_OUTPUT_LIMIT") from None
    except ProcessGuardError:
        raise RuntimeError(f"{name.upper()}_CONTAINMENT_FAILED") from None
    if result.returncode:
        # SQL tool output may contain research text; retain only the error class.
        raise RuntimeError(f"{name.upper()}_FAILED")


def db_connect(url, **kwargs):
    return psycopg.connect(
        make_url(url).render_as_string(hide_password=False).replace("postgresql+psycopg", "postgresql"),
        **kwargs,
    )


def make_backup(source_url, storage, source_bucket, destination, key, timeout=600, temporary_parent=None):
    destination = local_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("BACKUP_OUTPUT_ALREADY_EXISTS")
    folder = local_path(temporary_parent) if temporary_parent else ROOT / "runtime/recovery-tmp"
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    manifest = {
        "format_version": 1,
        "source_database": make_url(source_url).database,
        "source_bucket": source_bucket,
        "objects": [],
        "entity_counts": {},
        "ledger_checkpoint": current_checkpoint(origin_database(make_url(source_url).database)),
        "ledger_origin_database": origin_database(make_url(source_url).database),
    }
    with tempfile.TemporaryDirectory(prefix="backup-", dir=folder) as temporary:
        temporary = local_path(temporary)
        dump, bundle_path = temporary / "database.dump", temporary / "backup.zip"
        with db_connect(source_url, autocommit=True, options="-c timezone=UTC") as db:
            db.execute("SELECT pg_advisory_lock_shared(hashtextextended('backup-preserve',0))")
            try:
                db.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
                snapshot = db.execute("SELECT pg_export_snapshot()").fetchone()[0]
                manifest["snapshot_at"] = (
                    db.execute("SELECT transaction_timestamp()").fetchone()[0].isoformat()
                )
                manifest["migration_head"] = db.execute("SELECT version_num FROM alembic_version").fetchone()[
                    0
                ]
                manifest["postgres_version"] = db.execute("SHOW server_version").fetchone()[0]
                for (table,) in db.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
                ):
                    manifest["entity_counts"][table] = db.execute(
                        sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table))
                    ).fetchone()[0]
                files = db.execute(
                    "SELECT storage_key,sha256,size_bytes,availability_status,id FROM paper_files WHERE upload_status='uploaded'"
                ).fetchall()
                required = {row[0] for row in db.execute("SELECT DISTINCT paper_file_id FROM evidence")}
                pg_tool(
                    "pg_dump",
                    ["--format=custom", "--no-acl", f"--snapshot={snapshot}", f"--file={dump}"],
                    source_url,
                    timeout,
                )
                with dump.open("rb") as stream:
                    manifest["dump_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                with ZipFile(bundle_path, "w", compression=ZIP_STORED, allowZip64=True) as bundle:
                    bundle.write(dump, "database.dump")
                    for index, (object_key, checksum, expected_size, status, identifier) in enumerate(files):
                        if status != "available":
                            if identifier in required:
                                raise ValueError("BACKUP_REQUIRED_SOURCE_UNAVAILABLE")
                            continue
                        path = f"objects/{index:08d}.bin"
                        digest, size = hashlib.sha256(), 0
                        response = storage.get_object(Bucket=source_bucket, Key=object_key)
                        with response["Body"] as reader, bundle.open(path, "w", force_zip64=True) as writer:
                            while chunk := reader.read(1024 * 1024):
                                if time.monotonic() - started > timeout:
                                    raise ValueError("BACKUP_TIMEOUT")
                                writer.write(chunk)
                                digest.update(chunk)
                                size += len(chunk)
                        if digest.hexdigest() != checksum or size != expected_size:
                            raise ValueError("BACKUP_SOURCE_HASH_MISMATCH")
                        manifest["objects"].append(
                            {"path": path, "storage_key": object_key, "sha256": checksum, "size_bytes": size}
                        )
                    bundle.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
                db.execute("ROLLBACK")
            finally:
                if db.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                    db.execute("ROLLBACK")
                db.execute("SELECT pg_advisory_unlock_shared(hashtextextended('backup-preserve',0))")
        encrypt_file(bundle_path, destination, key)
    return {
        "source_database": manifest["source_database"],
        "snapshot_at": manifest["snapshot_at"],
        "objects": len(manifest["objects"]),
        "tables": len(manifest["entity_counts"]),
        "encrypted": True,
        "seconds": round(time.monotonic() - started, 3),
    }


def apply_runtime_privileges(db):
    db.execute("GRANT USAGE ON SCHEMA public TO researchos_app,researchos_cleanup")
    db.execute(
        "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO researchos_app,researchos_cleanup"
    )
    db.execute("REVOKE INSERT,UPDATE,DELETE ON alembic_version FROM researchos_app,researchos_cleanup")
    if db.execute("SELECT to_regclass('public.maintenance_checkpoints')").fetchone()[0]:
        db.execute("REVOKE ALL ON maintenance_checkpoints FROM researchos_app")
    if db.execute("SELECT 1 FROM pg_roles WHERE rolname='researchos_backup'").fetchone():
        db.execute("GRANT USAGE ON SCHEMA public TO researchos_backup")
        db.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO researchos_backup")
    db.execute(
        "REVOKE UPDATE,DELETE ON decision_revisions,decision_revision_evidence_links,decision_revision_hypothesis_links,decision_revision_note_links,thread_revisions,hypothesis_revisions,activity_events FROM researchos_app"
    )


def restore_backup(backup, target_url, cleanup_url, storage, target_bucket, key, maintenance_ack=False):
    if not maintenance_ack:
        raise ValueError("RESTORE_REQUIRES_OFFLINE_TARGET_ACKNOWLEDGEMENT")
    target, cleanup_target = make_url(target_url), make_url(cleanup_url)
    if (
        target.drivername != "postgresql+psycopg"
        or cleanup_target.drivername != target.drivername
        or cleanup_target.username != "researchos_cleanup"
        or (cleanup_target.host, cleanup_target.port or 5432, cleanup_target.database)
        != (target.host, target.port or 5432, target.database)
    ):
        raise ValueError("RESTORE_CLEANUP_TARGET_MISMATCH")
    backup = local_path(backup)
    folder = ROOT / "runtime/recovery-tmp"
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    target_name = make_url(target_url).database
    copied = []
    with tempfile.TemporaryDirectory(prefix="restore-", dir=folder) as temporary:
        temporary = local_path(temporary)
        plaintext = temporary / "backup.zip"
        decrypt_file(backup, plaintext, key)
        with ZipFile(plaintext) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            ledger_origin = manifest.get("ledger_origin_database", manifest["source_database"])
            if manifest.get("ledger_checkpoint", {}).get(
                "source_id", source_identity(ledger_origin)
            ) != source_identity(ledger_origin):
                raise ValueError("RESTORE_LEDGER_SOURCE_CONFIGURATION_MISMATCH")
            if (
                manifest.get("format_version") != 1
                or target_name == manifest["source_database"]
                or target_bucket == manifest["source_bucket"]
            ):
                raise ValueError("RESTORE_REQUIRES_DIFFERENT_ISOLATED_TARGETS")
            if storage.list_objects_v2(Bucket=target_bucket, MaxKeys=1).get("Contents"):
                raise ValueError("RESTORE_BUCKET_NOT_EMPTY")
            dump = temporary / "database.dump"
            digest = hashlib.sha256()
            with bundle.open("database.dump") as reader, dump.open("xb") as writer:
                while chunk := reader.read(1024 * 1024):
                    writer.write(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != manifest["dump_sha256"]:
                raise ValueError("BACKUP_DUMP_HASH_MISMATCH")
            # Authenticate every original before invoking any database restore SQL.
            for item in manifest["objects"]:
                if not item["path"].startswith("objects/") or "/../" in item["path"]:
                    raise ValueError("INVALID_BACKUP_OBJECT_ENTRY")
                digest, size = hashlib.sha256(), 0
                with bundle.open(item["path"]) as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                if digest.hexdigest() != item["sha256"] or size != item["size_bytes"]:
                    raise ValueError("BACKUP_OBJECT_HASH_MISMATCH")
            with db_connect(target_url, autocommit=True) as db:
                exists = db.execute(
                    "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','f') LIMIT 1"
                ).fetchone()
                if exists:
                    raise ValueError("RESTORE_DATABASE_NOT_EMPTY")
                other = db.execute(
                    "SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() LIMIT 1"
                ).fetchone()
                if other:
                    raise ValueError("RESTORE_TARGET_HAS_OTHER_CONNECTIONS")
                db.execute(
                    sql.SQL(
                        "REVOKE CONNECT ON DATABASE {} FROM PUBLIC,researchos_app,researchos_cleanup"
                    ).format(sql.Identifier(target_name))
                )
            pg_tool(
                "pg_restore",
                [
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-acl",
                    "--exit-on-error",
                    "--single-transaction",
                    str(dump),
                ],
                target_url,
            )
            with ExitStack() as ledger_gate:
                try:
                    for item in manifest["objects"]:
                        copied.append(item["storage_key"])
                        with bundle.open(item["path"]) as stream:
                            storage.upload_fileobj(stream, target_bucket, item["storage_key"])
                        digest, size = hashlib.sha256(), 0
                        response = storage.get_object(Bucket=target_bucket, Key=item["storage_key"])
                        with response["Body"] as stream:
                            while chunk := stream.read(1024 * 1024):
                                digest.update(chunk)
                                size += len(chunk)
                        if digest.hexdigest() != item["sha256"] or size != item["size_bytes"]:
                            raise ValueError("RESTORE_OBJECT_HASH_MISMATCH")
                    with db_connect(target_url, autocommit=True) as db:
                        head = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                        if head != manifest["migration_head"]:
                            raise ValueError("RESTORE_SCHEMA_HEAD_MISMATCH")
                        for table, count in manifest["entity_counts"].items():
                            if (
                                db.execute(
                                    sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table))
                                ).fetchone()[0]
                                != count
                            ):
                                raise ValueError("RESTORE_ROW_COUNT_MISMATCH")
                        apply_runtime_privileges(db)
                        db.execute(
                            sql.SQL("GRANT CONNECT ON DATABASE {} TO researchos_cleanup").format(
                                sql.Identifier(target_name)
                            )
                        )
                    from app.workers.deletions import (
                        ledger_directory,
                        recover_pending_deletions,
                        register_pending_deletions,
                        replay_ledger,
                    )

                    cleanup = create_engine(cleanup_url, hide_parameters=True)
                    try:
                        # Never let legacy-job registration repair or conceal an
                        # authority that is already missing/behind the backup.
                        with frozen_journal(
                            ledger_origin,
                            minimum=manifest.get("ledger_checkpoint"),
                            backup_snapshot_at=manifest["snapshot_at"],
                        ):
                            pass
                        register_pending_deletions(cleanup, ledger_origin)
                        journal = ledger_gate.enter_context(
                            frozen_journal(
                                ledger_origin,
                                minimum=manifest.get("ledger_checkpoint"),
                                backup_snapshot_at=manifest["snapshot_at"],
                            )
                        )
                        deleted = replay_ledger(
                            cleanup,
                            ledger_directory(ledger_origin),
                            ledger_origin,
                            storage=storage,
                            bucket=target_bucket,
                            journal=journal,
                        )
                        deleted += recover_pending_deletions(
                            cleanup,
                            ledger_origin,
                            storage=storage,
                            bucket=target_bucket,
                            journal=journal,
                        )
                    finally:
                        cleanup.dispose()
                    # Reopening is one transaction: failure of the final grant
                    # must not leave application CONNECT committed on its own.
                    with db_connect(target_url, autocommit=False) as db:
                        db.execute("DELETE FROM auth_sessions")
                        db.execute(
                            "UPDATE auth_tokens SET used_at=COALESCE(used_at,now()),delivery_ciphertext=NULL"
                        )
                        db.execute("DELETE FROM outbox_events")
                        db.execute("DELETE FROM api_idempotency_keys")
                        if db.execute("SELECT to_regclass('public.maintenance_checkpoints')").fetchone()[0]:
                            db.execute("DELETE FROM maintenance_checkpoints")
                        db.execute(
                            "UPDATE processing_jobs SET status='failed',error_code='RECOVERY_REQUIRES_REUPLOAD',finished_at=now() WHERE status IN ('queued','running')"
                        )
                        db.execute(
                            "UPDATE upload_sessions SET status='failed' WHERE status IN ('pending','validating')"
                        )
                        db.execute(
                            "UPDATE paper_files SET upload_status='failed',parse_status='failed',availability_status='missing',is_current=false WHERE upload_status='pending'"
                        )
                        db.execute(
                            "UPDATE export_jobs SET status='expired',storage_key=NULL WHERE status IN ('queued','running','succeeded')"
                        )
                        password = hasher.hash(secrets.token_urlsafe(48))
                        db.execute("UPDATE users SET password_hash=%s", (password,))
                        db.execute(
                            sql.SQL("GRANT CONNECT ON DATABASE {} TO researchos_app").format(
                                sql.Identifier(target_name)
                            )
                        )
                        db.execute(
                            sql.SQL("GRANT CONNECT ON DATABASE {} TO researchos_backup").format(
                                sql.Identifier(target_name)
                            )
                        )
                except Exception:
                    for object_key in copied:
                        storage.delete_object(Bucket=target_bucket, Key=object_key)
                    # Database is deliberately kept inaccessible to the application.
                    raise
    return {
        "restored_database": target_name,
        "schema_head": head,
        "objects_restored": len(copied),
        "deletion_requests_replayed": deleted,
        "verified_ledger_sequence": journal.head["sequence"],
        "ledger_configuration": {"source_id": journal.source, "origin_database": ledger_origin},
        "sessions_revoked": True,
        "password_recovery_required": True,
        "seconds": round(time.monotonic() - started, 3),
    }
