import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import ZipFile

from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.sql.sqltypes import Date, DateTime

from app import models
from app.core.config import ROOT
from app.core.security import hasher

ORDER = [
    "users",
    "workspaces",
    "research_profiles",
    "projects",
    "research_threads",
    "papers",
    "paper_files",
    "paper_pages",
    "project_papers",
    "thread_papers",
    "evidence",
    "notes",
    "project_notes",
    "thread_notes",
    "note_papers",
    "note_evidence_links",
    "hypotheses",
    "hypothesis_evidence_links",
    "hypothesis_revisions",
    "thread_revisions",
    "research_decisions",
    "decision_revisions",
    "decision_revision_evidence_links",
    "decision_revision_hypothesis_links",
    "decision_revision_note_links",
    "tasks",
    "activity_events",
]


def archive_document(path):
    with ZipFile(path) as bundle:
        if len(bundle.namelist()) != len(set(bundle.namelist())):
            raise ValueError("DUPLICATE_ARCHIVE_ENTRY")
        manifest = json.loads(bundle.read("manifest.json"))
        if manifest.get("schema_version") != 1 or set(manifest.get("entities", {})) != set(ORDER):
            raise ValueError("UNSUPPORTED_ARCHIVE_SCHEMA")
        if sum(info.file_size for info in bundle.infolist()) > 8 * 1024**3:
            raise ValueError("ARCHIVE_TOO_LARGE")
        tables = {name: json.loads(bundle.read(f"data/{name}.json")) for name in ORDER}
        if len(tables["users"]) != 1 or len(tables["workspaces"]) != 1:
            raise ValueError("ARCHIVE_MUST_CONTAIN_ONE_PRIVATE_SPACE")
        workspace = tables["workspaces"][0]
        if (
            workspace["id"] != manifest["workspace_id"]
            or workspace["owner_user_id"] != tables["users"][0]["id"]
        ):
            raise ValueError("ARCHIVE_IDENTITY_MISMATCH")
        for name, rows in tables.items():
            if len(rows) != manifest["entities"][name]:
                raise ValueError("ARCHIVE_COUNT_MISMATCH")
            table = models.Base.metadata.tables[name]
            for row in rows:
                if set(row) - set(table.c.keys()):
                    raise ValueError("UNEXPECTED_ARCHIVE_COLUMNS")
                if "workspace_id" in row and row["workspace_id"] != workspace["id"]:
                    raise ValueError("ARCHIVE_SPACE_MISMATCH")
        if "password_hash" in tables["users"][0]:
            raise ValueError("ARCHIVE_CONTAINS_AUTHENTICATION_DATA")
        files = {row["id"]: row for row in tables["paper_files"]}
        originals = set()
        for item in manifest["files"]:
            identifier = str(UUID(item["paper_file_id"]))
            file = files[identifier]
            expected = f"files/{UUID(file['paper_id'])}/{identifier}.pdf"
            if item["path"] != expected or identifier in originals:
                raise ValueError("ARCHIVE_FILE_PATH_MISMATCH")
            if item["sha256"] != file["sha256"] or item["size_bytes"] != file["size_bytes"]:
                raise ValueError("ARCHIVE_FILE_METADATA_MISMATCH")
            digest, size = hashlib.sha256(), 0
            with bundle.open(expected) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            if digest.hexdigest() != file["sha256"] or size != file["size_bytes"]:
                raise ValueError("ARCHIVE_FILE_HASH_MISMATCH")
            originals.add(identifier)
        removed = {row["paper_file_id"] for row in manifest.get("missing_files", [])}
        if manifest["include_files"]:
            retained = {row["id"] for row in files.values() if row["upload_status"] == "uploaded"}
            if retained != originals | removed:
                raise ValueError("ARCHIVE_ORIGINAL_SET_MISMATCH")
        return manifest, tables


def typed_row(table, value):
    result = {}
    for column in table.c:
        if column.name not in value:
            continue
        item = value[column.name]
        if item is not None:
            if isinstance(column.type, DateTime):
                item = datetime.fromisoformat(item)
                if item.tzinfo is None:
                    raise ValueError("ARCHIVE_TIMESTAMP_MUST_HAVE_TIMEZONE")
            elif isinstance(column.type, Date):
                item = date.fromisoformat(item)
            elif column.type.__class__.__name__ in {"UUID", "Uuid"}:
                item = UUID(item)
        result[column.name] = item
    return result


def reconstruct_archive(path, target_url, storage, target_bucket, initial_password):
    """Restore exported business objects into an empty, already-migrated database."""
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("RECOVERY_INPUT_MUST_BE_PROJECT_LOCAL")
    manifest, tables = archive_document(path)
    engine = create_engine(target_url, hide_parameters=True)
    copied = []
    run_id = uuid4()
    try:
        with engine.begin() as db:
            if db.execute(select(func.count()).select_from(models.User)).scalar_one():
                raise ValueError("RECOVERY_TARGET_NOT_EMPTY")
            if storage.list_objects_v2(Bucket=target_bucket, MaxKeys=1).get("Contents"):
                raise ValueError("RECOVERY_BUCKET_NOT_EMPTY")
            db.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            available = {item["paper_file_id"]: item for item in manifest["files"]}
            with ZipFile(path) as bundle:
                for file in tables["paper_files"]:
                    file["storage_key"] = (
                        f"final/{manifest['workspace_id']}/{file['paper_id']}/{file['id']}-recovered-{run_id}.pdf"
                    )
                    file["storage_version_id"] = None
                    if file["id"] in available:
                        with bundle.open(available[file["id"]]["path"]) as stream:
                            storage.upload_fileobj(stream, target_bucket, file["storage_key"])
                        copied.append(file["storage_key"])
                        digest = hashlib.sha256()
                        response = storage.get_object(Bucket=target_bucket, Key=file["storage_key"])
                        with response["Body"] as stream:
                            while chunk := stream.read(1024 * 1024):
                                digest.update(chunk)
                        if digest.hexdigest() != file["sha256"]:
                            raise ValueError("RECOVERY_STORAGE_HASH_MISMATCH")
                    else:
                        file["availability_status"], file["is_current"] = "missing", False
                        if file["upload_status"] != "uploaded":
                            file["upload_status"], file["parse_status"] = "failed", "failed"
                tables["users"][0]["password_hash"] = hasher.hash(initial_password)
                for name in ORDER:
                    table = models.Base.metadata.tables[name]
                    values = [typed_row(table, row) for row in tables[name]]
                    if values:
                        db.execute(insert(table), values)
        return {
            "workspace_id": manifest["workspace_id"],
            "entity_tables": len(tables),
            "objects_restored": len(copied),
            "credentials_imported": False,
        }
    except Exception:
        for key in copied:
            storage.delete_object(Bucket=target_bucket, Key=key)
        raise
    finally:
        engine.dispose()
