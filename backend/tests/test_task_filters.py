import pytest
from test_identity_research import project, thread
from test_pagination import pages
from test_workflow import create


def test_task_filters_combine_before_pagination_and_bind_cursor(account_factory, db_admin):
    client, user = account_factory()
    other, _ = account_factory("task-other@example.com")
    first, second = project(client, "First"), project(client, "Second")
    line = thread(client, first)
    foreign = project(other, "Foreign")
    # Equal timestamps exercise the UUID tie breaker; newer nonmatches must not
    # consume pages or hide the older matching records.
    db_admin.execute(
        "INSERT INTO tasks(workspace_id,project_id,thread_id,title,status,priority,due_date,created_at) "
        "SELECT %s,%s,%s,'match-'||i,'doing','high','2026-10-15','2025-01-01' "
        "FROM generate_series(1,43) i",
        (user["workspace_id"], first["id"], line["id"]),
    )
    for item, owner, status, priority, due in [
        (first, client, "todo", "high", "2026-10-15"),
        (first, client, "doing", "low", "2026-10-15"),
        (first, client, "doing", "high", None),
        (first, client, "doing", "high", "2026-10-14"),
        (first, client, "doing", "high", "2026-10-16"),
        (second, client, "doing", "high", "2026-10-15"),
        (foreign, other, "doing", "high", "2026-10-15"),
    ]:
        task = create(
            owner,
            "/api/v1/tasks",
            {
                "project_id": item["id"],
                "title": "Nonmatch",
                "priority": priority,
                "due_date": due,
            },
        )
        assert (
            owner.patch(
                f"/api/v1/tasks/{task['id']}",
                json={
                    "expected_version": 1,
                    "status": status,
                },
            ).status_code
            == 200
        )
    query = {
        "project_id": first["id"],
        "thread_id": line["id"],
        "status": "doing",
        "priority": "high",
        "due_from": "2026-10-15",
        "due_to": "2026-10-15",
    }
    rows, cursors = pages(client, "/api/v1/tasks", **query)
    assert len(rows) == 43 and len(cursors) == 2
    assert all(row["title"].startswith("match-") for row in rows)
    assert [row["id"] for row in rows] == sorted((row["id"] for row in rows), reverse=True)
    for key, value in [
        ("status", "todo"),
        ("priority", "low"),
        ("due_from", "2026-10-14"),
        ("due_to", "2026-10-16"),
        ("project_id", second["id"]),
        ("thread_id", None),
    ]:
        changed = {**query, key: value, "cursor": cursors[0]}
        changed = {key: value for key, value in changed.items() if value is not None}
        response = client.get("/api/v1/tasks", params=changed)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_CURSOR"
    # Cursor from another space is rejected even with otherwise identical filters.
    response = other.get("/api/v1/tasks", params={"status": "doing", "cursor": cursors[0]})
    assert response.status_code == 422
    assert client.get("/api/v1/tasks", params={"project_id": foreign["id"]}).status_code == 404
    assert other.get("/api/v1/tasks", params={"thread_id": line["id"]}).status_code == 404
    assert (
        len(
            pages(
                client,
                "/api/v1/tasks",
                status="doing",
                priority="high",
                due_from="2026-10-15",
                due_to="2026-10-15",
            )[0]
        )
        == 44
    )
    assert len(pages(client, "/api/v1/tasks", project_id=first["id"], due_to="2026-10-15")[0]) == 46


@pytest.mark.parametrize(
    "query",
    [
        {"status": "finished"},
        {"priority": "urgent"},
        {"due_from": "2026-02-30"},
        {"due_to": "not-a-date"},
        {"due_from": "2026-10-16", "due_to": "2026-10-15"},
    ],
)
def test_task_filter_validation(account_factory, query):
    client, _ = account_factory()
    response = client.get("/api/v1/tasks", params=query)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
