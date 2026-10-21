import hashlib
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, text

from app import models
from app.core.config import get_settings
from app.core.resource_locks import guard_resource
from app.core.runtime_paths import runtime_namespace
from app.core.storage import remove_object, s3_client
from app.models import ActivityEvent, ExportJob, User, Workspace
from app.workers.celery_app import celery_app
from app.workers.jobs import WorkerSession, heartbeat, sync_engine

EXPORT_TABLES = [
    models.ResearchProfile,
    models.Project,
    models.ResearchThread,
    models.Paper,
    models.PaperFile,
    models.PaperPage,
    models.ProjectPaper,
    models.ThreadPaper,
    models.Evidence,
    models.Hypothesis,
    models.HypothesisEvidenceLink,
    models.ResearchDecision,
    models.DecisionRevision,
    models.DecisionRevisionEvidenceLink,
    models.Task,
    models.Note,
    models.ProjectNote,
    models.ThreadNote,
    models.NotePaper,
    models.NoteEvidenceLink,
    models.ActivityEvent,
    models.ThreadRevision,
    models.HypothesisRevision,
    models.DecisionRevisionHypothesisLink,
    models.DecisionRevisionNoteLink,
]


def row_data(row, columns):
    return jsonable_encoder({column.name: row[column.name] for column in columns})


def markdown_note(content):
    kind = content.get("type")
    children = content.get("content", [])
    if kind == "text":
        return content.get("text", "")
    if kind in {"inlineMath", "blockMath"}:
        latex = content.get("attrs", {}).get("latex", "")
        return f"${latex}$" if kind == "inlineMath" else f"\n\n$$\n{latex}\n$$\n\n"
    inner = "".join(markdown_note(child) for child in children)
    if kind == "heading":
        return "#" * int(content.get("attrs", {}).get("level", 2)) + " " + inner.strip() + "\n\n"
    if kind == "paragraph":
        return inner + "\n\n"
    if kind == "blockquote":
        return "\n".join("> " + line for line in inner.splitlines()) + "\n\n"
    if kind == "listItem":
        return "- " + inner.strip() + "\n"
    if kind == "hardBreak":
        return "\n"
    return inner


def create_archive(job, token):
    deadline = time.monotonic() + get_settings().export_snapshot_seconds

    def check_budget():
        if time.monotonic() >= deadline:
            raise ValueError("EXPORT_SNAPSHOT_TIMEOUT")

    folder = runtime_namespace("export-tmp")
    folder.mkdir(exist_ok=True, parents=True)
    archive = folder / f"{job.id}-{token}.zip"
    manifest = {
        "schema_version": 1,
        "workspace_id": str(job.workspace_id),
        "snapshot_at": None,
        "include_files": job.include_files,
        "entities": {},
        "files": [],
        "missing_files": [],
    }
    files = []
    with sync_engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(
                text("SELECT set_config('statement_timeout',:value,true)"),
                {"value": str(get_settings().export_snapshot_seconds * 1000)},
            )
            required_files = set(
                connection.scalars(
                    select(models.Evidence.paper_file_id).where(
                        models.Evidence.workspace_id == job.workspace_id
                    )
                )
            )
            manifest["snapshot_at"] = (
                connection.execute(text("SELECT transaction_timestamp()")).scalar_one().isoformat()
            )
            workspace = (
                connection.execute(select(Workspace.__table__).where(Workspace.id == job.workspace_id))
                .mappings()
                .one()
            )
            user = (
                connection.execute(select(User.__table__).where(User.id == workspace["owner_user_id"]))
                .mappings()
                .one()
            )
            with ZipFile(archive, "w", compression=ZIP_DEFLATED, allowZip64=True) as bundle:
                bundle.writestr(
                    "data/workspaces.json",
                    json.dumps([row_data(workspace, Workspace.__table__.columns)], ensure_ascii=False),
                )
                sanitized_user = {
                    key: jsonable_encoder(value) for key, value in user.items() if key != "password_hash"
                }
                bundle.writestr("data/users.json", json.dumps([sanitized_user], ensure_ascii=False))
                manifest["entities"].update({"workspaces": 1, "users": 1})
                for model in EXPORT_TABLES:
                    table = model.__table__
                    query = select(table).where(table.c.workspace_id == job.workspace_id)
                    count = 0
                    with bundle.open(f"data/{table.name}.json", "w", force_zip64=True) as stream:
                        stream.write(b"[")
                        for row in (
                            connection.execution_options(stream_results=True, yield_per=200)
                            .execute(query)
                            .mappings()
                        ):
                            check_budget()
                            value = row_data(row, table.columns)
                            if count:
                                stream.write(b",\n")
                            stream.write(json.dumps(value, ensure_ascii=False).encode("utf-8"))
                            count += 1
                            if model is models.PaperFile and row["upload_status"] == "uploaded":
                                if row["availability_status"] == "available":
                                    files.append(value)
                                elif row["id"] in required_files and job.include_files:
                                    raise ValueError("EXPORT_REQUIRED_FILE_UNAVAILABLE")
                                else:
                                    manifest["missing_files"].append(
                                        {
                                            "paper_file_id": str(row["id"]),
                                            "reason": "referenced_version_unavailable"
                                            if row["id"] in required_files
                                            else "unreferenced_version_removed",
                                        }
                                    )
                        stream.write(b"]")
                    manifest["entities"][table.name] = count
                for note in connection.execute(
                    select(models.Note.__table__).where(models.Note.workspace_id == job.workspace_id)
                ).mappings():
                    check_budget()
                    bundle.writestr(
                        f"notes/{note['id']}.md",
                        "# " + note["title"] + "\n\n" + markdown_note(note["content"]),
                    )
                if job.include_files:
                    for file in files:
                        check_budget()
                        response = s3_client().get_object(
                            Bucket=get_settings().s3_bucket, Key=file["storage_key"]
                        )
                        checksum = hashlib.sha256()
                        size = 0
                        filename = f"files/{file['paper_id']}/{file['id']}.pdf"
                        with (
                            response["Body"] as source,
                            bundle.open(filename, "w", force_zip64=True) as destination,
                        ):
                            while chunk := source.read(1024 * 1024):
                                check_budget()
                                destination.write(chunk)
                                checksum.update(chunk)
                                size += len(chunk)
                        if checksum.hexdigest() != file["sha256"] or size != file["size_bytes"]:
                            raise ValueError("EXPORT_SOURCE_HASH_MISMATCH")
                        manifest["files"].append(
                            {
                                "paper_id": file["paper_id"],
                                "paper_file_id": file["id"],
                                "path": filename,
                                "sha256": checksum.hexdigest(),
                                "size_bytes": size,
                            }
                        )
                bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return archive, manifest


@celery_app.task(name="researchos.export_workspace")
@guard_resource(ExportJob)
def export_workspace(job_id):
    identifier = UUID(job_id)
    token = uuid4()
    now = datetime.now(UTC)
    with WorkerSession.begin() as db:
        job = db.execute(
            select(ExportJob).where(ExportJob.id == identifier).with_for_update()
        ).scalar_one_or_none()
        if (
            not job
            or job.status in {"succeeded", "failed", "expired"}
            or job.status == "running"
            and job.lease_expires_at > now
        ):
            return
        if job.attempts >= job.max_attempts:
            job.status, job.error_code = "failed", "ATTEMPTS_EXHAUSTED"
            return
        if job.status == "queued" and job.next_attempt_at > now:
            return
        job.status, job.attempt_token, job.lease_owner = "running", token, f"export-{identifier}"
        job.lease_expires_at, job.heartbeat_at = now + timedelta(minutes=15), now
        job.attempts += 1
    archive = runtime_namespace("export-tmp") / f"{identifier}-{token}.zip"
    key = None
    published = False
    stop = threading.Event()
    pulse = threading.Thread(target=heartbeat, args=(identifier, token, stop, ExportJob, 900), daemon=True)
    pulse.start()
    try:
        archive, manifest = create_archive(job, token)
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        key = f"exports/{job.workspace_id}/{identifier}-{token}.zip"
        with archive.open("rb") as stream:
            s3_client().upload_fileobj(stream, get_settings().s3_bucket, key)
        with WorkerSession.begin() as db:
            current = db.execute(
                select(ExportJob).where(ExportJob.id == identifier).with_for_update()
            ).scalar_one()
            if (
                current.status != "running"
                or current.attempt_token != token
                or current.lease_expires_at < datetime.now(UTC)
            ):
                return
            current.status, current.storage_key, current.manifest_hash = "succeeded", key, digest
            current.snapshot_at = datetime.fromisoformat(manifest["snapshot_at"])
            current.progress, current.finished_at = 100, datetime.now(UTC)
            current.expires_at = datetime.now(UTC) + timedelta(days=1)
            db.add(
                ActivityEvent(
                    id=uuid4(),
                    workspace_id=job.workspace_id,
                    actor_user_id=job.requested_by,
                    event_type="workspace_exported",
                    target_type="export_jobs",
                    target_id=job.id,
                    event_payload={"schema_version": 1, "include_files": job.include_files},
                )
            )
        published = True
    except Exception as error:
        with WorkerSession.begin() as db:
            current = db.execute(
                select(ExportJob).where(ExportJob.id == identifier).with_for_update()
            ).scalar_one()
            if current.status == "running" and current.attempt_token == token:
                current.error_code = (
                    str(error)
                    if isinstance(error, ValueError)
                    and str(error)
                    in {
                        "EXPORT_SOURCE_HASH_MISMATCH",
                        "EXPORT_SNAPSHOT_TIMEOUT",
                        "EXPORT_REQUIRED_FILE_UNAVAILABLE",
                    }
                    else "EXPORT_SOURCE_UNAVAILABLE"
                )
                if not isinstance(error, ValueError) and current.attempts < current.max_attempts:
                    current.status = "queued"
                    current.next_attempt_at = datetime.now(UTC) + timedelta(seconds=2**current.attempts)
                    db.add(
                        models.OutboxEvent(
                            id=uuid4(),
                            workspace_id=current.workspace_id,
                            event_type="export_workspace",
                            aggregate_id=current.id,
                            payload={"job_id": str(current.id)},
                            next_attempt_at=current.next_attempt_at,
                        )
                    )
                else:
                    current.status, current.finished_at = "failed", datetime.now(UTC)
    finally:
        stop.set()
        pulse.join(timeout=5)
        if archive:
            archive.unlink(missing_ok=True)
        if key and not published:
            try:
                remove_object(key)
            except Exception:
                pass
