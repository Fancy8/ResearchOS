import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest
from test_papers_evidence import pdf_bytes, upload

from app.core.config import get_settings
from app.workers.exports import export_workspace
from app.workers.maintenance import maintenance_once


def pending_upload(client, data):
    result = client.post(
        "/api/v1/papers/upload-init",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Pending upload",
            "filename": "pending.pdf",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )
    assert result.status_code == 201
    values = result.json()["data"]
    assert (
        client.post(
            values["upload_url"], files={"file": ("pending.pdf", data, "application/pdf")}
        ).status_code
        == 200
    )
    return values


def completed_export(client):
    result = client.post(
        "/api/v1/exports", headers={"Idempotency-Key": str(uuid4())}, json={"include_files": True}
    )
    assert result.status_code == 202
    job = result.json()["data"]
    export_workspace(job["id"])
    assert client.get(f"/api/v1/exports/{job['id']}").json()["data"]["status"] == "succeeded"
    return job


def expire_upload(db, values):
    db.execute(
        "UPDATE upload_sessions SET expires_at=now()-interval '1 second' WHERE id=%s", (values["upload_id"],)
    )


def test_expiry_erases_disposable_bytes_preserves_original_versions_and_other_space(
    account_factory, object_store, db_admin
):
    alice, account = account_factory()
    bob, _ = account_factory("bob@example.com")
    old = upload(alice, pdf_bytes())
    new = upload(alice, pdf_bytes(text="Second version"), old["paper_id"])
    expired = completed_export(alice)
    current = completed_export(bob)
    pending = pending_upload(alice, pdf_bytes())
    untouched = pending_upload(bob, pdf_bytes())
    validating = pending_upload(alice, pdf_bytes())
    response = alice.post(
        f"/api/v1/papers/{validating['paper_id']}/upload-complete",
        headers={"Idempotency-Key": str(uuid4())},
        json={"upload_id": validating["upload_id"]},
    )
    assert response.status_code == 202
    for values in (pending, validating):
        expire_upload(db_admin, values)
    db_admin.execute(
        "UPDATE export_jobs SET expires_at=now()-interval '1 second' WHERE id=%s", (expired["id"],)
    )
    source_keys = [
        row[0]
        for row in db_admin.execute(
            "SELECT storage_key FROM paper_files WHERE id IN (%s,%s)",
            (old["paper_file_id"], new["paper_file_id"]),
        )
    ]
    report = maintenance_once()
    assert report["exports_expired"] == report["uploads_expired"] == 1
    assert report["workspaces_failed"] == report["workspaces_busy"] == 0
    assert alice.get(f"/api/v1/exports/{expired['id']}").json()["data"]["status"] == "expired"
    assert alice.get(f"/api/v1/exports/{expired['id']}/download").status_code == 409
    assert bob.get(f"/api/v1/exports/{current['id']}/download").status_code == 200
    for values, expected in ((pending, "expired"), (untouched, "pending"), (validating, "validating")):
        assert (
            db_admin.execute(
                "SELECT status FROM upload_sessions WHERE id=%s", (values["upload_id"],)
            ).fetchone()[0]
            == expected
        )
    assert (
        db_admin.execute(
            "SELECT upload_status FROM paper_files WHERE id=%s", (pending["paper_file_id"],)
        ).fetchone()[0]
        == "failed"
    )
    assert not object_store.list_objects_v2(
        Bucket=get_settings().s3_bucket, Prefix=f"exports/{account['workspace_id']}/{expired['id']}-"
    ).get("Contents")
    assert not object_store.list_objects_v2(
        Bucket=get_settings().s3_bucket,
        Prefix=f"staging/{account['workspace_id']}/{pending['upload_id']}.pdf",
    ).get("Contents")
    for key in source_keys:
        assert object_store.head_object(Bucket=get_settings().s3_bucket, Key=key)["ContentLength"] > 0
    assert maintenance_once()["exports_expired"] == 0


def test_expiry_storage_failure_is_retryable_and_does_not_report_completion(
    account_factory, object_store, db_admin
):
    client, _ = account_factory()
    pending = pending_upload(client, pdf_bytes())
    expire_upload(db_admin, pending)

    class FailedDelete:
        def __getattr__(self, name):
            return getattr(object_store, name)

        def delete_object(self, **kwargs):
            raise OSError("storage unavailable")

    result = maintenance_once(storage=FailedDelete())
    assert result["workspaces_failed"] == 1 and result["uploads_expired"] == 0
    assert (
        db_admin.execute(
            "SELECT status FROM upload_sessions WHERE id=%s", (pending["upload_id"],)
        ).fetchone()[0]
        == "pending"
    )
    assert maintenance_once()["uploads_expired"] == 1


@pytest.mark.parametrize("scope", ["workspace", "backup", "maintenance"])
def test_expiry_skips_busy_work_without_waiting_or_deleting(account_factory, object_store, db_admin, scope):
    client, account = account_factory()
    pending = pending_upload(client, pdf_bytes())
    expire_upload(db_admin, pending)
    key = {
        "workspace": f"resource:{account['workspace_id']}",
        "backup": "backup-preserve",
        "maintenance": "maintenance-expiry",
    }[scope]
    db_admin.execute("SELECT pg_advisory_lock_shared(hashtextextended(%s,0))", (key,))
    try:
        report = maintenance_once()
        assert report["uploads_expired"] == 0
        if scope == "maintenance":
            assert report["already_running"]
        else:
            assert report["workspaces_busy"] == 1
    finally:
        db_admin.execute("SELECT pg_advisory_unlock_shared(hashtextextended(%s,0))", (key,))
    assert maintenance_once()["uploads_expired"] == 1


def test_periodic_expiry_queues_once_per_minute_and_retries_broker_failure(monkeypatch):
    from app.workers import dispatcher

    clock, messages = [100.0], []
    monkeypatch.setattr(dispatcher.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        dispatcher.celery_app, "send_task", lambda *args, **kwargs: messages.append((args, kwargs))
    )
    schedule = dispatcher.ExpirySchedule()
    assert schedule.tick() and not schedule.tick()
    clock[0] += 59
    assert not schedule.tick()
    clock[0] += 1
    assert schedule.tick() and len(messages) == 2
    assert messages[0] == (("researchos.expire_artifacts",), {"args": [], "retry": False})

    def unavailable(*args, **kwargs):
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(dispatcher.celery_app, "send_task", unavailable)
    clock[0] += 60
    with pytest.raises(ConnectionError):
        schedule.tick()
    monkeypatch.setattr(
        dispatcher.celery_app, "send_task", lambda *args, **kwargs: messages.append((args, kwargs))
    )
    assert schedule.tick() and len(messages) == 3


@pytest.mark.skipif(os.name != "nt", reason="Local Windows process supervision drill")
def test_registered_expiry_task_runs_in_real_isolated_queue_worker(
    account_factory, object_store, db_admin, tmp_path
):
    import redis
    from celery import Celery
    from test_processes import owned_probe, wait_marker

    client, _ = account_factory()
    pending = pending_upload(client, pdf_bytes())
    expire_upload(db_admin, pending)
    queue, prefix = f"expiry-{uuid4().hex}", f"researchos-crash-test-{uuid4().hex}:"
    publisher = Celery("expiry-test", broker=get_settings().redis_url, set_as_current=False)
    publisher.conf.broker_transport_options = {"global_keyprefix": prefix, "visibility_timeout": 5}
    (tmp_path / "probe.json").write_text(json.dumps({"queue": queue, "prefix": prefix}))
    probe = Path(__file__).parent / "helpers/celery_probe.py"
    with redis.Redis.from_url(get_settings().redis_url) as broker:
        try:
            with owned_probe(tmp_path, "expiry", probe=probe):
                wait_marker(tmp_path, "ready.json")
                publisher.send_task("researchos.expire_artifacts", args=[], queue=queue, retry=False)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    status = db_admin.execute(
                        "SELECT status FROM upload_sessions WHERE id=%s", (pending["upload_id"],)
                    ).fetchone()[0]
                    if status == "expired" and broker.hlen(prefix + "unacked") == 0:
                        break
                    time.sleep(0.05)
                else:
                    raise AssertionError("Queued expiry task did not finish and acknowledge")
        finally:
            publisher.close()
            keys = list(broker.scan_iter(match=prefix + "*"))
            assert prefix.startswith("researchos-crash-test-") and len(prefix) == 55
            if keys:
                assert all(key.decode().startswith(prefix) for key in keys)
                broker.delete(*keys)
