import os
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import boto3
import pytest
from moto import mock_aws
from test_maintenance import completed_export, expire_upload, pending_upload
from test_papers_evidence import pdf_bytes, upload

from app.core.config import ROOT, get_settings
from app.core.runtime_paths import runtime_namespace
from app.workers.deletions import remove_prefix
from app.workers.maintenance import maintenance_once
from app.workers.reconciliation import temp_page


class AgedObjects:
    """Control only server timestamp metadata; real storage performs every deletion."""

    def __init__(self, storage, aged):
        self.storage, self.aged = storage, set(aged)

    def __getattr__(self, name):
        return getattr(self.storage, name)

    def old(self, page):
        for kind in ("Contents", "Versions", "DeleteMarkers"):
            for row in page.get(kind, []):
                if row["Key"] in self.aged:
                    row["LastModified"] = datetime.now(UTC) - timedelta(days=2)
        return page

    def list_objects_v2(self, **kwargs):
        return self.old(self.storage.list_objects_v2(**kwargs))

    def list_object_versions(self, **kwargs):
        return self.old(self.storage.list_object_versions(**kwargs))


def put(storage, key, body=b"orphan bytes", bucket=None):
    storage.put_object(Bucket=bucket or get_settings().s3_bucket, Key=key, Body=body)


def keys(storage, prefix, bucket=None):
    return {
        row["Key"]
        for row in storage.list_objects_v2(Bucket=bucket or get_settings().s3_bucket, Prefix=prefix).get(
            "Contents", []
        )
    }


@contextmanager
def isolated_storage(real_storage, emulated=False):
    with mock_aws() if emulated else nullcontext():
        storage = (
            boto3.client(
                "s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test"
            )
            if emulated
            else real_storage
        )
        bucket = f"researchos-reconcile-test-{uuid4().hex[:10]}"
        storage.create_bucket(Bucket=bucket)
        try:
            yield storage, bucket
        finally:
            assert bucket.startswith("researchos-reconcile-test-") and bucket != get_settings().s3_bucket
            while True:
                page = storage.list_object_versions(Bucket=bucket, MaxKeys=1000)
                rows = page.get("Versions", []) + page.get("DeleteMarkers", [])
                if not rows:
                    break
                for row in rows:
                    storage.delete_object(Bucket=bucket, Key=row["Key"], VersionId=row["VersionId"])
            storage.delete_bucket(Bucket=bucket)


def test_reconciliation_removes_aged_remnants_preserves_sources_live_work_and_fresh_bytes(
    account_factory, object_store, db_admin
):
    client, account = account_factory()
    other, other_account = account_factory("other@example.com")
    old = upload(client, pdf_bytes())
    new = upload(client, pdf_bytes(text="New original"), old["paper_id"])
    exported = completed_export(client)
    active = pending_upload(client, pdf_bytes())
    queued = client.post(
        f"/api/v1/papers/{active['paper_id']}/upload-complete",
        headers={"Idempotency-Key": str(uuid4())},
        json={"upload_id": active["upload_id"]},
    )
    assert queued.status_code == 202
    abandoned = pending_upload(client, pdf_bytes())
    failed = client.post(
        f"/api/v1/papers/{abandoned['paper_id']}/upload-complete",
        headers={"Idempotency-Key": str(uuid4())},
        json={"upload_id": abandoned["upload_id"]},
    ).json()["data"]
    db_admin.execute("UPDATE processing_jobs SET attempts=max_attempts WHERE id=%s", (failed["job_id"],))
    from app.workers.jobs import parse_pdf

    parse_pdf(failed["job_id"])
    db_admin.execute(
        "UPDATE upload_sessions SET expires_at=now()-interval '2 days' WHERE id=%s", (abandoned["upload_id"],)
    )
    workspace = account["workspace_id"]
    source_keys = {
        row[0]
        for row in db_admin.execute(
            "SELECT storage_key FROM paper_files WHERE id IN (%s,%s)",
            (old["paper_file_id"], new["paper_file_id"]),
        )
    }
    published_export = db_admin.execute(
        "SELECT storage_key FROM export_jobs WHERE id=%s", (exported["id"],)
    ).fetchone()[0]
    orphan = f"final/{workspace}/{old['paper_id']}/{old['paper_file_id']}-{uuid4()}.pdf"
    in_progress = f"final/{workspace}/{active['paper_id']}/{active['paper_file_id']}-{uuid4()}.pdf"
    fresh = f"final/{workspace}/{uuid4()}/{uuid4()}-{uuid4()}.pdf"
    complete_staging = f"staging/{workspace}/{old['upload_id']}.pdf"
    active_staging = f"staging/{workspace}/{active['upload_id']}.pdf"
    failed_staging = f"staging/{workspace}/{abandoned['upload_id']}.pdf"
    export_orphan = f"exports/{workspace}/{exported['id']}-{uuid4()}.zip"
    unfamiliar = f"final/{workspace}/operator-investigation.bin"
    other_marker = f"final/{other_account['workspace_id']}/preserve.bin"
    for key in (orphan, in_progress, fresh, complete_staging, export_orphan, unfamiliar, other_marker):
        put(object_store, key)
    aged = source_keys | {
        published_export,
        orphan,
        in_progress,
        complete_staging,
        active_staging,
        failed_staging,
        export_orphan,
        unfamiliar,
        other_marker,
    }
    report = maintenance_once(storage=AgedObjects(object_store, aged))
    assert report["workspaces_failed"] == 0
    assert report["orphan_objects_removed"] == 4
    retained = keys(object_store, f"final/{workspace}/")
    assert source_keys | {fresh, in_progress, unfamiliar} <= retained and orphan not in retained
    assert complete_staging not in keys(object_store, f"staging/{workspace}/")
    assert active_staging in keys(object_store, f"staging/{workspace}/")
    assert published_export in keys(object_store, f"exports/{workspace}/")
    assert other_marker in keys(object_store, f"final/{other_account['workspace_id']}/")
    assert (
        db_admin.execute(
            "SELECT status FROM upload_sessions WHERE id=%s", (abandoned["upload_id"],)
        ).fetchone()[0]
        == "failed"
    )
    assert (
        db_admin.execute(
            "SELECT upload_status FROM paper_files WHERE id=%s", (abandoned["paper_file_id"],)
        ).fetchone()[0]
        == "failed"
    )
    assert other.get("/api/v1/me").status_code == 200


def test_persisted_workspace_cursor_visits_later_space_while_first_stays_busy(
    account_factory, object_store, db_admin
):
    first = account_factory()
    second = account_factory("later@example.com")
    ordered = sorted((first, second), key=lambda item: item[1]["workspace_id"])
    waiting = pending_upload(ordered[0][0], pdf_bytes())
    later = pending_upload(ordered[1][0], pdf_bytes())
    for value in (waiting, later):
        expire_upload(db_admin, value)
    scope = f"resource:{ordered[0][1]['workspace_id']}"
    db_admin.execute("SELECT pg_advisory_lock_shared(hashtextextended(%s,0))", (scope,))
    try:
        assert maintenance_once(batch_size=1)["workspaces_busy"] == 1
        cursor, state = db_admin.execute(
            "SELECT workspace_id,state FROM maintenance_checkpoints WHERE name='artifact-maintenance'"
        ).fetchone()
        assert str(cursor) == ordered[0][1]["workspace_id"] and "workspace_after" not in state
        assert maintenance_once(batch_size=1)["uploads_expired"] == 1
        assert (
            db_admin.execute(
                "SELECT status FROM upload_sessions WHERE id=%s", (waiting["upload_id"],)
            ).fetchone()[0]
            == "pending"
        )
    finally:
        db_admin.execute("SELECT pg_advisory_unlock_shared(hashtextextended(%s,0))", (scope,))
    assert maintenance_once(batch_size=1)["uploads_expired"] == 1


def test_object_cursor_passes_fresh_first_item_and_resumes_after_deleted_key(
    account_factory, object_store, db_admin
):
    _, account = account_factory()
    prefix = f"staging/{account['workspace_id']}/"
    items = [f"{prefix}{UUID(int=number)}.pdf" for number in range(3)]
    for key in items:
        put(object_store, key)
    storage = AgedObjects(object_store, items[1:])
    assert maintenance_once(storage=storage, batch_size=1)["orphan_objects_removed"] == 0
    assert maintenance_once(storage=storage, batch_size=1)["orphan_objects_removed"] == 1
    assert maintenance_once(storage=storage, batch_size=1)["orphan_objects_removed"] == 1
    assert keys(object_store, prefix) == {items[0]}


@pytest.mark.parametrize("emulated", [False, True])
def test_versioned_reconciliation_pages_versions_and_delete_markers(
    account_factory, object_store, db_admin, emulated
):
    client, account = account_factory()
    paper = upload(client, pdf_bytes())
    retained = db_admin.execute(
        "SELECT storage_key FROM paper_files WHERE id=%s", (paper["paper_file_id"],)
    ).fetchone()[0]
    orphan = f"final/{account['workspace_id']}/{uuid4()}/{uuid4()}-{uuid4()}.pdf"
    with isolated_storage(object_store, emulated) as (storage, bucket):
        storage.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        for key in (orphan, retained):
            put(storage, key, bucket=bucket)
            put(storage, key, body=b"second version", bucket=bucket)
        storage.delete_object(Bucket=bucket, Key=orphan)
        removed = 0
        for _ in range(10):
            result = maintenance_once(
                storage=AgedObjects(storage, {orphan, retained}), bucket=bucket, batch_size=1
            )
            assert result["workspaces_failed"] == 0
            removed += result["orphan_objects_removed"]
        versions = storage.list_object_versions(Bucket=bucket)
        assert removed == 3
        assert len(versions["Versions"]) == 2 and {item["Key"] for item in versions["Versions"]} == {retained}
        assert not versions.get("DeleteMarkers")


@pytest.mark.parametrize("versioning", [None, "Enabled", "Suspended"])
def test_explicit_prefix_erasure_drains_small_pages_including_hidden_versions(object_store, versioning):
    prefix = f"final/{uuid4()}/"
    with isolated_storage(object_store) as (storage, bucket):
        if versioning:
            storage.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        for key in (prefix + "source.pdf", prefix + "second.pdf"):
            put(storage, key, bucket=bucket)
            put(storage, key, body=b"older version", bucket=bucket)
            storage.delete_object(Bucket=bucket, Key=key)
        if versioning == "Suspended":
            storage.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Suspended"})
            put(storage, prefix + "null-version.pdf", bucket=bucket)
        put(storage, "final/another-space/preserve.pdf", bucket=bucket)

        class SmallPages:
            def __getattr__(self, name):
                return getattr(storage, name)

            def list_object_versions(self, **kwargs):
                return storage.list_object_versions(**{**kwargs, "MaxKeys": 1})

            def list_objects_v2(self, **kwargs):
                return storage.list_objects_v2(**{**kwargs, "MaxKeys": 1})

        remove_prefix(prefix, storage=SmallPages(), bucket=bucket)
        versions = storage.list_object_versions(Bucket=bucket, Prefix=prefix)
        assert not versions.get("Versions") and not versions.get("DeleteMarkers")
        assert storage.head_object(Bucket=bucket, Key="final/another-space/preserve.pdf")["ContentLength"] > 0


def test_orphan_storage_failure_preserves_checkpoint_for_retry(account_factory, object_store, db_admin):
    _, account = account_factory()
    key = f"staging/{account['workspace_id']}/{uuid4()}.pdf"
    put(object_store, key)

    class FailedDelete(AgedObjects):
        def delete_object(self, **kwargs):
            raise OSError("storage unavailable")

    report = maintenance_once(storage=FailedDelete(object_store, {key}))
    assert report["workspaces_failed"] == 1 and report["orphan_objects_removed"] == 0
    assert key in keys(object_store, f"staging/{account['workspace_id']}/")
    assert not db_admin.execute(
        "SELECT name FROM maintenance_checkpoints WHERE workspace_id=%s AND name LIKE 'artifact-reconcile/%%'",
        (account["workspace_id"],),
    ).fetchone()
    report = maintenance_once(storage=AgedObjects(object_store, {key}))
    assert report["orphan_objects_removed"] == 1 and report["workspaces_failed"] == 0


def test_prefix_cleanup_rejects_successful_delete_that_leaves_bytes(account_factory, object_store):
    _, account = account_factory()
    prefix = f"staging/{account['workspace_id']}/"
    key = prefix + f"{uuid4()}.pdf"
    put(object_store, key)

    class IgnoredDelete:
        def __getattr__(self, name):
            return getattr(object_store, name)

        def delete_object(self, **kwargs):
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    with pytest.raises(RuntimeError, match="OBJECTS_REMAIN"):
        remove_prefix(prefix, storage=IgnoredDelete())
    assert key in keys(object_store, prefix)


def test_account_erasure_removes_scoped_and_global_maintenance_identity(
    account_factory, object_store, db_admin, db_app
):
    import psycopg
    from test_deletions import execute, preview, receipt

    from app.workers.deletions import delete_data

    client, account = account_factory()
    maintenance_once()
    assert (
        db_admin.execute(
            "SELECT count(*) FROM maintenance_checkpoints WHERE workspace_id=%s", (account["workspace_id"],)
        ).fetchone()[0]
        == 2
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db_app.execute("SELECT name,state FROM maintenance_checkpoints")
    request = execute(client, preview(client))
    assert request.status_code == 202
    job = request.json()["data"]
    delete_data(job["id"])
    assert receipt(client, job).json()["data"]["status"] == "succeeded"
    assert db_admin.execute("SELECT count(*) FROM maintenance_checkpoints").fetchone()[0] == 0


def test_temp_reconciliation_respects_job_status_age_namespace_and_nonfiles(
    account_factory, object_store, db_admin
):
    client, _ = account_factory()
    source = upload(client, pdf_bytes())
    done = db_admin.execute(
        "SELECT id FROM processing_jobs WHERE paper_file_id=%s", (source["paper_file_id"],)
    ).fetchone()[0]
    active = pending_upload(client, pdf_bytes())
    queued = client.post(
        f"/api/v1/papers/{active['paper_id']}/upload-complete",
        headers={"Idempotency-Key": str(uuid4())},
        json={"upload_id": active["upload_id"]},
    ).json()["data"]["job_id"]
    directory = runtime_namespace("pdf-tmp", "researchos_test")
    directory.mkdir(parents=True, exist_ok=True)
    done_path, active_path, orphan_path, fresh_path, fake_dir = [
        directory / f"{identifier}-{uuid4()}.pdf" for identifier in (done, queued, uuid4(), uuid4(), uuid4())
    ]
    foreign_dir = runtime_namespace("pdf-tmp", "researchos_foreign_" + uuid4().hex[:10])
    foreign_dir.mkdir(parents=True)
    foreign = foreign_dir / f"{uuid4()}-{uuid4()}.pdf"
    paths = [done_path, active_path, orphan_path, fresh_path, foreign]
    try:
        for path in paths:
            path.write_bytes(b"parser temporary data")
            if path != fresh_path:
                old = (datetime.now(UTC) - timedelta(days=2)).timestamp()
                os.utime(path, (old, old))
        fake_dir.mkdir()
        report = maintenance_once()
        assert report["temporary_files_removed"] == 2
        assert report["temporary_files_busy"] == 1 and report["temporary_files_blocked"] == 1
        assert not done_path.exists() and not orphan_path.exists()
        assert active_path.exists() and fresh_path.exists() and foreign.exists() and fake_dir.exists()
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
        fake_dir.rmdir()
        foreign_dir.rmdir()
    with pytest.raises(RuntimeError, match="TEMP_NAMESPACE_SCOPE_INVALID"):
        temp_page(ROOT.parent, "", 10, ".pdf")
