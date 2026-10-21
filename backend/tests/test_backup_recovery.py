import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4

import psycopg
import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import make_url
from test_deletions import execute, preview
from test_identity_research import project, thread
from test_papers_evidence import evidence, pdf_bytes, upload

from app.core.config import ROOT, get_settings
from app.core.security import digest
from app.recovery.backup import make_backup, restore_backup
from app.recovery.crypto import decrypt_file, encrypt_file


def target_connection(target):
    return psycopg.connect(
        target["admin"].render_as_string(hide_password=False).replace("postgresql+psycopg", "postgresql"),
        autocommit=True,
    )


@pytest.mark.parametrize(
    "changes",
    [{"host": "other-host"}, {"port": 5433}, {"database": "other-db"}, {"username": "researchos_app"}],
)
def test_restore_rejects_differently_routed_cleanup_before_any_io(tmp_path, changes):
    target = make_url("postgresql+psycopg://researchos_admin:unused@127.0.0.1:5432/isolated")
    cleanup = target.set(username="researchos_cleanup").set(**changes)
    with pytest.raises(ValueError, match="RESTORE_CLEANUP_TARGET_MISMATCH"):
        restore_backup(tmp_path / "not-opened", target, cleanup, None, "not-accessed", b"x" * 32, True)


@pytest.mark.parametrize("recovery_target", [False], indirect=True)
@pytest.mark.parametrize(
    "scope,status,finish_after_snapshot",
    [
        ("file", "queued", False),
        ("file", "running", False),
        ("file", "failed", False),
        ("account", "queued", False),
        ("file", "queued", True),
    ],
)
def test_restore_finishes_pending_deletions_before_reopening(
    account_factory, object_store, recovery_target, db_admin, scope, status, finish_after_snapshot
):
    client, account = account_factory()
    original = upload(client, pdf_bytes())
    pending = client.post(
        "/api/v1/papers/upload-init",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "filename": "interrupted.pdf",
            "title": "Interrupted upload",
            "size_bytes": 1024,
            "sha256": "a" * 64,
        },
    )
    assert pending.status_code == 201
    pending = pending.json()["data"]
    requested = execute(
        client, preview(client, scope, original["paper_file_id"] if scope == "file" else None)
    )
    assert requested.status_code == 202
    job = requested.json()["data"]
    db_admin.execute(
        "UPDATE deletion_jobs SET status=%s,attempt_token=%s,lease_owner='old-worker',"
        "lease_expires_at=now()+interval '1 hour',error_code='OLD_ERROR',attempts=max_attempts WHERE id=%s",
        (status, uuid4(), job["id"]),
    )
    backup, key = ROOT / f"artifacts/pending-deletion-{uuid4()}.rosbak", os.urandom(32)
    make_backup(get_settings().admin_database_url, object_store, get_settings().s3_bucket, backup, key)
    if finish_after_snapshot:
        # The ledger was written after this backup, but its pending receipt is in the dump.
        from app.workers.deletions import delete_data

        db_admin.execute(
            "UPDATE deletion_jobs SET attempts=0,lease_expires_at=now()-interval '1 hour' WHERE id=%s",
            (job["id"],),
        )
        delete_data(job["id"])
    restored = restore_backup(
        backup,
        recovery_target["admin"],
        recovery_target["cleanup"],
        object_store,
        recovery_target["bucket"],
        key,
        maintenance_ack=True,
    )
    with target_connection(recovery_target) as db:
        result = db.execute(
            "SELECT status,workspace_id,requested_by,target_id,online_finished_at,error_code,"
            "attempt_token,lease_owner,lease_expires_at,receipt_hash FROM deletion_jobs WHERE id=%s",
            (job["id"],),
        ).fetchone()
        assert result[0] == "succeeded" and result[1:4] == (None, None, None)
        assert result[4] is not None and result[5:9] == (None, None, None, None)
        assert result[9] == digest(job["receipt"])
        assert db.execute("SELECT count(*) FROM outbox_events").fetchone()[0] == 0
        if scope == "account":
            assert not db.execute("SELECT id FROM users WHERE id=%s", (account["id"],)).fetchone()
        else:
            assert db.execute(
                "SELECT availability_status,is_current FROM paper_files WHERE id=%s",
                (original["paper_file_id"],),
            ).fetchone() == ("missing", False)
            assert db.execute("SELECT count(*) FROM processing_jobs").fetchone()[0] == 0
            assert (
                db.execute(
                    "SELECT status FROM upload_sessions WHERE id=%s", (pending["upload_id"],)
                ).fetchone()[0]
                == "failed"
            )
            assert db.execute(
                "SELECT upload_status,availability_status,is_current FROM paper_files WHERE id=%s",
                (pending["paper_file_id"],),
            ).fetchone() == ("failed", "missing", False)
        assert db.execute(
            "SELECT has_database_privilege('researchos_app',current_database(),'CONNECT')"
        ).fetchone()[0]
    assert restored["deletion_requests_replayed"] == 1
    assert not object_store.list_objects_v2(
        Bucket=recovery_target["bucket"], Prefix=f"final/{account['workspace_id']}/"
    ).get("Contents")
    if not finish_after_snapshot:
        # Only the isolated restore was cleaned; the source request is still pending.
        assert (
            db_admin.execute("SELECT status FROM deletion_jobs WHERE id=%s", (job["id"],)).fetchone()[0]
            == status
        )


@pytest.mark.parametrize("recovery_target", [False], indirect=True)
@pytest.mark.parametrize(
    "failure", ["restore_sql", "copied_object", "ledger_signature", "ledger_inventory", "reopen_permissions"]
)
def test_failed_restore_keeps_application_closed_and_source_unchanged(
    account_factory, object_store, recovery_target, monkeypatch, tmp_path, failure, ledger_admin
):
    client, account = account_factory()
    source_bytes = pdf_bytes()
    original = upload(client, source_bytes)
    backup, key = ROOT / f"artifacts/failed-restore-{uuid4()}.rosbak", os.urandom(32)
    source_bucket = get_settings().s3_bucket
    make_backup(get_settings().admin_database_url, object_store, source_bucket, backup, key)
    from app.recovery import backup as operations

    storage = object_store
    expected = "PG_RESTORE_FAILED"
    if failure == "restore_sql":
        real_tool = operations.pg_tool

        def failed_tool(name, *args, **kwargs):
            if name == "pg_restore":
                raise RuntimeError("PG_RESTORE_FAILED")
            return real_tool(name, *args, **kwargs)

        monkeypatch.setattr(operations, "pg_tool", failed_tool)
    elif failure == "copied_object":

        class CorruptedRead:
            def __getattr__(self, name):
                return getattr(object_store, name)

            def get_object(self, **kwargs):
                response = object_store.get_object(**kwargs)
                if kwargs["Bucket"] == recovery_target["bucket"]:
                    response["Body"].close()
                    response["Body"] = BytesIO(b"corrupt destination bytes")
                return response

        storage, expected = CorruptedRead(), "RESTORE_OBJECT_HASH_MISMATCH"
    elif failure == "reopen_permissions":
        real_connect = operations.db_connect

        class FinalGrantFailure:
            def __init__(self, db):
                self.db = db

            def __enter__(self):
                self.db.__enter__()
                return self

            def __exit__(self, *args):
                return self.db.__exit__(*args)

            def execute(self, statement, *args, **kwargs):
                rendered = statement.as_string(self.db) if hasattr(statement, "as_string") else str(statement)
                if "GRANT CONNECT" in rendered and "researchos_backup" in rendered:
                    raise RuntimeError("FINAL_REOPEN_FAILED")
                return self.db.execute(statement, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.db, name)

        monkeypatch.setattr(
            operations, "db_connect", lambda *args, **kwargs: FinalGrantFailure(real_connect(*args, **kwargs))
        )
        expected = "FINAL_REOPEN_FAILED"
    else:
        if failure == "ledger_signature":
            ledger_admin.execute("UPDATE public.ledger_heads SET signature=repeat('f',64)")
            expected = "LEDGER_HEAD_INTEGRITY_FAILURE"
        else:
            # A post-snapshot accepted request survives in the authority;
            # removing its entire entry must not silently resurrect the file.
            requested = execute(client, preview(client, "file", original["paper_file_id"]))
            assert requested.status_code == 202
            ledger_admin.execute("DELETE FROM public.ledger_entries")
            expected = "LEDGER_INVENTORY_INCOMPLETE"
    with pytest.raises((RuntimeError, ValueError), match=expected):
        restore_backup(
            backup,
            recovery_target["admin"],
            recovery_target["cleanup"],
            storage,
            recovery_target["bucket"],
            key,
            maintenance_ack=True,
        )
    with target_connection(recovery_target) as db:
        assert not db.execute(
            "SELECT has_database_privilege('researchos_app',current_database(),'CONNECT')"
        ).fetchone()[0]
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(
            recovery_target["app"]
            .render_as_string(hide_password=False)
            .replace("postgresql+psycopg", "postgresql"),
            connect_timeout=2,
        )
    assert not object_store.list_objects_v2(Bucket=recovery_target["bucket"]).get("Contents")
    assert get_settings().s3_bucket == source_bucket
    assert client.get("/api/v1/me").status_code == 200
    original_response = client.get(f"/api/v1/papers/{original['paper_id']}/file")
    assert original_response.status_code == (409 if failure == "ledger_inventory" else 200)
    if failure != "ledger_inventory":
        assert client.get(original_response.json()["data"]["url"]).content == source_bytes
    originals = object_store.list_objects_v2(
        Bucket=source_bucket, Prefix=f"final/{account['workspace_id']}/"
    )["Contents"]
    assert len(originals) == 1
    with object_store.get_object(Bucket=source_bucket, Key=originals[0]["Key"])["Body"] as stream:
        assert stream.read() == source_bytes


def test_backup_authentication_rejects_wrong_key_tamper_and_truncation(tmp_path):
    source, encrypted = tmp_path / "input", tmp_path / "encrypted"
    key = os.urandom(32)
    source.write_bytes(os.urandom(5 * 1024 * 1024))
    encrypt_file(source, encrypted, key)
    output = tmp_path / "output"
    decrypt_file(encrypted, output, key)
    assert output.read_bytes() == source.read_bytes()
    output.unlink()
    with pytest.raises(InvalidTag):
        decrypt_file(encrypted, output, os.urandom(32))
    assert not output.exists()
    contents = encrypted.read_bytes()
    for changed in (contents[:-30], contents[:50] + bytes([contents[50] ^ 1]) + contents[51:]):
        damaged = tmp_path / "damaged"
        damaged.write_bytes(changed)
        with pytest.raises((ValueError, InvalidTag)):
            decrypt_file(damaged, output, key)
        assert not output.exists()


@pytest.mark.parametrize("recovery_target", [False], indirect=True)
def test_backup_preserve_lock_blocks_real_file_cleanup_until_copy_finishes(
    account_factory, object_store, recovery_target, db_admin
):
    client, account = account_factory()
    original = upload(client, pdf_bytes())
    copying, release = threading.Event(), threading.Event()

    class PausedCopy:
        def __getattr__(self, name):
            return getattr(object_store, name)

        def get_object(self, **kwargs):
            copying.set()
            if not release.wait(20):
                raise TimeoutError("Backup copy test was not released")
            return object_store.get_object(**kwargs)

    key, backup = os.urandom(32), ROOT / f"artifacts/concurrent-backup-{uuid4()}.rosbak"
    with ThreadPoolExecutor(max_workers=2) as workers:
        captured = workers.submit(
            make_backup,
            get_settings().admin_database_url,
            PausedCopy(),
            get_settings().s3_bucket,
            backup,
            key,
        )
        try:
            assert copying.wait(10)
            requested = execute(client, preview(client, "file", original["paper_file_id"]))
            assert requested.status_code == 202
            job = requested.json()["data"]
            from app.workers.deletions import delete_data

            cleanup = workers.submit(delete_data, job["id"])
            deadline, blocked = time.monotonic() + 5, False
            while time.monotonic() < deadline:
                blocked = db_admin.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND NOT granted "
                    "AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
                    "AND classid=((hashtextextended('backup-preserve',0)>>32)&4294967295)::oid "
                    "AND objid=(hashtextextended('backup-preserve',0)&4294967295)::oid AND objsubid=1)"
                ).fetchone()[0]
                if blocked:
                    break
                time.sleep(0.03)
            assert blocked and not cleanup.done()
            assert object_store.list_objects_v2(
                Bucket=get_settings().s3_bucket, Prefix=f"final/{account['workspace_id']}/"
            ).get("Contents")
        finally:
            release.set()
        assert captured.result(timeout=20)["objects"] == 1
        cleanup.result(timeout=10)
    assert (
        db_admin.execute("SELECT status FROM deletion_jobs WHERE id=%s", (job["id"],)).fetchone()[0]
        == "succeeded"
    )
    restored = restore_backup(
        backup,
        recovery_target["admin"],
        recovery_target["cleanup"],
        object_store,
        recovery_target["bucket"],
        key,
        maintenance_ack=True,
    )
    assert restored["objects_restored"] == 1 and restored["deletion_requests_replayed"] == 1
    assert not object_store.list_objects_v2(Bucket=recovery_target["bucket"]).get("Contents")


@pytest.mark.parametrize("recovery_target", [False], indirect=True)
def test_encrypted_snapshot_backup_restores_originals_and_replays_later_deletion(
    account_factory, object_store, recovery_target, db_admin
):
    client, account = account_factory()
    deleted_client, deleted_account = account_factory("deleted@example.com")
    item = project(client)
    line = thread(client, item)
    first = upload(client, pdf_bytes())
    source = evidence(client, line, first)
    second = upload(client, pdf_bytes(text="New version"), first["paper_id"])
    decision_response = client.post(
        f"/api/v1/threads/{line['id']}/decisions",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Original decision",
            "reason": "Original reason",
            "decision_type": "adopt",
            "evidence_ids": [source["id"]],
        },
    )
    assert decision_response.status_code == 201
    decision = decision_response.json()["data"]
    task_response = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Original action",
            "project_id": item["id"],
            "thread_id": line["id"],
            "decision_id": decision["id"],
        },
    )
    assert task_response.status_code == 201
    task = task_response.json()["data"]
    upload(deleted_client, pdf_bytes(text="Account removed after backup"))
    from app.workers.maintenance import maintenance_once

    maintenance_once()
    assert db_admin.execute("SELECT count(*) FROM maintenance_checkpoints").fetchone()[0] > 0
    key = os.urandom(32)
    backup = ROOT / f"artifacts/backup-recovery-{uuid4()}.rosbak"
    captured = make_backup(
        get_settings().admin_database_url, object_store, get_settings().s3_bucket, backup, key
    )
    assert captured["objects"] == 3 and captured["encrypted"]
    job = execute(deleted_client, preview(deleted_client)).json()["data"]
    from app.workers.deletions import delete_data

    delete_data(job["id"])
    restored = restore_backup(
        backup,
        recovery_target["admin"],
        recovery_target["cleanup"],
        object_store,
        recovery_target["bucket"],
        key,
        maintenance_ack=True,
    )
    assert restored["deletion_requests_replayed"] == 1 and restored["sessions_revoked"]
    with psycopg.connect(
        recovery_target["admin"]
        .render_as_string(hide_password=False)
        .replace("postgresql+psycopg", "postgresql")
    ) as db:
        assert not db.execute("SELECT id FROM users WHERE id=%s", (deleted_account["id"],)).fetchone()
        assert db.execute("SELECT count(*) FROM auth_sessions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM maintenance_checkpoints").fetchone()[0] == 0
        assert not db.execute(
            "SELECT has_table_privilege('researchos_app','maintenance_checkpoints','SELECT')"
        ).fetchone()[0]
        assert not db.execute(
            "SELECT has_table_privilege('researchos_app','decision_revisions','UPDATE')"
        ).fetchone()[0]
        assert (
            db.execute("SELECT source_revision_no FROM tasks WHERE id=%s", (task["id"],)).fetchone()[0] == 1
        )
    assert not object_store.list_objects_v2(
        Bucket=recovery_target["bucket"], Prefix=f"final/{deleted_account['workspace_id']}/"
    ).get("Contents")
    probe = ROOT / f"runtime/tmp/backup-probe-{uuid4()}.json"
    probe.write_text(
        json.dumps(
            {
                "email": account["email"],
                "password": "ResearchOS-restored-2026",
                "recover": True,
                "paper": first["paper_id"],
                "old_file": first["paper_file_id"],
                "new_file": second["paper_file_id"],
                "decision": decision["id"],
                "task": task["id"],
            }
        )
    )
    env = {
        **os.environ,
        "RESEARCHOS_DATABASE_URL": recovery_target["app"].render_as_string(hide_password=False),
        "RESEARCHOS_ADMIN_DATABASE_URL": recovery_target["admin"].render_as_string(hide_password=False),
        "RESEARCHOS_CLEANUP_DATABASE_URL": recovery_target["cleanup"].render_as_string(hide_password=False),
        "RESEARCHOS_S3_BUCKET": recovery_target["bucket"],
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/probe_recovery.py"), str(probe)],
        env=env,
        cwd=ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    probe.unlink()
    assert result.returncode == 0, "Isolated restored API/password recovery probe failed"
    report = json.loads(result.stdout)
    (ROOT / "artifacts/backup-recovery-proof.json").write_text(
        json.dumps({"backup": captured, "restore": restored, "api": report}, indent=2)
    )
