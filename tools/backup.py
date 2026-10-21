"""Local operator CLI for encrypted backups and fresh isolated restoration."""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.storage import s3_client
from app.recovery.backup import (
    db_connect,
    restore_backup,
)
from app.recovery.catalog import BackupCatalog
from app.recovery.scheduler import configured_source, expire_backups, load_key, run_once


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-key")
    commands.add_parser("create")
    commands.add_parser("schedule-once")
    status = commands.add_parser("status")
    status.add_argument("--verify", action="store_true")
    commands.add_parser("enabled")
    commands.add_parser("check")
    prune = commands.add_parser("prune")
    prune.add_argument("--days", type=int)
    prune.add_argument("--apply", action="store_true")
    restore = commands.add_parser("restore")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--target-bucket", required=True)
    restore.add_argument("--maintenance-ack", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if args.command == "enabled":
        print(int(settings.backup_schedule_enabled))
        return
    if args.command == "check":
        configured_source()
        load_key()
        print("Backup reader/key inputs configured")
        return
    key_file = ROOT / "runtime/backup-key.json"
    if args.command == "init-key":
        if settings.environment == "production":
            parser.error(
                "Production backup keys must be supplied by the deployment secret store"
            )
        with key_file.open("x", encoding="utf-8") as stream:
            json.dump(
                {
                    "format_version": 1,
                    "key": base64.urlsafe_b64encode(os.urandom(32)).decode(),
                },
                stream,
            )
        print(
            "Local backup key created in gitignored runtime. Escrow this key separately; it is not included in backups."
        )
        return
    if args.command in {"create", "schedule-once", "status", "prune"}:
        source = configured_source()
        catalog = BackupCatalog(
            source,
            settings.s3_bucket,
            settings.control_secret,
            settings.backup_catalog_directory,
        )
        records = catalog.records()
        if args.command == "status":
            print(
                json.dumps(
                    {
                        "schedule_enabled": settings.backup_schedule_enabled,
                        "runs": [
                            {
                                key: row.get(key)
                                for key in (
                                    "id",
                                    "status",
                                    "slot",
                                    "snapshot_at",
                                    "error_code",
                                    "key_id",
                                )
                            }
                            for row in records
                        ],
                        **catalog.inspect(records, args.verify),
                    }
                )
            )
            return
        if args.command == "prune":
            days = args.days or settings.backup_retention_days
            if not days or not 1 <= days <= 3650:
                parser.error("Specify a retention interval of 1-3650 days")
            if args.apply and (
                not settings.backup_retention_approved
                or days != settings.backup_retention_days
            ):
                parser.error(
                    "Apply requires matching approved backup retention configuration"
                )
            with db_connect(settings.backup_database_url, autocommit=True) as db:
                if not db.execute(
                    "SELECT pg_try_advisory_lock(hashtextextended('scheduled-backup',0))"
                ).fetchone()[0]:
                    parser.error(
                        "Another backup operator is running; no retention change was applied"
                    )
                print(
                    json.dumps(
                        expire_backups(
                            catalog,
                            catalog.records(),
                            days,
                            datetime.now(UTC),
                            True,
                            args.apply,
                        )
                    )
                )
            return
        result = run_once(
            settings.backup_database_url,
            s3_client(),
            settings.s3_bucket,
            load_key(),
            catalog=catalog,
            hour=settings.backup_daily_hour_utc,
            force=args.command == "create",
            retention_days=settings.backup_retention_days,
            retention_approved=settings.backup_retention_approved,
        )
        print(json.dumps(result))
        if (
            result["status"] == "failed"
            or result.get("retention", {}).get("retention") == "failed"
        ):
            raise SystemExit(1)
    else:
        target = os.environ.get("RESEARCHOS_RECOVERY_DATABASE_URL")
        cleanup = os.environ.get("RESEARCHOS_RECOVERY_CLEANUP_URL")
        if not target or not cleanup:
            parser.error(
                "Configure isolated RESEARCHOS_RECOVERY_DATABASE_URL and RESEARCHOS_RECOVERY_CLEANUP_URL"
            )
        result = restore_backup(
            args.backup,
            target,
            cleanup,
            s3_client(),
            args.target_bucket,
            load_key(),
            args.maintenance_ack,
        )
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - sanitize secret-bearing infrastructure exceptions
        print(
            f"Backup/recovery operation failed ({type(error).__name__}); no complete result is claimed.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
