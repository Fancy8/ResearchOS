import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from test_deletions import execute, preview, receipt

from app.core.config import get_settings
from app.recovery.backup import make_backup, restore_backup
from app.recovery.journal import (
    activate_source,
    append_document,
    current_checkpoint,
    frozen_journal,
    source_identity,
)
from app.workers.deletions import delete_data, ledger_document

DATABASE = "researchos_test"


def document():
    return ledger_document(
        SimpleNamespace(id=uuid4(), scope="account", target_id=None, requested_at=datetime.now(UTC)),
        uuid4(),
        uuid4(),
        DATABASE,
    )


def test_ack_is_durable_before_worker_and_append_is_idempotent(account_factory, db_admin):
    client, account = account_factory()
    response = execute(client, preview(client))
    assert response.status_code == 202, response.text
    job = response.json()["data"]
    assert (
        db_admin.execute("SELECT status FROM deletion_jobs WHERE id=%s", (job["id"],)).fetchone()[0]
        == "queued"
    )
    with frozen_journal(DATABASE) as journal:
        rows = list(journal.documents())
        assert journal.head["sequence"] == len(rows) == 1
    assert rows[0]["job_id"] == job["id"]
    assert account["workspace_id"] not in json.dumps(rows)
    assert account["id"] not in json.dumps(rows) and account["email"] not in json.dumps(rows)
    append_document(rows[0])
    assert current_checkpoint(DATABASE)["sequence"] == 1


def test_control_roles_cannot_erase_update_truncate_or_activate(ledger_admin):
    settings = get_settings()
    for raw in (settings.ledger_writer_url, settings.ledger_reader_url):
        with psycopg.connect(raw.replace("postgresql+psycopg", "postgresql"), autocommit=True) as db:
            assert db.execute(
                "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone() == (False, False, False, False)
            for statement in (
                "DELETE FROM public.ledger_entries",
                "UPDATE public.ledger_heads SET sequence=0",
                "TRUNCATE public.ledger_entries",
                "DELETE FROM public.ledger_activation",
                "ALTER TABLE public.ledger_entries DISABLE TRIGGER ALL",
                "CREATE TABLE public.injected(id int)",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    db.execute(statement)
    # Even a business migration owner cannot connect to the authority database.
    from sqlalchemy import make_url

    source = make_url(settings.admin_database_url).set(database=make_url(settings.ledger_reader_url).database)
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(
            source.render_as_string(hide_password=False).replace("postgresql+psycopg", "postgresql"),
            connect_timeout=2,
        )


@pytest.mark.parametrize(
    "damage", ["whole_entry", "tail", "all_entries", "payload", "signature", "head", "activation"]
)
def test_inventory_and_chain_damage_fail_closed(ledger_admin, damage):
    for _ in range(3):
        append_document(document())
    source = source_identity(DATABASE)
    if damage in {"whole_entry", "tail"}:
        ledger_admin.execute(
            "DELETE FROM public.ledger_entries WHERE source_id=%s AND sequence=%s",
            (source, 2 if damage == "whole_entry" else 3),
        )
    elif damage == "all_entries":
        ledger_admin.execute("DELETE FROM public.ledger_entries WHERE source_id=%s", (source,))
    elif damage == "payload":
        ledger_admin.execute(
            "UPDATE public.ledger_entries SET payload=jsonb_set(payload,'{scope}','\"file\"') WHERE source_id=%s AND sequence=1",
            (source,),
        )
    elif damage == "signature":
        ledger_admin.execute(
            "UPDATE public.ledger_entries SET signature=repeat('f',64) WHERE source_id=%s AND sequence=1",
            (source,),
        )
    elif damage == "head":
        ledger_admin.execute(
            "UPDATE public.ledger_heads SET signature=repeat('f',64) WHERE source_id=%s", (source,)
        )
    else:
        ledger_admin.execute("DELETE FROM public.ledger_activation WHERE source_id=%s", (source,))
    with pytest.raises(ValueError, match="LEDGER_"):
        current_checkpoint(DATABASE)


def test_backup_minimum_detects_a_signed_older_head(ledger_admin):
    old = current_checkpoint(DATABASE)
    append_document(document())
    minimum = current_checkpoint(DATABASE)
    ledger_admin.execute("DELETE FROM public.ledger_entries")
    ledger_admin.execute(
        "UPDATE public.ledger_heads SET sequence=0,entry_hash=%s,signature=%s WHERE source_id=%s",
        (old["entry_hash"], old["signature"], old["source_id"]),
    )
    with pytest.raises(ValueError, match="LEDGER_BEHIND_BACKUP_CHECKPOINT"):
        with frozen_journal(DATABASE, minimum=minimum):
            pass


def test_concurrent_appends_and_duplicate_requests_have_no_gaps():
    values = [document() for _ in range(12)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(append_document, values + values + values))
    with frozen_journal(DATABASE) as journal:
        rows = list(journal.documents())
        assert journal.head["sequence"] == len(rows) == 12
    assert {row["job_id"] for row in rows} == {row["job_id"] for row in values}


def test_conflict_do_nothing_cannot_advance_head_without_an_insert():
    append_document(document())
    before = current_checkpoint(DATABASE)
    raw = get_settings().ledger_writer_url.replace("postgresql+psycopg", "postgresql")
    with psycopg.connect(raw, autocommit=True) as db:
        db.execute("""INSERT INTO public.ledger_entries
            (source_id,sequence,job_id,payload,previous_hash,entry_hash,signature,head_signature)
            SELECT source_id,sequence+1,job_id,payload,entry_hash,entry_hash,signature,head_signature
            FROM public.ledger_entries ON CONFLICT DO NOTHING""")
    assert current_checkpoint(DATABASE) == before


def test_frozen_current_head_blocks_append_until_replay_gate_releases():
    started = threading.Event()
    value = document()

    def append():
        started.set()
        append_document(value)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with frozen_journal(DATABASE) as journal:
            pending = pool.submit(append)
            assert started.wait(2)
            with pytest.raises(TimeoutError):
                pending.result(timeout=0.2)
            assert journal.head["sequence"] == 0 and list(journal.documents()) == []
        pending.result(timeout=5)
    assert current_checkpoint(DATABASE)["sequence"] == 1


def test_outage_before_acceptance_has_no_business_side_effects(account_factory, db_admin, monkeypatch):
    from app.api import deletions

    client, _ = account_factory()

    def unavailable(*args, **kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(deletions, "current_checkpoint", unavailable)
    response = execute(client, preview(client))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DELETION_JOURNAL_UNAVAILABLE"
    assert db_admin.execute("SELECT count(*) FROM deletion_jobs").fetchone()[0] == 0
    assert client.get("/api/v1/me").status_code == 200


def test_failure_after_business_commit_retains_receipt_and_worker_retries_safely(
    account_factory, db_admin, monkeypatch, object_store
):
    from app.api import deletions

    client, _ = account_factory()

    def unavailable(*args, **kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(deletions, "write_ledger", unavailable)
    response = execute(client, preview(client))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DELETION_JOURNAL_PENDING"
    job = response.json()["error"]["details"]
    assert receipt(client, job).json()["data"]["status"] == "queued"
    assert current_checkpoint(DATABASE)["sequence"] == 0
    assert db_admin.execute("SELECT count(*) FROM users").fetchone()[0] == 1
    delete_data(job["id"])
    assert receipt(client, job).json()["data"]["status"] == "succeeded"
    assert current_checkpoint(DATABASE)["sequence"] == 1


def test_diagnostic_mirror_outage_does_not_block_durable_ack_or_cleanup(
    account_factory, db_admin, monkeypatch, object_store
):
    from app.workers import deletions

    client, _ = account_factory()

    def unavailable(*args, **kwargs):
        raise OSError("test mirror unavailable")

    monkeypatch.setattr(deletions, "write_legacy_mirror", unavailable)
    response = execute(client, preview(client))
    assert response.status_code == 202, response.text
    job = response.json()["data"]
    assert current_checkpoint(DATABASE)["sequence"] == 1
    delete_data(job["id"])
    assert receipt(client, job).json()["data"]["status"] == "succeeded"
    assert db_admin.execute("SELECT count(*) FROM users").fetchone()[0] == 0


@pytest.mark.parametrize("recovery_target", [False], indirect=True)
@pytest.mark.parametrize("before_floor", [True, False])
def test_legacy_recovery_floor_refuses_old_snapshots_without_silently_recovering_them(
    account_factory,
    ledger_admin,
    recovery_target,
    object_store,
    tmp_path,
    before_floor,
):
    client, _ = account_factory()
    key, backup = os.urandom(32), tmp_path / "floor.rosbak"
    settings = get_settings()
    if before_floor:
        make_backup(settings.admin_database_url, object_store, settings.s3_bucket, backup, key)
    ledger_admin.execute("DELETE FROM public.ledger_activation")
    activate_source(DATABASE, not_before=datetime.now(UTC))
    if not before_floor:
        make_backup(settings.admin_database_url, object_store, settings.s3_bucket, backup, key)
    if before_floor:
        with pytest.raises(ValueError, match="LEDGER_LEGACY_SNAPSHOT_PREDATES_TRUSTED_BASELINE"):
            restore_backup(
                backup,
                recovery_target["admin"],
                recovery_target["cleanup"],
                object_store,
                recovery_target["bucket"],
                key,
                True,
            )
        raw = (
            recovery_target["app"]
            .render_as_string(hide_password=False)
            .replace("postgresql+psycopg", "postgresql")
        )
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(raw, connect_timeout=2)
    else:
        result = restore_backup(
            backup,
            recovery_target["admin"],
            recovery_target["cleanup"],
            object_store,
            recovery_target["bucket"],
            key,
            True,
        )
        assert result["sessions_revoked"]
    assert client.get("/api/v1/me").status_code == 200


def test_replacement_database_and_bucket_keep_original_logical_authority(monkeypatch):
    import subprocess
    import sys

    from sqlalchemy import make_url

    from app.core.config import ROOT
    from app.recovery.journal import origin_database

    settings = get_settings()
    original = current_checkpoint(DATABASE)
    monkeypatch.setattr(settings, "ledger_source_id", original["source_id"])
    monkeypatch.setattr(settings, "ledger_origin_database", DATABASE)
    monkeypatch.setattr(
        settings,
        "database_url",
        make_url(settings.database_url)
        .set(database="replacement_physical_db")
        .render_as_string(hide_password=False),
    )
    monkeypatch.setattr(settings, "s3_bucket", "replacement-physical-bucket")
    assert origin_database() == DATABASE
    assert current_checkpoint(origin_database()) == original
    append_document(document())
    assert current_checkpoint(origin_database())["sequence"] == 1
    env = {
        **os.environ,
        "RESEARCHOS_DATABASE_URL": settings.database_url,
        "RESEARCHOS_LEDGER_SOURCE_ID": original["source_id"],
        "RESEARCHOS_LEDGER_ORIGIN_DATABASE": DATABASE,
        "RESEARCHOS_S3_BUCKET": settings.s3_bucket,
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/ledger.py"), "status"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, "Replacement deployment journal status failed"
    assert json.loads(result.stdout)["checkpoint"]["sequence"] == 1
    with pytest.raises(ValueError, match="LEDGER_SOURCE_CONTEXT_MISMATCH"):
        current_checkpoint("replacement_physical_db")


def test_reader_writer_routing_and_production_failure_domain_are_validated():
    from pydantic import ValidationError
    from sqlalchemy import make_url

    from app.core.config import Settings

    settings = get_settings()
    wrong_reader = make_url(settings.ledger_reader_url).set(database="other_control")
    with pytest.raises(ValidationError, match="same independent authority"):
        Settings(ledger_reader_url=wrong_reader.render_as_string(hide_password=False))
    with pytest.raises(ValidationError, match="separate PostgreSQL service"):
        Settings(
            environment="production",
            cookie_secure=True,
            frontend_origin="https://research.example",
            s3_secret_key="different-storage-secret",
            mail_delivery="smtp",
            smtp_host="mail.example",
        )


def test_operator_can_initialize_a_genuinely_empty_migrated_source(recovery_target):
    import subprocess
    import sys

    from app.core.config import ROOT

    env = {
        **os.environ,
        "RESEARCHOS_DATABASE_URL": recovery_target["app"].render_as_string(hide_password=False),
        "RESEARCHOS_CLEANUP_DATABASE_URL": recovery_target["cleanup"].render_as_string(hide_password=False),
        "RESEARCHOS_S3_BUCKET": recovery_target["bucket"],
    }
    for command in (["init-empty", "--maintenance-ack"], ["status"]):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/ledger.py"), *command],
            env=env,
            cwd=ROOT,
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, "Empty source journal bootstrap/status failed"
        output = json.loads(result.stdout)
        assert output["checkpoint"]["sequence"] == 0
