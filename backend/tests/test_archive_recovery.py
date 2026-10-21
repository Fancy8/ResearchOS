import json
import os
import subprocess
import sys
from uuid import uuid4

import psycopg
from test_identity_research import project, thread
from test_papers_evidence import evidence, pdf_bytes, upload

from app.core.config import ROOT
from app.recovery.archive import reconstruct_archive
from app.workers.exports import export_workspace


def test_archive_reconstructs_real_database_original_versions_and_all_snapshots(
    account_factory, object_store, recovery_target, db_admin
):
    client, account = account_factory()
    item = project(client)
    line = thread(client, item)
    first = upload(client, pdf_bytes())
    source = evidence(client, line, first)
    second = upload(client, pdf_bytes(text="New file version."), first["paper_id"])
    note = client.post(
        "/api/v1/notes",
        json={
            "title": "Original note",
            "content": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Original method"}]},
                    {"type": "blockMath", "attrs": {"latex": "x^2+y^2"}},
                ],
            },
        },
    ).json()["data"]
    hypothesis = client.post(
        f"/api/v1/threads/{line['id']}/hypotheses", json={"statement": "Original hypothesis"}
    ).json()["data"]
    decision = client.post(
        f"/api/v1/threads/{line['id']}/decisions",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Original decision",
            "decision_type": "adopt",
            "reason": "Original reason",
            "evidence_ids": [source["id"]],
            "hypothesis_ids": [hypothesis["id"]],
            "note_ids": [note["id"]],
        },
    ).json()["data"]
    task = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Original action",
            "project_id": item["id"],
            "thread_id": line["id"],
            "decision_id": decision["id"],
        },
    ).json()["data"]
    client.patch(
        f"/api/v1/hypotheses/{hypothesis['id']}",
        json={
            "expected_version": hypothesis["version"],
            "statement": "Later hypothesis",
            "status": "testing",
        },
    )
    client.put(
        f"/api/v1/notes/{note['id']}",
        json={
            "expected_version": note["version"],
            "title": "Later note",
            "content": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Later method"}]}],
            },
        },
    )
    client.post(
        f"/api/v1/decisions/{decision['id']}/revisions",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "expected_revision": 1,
            "title": "Later decision",
            "decision_type": "adjust",
            "reason": "Later reason",
            "evidence_ids": [source["id"]],
            "hypothesis_ids": [hypothesis["id"]],
            "note_ids": [note["id"]],
        },
    )
    job = client.post(
        "/api/v1/exports", headers={"Idempotency-Key": str(uuid4())}, json={"include_files": True}
    ).json()["data"]
    export_workspace(job["id"])
    archive = ROOT / f"artifacts/archive-reconstruction-{uuid4()}.zip"
    downloaded = client.get(f"/api/v1/exports/{job['id']}/download")
    assert downloaded.status_code == 200
    archive.write_bytes(downloaded.content)
    result = reconstruct_archive(
        archive, recovery_target["admin"], object_store, recovery_target["bucket"], "ResearchOS-restored-2026"
    )
    assert result["entity_tables"] == 27 and result["objects_restored"] == 2
    with psycopg.connect(
        recovery_target["admin"]
        .render_as_string(hide_password=False)
        .replace("postgresql+psycopg", "postgresql")
    ) as db:
        assert (
            db.execute("SELECT source_revision_no FROM tasks WHERE id=%s", (task["id"],)).fetchone()[0] == 1
        )
        assert (
            db.execute(
                "SELECT statement_snapshot FROM decision_revision_hypothesis_links l JOIN decision_revisions r ON r.id=l.decision_revision_id WHERE r.decision_id=%s AND r.revision_no=1",
                (decision["id"],),
            ).fetchone()[0]
            == "Original hypothesis"
        )
        original_note = db.execute(
            "SELECT content_snapshot FROM decision_revision_note_links l JOIN decision_revisions r ON r.id=l.decision_revision_id WHERE r.decision_id=%s AND r.revision_no=1",
            (decision["id"],),
        ).fetchone()[0]
        assert original_note["content"][1]["attrs"]["latex"] == "x^2+y^2"
        old = db.execute(
            "SELECT storage_key FROM paper_files WHERE id=%s", (first["paper_file_id"],)
        ).fetchone()[0]
        assert "-recovered-" in old
    probe = ROOT / f"runtime/tmp/recovery-probe-{uuid4()}.json"
    probe.write_text(
        json.dumps(
            {
                "email": account["email"],
                "password": "ResearchOS-restored-2026",
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
        "RESEARCHOS_S3_BUCKET": recovery_target["bucket"],
    }
    run = subprocess.run(
        [sys.executable, str(ROOT / "tools/probe_recovery.py"), str(probe)],
        env=env,
        cwd=ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    probe.unlink()
    assert run.returncode == 0, "Restored API probe failed; retain isolated recovery evidence"
    report = json.loads(run.stdout)
    assert report["old_source_readable"] and report["task_revision_preserved"] and report["history_readable"]
    (ROOT / "artifacts/archive-reconstruction-proof.json").write_text(
        json.dumps({**result, **report}, indent=2)
    )
