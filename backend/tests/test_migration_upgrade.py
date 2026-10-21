from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from test_maintenance import completed_export
from test_papers_evidence import evidence, pdf_bytes, upload
from test_workflow import create, workflow

from alembic import command
from app.core.config import ROOT, get_settings
from app.recovery.archive import ORDER, reconstruct_archive


def content_snapshot(target):
    with psycopg.connect(
        target.render_as_string(hide_password=False).replace("postgresql+psycopg", "postgresql")
    ) as db:
        return {
            name: db.execute(
                sql.SQL("SELECT to_jsonb(t) FROM public.{} t ORDER BY to_jsonb(t)::text").format(
                    sql.Identifier(name)
                )
            ).fetchall()
            for name in ORDER
        }


@pytest.mark.parametrize("recovery_target", ["0007"], indirect=True)
def test_existing_research_history_and_originals_survive_0008_upgrade(
    account_factory, object_store, recovery_target
):
    client, _ = account_factory()
    project, line, _, _, body, decision = workflow(client)
    task = create(
        client,
        "/api/v1/tasks",
        {
            "title": "Pre-upgrade task",
            "project_id": project["id"],
            "thread_id": line["id"],
            "decision_id": decision["id"],
        },
    )
    first = upload(client, pdf_bytes())
    source = evidence(client, line, first)
    upload(client, pdf_bytes(text="New source version"), first["paper_id"])
    create(
        client,
        f"/api/v1/decisions/{decision['id']}/revisions",
        {
            **body,
            "expected_revision": 1,
            "reason": "Second immutable revision",
            "evidence_ids": [source["id"]],
        },
    )
    exported = completed_export(client)
    archive = ROOT / f"artifacts/upgrade-0007-{uuid4()}.zip"
    response = client.get(f"/api/v1/exports/{exported['id']}/download")
    assert response.status_code == 200
    archive.write_bytes(response.content)
    reconstructed = reconstruct_archive(
        archive,
        recovery_target["admin"],
        object_store,
        recovery_target["bucket"],
        "ResearchOS-upgrade-test-2026",
    )
    assert reconstructed["objects_restored"] == 2
    before = content_snapshot(recovery_target["admin"])
    settings, original_url = get_settings(), get_settings().admin_database_url
    try:
        settings.admin_database_url = recovery_target["admin"].render_as_string(hide_password=False)
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "0008")
    finally:
        settings.admin_database_url = original_url
    assert content_snapshot(recovery_target["admin"]) == before
    with psycopg.connect(
        recovery_target["admin"]
        .render_as_string(hide_password=False)
        .replace("postgresql+psycopg", "postgresql")
    ) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0008"
        assert (
            db.execute("SELECT source_revision_no FROM tasks WHERE id=%s", (task["id"],)).fetchone()[0] == 1
        )
        assert db.execute("SELECT count(*) FROM decision_revisions").fetchone()[0] == 2
        assert not db.execute(
            "SELECT has_table_privilege('researchos_app','maintenance_checkpoints','SELECT')"
        ).fetchone()[0]
        for key, size in db.execute("SELECT storage_key,size_bytes FROM paper_files"):
            assert (
                object_store.head_object(Bucket=recovery_target["bucket"], Key=key)["ContentLength"] == size
            )
