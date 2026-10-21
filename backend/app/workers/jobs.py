import hashlib
import json
import os
import sys
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import sessionmaker

from app.core.config import ROOT, get_settings
from app.core.processes import (
    ProcessGuardError,
    ProcessOutputLimit,
    ProcessTimeout,
    process_environment,
    run_contained,
)
from app.core.resource_locks import guard_resource
from app.core.runtime_paths import runtime_namespace
from app.core.storage import copy_object, get_object_bytes, remove_object
from app.models import (
    ActivityEvent,
    OutboxEvent,
    Paper,
    PaperFile,
    PaperPage,
    ProcessingJob,
    UploadSession,
    Workspace,
)
from app.workers.celery_app import celery_app

sync_engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    hide_parameters=True,
    connect_args={"options": "-c timezone=UTC"},
    pool_size=2,
    max_overflow=2,
)
WorkerSession = sessionmaker(sync_engine, expire_on_commit=False)
PARSER_VERSION = "pypdf-6.20.1-anchor-v1"


def parse_isolated(data, job_id):
    temporary = runtime_namespace("pdf-tmp")
    temporary.mkdir(exist_ok=True, parents=True)
    path = temporary / f"{job_id}-{uuid4()}.pdf"
    path.write_bytes(data)
    try:
        try:
            parsed = run_contained(
                [sys.executable, "-m", "app.workers.pdf_parse", str(path), str(get_settings().max_pdf_pages)],
                cwd=ROOT / "backend",
                env=process_environment(temporary),
                timeout=120,
                memory_limit=512 * 1024 * 1024,
            )
        except ProcessTimeout:
            raise ValueError("PARSE_TIMEOUT") from None
        except ProcessOutputLimit:
            raise ValueError("PARSE_OUTPUT_LIMIT") from None
        except ProcessGuardError:
            raise ValueError("PARSE_CONTAINMENT_FAILED") from None
        stdout = parsed.stdout
        result = json.loads(stdout.decode("utf-8"))
        if not result.get("ok"):
            raise ValueError(result.get("error_code", "INVALID_PDF"))
        return result["result"]
    finally:
        path.unlink(missing_ok=True)


def claim(job_id):
    now = datetime.now(UTC)
    with WorkerSession.begin() as db:
        job = db.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update()
        ).scalar_one_or_none()
        if not job or job.status in {"succeeded", "failed"}:
            return None
        if job.status == "queued" and job.next_attempt_at > now:
            return None
        if job.status == "running" and job.lease_expires_at and job.lease_expires_at > now:
            return None
        if job.attempts >= job.max_attempts:
            job.status, job.error_code, job.finished_at = "failed", "ATTEMPTS_EXHAUSTED", now
            file = db.get(PaperFile, job.paper_file_id)
            file.parse_status = "failed"
            return None
        token = uuid4()
        job.status, job.attempt_token, job.started_at = "running", token, now
        job.lease_owner = f"worker-{os.getpid()}"
        job.heartbeat_at, job.lease_expires_at = now, now + timedelta(seconds=180)
        job.attempts += 1
        file = db.get(PaperFile, job.paper_file_id)
        file.parse_status = "processing"
        upload = db.execute(
            select(UploadSession).where(UploadSession.paper_file_id == file.id)
        ).scalar_one_or_none()
        return {
            "token": token,
            "file_id": file.id,
            "workspace_id": file.workspace_id,
            "key": upload.staging_key if upload and upload.status != "completed" else file.storage_key,
            "final_key": f"final/{file.workspace_id}/{file.paper_id}/{file.id}-{token}.pdf"
            if upload and upload.status != "completed"
            else file.storage_key,
            "expected_size": upload.expected_size if upload else file.size_bytes,
            "expected_sha256": upload.expected_sha256 if upload else file.sha256,
            "upload_id": upload.id if upload else None,
            "needs_finalize": bool(upload and upload.status != "completed"),
        }


def failure(job_id, token, code, retryable=False):
    with WorkerSession.begin() as db:
        job = db.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update()
        ).scalar_one_or_none()
        if not job or job.attempt_token != token or job.status != "running":
            return
        if retryable and job.attempts < job.max_attempts:
            job.status = "queued"
            job.next_attempt_at = datetime.now(UTC) + timedelta(seconds=2**job.attempts)
            db.add(
                OutboxEvent(
                    id=uuid4(),
                    workspace_id=job.workspace_id,
                    event_type="parse_pdf",
                    aggregate_id=job.id,
                    payload={"job_id": str(job.id)},
                    next_attempt_at=job.next_attempt_at,
                )
            )
        else:
            job.status, job.finished_at = "failed", datetime.now(UTC)
        job.error_code = code
        file = db.get(PaperFile, job.paper_file_id)
        file.parse_status = "queued" if job.status == "queued" else "failed"
        if file.upload_status != "uploaded" and job.status == "failed":
            file.upload_status = "failed"
        upload = db.execute(
            select(UploadSession).where(UploadSession.paper_file_id == file.id)
        ).scalar_one_or_none()
        if upload and job.status == "failed" and upload.status != "completed":
            upload.status = "failed"


def heartbeat(job_id, token, stop, model=ProcessingJob, seconds=180):
    while not stop.wait(20):
        try:
            now = datetime.now(UTC)
            with WorkerSession.begin() as db:
                db.execute(
                    update(model)
                    .where(
                        model.id == job_id,
                        model.attempt_token == token,
                        model.status == "running",
                    )
                    .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=seconds))
                )
        except Exception:
            # A stale attempt remains unable to publish; lease recovery owns retries.
            pass


@celery_app.task(name="researchos.parse_pdf")
@guard_resource(ProcessingJob)
def parse_pdf(job_id):
    identifier = UUID(job_id)
    claimed = claim(identifier)
    if not claimed:
        return
    token = claimed["token"]
    stop = threading.Event()
    pulse = threading.Thread(target=heartbeat, args=(identifier, token, stop), daemon=True)
    pulse.start()
    try:
        data = get_object_bytes(claimed["key"])
        if (
            len(data) != claimed["expected_size"]
            or len(data) > get_settings().max_upload_bytes
            or not data.startswith(b"%PDF-")
        ):
            raise ValueError("INVALID_PDF_SIZE_OR_SIGNATURE")
        checksum = hashlib.sha256(data).hexdigest()
        if claimed["expected_sha256"] and claimed["expected_sha256"] != checksum:
            raise ValueError("FILE_HASH_MISMATCH")
        parsed = parse_isolated(data, identifier)
        if claimed["needs_finalize"]:
            copy_object(claimed["key"], claimed["final_key"])
            final = get_object_bytes(claimed["final_key"])
            if hashlib.sha256(final).hexdigest() != checksum:
                raise ValueError("FINAL_FILE_HASH_MISMATCH")
        with WorkerSession.begin() as db:
            job = db.execute(
                select(ProcessingJob).where(ProcessingJob.id == identifier).with_for_update()
            ).scalar_one()
            if (
                job.status != "running"
                or job.attempt_token != token
                or job.lease_expires_at < datetime.now(UTC)
            ):
                return
            workspace = db.get(Workspace, claimed["workspace_id"])
            if workspace.status != "active":
                job.status, job.error_code, job.finished_at = "failed", "WORKSPACE_FROZEN", datetime.now(UTC)
                return
            file = db.get(PaperFile, claimed["file_id"])
            paper = db.execute(select(Paper).where(Paper.id == file.paper_id).with_for_update()).scalar_one()
            old = list(
                db.execute(
                    select(PaperFile).where(PaperFile.paper_id == paper.id, PaperFile.is_current.is_(True))
                ).scalars()
            )
            if claimed["needs_finalize"]:
                for row in old:
                    row.is_current = False
                db.flush()
                file.upload_status, file.is_current, file.uploaded_at = "uploaded", True, datetime.now(UTC)
                file.storage_key = claimed["final_key"]
            file.sha256, file.page_count, file.has_text_layer = (
                checksum,
                parsed["page_count"],
                parsed["has_text_layer"],
            )
            file.parse_status, file.parser_version = "ready", parsed["parser_version"]
            db.execute(delete(PaperPage).where(PaperPage.paper_file_id == file.id))
            for page in parsed["pages"]:
                db.add(
                    PaperPage(
                        workspace_id=file.workspace_id, paper_id=file.paper_id, paper_file_id=file.id, **page
                    )
                )
            if claimed["upload_id"]:
                db.get(UploadSession, claimed["upload_id"]).status = "completed"
            job.status, job.finished_at, job.error_code = "succeeded", datetime.now(UTC), None
            job.parser_version = parsed["parser_version"]
            db.add(
                ActivityEvent(
                    id=uuid4(),
                    workspace_id=file.workspace_id,
                    actor_user_id=workspace.owner_user_id,
                    event_type="paper_imported" if claimed["needs_finalize"] else "paper_reparsed",
                    target_type="papers",
                    target_id=file.paper_id,
                    event_payload={"paper_file_id": str(file.id), "version_no": file.version_no},
                )
            )
        if claimed["needs_finalize"]:
            remove_object(claimed["key"])
    except ValueError as error:
        failure(identifier, token, str(error))
    except Exception:
        failure(identifier, token, "PROCESSING_SERVICE_UNAVAILABLE", retryable=True)
    finally:
        stop.set()
        pulse.join(timeout=5)


def dispatch_once():
    now = datetime.now(UTC)
    with WorkerSession.begin() as db:
        expired = list(
            db.execute(
                select(ProcessingJob)
                .where(ProcessingJob.status == "running", ProcessingJob.lease_expires_at < now)
                .with_for_update(skip_locked=True)
            ).scalars()
        )
        for job in expired:
            job.status = "queued"
            db.add(
                OutboxEvent(
                    id=uuid4(),
                    workspace_id=job.workspace_id,
                    event_type="parse_pdf",
                    aggregate_id=job.id,
                    payload={"job_id": str(job.id)},
                )
            )
        from app.models import DeletionJob, ExportJob

        expired_exports = list(
            db.execute(
                select(ExportJob)
                .where(ExportJob.status == "running", ExportJob.lease_expires_at < now)
                .with_for_update(skip_locked=True)
            ).scalars()
        )
        for job in expired_exports:
            job.status = "queued"
            db.add(
                OutboxEvent(
                    id=uuid4(),
                    workspace_id=job.workspace_id,
                    event_type="export_workspace",
                    aggregate_id=job.id,
                    payload={"job_id": str(job.id)},
                )
            )
        expired_deletions = list(
            db.scalars(
                select(DeletionJob)
                .where(DeletionJob.status == "running", DeletionJob.lease_expires_at < now)
                .with_for_update(skip_locked=True)
            )
        )
        for job in expired_deletions:
            job.status = "queued"
            db.add(
                OutboxEvent(
                    id=uuid4(),
                    workspace_id=job.workspace_id,
                    event_type="delete_data",
                    aggregate_id=job.id,
                    payload={"job_id": str(job.id)},
                )
            )
        events = list(
            db.execute(
                select(OutboxEvent)
                .where(OutboxEvent.dispatched_at.is_(None), OutboxEvent.next_attempt_at <= now)
                .order_by(OutboxEvent.created_at)
                .limit(20)
                .with_for_update(skip_locked=True)
            ).scalars()
        )
        for event in events:
            task_name = {
                "parse_pdf": "researchos.parse_pdf",
                "export_workspace": "researchos.export_workspace",
                "delete_data": "researchos.delete_data",
                "send_auth_email": "researchos.send_auth_email",
            }.get(event.event_type)
            if not task_name:
                event.attempts += 1
                event.next_attempt_at = now + timedelta(seconds=60)
                continue
            try:
                celery_app.send_task(task_name, args=[str(event.aggregate_id)], retry=False)
                event.dispatched_at = now
            except Exception:
                event.attempts += 1
                event.next_attempt_at = now + timedelta(seconds=min(60, 2 ** min(event.attempts, 5)))
    return len(events)
