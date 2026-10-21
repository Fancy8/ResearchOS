import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import make_url
from test_papers_evidence import evidence, pdf_bytes, upload
from test_workflow import create, workflow

from app.core.config import ROOT, get_settings
from app.recovery.backup import db_connect, restore_backup
from app.recovery.catalog import BackupCatalog
from app.recovery.scheduler import configured_source, daily_slot, expire_backups, load_key, run_once


@pytest.fixture
def backup_operator(tmp_path):
    settings = get_settings()
    source = configured_source()
    return (
        source,
        BackupCatalog(source, settings.s3_bucket, settings.control_secret, tmp_path / "catalog"),
        os.urandom(32),
    )


def test_backup_reader_cannot_mutate_or_own_domain_data(backup_operator):
    source, _, _ = backup_operator
    with db_connect(source, autocommit=True) as db:
        assert db.execute("SELECT current_user").fetchone()[0] == "researchos_backup"
        assert db.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        assert db.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone() == (False, False, False, False)
        db.execute("SET default_transaction_read_only=off")
        for statement in (
            "UPDATE users SET display_name='blocked'",
            "DELETE FROM decision_revisions",
            "ALTER TABLE papers ADD COLUMN forbidden TEXT",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)


@pytest.mark.parametrize("recovery_target", [False], indirect=True)
def test_daily_backup_is_restart_safe_and_restores_real_originals(
    backup_operator, account_factory, object_store, recovery_target
):
    source, catalog, key = backup_operator
    client, _ = account_factory()
    project, line, _, _, body, decision = workflow(client)
    task = create(
        client,
        "/api/v1/tasks",
        {
            "title": "Original task",
            "project_id": project["id"],
            "thread_id": line["id"],
            "decision_id": decision["id"],
        },
    )
    first = upload(client, pdf_bytes())
    original = evidence(client, line, first)
    upload(client, pdf_bytes(text="New version"), first["paper_id"])
    create(
        client,
        f"/api/v1/decisions/{decision['id']}/revisions",
        {**body, "expected_revision": 1, "evidence_ids": [original["id"]]},
    )
    result = run_once(source, object_store, get_settings().s3_bucket, key, catalog=catalog, hour=0)
    assert result["status"] == "succeeded"
    restarted = BackupCatalog(source, get_settings().s3_bucket, get_settings().control_secret, catalog.root)
    assert (
        run_once(source, object_store, get_settings().s3_bucket, key, catalog=restarted, hour=0)["status"]
        == "not_due"
    )
    assert len(catalog.records()) == 1 and not list((catalog.root / "work").iterdir())
    restored = restore_backup(
        catalog.file(result["id"]),
        recovery_target["admin"],
        recovery_target["cleanup"],
        object_store,
        recovery_target["bucket"],
        key,
        True,
    )
    assert restored["objects_restored"] == 2
    with db_connect(recovery_target["admin"]) as db:
        assert (
            db.execute("SELECT source_revision_no FROM tasks WHERE id=%s", (task["id"],)).fetchone()[0] == 1
        )
        assert (
            db.execute(
                "SELECT current_revision FROM research_decisions WHERE id=%s", (decision["id"],)
            ).fetchone()[0]
            == 2
        )
        for storage_key, digest in db.execute("SELECT storage_key,sha256 FROM paper_files"):
            response = object_store.get_object(Bucket=recovery_target["bucket"], Key=storage_key)
            with response["Body"] as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == digest
    (ROOT / "artifacts/daily-backup-proof.json").write_text(
        json.dumps({"created": result, "restored": restored, "same_slot_repeated": False}, indent=2)
    )


def test_failed_backup_retries_without_publishing_plaintext_or_success(
    backup_operator, account_factory, object_store, monkeypatch
):
    source, catalog, key = backup_operator
    client, _ = account_factory()
    upload(client, pdf_bytes())
    from app.recovery import scheduler

    actual = scheduler.make_backup

    def failed(*args, **kwargs):
        (kwargs["temporary_parent"] / "private.dump").write_bytes(b"private research bytes")
        raise RuntimeError("private exception must not be logged")

    monkeypatch.setattr(scheduler, "make_backup", failed)
    first = run_once(source, object_store, get_settings().s3_bucket, key, catalog=catalog, hour=0)
    assert first["status"] == "failed" and first["error_code"] == "BACKUP_FAILED"
    assert not catalog.workspace(first["id"]).exists() and not catalog.file(first["id"]).exists()
    assert (
        run_once(source, object_store, get_settings().s3_bucket, key, catalog=catalog, hour=0)["status"]
        == "not_due"
    )
    monkeypatch.setattr(scheduler, "make_backup", actual)
    retried = run_once(
        source,
        object_store,
        get_settings().s3_bucket,
        key,
        catalog=catalog,
        hour=0,
        now=datetime.now(UTC) + timedelta(seconds=65),
    )
    assert retried["status"] == "succeeded"


def test_live_database_lock_prevents_false_crash_recovery(backup_operator, object_store):
    source, catalog, key = backup_operator
    now, identifier = datetime.now(UTC), str(uuid4())
    catalog.write(
        {
            "id": identifier,
            "status": "running",
            "slot": daily_slot(now, 0).isoformat(),
            "started_at": now.isoformat(),
            "key_id": hashlib.sha256(key).hexdigest(),
        }
    )
    workspace = catalog.workspace(identifier)
    workspace.mkdir()
    (workspace / "unfinished.dump").write_bytes(b"unfinished")
    catalog.file(identifier, ".part").write_bytes(b"partial")
    with db_connect(source, autocommit=True) as live:
        live.execute("SELECT pg_advisory_lock(hashtextextended('scheduled-backup',0))")
        assert (
            run_once(source, object_store, get_settings().s3_bucket, key, catalog=catalog, hour=0)["status"]
            == "already_running"
        )
        assert workspace.exists() and catalog.records()[0]["status"] == "running"
    result = run_once(source, object_store, get_settings().s3_bucket, key, catalog=catalog, hour=0)
    assert result["status"] == "not_due" and not workspace.exists()
    assert (
        not catalog.file(identifier, ".part").exists()
        and catalog.records()[0]["error_code"] == "BACKUP_INTERRUPTED"
    )


def test_retention_preview_approval_integrity_and_actual_expiry(backup_operator, object_store):
    source, catalog, key = backup_operator
    result = run_once(
        source, object_store, get_settings().s3_bucket, key, catalog=catalog, force=True, hour=0
    )
    row, now = catalog.records()[0], datetime.now(UTC)
    row["snapshot_at"] = (now - timedelta(days=3)).isoformat()
    catalog.write(row)
    assert expire_backups(catalog, catalog.records(), 1, now, False, True)["expired"] == 0
    assert expire_backups(catalog, catalog.records(), 1, now, True, False)["eligible"] == 1
    path = catalog.file(result["id"])
    contents = path.read_bytes()
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="RETENTION_HASH_MISMATCH"):
        expire_backups(catalog, catalog.records(), 1, now, True, True)
    path.write_bytes(contents)
    expired = expire_backups(catalog, catalog.records(), 1, now, True, True)
    assert expired["expired"] == 1 and expired["backup_window_empty"]
    assert not path.exists() and catalog.records()[0]["status"] == "expired"
    assert expire_backups(catalog, catalog.records(), 1, now, True, True)["expired"] == 0


def test_catalog_rejects_signature_context_and_path_tampering(backup_operator):
    source, catalog, _ = backup_operator
    identifier = str(uuid4())
    catalog.write({"id": identifier, "status": "running"})
    path = catalog.root / "records" / f"{identifier}.json"
    original = path.read_text()
    changed = json.loads(original)
    changed["status"] = "succeeded"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="CATALOG_INTEGRITY"):
        catalog.records()
    path.write_text(original)
    foreign = BackupCatalog(source, "another-bucket", get_settings().control_secret, catalog.root)
    with pytest.raises(ValueError, match="CATALOG_INTEGRITY"):
        foreign.records()
    with pytest.raises(ValueError, match="CATALOG_PATH"):
        BackupCatalog(source, "unused", "unused", ROOT.parent)


def test_utc_schedule_boundary_and_key_validation(monkeypatch):
    before = datetime(2026, 10, 14, 2, 59, tzinfo=timezone(timedelta(hours=8)))
    assert daily_slot(before, 19) == datetime(2026, 10, 12, 19, tzinfo=UTC)
    assert daily_slot(before + timedelta(minutes=1), 19) == datetime(2026, 10, 13, 19, tzinfo=UTC)
    raw = os.urandom(32)
    monkeypatch.setenv("RESEARCHOS_BACKUP_KEY", base64.urlsafe_b64encode(raw).decode())
    assert load_key() == raw
    monkeypatch.setenv("RESEARCHOS_BACKUP_KEY", "malformed-key")
    with pytest.raises(ValueError, match="KEY_INVALID"):
        load_key()
    settings = get_settings()
    monkeypatch.setattr(
        settings, "backup_database_url", str(make_url(settings.backup_database_url).set(database="foreign"))
    )
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        configured_source()


def test_missed_daily_slot_catches_up_with_current_key_and_retains_old_key_id(backup_operator, object_store):
    source, catalog, key = backup_operator
    now = datetime.now(UTC)
    initial = run_once(source, object_store, get_settings().s3_bucket, key, catalog=catalog, hour=0)
    row = catalog.records()[0]
    row["slot"] = (daily_slot(now, 0) - timedelta(days=2)).isoformat()
    row["snapshot_at"] = (now - timedelta(days=2)).isoformat()
    catalog.write(row)
    new_key = os.urandom(32)
    caught_up = run_once(source, object_store, get_settings().s3_bucket, new_key, catalog=catalog, hour=0)
    assert caught_up["status"] == "succeeded" and caught_up["id"] != initial["id"]
    assert {item["key_id"] for item in catalog.records()} == {
        hashlib.sha256(key).hexdigest(),
        hashlib.sha256(new_key).hexdigest(),
    }
    assert catalog.file(initial["id"]).exists()


def test_scheduler_entrypoint_uses_separate_real_process_and_signed_restart_state(
    backup_operator, object_store, tmp_path
):
    source, _, key = backup_operator
    folder = tmp_path / "separate-process-catalog"
    env = {
        **os.environ,
        "RESEARCHOS_BACKUP_SCHEDULE_ENABLED": "true",
        "RESEARCHOS_BACKUP_CATALOG_DIRECTORY": str(folder),
        "RESEARCHOS_BACKUP_DAILY_HOUR_UTC": "0",
        "RESEARCHOS_BACKUP_KEY": base64.urlsafe_b64encode(key).decode(),
    }
    statuses = []
    for _ in range(2):
        process = subprocess.run(
            [sys.executable, "-m", "app.recovery.scheduler", "--once"],
            cwd=ROOT / "backend",
            env=env,
            capture_output=True,
            text=True,
            timeout=40,
        )
        assert process.returncode == 0, "Separate backup process failed; inspect project-local test evidence"
        statuses.append(json.loads(process.stdout)["status"])
    assert statuses == ["succeeded", "not_due"]
    catalog = BackupCatalog(source, get_settings().s3_bucket, get_settings().control_secret, folder)
    assert len(catalog.records()) == 1


def test_operator_config_failure_does_not_log_settings_or_credentials():
    env = {
        **os.environ,
        "RESEARCHOS_BACKUP_RETENTION_DAYS": "30",
        "RESEARCHOS_BACKUP_RETENTION_APPROVED": "false",
        "RESEARCHOS_CONTROL_SECRET": "do-not-log-this-control-secret",
    }
    process = subprocess.run(
        [sys.executable, str(ROOT / "tools/backup.py"), "enabled"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 1
    assert "ValidationError" in process.stderr
    assert "do-not-log-this-control-secret" not in process.stderr and "postgresql" not in process.stderr


def test_catalog_context_mismatch_is_rejected_before_backup(backup_operator, object_store):
    source, catalog, key = backup_operator
    with pytest.raises(ValueError, match="CATALOG_SOURCE_MISMATCH"):
        run_once(source, object_store, "wrong-bucket", key, catalog=catalog)
    assert catalog.records() == []


def test_catalog_integrity_check_detects_equal_size_ciphertext_damage(backup_operator, object_store):
    source, catalog, key = backup_operator
    result = run_once(source, object_store, get_settings().s3_bucket, key, catalog=catalog, hour=0)
    assert catalog.inspect(catalog.records(), True)["file_errors"] == []
    path = catalog.file(result["id"])
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    inspected = catalog.inspect(catalog.records(), True)
    assert inspected["hash_checked_files"] == 1
    assert inspected["file_errors"][0]["error_code"] == "BACKUP_CIPHERTEXT_HASH_CHANGED"


def test_settings_exception_hides_secret_inputs_even_outside_operator_cli():
    from pydantic import ValidationError

    from app.core.config import Settings

    values = get_settings().model_dump()
    values.update(
        control_secret="private-config-sentinel", backup_retention_days=30, backup_retention_approved=False
    )
    with pytest.raises(ValidationError) as failure:
        Settings(**values)
    assert "private-config-sentinel" not in str(failure.value)
    assert "input_value" not in str(failure.value)


def test_one_shot_operator_reports_retention_failure_to_external_controller(monkeypatch):
    from app.recovery import scheduler

    monkeypatch.setattr(get_settings(), "backup_schedule_enabled", True)
    monkeypatch.setattr(scheduler, "load_key", lambda: b"x" * 32)
    monkeypatch.setattr(scheduler, "s3_client", lambda: None)
    monkeypatch.setattr(
        scheduler,
        "run_once",
        lambda *args, **kwargs: {
            "status": "succeeded",
            "retention": {"retention": "failed", "error_code": "RETENTION_VERIFICATION_FAILED"},
        },
    )
    with pytest.raises(SystemExit) as result:
        scheduler.main(once=True)
    assert result.value.code == 1
