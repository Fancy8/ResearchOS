"""Real Windows children, including forced owner death and native PostgreSQL."""

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import ROOT
from app.core.processes import (
    ProcessOutputLimit,
    ProcessTimeout,
    process_environment,
    run_contained,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows supervisor; other platforms fail closed")
PROBE = Path(__file__).parent / "helpers/process_probe.py"


def wait_marker(directory, name):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        path = directory / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        time.sleep(0.02)
    raise AssertionError(f"Missing probe marker: {name}")


def open_process(pid):
    import win32api
    import win32con

    return win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, pid)


def assert_exited(handle, timeout=5000):
    import win32event

    assert win32event.WaitForSingleObject(handle, timeout) == win32event.WAIT_OBJECT_0


def run_code(tmp_path, code, **options):
    return run_contained(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=process_environment(tmp_path),
        timeout=options.pop("timeout", 10),
        **options,
    )


@contextmanager
def owned_probe(tmp_path, mode, *, probe=PROBE):
    """An outer test job cleans only this test's processes even after a failure."""
    for name in ("owner.json", "allow", "started.json", "completed.json", "ready.json"):
        (tmp_path / name).unlink(missing_ok=True)
    release, handles, failures = threading.Event(), [], []

    def runner():
        try:
            # Keep the outer job open after probe-owner death until assertions
            # finish. Otherwise its cleanup could conceal a broken inner job.
            run_contained(
                [sys.executable, str(probe), mode, str(tmp_path)],
                cwd=ROOT,
                env=dict(os.environ),
                timeout=35,
                on_started=lambda pid: release.wait(60),
            )
        except Exception as error:
            failures.append(type(error).__name__)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    try:
        owner_id = wait_marker(tmp_path, "owner.json")["pid"]
        owner = open_process(owner_id)
        handles.append(owner)
        (tmp_path / "allow").write_text("start", encoding="utf-8")
        yield owner, handles
    finally:
        if handles:
            import win32api
            import win32event

            if win32event.WaitForSingleObject(handles[0], 0) == win32event.WAIT_TIMEOUT:
                win32api.TerminateProcess(handles[0], 94)
        release.set()
        thread.join(timeout=15)
        for handle in handles:
            handle.Close()
        assert not thread.is_alive()
        assert not failures


def test_unicode_quoting_private_environment_and_dual_streams(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCHOS_CONTROL_SECRET", "private-canary")
    args = ["空 格", 'quote"back\\', "trailing\\"]
    result = run_contained(
        [
            sys.executable,
            "-c",
            "import os,sys,json;print(json.dumps([sys.argv[1:],os.getenv('RESEARCHOS_CONTROL_SECRET')]));sys.stderr.write('error-stream')",
            *args,
        ],
        cwd=ROOT,
        env=process_environment(tmp_path),
        timeout=10,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == [args, None]
    assert result.stderr == b"error-stream"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_cap_rejects_without_echoing_private_output(tmp_path, stream):
    with pytest.raises(ProcessOutputLimit, match="^PROCESS_OUTPUT_LIMIT$"):
        run_code(tmp_path, f"import sys;sys.{stream}.write('private-canary'*1000000)", output_limit=4096)


def test_timeout_terminates_child(tmp_path):
    handles = []
    try:
        with pytest.raises(ProcessTimeout, match="^PROCESS_TIMEOUT$"):
            run_code(
                tmp_path,
                "import time;time.sleep(60)",
                timeout=0.2,
                on_started=lambda pid: handles.append(open_process(pid)),
            )
        assert_exited(handles[0])
    finally:
        for handle in handles:
            handle.Close()


def test_callback_failure_also_terminates_child(tmp_path):
    handles = []

    def observer(pid):
        handles.append(open_process(pid))
        raise RuntimeError("PROBE_OBSERVER_FAILURE")

    try:
        with pytest.raises(RuntimeError, match="PROBE_OBSERVER_FAILURE"):
            run_code(tmp_path, "import time;time.sleep(60)", on_started=observer)
        assert_exited(handles[0])
    finally:
        for handle in handles:
            handle.Close()


def test_memory_limit_rejects_large_allocation(tmp_path):
    result = run_code(tmp_path, "bytearray(512*1024*1024)", memory_limit=96 * 1024 * 1024)
    assert result.returncode != 0
    assert b"MemoryError" in result.stderr


def test_primary_exit_cleans_living_descendant(tmp_path):
    leaf = []

    def observe(pid):
        marker = wait_marker(tmp_path, "leaf.json")
        leaf.append(open_process(marker["pid"]))

    # The primary waits for the observer before exiting, avoiding PID reuse races.
    code = (
        "import subprocess,sys,time;from pathlib import Path;"
        f"subprocess.Popen([sys.executable,{str(PROBE)!r},'leaf',{str(tmp_path)!r}]);"
        f"p=Path({str(tmp_path / 'finish')!r});"
        "exec('while not p.exists(): time.sleep(0.02)')"
    )

    def release(pid):
        observe(pid)
        (tmp_path / "finish").touch()

    try:
        assert run_code(tmp_path, code, on_started=release).returncode == 0
        assert_exited(leaf[0])
    finally:
        for handle in leaf:
            handle.Close()


@pytest.mark.parametrize("mode", ["owner", "pg-owner"])
def test_forced_owner_death_kills_process_tree(tmp_path, mode, db_admin):
    import win32api
    import win32event

    with owned_probe(tmp_path, mode) as (owner, handles):
        primary = open_process(wait_marker(tmp_path, "started.json")["pid"])
        handles.append(primary)
        if mode == "owner":
            for name in ("tree.json", "leaf.json"):
                handles.append(open_process(wait_marker(tmp_path, name)["pid"]))
        else:
            import win32process

            application_name = f"researchos-pg_dump-{win32process.GetProcessId(owner)}"
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if db_admin.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name=%s", (application_name,)
                ).fetchone()[0]:
                    break
                time.sleep(0.02)
            else:
                raise AssertionError("Real pg_dump did not connect")
        # Confirm we kill the actual owner while the tested children are live.
        assert win32event.WaitForSingleObject(primary, 0) == win32event.WAIT_TIMEOUT
        win32api.TerminateProcess(owner, 91)
        assert_exited(owner)
        for handle in handles[1:]:
            assert_exited(handle)
        if mode == "pg-owner":
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if not db_admin.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name=%s", (application_name,)
                ).fetchone()[0]:
                    break
                time.sleep(0.02)
            else:
                raise AssertionError("Killed pg_dump left a server connection")


def test_start_failure_is_sanitized_and_handles_do_not_accumulate(tmp_path):
    result = run_contained(
        [sys.executable, str(PROBE), "handles", str(tmp_path)],
        cwd=ROOT,
        env=process_environment(tmp_path),
        timeout=15,
    )
    assert result.returncode == 0
    counts = json.loads(result.stdout)
    assert counts["checked_failures"] == 40
    assert counts["after"] <= counts["before"] + 2


@pytest.mark.parametrize("recovery_target", [False], indirect=True)
def test_killed_backup_operator_releases_locks_cleans_owned_dump_and_retries(
    tmp_path, db_admin, account_factory, object_store, recovery_target
):
    import base64
    import hashlib

    import win32api
    from test_papers_evidence import pdf_bytes, upload

    from app.core.config import get_settings
    from app.recovery.backup import db_connect, restore_backup
    from app.recovery.catalog import BackupCatalog
    from app.recovery.scheduler import run_once

    settings, key = get_settings(), os.urandom(32)
    client, _ = account_factory()
    values = upload(client, pdf_bytes())
    (tmp_path / "probe.json").write_text(json.dumps({"key": base64.b64encode(key).decode()}))
    catalog = BackupCatalog(
        settings.backup_database_url, settings.s3_bucket, settings.control_secret, tmp_path / "catalog"
    )
    with owned_probe(tmp_path, "scheduler-owner") as (owner, handles):
        wait_marker(tmp_path, "dumped.json")
        row = catalog.records()[0]
        assert row["status"] == "running"
        dumps = list(catalog.workspace(row["id"]).rglob("database.dump"))
        assert len(dumps) == 1 and dumps[0].stat().st_size > 1000
        for name in ("scheduled-backup", "backup-preserve"):
            assert not db_admin.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,0))", (name,)
            ).fetchone()[0]
        win32api.TerminateProcess(owner, 92)
        assert_exited(owner)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            acquired = db_admin.execute(
                "SELECT pg_try_advisory_lock(hashtextextended('backup-preserve',0))"
            ).fetchone()[0]
            if acquired:
                db_admin.execute("SELECT pg_advisory_unlock(hashtextextended('backup-preserve',0))")
                break
            time.sleep(0.02)
        else:
            raise AssertionError("Killed backup owner retained preservation lock")
        assert catalog.records()[0]["status"] == "running" and dumps[0].exists()
        assert not catalog.file(row["id"]).exists()
    # Recover using actual scheduler state, rather than editing the signed catalog.
    now = datetime.now(UTC)
    assert (
        run_once(
            settings.backup_database_url,
            object_store,
            settings.s3_bucket,
            key,
            catalog=catalog,
            hour=0,
            now=now,
        )["status"]
        == "not_due"
    )
    failed = catalog.records()[0]
    assert failed["status"] == "failed" and failed["error_code"] == "BACKUP_INTERRUPTED"
    assert not catalog.workspace(row["id"]).exists()
    retried = run_once(
        settings.backup_database_url,
        object_store,
        settings.s3_bucket,
        key,
        catalog=catalog,
        hour=0,
        now=now + timedelta(seconds=65),
    )
    assert retried["status"] == "succeeded" and retried["id"] != row["id"]
    restored = restore_backup(
        catalog.file(retried["id"]),
        recovery_target["admin"],
        recovery_target["cleanup"],
        object_store,
        recovery_target["bucket"],
        key,
        True,
    )
    assert restored["objects_restored"] == 1
    with db_connect(recovery_target["admin"]) as db:
        storage_key, checksum = db.execute(
            "SELECT storage_key,sha256 FROM paper_files WHERE id=%s", (values["paper_file_id"],)
        ).fetchone()
    with object_store.get_object(Bucket=recovery_target["bucket"], Key=storage_key)["Body"] as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == checksum


def test_killed_pdf_task_owner_leaves_recoverable_lease_and_exactly_one_publication(
    tmp_path, account_factory, db_admin, object_store, monkeypatch
):
    import hashlib

    import win32api
    import win32event
    from reportlab.pdfgen import canvas

    from app.core.runtime_paths import runtime_namespace
    from app.core.storage import get_object_bytes
    from app.workers import jobs

    # One real PDF with enough text to block structured output while the probe
    # deliberately holds its reader. No malformed parser or fake parse result.
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    text = pdf.beginText(30, 750)
    for _ in range(3500):
        text.textLine("ResearchOS original source retained through worker crash.")
    pdf.drawText(text)
    pdf.showPage()
    pdf.save()
    data = buffer.getvalue()
    client, user = account_factory()
    initial = client.post(
        "/api/v1/papers/upload-init",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "filename": "crash.pdf",
            "title": "Crash recovery source",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )
    assert initial.status_code == 201
    values = initial.json()["data"]
    assert (
        client.post(values["upload_url"], files={"file": ("crash.pdf", data, "application/pdf")}).status_code
        == 200
    )
    completed = client.post(
        f"/api/v1/papers/{values['paper_id']}/upload-complete",
        headers={"Idempotency-Key": str(uuid4())},
        json={"upload_id": values["upload_id"]},
    )
    assert completed.status_code == 202
    identifier = completed.json()["data"]["job_id"]
    (tmp_path / "probe.json").write_text(json.dumps({"job_id": identifier}))
    with owned_probe(tmp_path, "pdf-owner") as (owner, handles):
        primary = open_process(wait_marker(tmp_path, "started.json")["pid"])
        handles.append(primary)
        row = db_admin.execute(
            "SELECT status,attempts,attempt_token FROM processing_jobs WHERE id=%s", (identifier,)
        ).fetchone()
        assert row[0:2] == ("running", 1)
        assert win32event.WaitForSingleObject(primary, 250) == win32event.WAIT_TIMEOUT
        win32api.TerminateProcess(owner, 93)
        assert_exited(owner)
        assert_exited(primary)
        assert (
            db_admin.execute(
                "SELECT count(*) FROM paper_pages WHERE paper_file_id=%s", (values["paper_file_id"],)
            ).fetchone()[0]
            == 0
        )
    temporary = list(runtime_namespace("pdf-tmp").glob(f"{identifier}-*.pdf"))
    assert len(temporary) == 1  # Parent death cannot execute a Python finally block.
    # Advance only the stored lease; do not wait 180 seconds or bypass claim().
    db_admin.execute(
        "UPDATE processing_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (identifier,)
    )
    deliveries = []
    monkeypatch.setattr(
        jobs.celery_app, "send_task", lambda *args, **kwargs: deliveries.append((args, kwargs))
    )
    jobs.dispatch_once()
    assert any(
        args[0] == "researchos.parse_pdf" and kwargs["args"] == [identifier] for args, kwargs in deliveries
    )
    with owned_probe(tmp_path, "pdf-retry") as (owner, handles):
        wait_marker(tmp_path, "completed.json")
    status = db_admin.execute(
        "SELECT status,attempts,attempt_token FROM processing_jobs WHERE id=%s", (identifier,)
    ).fetchone()
    assert status[0:2] == ("succeeded", 2) and status[2] != row[2]
    jobs.parse_pdf(identifier)  # Duplicate delivery is an idempotent no-op.
    assert (
        db_admin.execute(
            "SELECT count(*) FROM paper_pages WHERE paper_file_id=%s", (values["paper_file_id"],)
        ).fetchone()[0]
        == 1
    )
    assert (
        db_admin.execute(
            "SELECT count(*) FROM activity_events WHERE target_id=%s AND event_type='paper_imported'",
            (values["paper_id"],),
        ).fetchone()[0]
        == 1
    )
    storage_key, checksum = db_admin.execute(
        "SELECT storage_key,sha256 FROM paper_files WHERE id=%s", (values["paper_file_id"],)
    ).fetchone()
    assert (
        hashlib.sha256(get_object_bytes(storage_key)).hexdigest()
        == checksum
        == hashlib.sha256(data).hexdigest()
    )
    # Exact known orphan; ordinary maintenance's age grace remains unchanged.
    temporary[0].unlink()
