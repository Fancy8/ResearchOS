import json
from uuid import uuid4

from test_identity_research import project, thread
from test_papers_evidence import evidence, pdf_bytes, upload

from app.core.config import ROOT, get_settings
from app.workers.deletions import delete_data


def preview(client, scope="account", target=None):
    response = client.post("/api/v1/deletion-previews", json={"scope": scope, "target_id": target})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def execute(client, value, password="ResearchOS-test-2026"):
    return client.post(
        "/api/v1/deletions",
        json={
            "scope": value["scope"],
            "target_id": value.get("paper_file_id"),
            "preview_token": value["preview_token"],
            "password": password,
            "confirmation": "DELETE",
        },
    )


def receipt(client, result):
    return client.get(f"/api/v1/deletions/{result['id']}", headers={"X-Deletion-Receipt": result["receipt"]})


def test_preview_is_readonly_bound_and_reauth_required(account_factory, db_admin):
    alice, _ = account_factory()
    bob, _ = account_factory("bob@example.com")
    value = preview(alice)
    assert "maintenance_checkpoints" not in value["counts"]
    assert db_admin.execute("SELECT count(*) FROM deletion_jobs").fetchone()[0] == 0
    assert execute(alice, value, "wrong-password").status_code == 403
    assert execute(bob, value).status_code == 409
    project(alice)
    assert execute(alice, value).status_code == 409
    assert alice.get("/api/v1/me").status_code == 200


def test_referenced_file_and_active_export_cannot_delete(account_factory, object_store):
    client, _ = account_factory()
    line = thread(client, project(client))
    values = upload(client, pdf_bytes())
    source = evidence(client, line, values)
    value = preview(client, "file", source["paper_file_id"])
    assert value["blocked"] and value["counts"]["evidence"] == 1
    assert execute(client, value).status_code == 409
    other = upload(client, pdf_bytes(text="Other document"))
    client.post("/api/v1/exports", headers={"Idempotency-Key": str(uuid4())}, json={"include_files": True})
    value = preview(client, "file", other["paper_file_id"])
    assert value["blocked"] and value["counts"]["active_exports"] == 1
    assert execute(client, value).status_code == 409


def test_file_cleanup_keeps_record_and_removes_real_bytes(account_factory, object_store, db_admin):
    client, _ = account_factory()
    values = upload(client, pdf_bytes())
    file_id = values["paper_file_id"]
    key = db_admin.execute("SELECT storage_key FROM paper_files WHERE id=%s", (file_id,)).fetchone()[0]
    value = preview(client, "file", file_id)
    created = execute(client, value)
    assert created.status_code == 202, created.text
    job = created.json()["data"]
    assert client.get(f"/api/v1/deletions/{job['id']}").status_code == 404
    delete_data(job["id"])
    result = receipt(client, job)
    assert result.json()["data"]["status"] == "succeeded", result.text
    assert db_admin.execute(
        "SELECT availability_status,is_current FROM paper_files WHERE id=%s", (file_id,)
    ).fetchone() == ("missing", False)
    assert (
        db_admin.execute("SELECT count(*) FROM papers WHERE id=%s", (values["paper_id"],)).fetchone()[0] == 1
    )
    assert not object_store.list_objects_v2(Bucket=get_settings().s3_bucket, Prefix=key).get("Contents")
    assert client.get("/api/v1/me").status_code == 200
    delete_data(job["id"])
    assert receipt(client, job).json()["data"]["status"] == "succeeded"

    export = client.post(
        "/api/v1/exports", headers={"Idempotency-Key": str(uuid4())}, json={"include_files": True}
    ).json()["data"]
    from io import BytesIO
    from zipfile import ZipFile

    from app.workers.exports import export_workspace

    export_workspace(export["id"])
    downloaded = client.get(f"/api/v1/exports/{export['id']}/download")
    assert downloaded.status_code == 200, downloaded.text
    with ZipFile(BytesIO(downloaded.content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["files"] == [] and manifest["missing_files"][0]["paper_file_id"] == file_id


def test_file_deletion_releases_quota_only_after_bytes_are_erased(account_factory, object_store, monkeypatch):
    import hashlib

    client, _ = account_factory()
    data = pdf_bytes()
    monkeypatch.setattr(get_settings(), "workspace_quota_bytes", len(data))
    original = upload(client, data)

    def reserve():
        return client.post(
            "/api/v1/papers/upload-init",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "title": "Replacement",
                "filename": "replacement.pdf",
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )

    assert reserve().status_code == 413
    job = execute(client, preview(client, "file", original["paper_file_id"])).json()["data"]
    assert reserve().status_code == 413  # Bytes are still present while cleanup is pending.
    delete_data(job["id"])
    assert receipt(client, job).json()["data"]["status"] == "succeeded"
    replacement = reserve()
    assert replacement.status_code == 201
    assert replacement.json()["data"]["duplicates"] == []
    assert reserve().status_code == 413  # The new unfinished upload reserves its quota.


def test_full_account_cleanup_cycles_history_other_space_and_receipt(account_factory, object_store, db_admin):
    client, account = account_factory()
    bob, _ = account_factory("bob@example.com")
    item = project(client)
    line = thread(client, item)
    values = upload(client, pdf_bytes())
    source = evidence(client, line, values)
    hypothesis = client.post(
        f"/api/v1/threads/{line['id']}/hypotheses",
        headers={"Idempotency-Key": str(uuid4())},
        json={"statement": "Possible improvement"},
    ).json()["data"]
    decision = client.post(
        f"/api/v1/threads/{line['id']}/decisions",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Adopt",
            "reason": "Validate",
            "decision_type": "adopt",
            "evidence_ids": [source["id"]],
            "hypothesis_ids": [hypothesis["id"]],
        },
    ).json()["data"]
    client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Act",
            "project_id": item["id"],
            "thread_id": line["id"],
            "decision_id": decision["id"],
        },
    )
    job_response = execute(client, preview(client))
    assert job_response.status_code == 202, job_response.text
    job = job_response.json()["data"]
    assert client.get("/api/v1/me").status_code == 401
    delete_data(job["id"])
    result = receipt(client, job)
    assert result.json()["data"]["status"] == "succeeded", result.text
    assert not db_admin.execute("SELECT id FROM users WHERE id=%s", (account["id"],)).fetchone()
    assert not db_admin.execute(
        "SELECT id FROM workspaces WHERE id=%s", (account["workspace_id"],)
    ).fetchone()
    assert db_admin.execute(
        "SELECT workspace_id,requested_by,target_id,receipt_hash FROM deletion_jobs WHERE id=%s", (job["id"],)
    ).fetchone()[:3] == (None, None, None)
    for prefix in ("final", "staging", "exports"):
        assert not object_store.list_objects_v2(
            Bucket=get_settings().s3_bucket, Prefix=f"{prefix}/{account['workspace_id']}/"
        ).get("Contents")
    assert bob.get("/api/v1/me").status_code == 200
    assert bob.get(f"/api/v1/deletions/{job['id']}").status_code == 404
    ledger = json.loads((ROOT / f"runtime/deletion-ledger/researchos_test/{job['id']}.json").read_text())
    assert ledger["scope"] == "account" and str(account["workspace_id"]) not in json.dumps(ledger)
    assert result.json()["data"]["backup_expiry_at"] is None


def test_cleanup_storage_failure_retry_does_not_report_success(account_factory, object_store, monkeypatch):
    client, _ = account_factory()
    upload(client, pdf_bytes())
    job = execute(client, preview(client)).json()["data"]
    from app.workers import deletions

    actual = deletions.remove_prefix

    def unavailable(prefix, **kwargs):
        raise OSError("temporary storage failure")

    monkeypatch.setattr(deletions, "remove_prefix", unavailable)
    delete_data(job["id"])
    status = receipt(client, job).json()["data"]
    assert status["status"] == "queued" and status["online_finished_at"] is None
    assert client.get("/api/v1/me").status_code == 401
    monkeypatch.setattr(deletions, "remove_prefix", actual)
    delete_data(job["id"])
    assert receipt(client, job).json()["data"]["status"] == "succeeded"


def test_account_cleanup_completes_its_pending_file_receipts(account_factory, object_store, db_admin):
    client, _ = account_factory()
    file = upload(client, pdf_bytes())
    pending = execute(client, preview(client, "file", file["paper_file_id"])).json()["data"]
    account = execute(client, preview(client)).json()["data"]
    delete_data(account["id"])
    for job in (pending, account):
        status = receipt(client, job).json()["data"]
        assert status["status"] == "succeeded" and status["online_finished_at"] is not None
        assert db_admin.execute(
            "SELECT workspace_id,requested_by,target_id,lease_owner,attempt_token,lease_expires_at "
            "FROM deletion_jobs WHERE id=%s",
            (job["id"],),
        ).fetchone() == (None, None, None, None, None, None)
    # Redelivery of the superseded file task remains a harmless no-op.
    delete_data(pending["id"])
    assert receipt(client, pending).json()["data"]["status"] == "succeeded"


def test_signed_ledger_replay_erases_restored_account_and_rejects_tamper(
    account_factory, object_store, db_admin, tmp_path, ledger_admin
):
    client, account = account_factory()
    project(client)
    original_user = db_admin.execute("SELECT * FROM users WHERE id=%s", (account["id"],))
    user_columns = [column.name for column in original_user.description]
    user_data = original_user.fetchone()
    original_workspace = db_admin.execute("SELECT * FROM workspaces WHERE id=%s", (account["workspace_id"],))
    workspace_columns = [column.name for column in original_workspace.description]
    workspace_data = original_workspace.fetchone()
    job = execute(client, preview(client)).json()["data"]
    delete_data(job["id"])
    assert receipt(client, job).json()["data"]["status"] == "succeeded"
    db_admin.execute(
        f"INSERT INTO users ({','.join(user_columns)}) VALUES ({','.join(['%s'] * len(user_columns))})",
        user_data,
    )
    db_admin.execute(
        f"INSERT INTO workspaces ({','.join(workspace_columns)}) VALUES ({','.join(['%s'] * len(workspace_columns))})",
        workspace_data,
    )
    from app.workers.deletions import cleanup_engine, replay_ledger

    ledger = json.loads((ROOT / f"runtime/deletion-ledger/researchos_test/{job['id']}.json").read_text())
    copied = tmp_path / "ledger.json"
    copied.write_text(json.dumps(ledger), encoding="utf-8")
    assert replay_ledger(cleanup_engine(), tmp_path, "researchos_test") == 1
    assert not db_admin.execute("SELECT id FROM users WHERE id=%s", (account["id"],)).fetchone()
    # Local mirrors are not authoritative; corruption in the independent
    # current journal must prevent replay even when every mirror is present.
    ledger_admin.execute("UPDATE public.ledger_entries SET signature=repeat('f',64)")
    import pytest

    with pytest.raises(ValueError, match="LEDGER_CHAIN_INTEGRITY_FAILURE"):
        replay_ledger(cleanup_engine(), tmp_path, "researchos_test")
