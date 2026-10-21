"""Daily read-only backups and policy-controlled retention in a separate process."""

import argparse
import base64
import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import make_url

from app.core.config import ROOT, get_settings
from app.core.storage import s3_client
from app.recovery.backup import db_connect, make_backup
from app.recovery.catalog import BackupCatalog, checksum


def load_key():
    encoded = os.environ.get("RESEARCHOS_BACKUP_KEY")
    local = ROOT / "runtime/backup-key.json"
    if not encoded and get_settings().environment != "production" and local.exists():
        encoded = json.loads(local.read_text(encoding="utf-8"))["key"]
    if not encoded:
        raise ValueError("BACKUP_KEY_NOT_CONFIGURED")
    try:
        key = base64.b64decode(encoded, altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise ValueError("BACKUP_KEY_INVALID") from None
    if len(key) != 32:
        raise ValueError("BACKUP_KEY_INVALID")
    return key


def daily_slot(now, hour):
    if now.tzinfo is None or not 0 <= hour <= 23:
        raise ValueError("BACKUP_SCHEDULE_INVALID")
    now = now.astimezone(UTC)
    slot = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return slot if slot <= now else slot - timedelta(days=1)


def configured_source():
    settings = get_settings()
    if not settings.backup_database_url:
        raise ValueError("BACKUP_READER_NOT_CONFIGURED")
    source, app = make_url(settings.backup_database_url), make_url(settings.database_url)
    if (
        source.username != "researchos_backup"
        or source.drivername != "postgresql+psycopg"
        or (source.host, source.port or 5432, source.database) != (app.host, app.port or 5432, app.database)
    ):
        raise ValueError("BACKUP_READER_SOURCE_MISMATCH")
    return settings.backup_database_url


def expire_backups(catalog, records, days, now, approved=False, apply=False):
    if not days or not 1 <= days <= 3650 or not approved:
        return {"retention": "not_configured", "eligible": 0, "expired": 0}
    cutoff = now - timedelta(days=days)
    eligible = [
        row
        for row in records
        if row["status"] in {"succeeded", "expiring", "failed"}
        and datetime.fromisoformat(row.get("snapshot_at") or row["started_at"]) <= cutoff
    ]
    result = {"retention": "applied" if apply else "preview", "eligible": len(eligible), "expired": 0}
    for row in eligible:
        path = catalog.file(row["id"])
        if path.exists() and (not path.is_file() or (row.get("sha256") and checksum(path) != row["sha256"])):
            raise ValueError("BACKUP_RETENTION_HASH_MISMATCH")
        if not apply:
            continue
        row["status"] = "expiring"
        catalog.write(row)  # Durable intent permits retry after unlink/record interruption.
        path.unlink(missing_ok=True)
        row["status"], row["expired_at"] = "expired", now.isoformat()
        catalog.write(row)
        result["expired"] += 1
    remaining = sum(row["status"] == "succeeded" for row in records)
    result["backup_window_empty"] = remaining == 0
    result["unregistered_files"] = catalog.unregistered(records)
    return result


def run_once(
    source_url,
    storage,
    bucket,
    key,
    *,
    catalog=None,
    now=None,
    hour=19,
    force=False,
    retention_days=None,
    retention_approved=False,
):
    now = now or datetime.now(UTC)
    slot = daily_slot(now, hour).isoformat()
    if len(key) != 32:
        raise ValueError("BACKUP_KEY_INVALID")
    catalog = catalog or BackupCatalog(
        source_url, bucket, get_settings().control_secret, get_settings().backup_catalog_directory
    )
    if catalog.context != BackupCatalog.source_context(source_url, bucket):
        raise ValueError("BACKUP_CATALOG_SOURCE_MISMATCH")
    with db_connect(source_url, autocommit=True) as guard:
        if guard.execute("SELECT current_user").fetchone()[0] != "researchos_backup":
            raise ValueError("SCHEDULE_REQUIRES_BACKUP_READER")
        if not guard.execute(
            "SELECT pg_try_advisory_lock(hashtextextended('scheduled-backup',0))"
        ).fetchone()[0]:
            return {"status": "already_running"}
        try:
            records = catalog.records()
            for row in records:
                if (
                    row["status"] == "running"
                    or row.get("error_code") == "BACKUP_INTERRUPTED_CLEANUP_PENDING"
                ):
                    row["status"], row["error_code"], row["finished_at"] = (
                        "failed",
                        "BACKUP_INTERRUPTED",
                        now.isoformat(),
                    )
                    row["retry_at"] = (now + timedelta(minutes=1)).isoformat()
                    try:
                        catalog.cleanup_work(row["id"])
                    except Exception:
                        row["error_code"] = "BACKUP_INTERRUPTED_CLEANUP_PENDING"
                    catalog.write(row)
            successes = [
                row
                for row in records
                if row["status"] == "succeeded"
                and row["slot"] == slot
                and catalog.file(row["id"]).is_file()
                and catalog.file(row["id"]).stat().st_size == row["size_bytes"]
            ]
            failures = [row for row in records if row["status"] == "failed" and row["slot"] == slot]
            due = not successes and not any(datetime.fromisoformat(row["retry_at"]) > now for row in failures)
            result = {"status": "not_due", "slot": slot}
            if force or due:
                identifier = str(uuid4())
                row = {
                    "id": identifier,
                    "slot": slot,
                    "started_at": now.isoformat(),
                    "status": "running",
                    "key_id": hashlib.sha256(key).hexdigest(),
                    "trigger": "manual" if force else "scheduled",
                }
                catalog.write(row)
                try:
                    work = catalog.workspace(identifier)
                    work.mkdir(parents=True)
                    report = make_backup(
                        source_url,
                        storage,
                        bucket,
                        catalog.file(identifier, ".part"),
                        key,
                        temporary_parent=work,
                    )
                    partial, complete = catalog.file(identifier, ".part"), catalog.file(identifier)
                    if datetime.fromisoformat(report["snapshot_at"]) < datetime.fromisoformat(slot):
                        raise ValueError("BACKUP_SNAPSHOT_CLOCK_BEFORE_SLOT")
                    digest, size = checksum(partial), partial.stat().st_size
                    if complete.exists():
                        raise ValueError("BACKUP_FINAL_ALREADY_EXISTS")
                    partial.rename(complete)
                    catalog.cleanup_work(identifier)
                    row.update(
                        status="succeeded",
                        finished_at=datetime.now(UTC).isoformat(),
                        snapshot_at=report["snapshot_at"],
                        sha256=digest,
                        size_bytes=size,
                        report=report,
                    )
                    catalog.write(row)
                    result = {
                        "status": "succeeded",
                        "id": identifier,
                        "slot": slot,
                        "file": str(complete.relative_to(ROOT)),
                        "snapshot_at": report["snapshot_at"],
                    }
                except Exception:
                    row.update(
                        status="failed",
                        error_code="BACKUP_FAILED",
                        finished_at=now.isoformat(),
                        retry_at=(
                            now + timedelta(seconds=min(3600, 60 * 2 ** min(len(failures), 6)))
                        ).isoformat(),
                    )
                    try:
                        catalog.cleanup_work(identifier)
                    except Exception:
                        row["error_code"] = "BACKUP_INTERRUPTED_CLEANUP_PENDING"
                    catalog.write(row)
                    result = {
                        "status": "failed",
                        "id": identifier,
                        "error_code": row["error_code"],
                        "retry_at": row["retry_at"],
                    }
                records.append(row)
            try:
                result["retention"] = expire_backups(
                    catalog, records, retention_days, now, retention_approved, apply=True
                )
            except Exception:
                result["retention"] = {"retention": "failed", "error_code": "RETENTION_VERIFICATION_FAILED"}
            return result
        finally:
            guard.execute("SELECT pg_advisory_unlock(hashtextextended('scheduled-backup',0))")


def main(once=False):
    settings = get_settings()
    if not settings.backup_schedule_enabled:
        print(json.dumps({"event": "backup_scheduler", "status": "disabled"}), flush=True)
        return
    while True:
        try:
            report = run_once(
                configured_source(),
                s3_client(),
                settings.s3_bucket,
                load_key(),
                hour=settings.backup_daily_hour_utc,
                retention_days=settings.backup_retention_days,
                retention_approved=settings.backup_retention_approved,
            )
            print(json.dumps({"event": "backup_scheduler", **report}), flush=True)
        except Exception:
            print(
                json.dumps(
                    {
                        "event": "backup_scheduler",
                        "status": "failed",
                        "error_code": "BACKUP_OPERATOR_UNAVAILABLE",
                    }
                ),
                flush=True,
            )
            if once:
                raise SystemExit(1) from None
        if once:
            failed = report["status"] == "failed" or report.get("retention", {}).get("retention") == "failed"
            raise SystemExit(1 if failed else 0)
        time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        main(args.once)
    except Exception:
        print(
            json.dumps(
                {
                    "event": "backup_scheduler",
                    "status": "failed",
                    "error_code": "BACKUP_CONFIGURATION_INVALID",
                }
            ),
            flush=True,
        )
        raise SystemExit(1) from None
