import hashlib
import json
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

from test_identity_research import project, thread
from test_papers_evidence import evidence, pdf_bytes, upload


def test_export_full_relationships_files_and_privacy(account_factory, object_store):
    client, _ = account_factory()
    item = project(client)
    line = thread(client, item)
    values = upload(client, pdf_bytes())
    source = evidence(client, line, values)
    decision = client.post(
        f"/api/v1/threads/{line['id']}/decisions",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Compare evidence",
            "reason": "Validate",
            "decision_type": "adopt",
            "evidence_ids": [source["id"]],
        },
    ).json()["data"]
    client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Run experiment",
            "project_id": item["id"],
            "thread_id": line["id"],
            "decision_id": decision["id"],
        },
    )
    client.post(
        "/api/v1/notes",
        json={
            "title": "Exportable note",
            "content": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Original thought"}]}],
            },
        },
    )
    key = str(uuid4())
    response = client.post("/api/v1/exports", headers={"Idempotency-Key": key}, json={"include_files": True})
    assert response.status_code == 202, response.text
    job_id = response.json()["data"]["id"]
    from app.workers.exports import export_workspace

    export_workspace(job_id)
    status = client.get(f"/api/v1/exports/{job_id}")
    assert status.json()["data"]["status"] == "succeeded", status.text
    download = client.get(f"/api/v1/exports/{job_id}/download")
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == download.headers["x-archive-sha256"]
    with ZipFile(BytesIO(download.content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["schema_version"] == 1 and manifest["snapshot_at"]
        assert manifest["entities"]["research_decisions"] == 1 and manifest["entities"]["tasks"] == 1
        files = manifest["files"]
        assert (
            len(files) == 1
            and hashlib.sha256(bundle.read(files[0]["path"])).hexdigest() == files[0]["sha256"]
        )
        evidence_rows = json.loads(bundle.read("data/evidence.json"))
        task_rows = json.loads(bundle.read("data/tasks.json"))
        assert evidence_rows[0]["paper_file_id"] == files[0]["paper_file_id"]
        assert task_rows[0]["decision_id"] == decision["id"] and task_rows[0]["source_revision_no"] == 1
        assert "password_hash" not in bundle.read("data/users.json").decode()
        assert (
            "data/auth_sessions.json" not in bundle.namelist()
            and "data/auth_tokens.json" not in bundle.namelist()
        )
        assert any(name.startswith("notes/") for name in bundle.namelist())


def test_export_other_user_and_expired_download(account_factory, object_store, db_admin):
    alice, _ = account_factory("alice@example.com")
    bob, _ = account_factory("bob@example.com")
    response = alice.post(
        "/api/v1/exports", headers={"Idempotency-Key": str(uuid4())}, json={"include_files": False}
    )
    identifier = response.json()["data"]["id"]
    from app.workers.exports import export_workspace

    export_workspace(identifier)
    assert bob.get(f"/api/v1/exports/{identifier}").status_code == 404
    assert bob.get(f"/api/v1/exports/{identifier}/download").status_code == 404
    db_admin.execute("UPDATE export_jobs SET expires_at=now()-interval '1 second' WHERE id=%s", (identifier,))
    assert alice.get(f"/api/v1/exports/{identifier}/download").status_code == 409


def test_modified_original_is_not_displayed_or_exported(account_factory, object_store, db_admin):
    client, _ = account_factory()
    values = upload(client, pdf_bytes())
    key = db_admin.execute(
        "SELECT storage_key FROM paper_files WHERE id=%s", (values["paper_file_id"],)
    ).fetchone()[0]
    from app.core.config import ROOT, get_settings

    object_store.put_object(Bucket=get_settings().s3_bucket, Key=key, Body=b"%PDF-corrupted-original")
    response = client.get(f"/api/v1/papers/{values['paper_id']}/content")
    assert response.status_code == 409 and response.json()["error"]["code"] == "SOURCE_INTEGRITY_FAILURE"
    job = client.post(
        "/api/v1/exports", headers={"Idempotency-Key": str(uuid4())}, json={"include_files": True}
    ).json()["data"]
    from app.workers.exports import export_workspace

    export_workspace(job["id"])
    status = client.get(f"/api/v1/exports/{job['id']}").json()["data"]
    assert status["status"] == "failed" and status["error_code"] == "EXPORT_SOURCE_HASH_MISMATCH"
    assert not list((ROOT / "runtime/export-tmp/researchos_test").glob(f"{job['id']}-*"))
    assert client.get(f"/api/v1/exports/{job['id']}/download").status_code == 409


def test_missing_source_retry_exhaustion_and_snapshot_deadline(
    account_factory, object_store, db_admin, monkeypatch
):
    client, _ = account_factory()
    values = upload(client, pdf_bytes())
    key = db_admin.execute(
        "SELECT storage_key FROM paper_files WHERE id=%s", (values["paper_file_id"],)
    ).fetchone()[0]
    from app.core.config import ROOT, get_settings

    object_store.delete_object(Bucket=get_settings().s3_bucket, Key=key)
    job = client.post(
        "/api/v1/exports", headers={"Idempotency-Key": str(uuid4())}, json={"include_files": True}
    ).json()["data"]
    from app.workers.exports import export_workspace

    for index in range(3):
        db_admin.execute(
            "UPDATE export_jobs SET next_attempt_at=now()-interval '1 second' WHERE id=%s", (job["id"],)
        )
        export_workspace(job["id"])
        assert client.get(f"/api/v1/exports/{job['id']}").json()["data"]["attempts"] == index + 1
        if index < 2:
            export_workspace(job["id"])
            assert client.get(f"/api/v1/exports/{job['id']}").json()["data"]["attempts"] == index + 1
    status = client.get(f"/api/v1/exports/{job['id']}").json()["data"]
    assert status["status"] == "failed" and status["attempts"] == 3
    assert not list((ROOT / "runtime/export-tmp/researchos_test").glob(f"{job['id']}-*"))
    monkeypatch.setattr(get_settings(), "export_snapshot_seconds", 0)
    timed = client.post(
        "/api/v1/exports", headers={"Idempotency-Key": str(uuid4())}, json={"include_files": False}
    ).json()["data"]
    export_workspace(timed["id"])
    status = client.get(f"/api/v1/exports/{timed['id']}").json()["data"]
    assert status["status"] == "failed" and status["error_code"] == "EXPORT_SNAPSHOT_TIMEOUT"
    assert not list((ROOT / "runtime/export-tmp/researchos_test").glob(f"{timed['id']}-*"))
