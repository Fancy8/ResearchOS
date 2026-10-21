"""Restore gate: apply the independent ledger before exposing a restored database."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.workers.deletions import cleanup_engine, ledger_directory, replay_ledger  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-database", required=True, help="Database name recorded by the original deployment")
    parser.add_argument("--maintenance-ack", action="store_true", help="Confirm that application/worker access to this restored database is stopped")
    args = parser.parse_args()
    if not args.maintenance_ack:
        parser.error("Stop application/worker access, then supply --maintenance-ack")
    if not get_settings().cleanup_database_url:
        parser.error("Configure dedicated RESEARCHOS_CLEANUP_DATABASE_URL for the restored database")
    actions = replay_ledger(cleanup_engine(), ledger_directory(args.source_database), args.source_database)
    print(f"Deletion ledger replay completed: {actions} restored objects removed. Validate the remaining archive before reopening access.")


if __name__ == "__main__":
    main()
