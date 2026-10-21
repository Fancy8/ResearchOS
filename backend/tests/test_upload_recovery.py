import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from test_papers_evidence import pdf_bytes, upload


def initialize(client, data):
    body = {"filename": "recovery.pdf", "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    headers = {"Idempotency-Key": str(uuid4())}
    result = client.post("/api/v1/papers/upload-init", headers=headers, json=body)
    assert result.status_code == 201, result.text
    return result.json()["data"], body, headers


def complete(client, values, key=None):
    return client.post(
        f"/api/v1/papers/{values['paper_id']}/upload-complete",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"upload_id": values["upload_id"]},
    )


def send(client, values, data):
    return client.post(values["upload_url"], files={"file": ("recovery.pdf", data, "application/pdf")})


def test_completed_upload_failed_parse_does_not_implicitly_start_another_job(
    account_factory, object_store, db_admin
):
    client, _ = account_factory()
    values = upload(client, pdf_bytes())
    job = db_admin.execute(
        "SELECT id FROM processing_jobs WHERE paper_file_id=%s", (values["paper_file_id"],)
    ).fetchone()[0]
    db_admin.execute(
        "UPDATE processing_jobs SET status='failed',error_code='PARSER_FAILED' WHERE id=%s", (job,)
    )
    db_admin.execute("UPDATE paper_files SET parse_status='failed' WHERE id=%s", (values["paper_file_id"],))
    result = complete(client, values)
    assert result.status_code == 202, result.text
    assert result.json()["data"]["job_id"] == str(job)
    assert result.json()["data"]["status"] == "failed"
    assert (
        db_admin.execute(
            "SELECT count(*) FROM processing_jobs WHERE paper_file_id=%s", (values["paper_file_id"],)
        ).fetchone()[0]
        == 1
    )
    assert (
        db_admin.execute(
            "SELECT parse_status FROM paper_files WHERE id=%s", (values["paper_file_id"],)
        ).fetchone()[0]
        == "failed"
    )


def test_repeated_complete_preserves_processing_status_and_original_receipt(
    account_factory, object_store, db_admin
):
    client, _ = account_factory()
    data = pdf_bytes()
    values, _, _ = initialize(client, data)
    assert send(client, values, data).status_code == 200
    key = str(uuid4())
    first = complete(client, values, key)
    assert first.status_code == 202
    job = first.json()["data"]["job_id"]
    db_admin.execute("UPDATE processing_jobs SET status='running' WHERE id=%s", (job,))
    db_admin.execute(
        "UPDATE paper_files SET parse_status='processing' WHERE id=%s", (values["paper_file_id"],)
    )
    replay = complete(client, values, key)
    assert replay.json() == first.json()
    latest = complete(client, values)
    assert latest.status_code == 202 and latest.json()["data"]["job_id"] == job
    assert latest.json()["data"]["status"] == "running"
    assert (
        db_admin.execute(
            "SELECT parse_status FROM paper_files WHERE id=%s", (values["paper_file_id"],)
        ).fetchone()[0]
        == "processing"
    )


def test_expired_init_replay_retains_identity_and_cannot_restart_content(
    account_factory, object_store, db_admin
):
    client, _ = account_factory()
    data = pdf_bytes()
    values, body, headers = initialize(client, data)
    db_admin.execute(
        "UPDATE upload_sessions SET expires_at=%s WHERE id=%s",
        (datetime.now(UTC) - timedelta(minutes=1), values["upload_id"]),
    )
    replay = client.post("/api/v1/papers/upload-init", json=body, headers=headers)
    assert replay.status_code == 201 and replay.json()["data"] == values
    assert send(client, values, data).status_code == 409
    result = complete(client, values)
    assert result.status_code == 409 and result.json()["error"]["code"] == "UPLOAD_EXPIRED"
    assert (
        db_admin.execute(
            "SELECT count(*) FROM processing_jobs WHERE paper_file_id=%s", (values["paper_file_id"],)
        ).fetchone()[0]
        == 0
    )


def test_same_bytes_can_retransmit_only_before_confirmation_and_concurrent_complete_is_single_job(
    account_factory, object_store, db_admin
):
    client, _ = account_factory()
    data = pdf_bytes()
    values, _, _ = initialize(client, data)
    assert send(client, values, data).status_code == 200
    assert send(client, values, data).status_code == 200
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: complete(client, values), range(3)))
    assert all(result.status_code == 202 for result in results)
    jobs = {result.json()["data"]["job_id"] for result in results}
    assert len(jobs) == 1
    assert send(client, values, data).status_code == 409
    from app.workers.jobs import parse_pdf

    parse_pdf(next(iter(jobs)))
    address = client.get(f"/api/v1/papers/{values['paper_id']}/file").json()["data"]
    assert hashlib.sha256(client.get(address["url"]).content).digest() == hashlib.sha256(data).digest()
    assert (
        db_admin.execute(
            "SELECT count(*) FROM paper_files WHERE paper_id=%s", (values["paper_id"],)
        ).fetchone()[0]
        == 1
    )
    assert (
        db_admin.execute(
            "SELECT count(*) FROM processing_jobs WHERE paper_file_id=%s", (values["paper_file_id"],)
        ).fetchone()[0]
        == 1
    )


def test_completed_upload_without_job_fails_closed(account_factory, object_store, db_admin):
    client, _ = account_factory()
    values = upload(client, pdf_bytes())
    db_admin.execute("DELETE FROM processing_jobs WHERE paper_file_id=%s", (values["paper_file_id"],))
    result = complete(client, values)
    assert result.status_code == 409 and result.json()["error"]["code"] == "STATE_CONFLICT"
    assert (
        db_admin.execute(
            "SELECT count(*) FROM processing_jobs WHERE paper_file_id=%s", (values["paper_file_id"],)
        ).fetchone()[0]
        == 0
    )
