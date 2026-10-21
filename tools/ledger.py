"""Review/migrate a legacy deletion inventory and inspect the independent authority."""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import models
from app.recovery.journal import (
    activate_source,
    activation_for,
    append_document,
    checked_document,
    current_checkpoint,
    encoded,
    frozen_journal,
    initialize_source,
    origin_database,
)
from app.workers.deletions import cleanup_engine, ledger_directory, ledger_document


def inventory(database):
    if database != origin_database():
        raise ValueError("LEDGER_MIGRATION_SOURCE_MISMATCH")
    documents, files = {}, []
    for path in sorted(ledger_directory(database).glob("*.json")):
        document = checked_document(
            json.loads(path.read_text(encoding="utf-8")), database
        )
        if path.stem != document["job_id"]:
            raise ValueError("LEDGER_LEGACY_FILENAME_MISMATCH")
        documents[document["job_id"]] = document
        files.append(
            {
                "filename": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    with sessionmaker(cleanup_engine())() as db:
        jobs = list(
            db.scalars(
                select(models.DeletionJob).order_by(
                    models.DeletionJob.requested_at, models.DeletionJob.id
                )
            )
        )
        count = len(jobs)
        receipts = [
            {
                "job_id": str(job.id),
                "scope": job.scope,
                "status": job.status,
                "has_individual_record": str(job.id) in documents,
            }
            for job in jobs
        ]
        for job in jobs:
            if job.status == "succeeded":
                continue
            space = db.get(models.Workspace, job.workspace_id)
            if not space:
                raise ValueError("LEDGER_INVALID_PENDING_JOB")
            document = ledger_document(job, space.id, space.owner_user_id, database)
            if str(job.id) in documents and documents[str(job.id)] != document:
                raise ValueError("LEDGER_LEGACY_JOB_MISMATCH")
            documents[str(job.id)] = document
    result = {
        "database": database,
        "files": files,
        "business_receipts": count,
        "receipts": receipts,
        "documents": sorted(
            documents.values(), key=lambda x: (x["requested_at"], x["job_id"])
        ),
    }
    return result, hashlib.sha256(encoded(result)).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("inventory", "init-empty", "migrate-legacy", "status")
    )
    parser.add_argument("--inventory-sha256")
    parser.add_argument("--maintenance-ack", action="store_true")
    parser.add_argument("--deny-pre-migration-backups", action="store_true")
    args = parser.parse_args()
    database = origin_database()
    if args.command == "status":
        with frozen_journal(database) as journal:
            activation = activation_for(journal.db, journal.source)
            print(
                json.dumps(
                    {
                        "checkpoint": journal.head,
                        "restore_not_before": activation["not_before"],
                        "reviewed_requests": activation["reviewed_sequence"],
                    }
                )
            )
        return
    value, digest = inventory(database)
    summary = {
        "inventory_sha256": digest,
        "legacy_files": len(value["files"]),
        "requests": len(value["documents"]),
        "business_receipts": value["business_receipts"],
    }
    if args.command == "inventory":
        report = ROOT / f"artifacts/ledger-inventory-{database}-{digest}.json"
        if report.exists():
            if (
                hashlib.sha256(
                    encoded(json.loads(report.read_text(encoding="utf-8")))
                ).hexdigest()
                != digest
            ):
                raise ValueError("LEDGER_SAVED_INVENTORY_CHANGED")
        else:
            with report.open("x", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True, indent=2)
        print(json.dumps({**summary, "report": str(report.relative_to(ROOT))}))
        return
    if not args.maintenance_ack:
        parser.error("Stop source writers/workers and supply --maintenance-ack")
    if args.command == "init-empty" and (
        value["documents"] or value["business_receipts"]
    ):
        raise ValueError("LEDGER_LEGACY_INVENTORY_REVIEW_REQUIRED")
    if args.command == "migrate-legacy" and args.inventory_sha256 != digest:
        raise ValueError("LEDGER_REVIEWED_INVENTORY_DIGEST_REQUIRED")
    gaps = [row for row in value["receipts"] if not row["has_individual_record"]]
    if gaps and not args.deny_pre_migration_backups:
        raise ValueError("LEDGER_LEGACY_GAPS_REQUIRE_RECOVERY_FLOOR")
    initialize_source(database)
    if args.command == "init-empty":
        from app.recovery.journal import connection, source_identity

        with connection() as db:
            head = db.execute(
                "SELECT sequence FROM public.ledger_heads WHERE source_id=%s",
                (source_identity(database),),
            ).fetchone()
            if head["sequence"] != 0:
                raise ValueError("LEDGER_EMPTY_INITIALIZATION_HAS_HISTORY")
    for document in value["documents"]:
        append_document(document)
    activate_source(database, not_before=datetime.now(UTC) if gaps else None)
    print(json.dumps({**summary, "checkpoint": current_checkpoint(database)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 -- operator boundary must redact every driver failure
        # Never echo driver parameters or connection URLs.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_class": type(error).__name__,
                    "code": str(error)
                    if isinstance(error, ValueError)
                    else "LEDGER_OPERATOR_FAILED",
                }
            )
        )
        raise SystemExit(1) from None
