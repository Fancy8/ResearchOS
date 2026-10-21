"""Dedicated-role cleanup, exclusion from remote writers, anonymous restore ledger."""

import hashlib
import hmac
import json
import logging
import os
import shutil
import threading
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import sessionmaker

from app import models
from app.core.config import ROOT, get_settings
from app.core.resource_locks import exclusive_resource
from app.core.runtime_paths import runtime_namespace
from app.core.storage import s3_client
from app.recovery.journal import (
    append_document,
    checked_document,
    frozen_journal,
    origin_database,
    require_activated,
)
from app.workers.celery_app import celery_app

# Children precede RESTRICT parents. Deferred current-revision pointers are
# checked only after their owning objects have also been removed.
CLEANUP_TABLES = [
    "activity_events",
    "decision_revision_note_links",
    "decision_revision_hypothesis_links",
    "decision_revision_evidence_links",
    "tasks",
    "decision_revisions",
    "research_decisions",
    "hypothesis_evidence_links",
    "hypothesis_revisions",
    "hypotheses",
    "note_evidence_links",
    "note_papers",
    "thread_notes",
    "project_notes",
    "notes",
    "evidence",
    "thread_papers",
    "project_papers",
    "processing_jobs",
    "upload_sessions",
    "paper_pages",
    "paper_files",
    "papers",
    "thread_revisions",
    "research_threads",
    "projects",
    "research_profiles",
    "outbox_events",
    "api_idempotency_keys",
    "export_jobs",
]


@lru_cache
def cleanup_engine():
    url = get_settings().cleanup_database_url
    if not url:
        raise RuntimeError("Dedicated cleanup credentials are required")
    return create_engine(url, hide_parameters=True, pool_pre_ping=True, pool_size=2, max_overflow=1)


def ledger_hash(kind, identifier):
    return hmac.new(
        get_settings().control_secret.encode(), f"{kind}:{identifier}".encode(), hashlib.sha256
    ).hexdigest()


def ledger_directory(database):
    return runtime_namespace("deletion-ledger", database)


def ledger_document(job, workspace_id, user_id, source_database):
    document = {
        "schema_version": 1,
        "job_id": str(job.id),
        "scope": job.scope,
        "workspace_hash": ledger_hash("workspace", workspace_id),
        "user_hash": ledger_hash("user", user_id) if user_id else None,
        "file_hash": ledger_hash("file", job.target_id) if job.scope == "file" else None,
        "requested_at": job.requested_at.isoformat(),
        "database": source_database,
    }
    document["signature"] = ledger_signature(document)
    return checked_document(document, source_database)


def write_ledger(job, workspace_id, user_id, source_database=None):
    # A local mirror remains diagnostic/legacy-transfer material, never authority.
    database = source_database or origin_database(cleanup_engine().url.database)
    require_activated(database)
    document = ledger_document(job, workspace_id, user_id, database)
    append_document(document)
    try:
        write_legacy_mirror(database, document)
    except OSError:
        logging.getLogger("researchos").warning(
            json.dumps({"event": "deletion_mirror_unavailable", "job_id": str(job.id)})
        )


def write_legacy_mirror(database, document):
    directory = ledger_directory(database)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{document['job_id']}.json"
    if target.exists():
        return
    temporary = directory / f"{document['job_id']}-{uuid4()}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(document, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def ledger_signature(document):
    return hmac.new(
        get_settings().control_secret.encode(),
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()


def complete_deletion(job):
    """Retain the opaque receipt while removing identifiers and stale worker leases."""
    if not job.online_finished_at:
        job.online_finished_at = datetime.now(UTC)
        days = get_settings().backup_retention_days
        job.backup_expiry_at = datetime.now(UTC) + timedelta(days=days) if days else None
    job.status, job.error_code = "succeeded", None
    job.workspace_id = job.requested_by = job.target_id = None
    job.attempt_token = job.lease_owner = job.lease_expires_at = None


def replay_ledger(engine, ledger_directory, source_database, *, storage=None, bucket=None, journal=None):
    """Run while the restored service is offline, before reopening access."""
    if journal is None:
        with frozen_journal(source_database) as verified:
            return replay_ledger(
                engine, ledger_directory, source_database, storage=storage, bucket=bucket, journal=verified
            )
    CleanupSession = sessionmaker(engine)
    actions = 0
    for document in journal.documents():
        supplied = document.pop("signature", "")
        if not supplied or not hmac.compare_digest(supplied, ledger_signature(document)):
            raise RuntimeError("Unsigned or altered deletion ledger: restore must remain offline")
        if document.get("schema_version") != 1 or document.get("scope") not in {"account", "file"}:
            raise RuntimeError("Unsupported deletion ledger: restore must remain offline")
        with CleanupSession.begin() as db:
            if db.execute(text("SELECT current_user")).scalar_one() != "researchos_cleanup":
                raise RuntimeError("Restore replay requires the dedicated cleanup role")
            workspace = next(
                (
                    row
                    for row in db.scalars(select(models.Workspace))
                    if ledger_hash("workspace", row.id) == document["workspace_hash"]
                ),
                None,
            )
            job = db.get(models.DeletionJob, UUID(document["job_id"]))
            if job and (
                job.scope != document["scope"]
                or (
                    job.workspace_id
                    and ledger_hash("workspace", job.workspace_id) != document["workspace_hash"]
                )
                or (job.target_id and ledger_hash("file", job.target_id) != document["file_hash"])
            ):
                raise RuntimeError("Deletion ledger receipt mismatch: restore must remain offline")
            if workspace:
                with exclusive_resource(engine, workspace.id):
                    if document["scope"] == "account":
                        workspace.status = "deleting"
                        db.flush()
                        remove_account(
                            db, workspace.id, workspace.owner_user_id, storage=storage, bucket=bucket
                        )
                        actions += 1
                    elif document["scope"] == "file":
                        file = next(
                            (
                                row
                                for row in db.scalars(
                                    select(models.PaperFile).where(
                                        models.PaperFile.workspace_id == workspace.id
                                    )
                                )
                                if ledger_hash("file", row.id) == document["file_hash"]
                            ),
                            None,
                        )
                        if file:
                            remove_file(db, file, storage=storage, bucket=bucket)
                            actions += 1
            if job:
                complete_deletion(job)
    return actions


def register_pending_deletions(engine, source_database):
    """Authenticated legacy pending jobs join the authority before its read lock."""
    require_activated(source_database)
    Session = sessionmaker(engine)
    with Session() as db:
        for job in db.scalars(select(models.DeletionJob).where(models.DeletionJob.status != "succeeded")):
            workspace = db.get(models.Workspace, job.workspace_id) if job.workspace_id else None
            if not workspace:
                raise RuntimeError("RESTORE_INVALID_PENDING_DELETION")
            append_document(ledger_document(job, workspace.id, workspace.owner_user_id, source_database))


def recover_pending_deletions(engine, source_database, *, storage=None, bucket=None, journal=None):
    """Honor durable requests in the dump even if no worker wrote a ledger yet."""
    CleanupSession = sessionmaker(engine)
    with CleanupSession() as db:
        if db.execute(text("SELECT current_user")).scalar_one() != "researchos_cleanup":
            raise RuntimeError("Restore replay requires the dedicated cleanup role")
        frozen = set(db.scalars(select(models.Workspace.id).where(models.Workspace.status == "deleting")))
        accounts = set(
            db.scalars(select(models.DeletionJob.workspace_id).where(models.DeletionJob.scope == "account"))
        )
        if frozen - accounts:
            raise RuntimeError("RESTORE_FROZEN_SPACE_WITHOUT_DELETION_REQUEST")
        identifiers = list(
            db.scalars(
                select(models.DeletionJob.id)
                .where(models.DeletionJob.status != "succeeded")
                .order_by(models.DeletionJob.scope, models.DeletionJob.requested_at, models.DeletionJob.id)
            )
        )
    actions = 0
    for identifier in identifiers:
        with CleanupSession.begin() as db:
            job = db.get(models.DeletionJob, identifier)
            if job.status == "succeeded":  # An account removal subsumes its file requests.
                continue
            workspace = db.get(models.Workspace, job.workspace_id) if job.workspace_id else None
            if not workspace or job.scope not in {"account", "file"}:
                raise RuntimeError("RESTORE_INVALID_PENDING_DELETION")
            with exclusive_resource(engine, workspace.id):
                if journal is None:
                    write_ledger(job, workspace.id, workspace.owner_user_id, source_database=source_database)
                else:
                    raise RuntimeError("RESTORE_PENDING_DELETION_NOT_REPLAYED")
                if job.scope == "account":
                    remove_account(db, workspace.id, workspace.owner_user_id, storage=storage, bucket=bucket)
                else:
                    file = db.get(models.PaperFile, job.target_id) if job.target_id else None
                    if not file or file.workspace_id != workspace.id:
                        raise RuntimeError("RESTORE_INVALID_PENDING_DELETION_TARGET")
                    remove_file(db, file, storage=storage, bucket=bucket)
                complete_deletion(job)
                actions += 1
    return actions


def remove_prefix(prefix, *, storage=None, bucket=None):
    client, bucket = storage or s3_client(), bucket or get_settings().s3_bucket
    # Remove all versions and delete markers when the S3 backend uses versioning.
    versioning = client.get_bucket_versioning(Bucket=bucket).get("Status")
    versioned, preceding = versioning in {"Enabled", "Suspended"}, None
    while True:
        # Restart at the first remaining page: a cursor referring to a version
        # just erased is not a safe position for subsequent version listings.
        if versioned:
            page = client.list_object_versions(Bucket=bucket, Prefix=prefix, MaxKeys=1000)
            rows = page.get("Versions", []) + page.get("DeleteMarkers", [])
        else:
            rows = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1000).get("Contents", [])
        if not rows:
            break
        identifiers = tuple(sorted((row["Key"], row.get("VersionId", "")) for row in rows))
        if identifiers == preceding:
            raise RuntimeError("OBJECTS_REMAIN")
        preceding = identifiers
        for row in rows:
            if not row["Key"].startswith(prefix):
                raise RuntimeError("OBJECT_PREFIX_SCOPE_INVALID")
            options = {"VersionId": row["VersionId"]} if versioned else {}
            client.delete_object(Bucket=bucket, Key=row["Key"], **options)
    if client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1).get("KeyCount", 0):
        raise RuntimeError("OBJECTS_REMAIN")


def remove_local_job_files(db, workspace_id, file_id=None):
    for model, folder in ((models.ProcessingJob, "pdf-tmp"), (models.ExportJob, "export-tmp")):
        if file_id and model is models.ExportJob:
            continue
        clauses = [model.workspace_id == workspace_id]
        if file_id:
            clauses.append(model.paper_file_id == file_id)
        identifiers = list(db.scalars(select(model.id).where(*clauses)))
        directory = runtime_namespace(folder, db.bind.url.database).resolve()
        for identifier in identifiers:
            for path in directory.glob(f"{identifier}-*"):
                if not path.resolve().is_relative_to(directory):
                    raise RuntimeError("TEMPORARY_FILE_SCOPE_INVALID")
                if path.is_file():
                    path.unlink()


def remove_file(db, file, *, storage=None, bucket=None):
    if db.execute(
        select(models.Evidence.id).where(models.Evidence.paper_file_id == file.id).limit(1)
    ).first():
        raise RuntimeError("FILE_HAS_EVIDENCE")
    uploads = list(
        db.scalars(select(models.UploadSession).where(models.UploadSession.paper_file_id == file.id))
    )
    client, target_bucket = storage or s3_client(), bucket or get_settings().s3_bucket
    for upload in uploads:
        client.delete_object(Bucket=target_bucket, Key=upload.staging_key)
    # Includes abandoned attempt-specific finalized copies of this file version.
    remove_prefix(
        f"final/{file.workspace_id}/{file.paper_id}/{file.id}", storage=client, bucket=target_bucket
    )
    remove_local_job_files(db, file.workspace_id, file.id)
    for model in (models.ProcessingJob, models.UploadSession, models.PaperPage):
        db.execute(delete(model).where(model.paper_file_id == file.id))
    # Retain version numbering and a clear unavailable marker; never serve bytes.
    file.availability_status, file.is_current = "missing", False


def remove_account(db, workspace_id, user_id, *, storage=None, bucket=None):
    receipts = list(
        db.scalars(select(models.DeletionJob).where(models.DeletionJob.workspace_id == workspace_id))
    )
    workspace = db.get(models.Workspace, workspace_id)
    if workspace:
        if workspace.status != "deleting":
            raise RuntimeError("WORKSPACE_NOT_FROZEN")
        for prefix in (f"final/{workspace_id}/", f"staging/{workspace_id}/", f"exports/{workspace_id}/"):
            remove_prefix(prefix, storage=storage, bucket=bucket)
        remove_local_job_files(db, workspace_id)
        directory = (
            runtime_namespace("mail-preview", db.bind.url.database)
            / get_settings().environment
            / str(workspace_id)
        ).resolve()
        allowed = (ROOT / "runtime/mail-preview").resolve()
        if not directory.is_relative_to(allowed):
            raise RuntimeError("MAIL_PREVIEW_SCOPE_INVALID")
        if directory.exists():
            shutil.rmtree(directory)
        db.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        for name in CLEANUP_TABLES:
            table = models.Base.metadata.tables[name]
            db.execute(delete(table).where(table.c.workspace_id == workspace_id))
        db.delete(workspace)
    user = db.get(models.User, user_id) if user_id else None
    if user:
        db.execute(delete(models.AuthSession).where(models.AuthSession.user_id == user_id))
        db.execute(
            delete(models.AuthToken).where(
                (models.AuthToken.user_id == user_id) | (models.AuthToken.email == user.email)
            )
        )
        db.delete(user)
    for job in receipts:
        complete_deletion(job)


@celery_app.task(name="researchos.delete_data")
def delete_data(job_id):
    identifier, token, now = UUID(str(job_id)), uuid4(), datetime.now(UTC)
    CleanupSession = sessionmaker(cleanup_engine(), expire_on_commit=False)
    with CleanupSession.begin() as db:
        job = db.execute(
            select(models.DeletionJob).where(models.DeletionJob.id == identifier).with_for_update()
        ).scalar_one_or_none()
        if (
            not job
            or job.status == "succeeded"
            or (job.status == "running" and job.lease_expires_at and job.lease_expires_at > now)
        ):
            return
        if job.attempts >= job.max_attempts:
            job.status, job.error_code = "failed", "CLEANUP_ATTEMPTS_EXHAUSTED"
            return
        job.status, job.attempt_token, job.lease_owner = "running", token, f"cleanup-{os.getpid()}"
        job.attempts += 1
        job.lease_expires_at = now + timedelta(minutes=15)
        workspace_id, user_id = job.workspace_id, job.requested_by
    stop = threading.Event()

    # deletion_jobs has no heartbeat_at; extend its lease with its own heartbeat.
    def pulse():
        while not stop.wait(20):
            try:
                with CleanupSession.begin() as db:
                    db.execute(
                        models.DeletionJob.__table__.update()
                        .where(
                            models.DeletionJob.id == identifier,
                            models.DeletionJob.attempt_token == token,
                            models.DeletionJob.status == "running",
                        )
                        .values(lease_expires_at=datetime.now(UTC) + timedelta(minutes=15))
                    )
            except Exception:
                pass

    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    try:
        with exclusive_resource(cleanup_engine(), workspace_id):
            with CleanupSession.begin() as db:
                job = db.execute(
                    select(models.DeletionJob).where(models.DeletionJob.id == identifier).with_for_update()
                ).scalar_one()
                if job.attempt_token != token or job.status != "running":
                    return
                write_ledger(job, workspace_id, user_id)
                if job.scope == "account":
                    remove_account(db, workspace_id, user_id)
                elif job.scope == "file":
                    file = db.get(models.PaperFile, job.target_id)
                    if file and file.workspace_id == workspace_id:
                        remove_file(db, file)
                else:
                    raise RuntimeError("UNKNOWN_CLEANUP_SCOPE")
                complete_deletion(job)
    except Exception:
        with CleanupSession.begin() as db:
            job = db.get(models.DeletionJob, identifier)
            if job and job.attempt_token == token and job.status == "running":
                job.status, job.error_code = "failed", "CLEANUP_SERVICE_UNAVAILABLE"
                if job.attempts < job.max_attempts:
                    job.status = "queued"
                    db.add(
                        models.OutboxEvent(
                            id=uuid4(),
                            workspace_id=workspace_id,
                            event_type="delete_data",
                            aggregate_id=identifier,
                            payload={"job_id": str(identifier)},
                            next_attempt_at=datetime.now(UTC) + timedelta(seconds=2**job.attempts),
                        )
                    )
    finally:
        stop.set()
        thread.join(timeout=5)
