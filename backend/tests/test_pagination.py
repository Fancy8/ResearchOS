import base64
import json
from uuid import uuid4

import pytest
from sqlalchemy import event
from test_identity_research import project, thread
from test_papers_evidence import pdf_bytes, upload
from test_workflow import create, workflow


def pages(client, path, **params):
    rows, cursors = [], []
    for _ in range(50):
        result = client.get(path, params={"limit": 20, **params})
        assert result.status_code == 200, result.text
        page = result.json()
        rows.extend(page["data"])
        cursor = page["meta"]["next_cursor"]
        assert page["meta"]["has_more"] == bool(cursor)
        if not cursor:
            break
        assert cursor not in cursors
        cursors.append(cursor)
        params["cursor"] = cursor
    else:
        pytest.fail("pagination did not terminate")
    assert len({row["id"] for row in rows}) == len(rows)
    return rows, cursors


def tampered(cursor, index, value):
    data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    data[index] = value
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def test_papers_beyond_100_equal_timestamps_literal_search_and_batched_summary(account_factory, db_admin):
    client, user = account_factory()
    other, _ = account_factory("bob@example.com")
    workspace = user["workspace_id"]
    db_admin.execute(
        "INSERT INTO papers(workspace_id,title,created_at) SELECT %s,'文献 '||i,"
        "'2026-01-01T00:00:00Z' FROM generate_series(1,107) i",
        (workspace,),
    )
    special = create(client, "/api/v1/papers", {"title": r"旧文献 100%_中文\source"})
    db_admin.execute("UPDATE papers SET created_at='2025-01-01' WHERE id=%s", (special["id"],))
    foreign = create(other, "/api/v1/papers", {"title": special["title"]})
    rows, cursors = pages(client, "/api/v1/papers")
    assert len(rows) == 108 and rows[-1]["id"] == special["id"]
    assert foreign["id"] not in {row["id"] for row in rows}
    for q in ("100%_中文", r"中文\source", "  100%_中文  "):
        result = client.get("/api/v1/papers", params={"q": q}).json()
        assert [row["id"] for row in result["data"]] == [special["id"]]
    assert client.get("/api/v1/papers", params={"q": "中文", "cursor": cursors[0]}).status_code == 422
    assert other.get("/api/v1/papers", params={"cursor": cursors[0]}).status_code == 422
    assert client.get("/api/v1/papers", params={"q": "x" * 101}).status_code == 422

    from app.db.session import engine

    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if "paper_files" in statement.lower():
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        assert client.get("/api/v1/papers?limit=100").status_code == 200
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert len(statements) == 1  # One latest-file lookup for the whole page.


def test_current_project_outside_first_page_and_archived_default(account_factory, db_admin):
    client, user = account_factory()
    oldest = project(client, "旧默认课题")
    db_admin.execute(
        "INSERT INTO projects(workspace_id,title) SELECT %s,'新课题 '||i FROM generate_series(1,105) i",
        (user["workspace_id"],),
    )
    assert oldest["id"] not in {row["id"] for row in client.get("/api/v1/projects").json()["data"]}
    assert client.get("/api/v1/projects/current").json()["data"]["id"] == oldest["id"]
    assert len(pages(client, "/api/v1/projects")[0]) == 106
    assert (
        client.patch(
            f"/api/v1/projects/{oldest['id']}", json={"expected_version": 1, "status": "archived"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/projects/current").json()["data"]["id"] != oldest["id"]


def test_association_pages_kind_parent_workspace_binding_and_trash(account_factory, db_admin):
    client, user = account_factory()
    other, _ = account_factory("bob@example.com")
    first, second = project(client, "A"), project(client, "B")
    note = create(client, "/api/v1/notes", {"title": "共用"})
    for index in range(25):
        paper = create(client, "/api/v1/papers", {"title": f"文献{index}"})
        assert (
            client.post(f"/api/v1/projects/{first['id']}/paper-links", json={"id": paper["id"]}).status_code
            == 200
        )
        assert (
            client.post(f"/api/v1/notes/{note['id']}/paper-links", json={"id": paper["id"]}).status_code
            == 200
        )
    papers, cursors = pages(client, f"/api/v1/projects/{first['id']}/paper-links")
    linked, note_cursors = pages(client, f"/api/v1/notes/{note['id']}/links", kind="paper")
    assert len(papers) == len(linked) == 25
    assert (
        client.get(f"/api/v1/projects/{second['id']}/paper-links", params={"cursor": cursors[0]}).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/notes/{note['id']}/links", params={"kind": "project", "cursor": note_cursors[0]}
        ).status_code
        == 422
    )
    assert other.get(f"/api/v1/notes/{note['id']}/links?kind=paper").status_code == 404
    assert client.get(f"/api/v1/notes/{note['id']}/links").status_code == 422
    db_admin.execute(
        "INSERT INTO notes(workspace_id,title) SELECT %s,'笔记 '||i FROM generate_series(1,26) i",
        (user["workspace_id"],),
    )
    db_admin.execute(
        "INSERT INTO project_notes(workspace_id,project_id,note_id) SELECT workspace_id,%s,id FROM notes WHERE workspace_id=%s",
        (first["id"], user["workspace_id"]),
    )
    assert len(pages(client, f"/api/v1/projects/{first['id']}/note-links")[0]) == 27
    assert (
        client.request("DELETE", f"/api/v1/notes/{note['id']}", json={"expected_version": 1}).status_code
        == 200
    )
    assert len(pages(client, f"/api/v1/projects/{first['id']}/note-links")[0]) == 26
    assert client.get(f"/api/v1/notes/{note['id']}/links?kind=paper").status_code == 404


def test_revision_pages_use_revision_number_and_retain_original_task_basis(account_factory):
    client, _ = account_factory()
    item, line, note, hypothesis, body, decision = workflow(client)
    for revision in range(1, 25):
        assert (
            client.patch(
                f"/api/v1/threads/{line['id']}",
                json={"expected_version": revision, "question": f"问题{revision + 1}"},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/api/v1/hypotheses/{hypothesis['id']}",
                json={"expected_version": revision, "statement": f"判断{revision + 1}"},
            ).status_code
            == 200
        )
        create(
            client,
            f"/api/v1/decisions/{decision['id']}/revisions",
            {**body, "expected_revision": revision, "reason": f"理由{revision + 1}"},
        )
    for path in (f"threads/{line['id']}", f"hypotheses/{hypothesis['id']}", f"decisions/{decision['id']}"):
        rows, cursors = pages(client, f"/api/v1/{path}/revisions")
        assert [row["revision_no"] for row in rows] == list(range(25, 0, -1))
        for bad in (True, 0, 1.5, "25", 2147483648):
            assert (
                client.get(
                    f"/api/v1/{path}/revisions", params={"cursor": tampered(cursors[0], 0, bad)}
                ).status_code
                == 422
            )
    second = thread(client, item)
    cursor = client.get(f"/api/v1/threads/{line['id']}/revisions").json()["meta"]["next_cursor"]
    assert (
        client.get(f"/api/v1/threads/{second['id']}/revisions", params={"cursor": cursor}).status_code == 422
    )
    task = create(
        client,
        f"/api/v1/decisions/{decision['id']}/revisions/1/tasks",
        {"title": "原版本行动", "project_id": item["id"]},
    )
    assert task["source_revision_no"] == 1
    assert (
        client.get(f"/api/v1/decisions/{decision['id']}/revisions/1").json()["data"]["reason"]
        == body["reason"]
    )


def test_invalid_date_cursor_and_query_bounds(account_factory):
    client, _ = account_factory()
    for index in range(3):
        project(client, f"课题{index}")
    cursor = client.get("/api/v1/projects?limit=1").json()["meta"]["next_cursor"]
    for bad in (
        "bad",
        "x" * 2050,
        tampered(cursor, 0, "2026-01-01"),
        tampered(cursor, 1, 17),
        tampered(cursor, 1, str(uuid4()) + "bad"),
    ):
        assert client.get("/api/v1/projects", params={"cursor": bad}).status_code == 422
    for limit in (0, 101):
        assert client.get("/api/v1/projects", params={"limit": limit}).status_code == 422


def test_file_version_pages_are_numeric_and_parent_bound(account_factory, db_admin):
    client, user = account_factory()
    first = create(client, "/api/v1/papers", {"title": "多版本"})
    second = create(client, "/api/v1/papers", {"title": "另一文献"})
    db_admin.execute(
        "INSERT INTO paper_files(workspace_id,paper_id,version_no,storage_key,original_filename,size_bytes) "
        "SELECT %s,%s,i,'pagination-fixture/'||gen_random_uuid(),'pending.pdf',10 FROM generate_series(1,25) i",
        (user["workspace_id"], first["id"]),
    )
    rows, cursors = pages(client, f"/api/v1/papers/{first['id']}/files")
    assert [row["version_no"] for row in rows] == list(range(25, 0, -1))
    assert "storage_key" not in json.dumps(rows)
    assert (
        client.get(f"/api/v1/papers/{second['id']}/files", params={"cursor": cursors[0]}).status_code == 422
    )


def test_duplicates_skip_removed_original_and_summary_exposes_availability(
    account_factory, object_store, db_admin
):
    client, _ = account_factory()
    first = upload(client, pdf_bytes("old original"))
    second = upload(client, pdf_bytes("new original"), paper_id=first["paper_id"])
    sha = db_admin.execute(
        "SELECT sha256 FROM paper_files WHERE id=%s", (first["paper_file_id"],)
    ).fetchone()[0]
    found = client.get("/api/v1/papers/duplicates", params={"sha256": sha}).json()["data"]
    assert found[0]["paper_file_id"] == first["paper_file_id"]
    db_admin.execute(
        "UPDATE paper_files SET availability_status='missing' WHERE id=%s", (first["paper_file_id"],)
    )
    assert client.get("/api/v1/papers/duplicates", params={"sha256": sha}).json()["data"] == []
    db_admin.execute(
        "UPDATE paper_files SET availability_status='missing' WHERE id=%s", (second["paper_file_id"],)
    )
    summary = client.get("/api/v1/papers").json()["data"][0]["file"]
    assert summary["availability_status"] == "missing"
    assert "storage_key" not in json.dumps(summary)
