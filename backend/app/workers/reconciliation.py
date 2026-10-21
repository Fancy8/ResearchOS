"""Aged orphan reconciliation inside owned namespaces, with durable page cursors."""

import heapq
import os
import re
import stat
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.core.config import ROOT
from app.core.resource_locks import exclusive_resource
from app.core.runtime_paths import runtime_namespace
from app.models import ExportJob, PaperFile, ProcessingJob, UploadSession

IDENTIFIER = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
FINAL = re.compile(rf"({IDENTIFIER})/({IDENTIFIER})(?:-(?:recovered-)?{IDENTIFIER})?\.pdf")
STAGING = re.compile(rf"({IDENTIFIER})\.pdf")
EXPORT = re.compile(rf"({IDENTIFIER})-{IDENTIFIER}\.zip")
TEMP = re.compile(rf"({IDENTIFIER})-{IDENTIFIER}\.(pdf|zip)")


def object_page(storage, bucket, prefix, cursor, versioned, limit):
    args = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": limit}
    if versioned:
        if cursor.get("key"):
            args["KeyMarker"] = cursor["key"]
            if cursor.get("version"):
                args["VersionIdMarker"] = cursor["version"]
        page = storage.list_object_versions(**args)
        rows = page.get("Versions", []) + page.get("DeleteMarkers", [])
        next_page = (
            {"key": page["NextKeyMarker"], "version": page.get("NextVersionIdMarker")}
            if page.get("IsTruncated")
            else {}
        )
    else:
        if cursor.get("after"):
            args["StartAfter"] = cursor["after"]
        page = storage.list_objects_v2(**args)
        rows = page.get("Contents", [])
        next_page = {"after": rows[-1]["Key"]} if page.get("IsTruncated") and rows else {}
    return rows, next_page


def protected_keys(db, workspace_id, kind, rows, now, cutoff):
    prefix = f"{kind}/{workspace_id}/"
    pattern = {"final": FINAL, "staging": STAGING, "exports": EXPORT}[kind]
    recognized = {
        row["Key"]: pattern.fullmatch(row["Key"][len(prefix) :])
        for row in rows
        if row["Key"].startswith(prefix)
    }
    recognized = {key: match for key, match in recognized.items() if match}
    keys = list(recognized)
    protected = set()
    if not keys:
        return recognized, protected
    if kind == "final":
        protected.update(
            db.scalars(
                select(PaperFile.storage_key).where(
                    PaperFile.workspace_id == workspace_id, PaperFile.storage_key.in_(keys)
                )
            )
        )
        files = {UUID(match[2]) for match in recognized.values()}
        active = set(
            db.scalars(
                select(ProcessingJob.paper_file_id).where(
                    ProcessingJob.workspace_id == workspace_id,
                    ProcessingJob.paper_file_id.in_(files),
                    ProcessingJob.status.in_(["queued", "running"]),
                )
            )
        )
        protected.update(key for key, match in recognized.items() if UUID(match[2]) in active)
    elif kind == "exports":
        jobs = {UUID(match[1]) for match in recognized.values()}
        for job in db.scalars(
            select(ExportJob).where(ExportJob.workspace_id == workspace_id, ExportJob.id.in_(jobs))
        ):
            if job.storage_key:
                protected.add(job.storage_key)
            if job.status in {"queued", "running"}:
                protected.update(key for key, match in recognized.items() if UUID(match[1]) == job.id)
    else:
        uploads = list(
            db.scalars(
                select(UploadSession).where(
                    UploadSession.workspace_id == workspace_id,
                    UploadSession.id.in_({UUID(match[1]) for match in recognized.values()}),
                )
            )
        )
        active = set(
            db.scalars(
                select(ProcessingJob.paper_file_id).where(
                    ProcessingJob.workspace_id == workspace_id,
                    ProcessingJob.paper_file_id.in_([item.paper_file_id for item in uploads]),
                    ProcessingJob.status.in_(["queued", "running"]),
                )
            )
        )
        for upload in uploads:
            if (
                upload.paper_file_id in active
                or (upload.lease_expires_at and upload.lease_expires_at > now)
                or (upload.status in {"pending", "validating"} and upload.expires_at > cutoff)
            ):
                protected.add(upload.staging_key)
            elif upload.status in {"pending", "validating"}:
                upload.status, upload.lease_token, upload.lease_expires_at = "failed", None, None
                file = db.get(PaperFile, upload.paper_file_id)
                if file and file.upload_status == "pending":
                    file.upload_status, file.parse_status, file.availability_status, file.is_current = (
                        "failed",
                        "failed",
                        "missing",
                        False,
                    )
    return recognized, protected


def reconcile_objects(db, workspace_id, storage, bucket, state, now, cutoff, limit):
    report = {"orphan_objects_removed": 0, "orphan_bytes_removed": 0, "unrecognized_objects": 0}
    versioned = storage.get_bucket_versioning(Bucket=bucket).get("Status") in {"Enabled", "Suspended"}
    for kind in ("final", "staging", "exports"):
        prefix = f"{kind}/{workspace_id}/"
        cursor = state.get(kind, {})
        if cursor.get("versioned") != versioned:
            cursor = {}
        rows, following = object_page(storage, bucket, prefix, cursor, versioned, limit)
        recognized, protected = protected_keys(db, workspace_id, kind, rows, now, cutoff)
        deleted_versions = set()
        for row in rows:
            key = row["Key"]
            if key not in recognized:
                report["unrecognized_objects"] += 1
                continue
            modified = row.get("LastModified")
            if key in protected or not modified or modified.tzinfo is None or modified >= cutoff:
                continue
            args = {"Bucket": bucket, "Key": key}
            if versioned:
                args["VersionId"] = row["VersionId"]
            storage.delete_object(**args)
            if versioned:
                deleted_versions.add((key, row["VersionId"]))
            report["orphan_objects_removed"] += 1
            report["orphan_bytes_removed"] += row.get("Size", 0)
        # A version marker must still exist when the next page is requested.
        # If this page removed its final marker, resume from the preceding stable
        # page boundary; already-deleted versions disappear, so the scan progresses.
        if versioned and (following.get("key"), following.get("version")) in deleted_versions:
            following = {key: cursor[key] for key in ("key", "version") if key in cursor}
        state[kind] = {**following, "versioned": versioned}
    return report


def temp_page(directory, after, limit, extension):
    if not directory.exists():
        return [], None
    # Namespace/entry links are never followed, including Windows reparse points.
    if directory.resolve() != directory.absolute() or not directory.resolve().is_relative_to(ROOT):
        raise RuntimeError("TEMP_NAMESPACE_SCOPE_INVALID")
    with os.scandir(directory) as entries:
        names = heapq.nsmallest(
            limit + 1,
            (
                entry.name
                for entry in entries
                if entry.name > after and entry.name.endswith(extension) and TEMP.fullmatch(entry.name)
            ),
        )
    return names[:limit], names[limit - 1] if len(names) > limit else None


def reconcile_temp(engine, Sessions, database, state, cutoff, limit):
    report = {
        "temporary_files_removed": 0,
        "temporary_bytes_removed": 0,
        "temporary_files_busy": 0,
        "temporary_files_blocked": 0,
    }
    for purpose, model, extension in (("pdf-tmp", ProcessingJob, ".pdf"), ("export-tmp", ExportJob, ".zip")):
        directory = runtime_namespace(purpose, database)
        names, following = temp_page(directory, state.get(purpose) or "", limit, extension)
        for name in names:
            identifier = UUID(TEMP.fullmatch(name)[1])
            with Sessions() as db:
                workspace = db.scalar(select(model.workspace_id).where(model.id == identifier))
            with exclusive_resource(engine, workspace or UUID(int=0), wait=False) as acquired:
                if not acquired:
                    report["temporary_files_busy"] += 1
                    continue
                with Sessions() as db:
                    job = db.get(model, identifier)
                    if job and (job.workspace_id != workspace or job.status in {"queued", "running"}):
                        report["temporary_files_busy"] += 1
                        continue
                path = directory / name
                try:
                    metadata = path.lstat()
                except FileNotFoundError:
                    continue
                if (
                    directory.resolve() != directory.absolute()
                    or not directory.resolve().is_relative_to(ROOT)
                    or not stat.S_ISREG(metadata.st_mode)
                    or path.is_symlink()
                    or getattr(metadata, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                    or path.resolve().parent != directory.resolve()
                ):
                    report["temporary_files_blocked"] += 1
                    continue
                if datetime.fromtimestamp(metadata.st_mtime, UTC) >= cutoff:
                    continue
                path.unlink()
                report["temporary_files_removed"] += 1
                report["temporary_bytes_removed"] += metadata.st_size
        state[purpose] = following
    return report
