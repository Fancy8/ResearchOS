"""Forced full Celery-owner death, actual Redis visibility restore and outbox."""

import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import redis
from celery import Celery
from reportlab.pdfgen import canvas
from test_maintenance import pending_upload
from test_processes import assert_exited, open_process, owned_probe, wait_marker

from app.core.config import ROOT, get_settings
from app.core.processes import run_contained
from app.core.runtime_paths import runtime_namespace
from app.core.storage import get_object_bytes
from app.workers import jobs
from app.workers.dispatcher import broker_state
from app.workers.maintenance import maintenance_once

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="Local Windows mechanism drill, not production support"
)
PROBE = Path(__file__).parent / "helpers/celery_probe.py"


def until(condition, message, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := condition():
            return result
        time.sleep(0.025)
    raise AssertionError(message)


def deliveries(path):
    if not path.exists():
        return []
    # Ignore an in-progress final line; flushed records precede observable effects.
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    return [json.loads(line) for line in lines if line.endswith("\n")]


@pytest.fixture
def isolated_broker(tmp_path):
    settings = get_settings()
    prefix, queue = f"researchos-crash-test-{uuid4().hex}:", f"crash-{uuid4().hex}"
    broker = redis.Redis.from_url(settings.redis_url)
    publisher = Celery("crash-test-publisher", broker=settings.redis_url, set_as_current=False)
    publisher.conf.update(
        task_serializer="json",
        task_ignore_result=True,
        broker_transport_options={"global_keyprefix": prefix, "visibility_timeout": 5},
        task_default_queue=queue,
    )
    (tmp_path / "probe.json").write_text(json.dumps({"prefix": prefix, "queue": queue}))
    assert not list(broker.scan_iter(match=prefix + "*"))
    try:
        yield broker, publisher, prefix, queue
    finally:
        publisher.close()
        # Delete only this test's random prefix, including its own unacked keys.
        assert re.fullmatch(r"researchos-crash-test-[0-9a-f]{32}:", prefix)
        keys = list(broker.scan_iter(match=prefix + "*"))
        inventory = []
        for key in keys:
            kind = broker.type(key).decode()
            inventory.append(
                {
                    "name": key.decode()[len(prefix) :],
                    "type": kind,
                    "size": broker.hlen(key)
                    if kind == "hash"
                    else broker.llen(key)
                    if kind == "list"
                    else None,
                    "ttl": broker.ttl(key),
                }
            )
        (tmp_path / "broker-final-inventory.json").write_text(json.dumps(inventory, indent=2))
        if keys:
            assert all(key.decode().startswith(prefix) for key in keys)
            broker.delete(*keys)
        broker.close()


@pytest.mark.parametrize("lease_expired_before_redelivery", [True, False])
def test_full_worker_kill_visibility_restore_and_duplicate_publication(
    tmp_path,
    account_factory,
    db_admin,
    object_store,
    isolated_broker,
    monkeypatch,
    lease_expired_before_redelivery,
):
    import win32api
    import win32event

    broker, publisher, prefix, queue = isolated_broker
    client, account = account_factory()
    buffer = BytesIO()
    document = canvas.Canvas(buffer)
    text = document.beginText(30, 750)
    for _ in range(3500):
        text.textLine("Retain the exact original across full queue worker death.")
    document.drawText(text)
    document.showPage()
    document.save()
    original = buffer.getvalue()
    values = pending_upload(client, original)
    completed = client.post(
        f"/api/v1/papers/{values['paper_id']}/upload-complete",
        headers={"Idempotency-Key": str(uuid4())},
        json={"upload_id": values["upload_id"]},
    )
    assert completed.status_code == 202
    identifier = completed.json()["data"]["job_id"]
    published = []

    def publish(name, **kwargs):
        sent = publisher.send_task(name, queue=queue, **kwargs)
        if name == "researchos.parse_pdf":
            published.append(sent.id)
        return sent

    # The real dispatcher publishes to a real broker; only its connection namespace changes.
    monkeypatch.setattr(jobs.celery_app, "send_task", publish)
    jobs.dispatch_once()
    assert len(published) == 1
    message_id = published[0]
    with owned_probe(tmp_path, "crash", probe=PROBE) as (owner, handles):
        wait_marker(tmp_path, "ready.json")
        primary = open_process(wait_marker(tmp_path, "started.json")["pid"])
        handles.append(primary)
        row = db_admin.execute(
            "SELECT status,attempts,attempt_token FROM processing_jobs WHERE id=%s", (identifier,)
        ).fetchone()
        assert row[0:2] == ("running", 1)
        unacked = broker.hgetall(prefix + "unacked")
        assert len(unacked) == 1
        tag, serialized = next(iter(unacked.items()))
        assert json.loads(serialized)[0]["headers"]["id"] == message_id
        accepted_at = broker.zscore(prefix + "unacked_index", tag)
        assert accepted_at is not None
        assert win32event.WaitForSingleObject(primary, 250) == win32event.WAIT_TIMEOUT
        win32api.TerminateProcess(owner, 95)
        assert_exited(owner)
        assert_exited(primary)
        assert broker.hexists(prefix + "unacked", tag)  # No warm shutdown/requeue took place.
    temporary = list(runtime_namespace("pdf-tmp").glob(f"{identifier}-*.pdf"))
    assert len(temporary) == 1
    aged = temporary[0]
    old = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(aged, (old, old))
    young = aged.parent / f"{identifier}-{uuid4()}.pdf"
    young.write_bytes(b"fresh parser temporary")

    def resource_released():
        scope = f"resource:{account['workspace_id']}"
        acquired = db_admin.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0))", (scope,)
        ).fetchone()[0]
        if acquired:
            db_admin.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (scope,))
        return acquired

    until(resource_released, "Killed worker retained its resource lock")
    before_cleanup = maintenance_once(batch_size=500)
    assert before_cleanup["temporary_files_busy"] >= 2 and aged.exists() and young.exists()
    if lease_expired_before_redelivery:
        db_admin.execute(
            "UPDATE processing_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (identifier,)
        )
    until(lambda: time.time() > accepted_at + 5.1, "Visibility timeout did not elapse")
    snapshot = broker_state(publisher)
    assert snapshot["unacked"] == snapshot["delivery_index_entries"] == snapshot["expired_unacked"] == 1
    assert snapshot["keyprefix_configured"] and snapshot["oldest_unacked_age_seconds"] >= 5
    assert broker.hexists(prefix + "unacked", tag)  # Metadata inspection did not restore/consume it.
    reaper_path = tmp_path / "reaper"
    reaper_path.mkdir()
    (reaper_path / "probe.json").write_bytes((tmp_path / "probe.json").read_bytes())
    with owned_probe(reaper_path, "reaper", probe=PROBE), owned_probe(tmp_path, "retry", probe=PROBE):
        wait_marker(reaper_path, "ready.json")
        wait_marker(tmp_path, "ready.json")
        until(
            lambda: any(
                item["event"] == "finished" and item["mode"] == "retry"
                for item in deliveries(tmp_path / "deliveries.jsonl")
            ),
            "Broker did not redeliver",
        )
        retried = [
            item
            for item in deliveries(tmp_path / "deliveries.jsonl")
            if item["event"] == "started" and item["mode"] == "retry"
        ]
        assert retried == [{"event": "started", "task_id": message_id, "mode": "retry", "redelivered": True}]
        until(lambda: broker.hlen(prefix + "unacked") == 0, "Recovered message was not acknowledged")
        if not lease_expired_before_redelivery:
            assert db_admin.execute(
                "SELECT status,attempts FROM processing_jobs WHERE id=%s", (identifier,)
            ).fetchone() == ("running", 1)
            # A still-valid business lease makes the recovered delivery a no-op;
            # the actual dispatcher must recover it after the lease later expires.
            db_admin.execute(
                "UPDATE processing_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s",
                (identifier,),
            )

            def dispatched_again():
                jobs.dispatch_once()
                return len(published) >= 2

            # A newly flushed outbox row's database timestamp can be later than
            # the dispatcher's captured clock; the next real iteration sends it.
            until(dispatched_again, "Expired business lease was not dispatched")
            assert len(published) == 2 and published[-1] != message_id
        until(
            lambda: (
                db_admin.execute("SELECT status FROM processing_jobs WHERE id=%s", (identifier,)).fetchone()[
                    0
                ]
                == "succeeded"
            ),
            "Task did not recover",
        )
        # Deliver the exact original Celery ID again via the real transport.
        publisher.send_task("researchos.parse_pdf", args=[identifier], queue=queue, task_id=message_id)
        expected_finished = 2 if lease_expired_before_redelivery else 3
        until(
            lambda: (
                len(
                    [
                        item
                        for item in deliveries(tmp_path / "deliveries.jsonl")
                        if item["event"] == "finished" and item["mode"] == "retry"
                    ]
                )
                >= expected_finished
            ),
            "Duplicate delivery was not consumed",
        )
        until(lambda: broker.hlen(prefix + "unacked") == 0, "Duplicate message was not acknowledged")
        cleaned = maintenance_once(batch_size=500)
        assert cleaned["temporary_files_removed"] >= 1 and not aged.exists() and young.exists()
    status = db_admin.execute(
        "SELECT status,attempts,attempt_token FROM processing_jobs WHERE id=%s", (identifier,)
    ).fetchone()
    assert status[0:2] == ("succeeded", 2) and status[2] != row[2]
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
    storage_key = db_admin.execute(
        "SELECT storage_key FROM paper_files WHERE id=%s", (values["paper_file_id"],)
    ).fetchone()[0]
    assert hashlib.sha256(get_object_bytes(storage_key)).digest() == hashlib.sha256(original).digest()
    proof = {
        "full_solo_worker_killed": True,
        "unacked_survived": True,
        "real_redelivery_same_message_id": True,
        "duplicate_consumed": True,
        "lease_expired_before_redelivery": lease_expired_before_redelivery,
        "attempts": status[1],
        "published_page_sets": 1,
        "visibility_timeout_seconds": 5,
        "independent_recovery_process": True,
        "aged_crash_temp_preserved_while_active": True,
        "aged_crash_temp_removed_after_success": True,
        "young_temp_preserved": True,
        "scope": "Windows local solo worker; persisted business lease clock advanced; production timing not certified",
    }
    (ROOT / f"artifacts/broker-recovery-{lease_expired_before_redelivery}.json").write_text(
        json.dumps(proof, indent=2)
    )
    # Only the fresh test file remains after actual maintenance removed the aged one.
    for path in runtime_namespace("pdf-tmp").glob(f"{identifier}-*.pdf"):
        path.unlink()


def test_recovery_failure_preserves_actual_outbox_progress_and_private_error_values(
    account_factory, isolated_broker, db_admin, monkeypatch, capsys
):
    from app.workers import dispatcher

    broker, publisher, prefix, queue = isolated_broker
    account_factory()

    def failed():
        raise ConnectionError("private-test-password-and-broker-url")

    def publish(name, **kwargs):
        return publisher.send_task(name, queue=queue, **kwargs)

    monkeypatch.setattr(jobs.celery_app, "send_task", publish)
    dispatcher.dispatch_iteration(SimpleNamespace(tick=failed), dispatcher.ExpirySchedule())
    assert (
        db_admin.execute("SELECT count(*) FROM outbox_events WHERE dispatched_at IS NOT NULL").fetchone()[0]
        == 1
    )
    assert broker.llen(prefix + queue) == 2  # Verification mail plus actual periodic expiry task.
    assert broker_state(publisher)["ready"] == 2 and broker_state(publisher)["unacked"] == 0
    assert capsys.readouterr().out == "dispatcher_broker_recovery_failed\n"


def test_broker_metadata_reads_one_physical_namespace_without_consuming(isolated_broker):
    broker, publisher, prefix, queue = isolated_broker
    old = time.time() - 10
    broker.hset(prefix + "unacked", "owned-tag", "not a consumed task")
    broker.zadd(prefix + "unacked_index", {"owned-tag": old})
    broker.set(prefix + "unacked_mutex", "owned-test-lock", ex=30)
    broker.lpush(prefix + queue, "owned-ready")
    # Nested, independently addressed keys are still within this fixture's cleanup scope.
    broker.hset(prefix + "foreign:unacked", mapping={"foreign-1": "x", "foreign-2": "y"})
    broker.zadd(prefix + "foreign:unacked_index", {"foreign-1": old - 100, "foreign-2": old - 90})
    snapshot = broker_state(publisher)
    assert snapshot["ready"] == snapshot["unacked"] == snapshot["delivery_index_entries"] == 1
    assert snapshot["expired_unacked"] == 1 and 10 <= snapshot["oldest_unacked_age_seconds"] < 20
    assert 0 < snapshot["restore_mutex_ttl_seconds"] <= 30
    assert broker.hget(prefix + "unacked", "owned-tag") == b"not a consumed task"
    assert broker.hlen(prefix + "foreign:unacked") == 2
    assert broker.llen(prefix + queue) == 1 and broker.get(prefix + "unacked_mutex") == b"owned-test-lock"


@pytest.mark.parametrize("invalid_configuration", [True, False])
def test_broker_metadata_cli_redacts_configuration_and_connection_failures(tmp_path, invalid_configuration):
    overrides = (
        {"RESEARCHOS_ENVIRONMENT": "production", "RESEARCHOS_COOKIE_SECURE": "false"}
        if invalid_configuration
        else {"RESEARCHOS_REDIS_URL": "redis://:private-canary@127.0.0.1:1/0"}
    )
    result = run_contained(
        [sys.executable, str(ROOT / "tools/broker_status.py")],
        cwd=ROOT,
        env={**os.environ, **overrides},
        timeout=15,
    )
    redacted = (
        result.returncode == 2
        and not result.stderr
        and result.stdout.strip() == b'{"error_code": "BROKER_STATUS_UNAVAILABLE"}'
    )
    assert redacted, "Broker operator failure must emit only a constant diagnostic"
