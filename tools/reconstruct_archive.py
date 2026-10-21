"""Operator-only reconstruction of a private P0 archive into empty isolated targets."""
import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import get_settings  # noqa: E402
from app.core.storage import s3_client  # noqa: E402
from app.recovery.archive import reconstruct_archive  # noqa: E402
from sqlalchemy import make_url  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--target-bucket", required=True)
    parser.add_argument("--isolated-target-ack", action="store_true")
    args = parser.parse_args()
    target_url = os.environ.get("RESEARCHOS_RECOVERY_DATABASE_URL")
    if not target_url or not args.isolated_target_ack:
        parser.error("Configure a migrated empty RESEARCHOS_RECOVERY_DATABASE_URL and acknowledge isolated targets")
    settings = get_settings()
    if make_url(target_url).database == make_url(settings.database_url).database or args.target_bucket == settings.s3_bucket:
        parser.error("Recovery cannot target the running database or source bucket")
    password = getpass.getpass("New login password for the reconstructed account (minimum 12 characters): ")
    if len(password) < 12:
        parser.error("A new password of at least 12 characters is required; original credentials are never imported")
    result = reconstruct_archive(args.archive, target_url, s3_client(), args.target_bucket, password)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
