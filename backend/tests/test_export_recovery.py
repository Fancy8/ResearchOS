import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

from test_identity_research import project, thread
from test_papers_evidence import evidence, pdf_bytes, upload


def create(client, key, include_files=False):
    return client.post(
        "/api/v1/exports", headers={"Idempotency-Key": key}, json={"include_files": include_files}
    )


def test_export_replay_after_completion_preserves_archive_and_snapshot(
    account_factory, object_store, db_admin
):
    client, _ = account_factory()
    first_project = project(client)
    key = str(uuid4())
    accepted = create(client, key)
    assert accepted.status_code == 202, accepted.text
    job = accepted.json()["data"]["id"]
    from app.workers.exports import export_workspace

    export_workspace(job)
    current = client.get(f"/api/v1/exports/{job}").json()["data"]
    assert current["status"] == "succeeded"
    archive = client.get(f"/api/v1/exports/{job}/download")
    assert archive.status_code == 200
    assert hashlib.sha256(archive.content).hexdigest() == archive.headers["x-archive-sha256"]
    project(client, "Created after the original export")
    replay = create(client, key)
    assert replay.status_code == 202 and replay.json() == accepted.json()
    assert client.get(f"/api/v1/exports/{job}").json()["data"] == current
    assert client.get(f"/api/v1/exports/{job}/download").content == archive.content
    with ZipFile(BytesIO(archive.content)) as bundle:
        rows = json.loads(bundle.read("data/projects.json"))
        assert [row["id"] for row in rows] == [first_project["id"]]
        assert json.loads(bundle.read("manifest.json"))["include_files"] is False
    assert db_admin.execute("SELECT count(*) FROM export_jobs").fetchone()[0] == 1
    assert (
        db_admin.execute("SELECT count(*) FROM outbox_events WHERE event_type='export_workspace'").fetchone()[
            0
        ]
        == 1
    )


def test_same_key_concurrent_export_is_one_job_and_changed_options_conflict(
    account_factory, object_store, db_admin
):
    client, _ = account_factory()
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: create(client, key), range(3)))
    assert all(result.status_code == 202 for result in results)
    assert all(result.json() == results[0].json() for result in results)
    conflict = create(client, key, True)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert db_admin.execute("SELECT count(*) FROM export_jobs").fetchone()[0] == 1


def test_active_export_rejection_does_not_consume_new_intent_key(account_factory, object_store, db_admin):
    client, _ = account_factory()
    first = create(client, str(uuid4())).json()["data"]
    second_key = str(uuid4())
    blocked = create(client, second_key, True)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "EXPORT_IN_PROGRESS"
    assert (
        db_admin.execute("SELECT count(*) FROM api_idempotency_keys WHERE key=%s", (second_key,)).fetchone()[
            0
        ]
        == 0
    )
    from app.workers.exports import export_workspace

    export_workspace(first["id"])
    second = create(client, second_key, True)
    assert second.status_code == 202 and second.json()["data"]["id"] != first["id"]
    assert second.json()["data"]["include_files"] is True


def test_failed_or_expired_job_replay_never_restarts_it(account_factory, object_store, db_admin):
    client, _ = account_factory()
    from app.workers.exports import export_workspace

    for status in ["failed", "expired"]:
        key = str(uuid4())
        accepted = create(client, key)
        job = accepted.json()["data"]["id"]
        export_workspace(job)
        # Precise fixture state, not a claim that a real exporter failure occurred.
        db_admin.execute(
            "UPDATE export_jobs SET status=%s,expires_at=now()-interval '1 second' WHERE id=%s", (status, job)
        )
        replay = create(client, key)
        assert replay.json() == accepted.json()
        assert client.get(f"/api/v1/exports/{job}").json()["data"]["status"] == status
        assert client.get(f"/api/v1/exports/{job}/download").status_code == 409
    assert db_admin.execute("SELECT count(*) FROM export_jobs").fetchone()[0] == 2


def test_export_replay_key_is_private_to_actor_and_workspace(account_factory, object_store):
    alice, _ = account_factory("export-alice@example.com")
    bob, _ = account_factory("export-bob@example.com")
    key = str(uuid4())
    a, b = create(alice, key), create(bob, key)
    assert a.status_code == b.status_code == 202
    a_id, b_id = a.json()["data"]["id"], b.json()["data"]["id"]
    assert a_id != b_id
    for client, foreign_id in [(alice, b_id), (bob, a_id)]:
        assert client.get(f"/api/v1/exports/{foreign_id}").status_code == 404
        assert client.get(f"/api/v1/exports/{foreign_id}/download").status_code == 404


def test_records_only_export_preserves_unavailable_referenced_source_without_claiming_pdf_inclusion(
    account_factory, object_store, db_admin, tmp_path
):
    client, _ = account_factory()
    item = project(client)
    line = thread(client, item)
    file = upload(client, pdf_bytes())
    source = evidence(client, line, file)
    # A precise metadata-unavailability fixture; source identity and evidence stay immutable.
    db_admin.execute(
        "UPDATE paper_files SET availability_status='missing' WHERE id=%s", (file["paper_file_id"],)
    )
    from app.workers.exports import export_workspace

    full = create(client, str(uuid4()), True).json()["data"]
    export_workspace(full["id"])
    failed = client.get(f"/api/v1/exports/{full['id']}").json()["data"]
    assert failed["status"] == "failed" and failed["error_code"] == "EXPORT_REQUIRED_FILE_UNAVAILABLE"
    assert client.get(f"/api/v1/exports/{full['id']}/download").status_code == 409
    records = create(client, str(uuid4()), False).json()["data"]
    export_workspace(records["id"])
    current = client.get(f"/api/v1/exports/{records['id']}").json()["data"]
    assert current["status"] == "succeeded", current
    archive = client.get(f"/api/v1/exports/{records['id']}/download")
    assert archive.status_code == 200
    with ZipFile(BytesIO(archive.content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["include_files"] is False and manifest["files"] == []
        assert manifest["missing_files"] == [
            {"paper_file_id": file["paper_file_id"], "reason": "referenced_version_unavailable"}
        ]
        evidence_rows = json.loads(bundle.read("data/evidence.json"))
        file_rows = json.loads(bundle.read("data/paper_files.json"))
        assert (
            evidence_rows[0]["id"] == source["id"]
            and evidence_rows[0]["paper_file_id"] == file["paper_file_id"]
        )
        assert file_rows[0]["availability_status"] == "missing" and file_rows[0]["sha256"]
        assert not any(name.startswith("files/") for name in bundle.namelist())
    from app.recovery.archive import archive_document

    saved = tmp_path / "records-only-unavailable.zip"
    saved.write_bytes(archive.content)
    checked_manifest, tables = archive_document(saved)
    assert checked_manifest["include_files"] is False
    assert tables["evidence"][0]["paper_file_id"] == file["paper_file_id"]
