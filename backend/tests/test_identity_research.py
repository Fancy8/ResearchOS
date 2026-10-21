from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest


def project(client, title="隐私保护空间众包"):
    result = client.post("/api/v1/projects", json={"title": title})
    assert result.status_code == 201, result.text
    return result.json()["data"]


def thread(client, item):
    result = client.post(
        f"/api/v1/projects/{item['id']}/threads",
        json={"title": "查询价值", "question": "哪些查询可以改善分配决策？"},
    )
    assert result.status_code == 201, result.text
    return result.json()["data"]


def test_real_postgres_domain_and_maintenance_tables_and_role(db_admin, db_app):
    assert db_admin.execute("SHOW server_version").fetchone()[0].startswith("16.")
    names = {
        row[0]
        for row in db_admin.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename<>'alembic_version'"
        )
    }
    assert len(names) == 36 and "maintenance_checkpoints" in names
    assert db_app.execute("SELECT current_user").fetchone()[0] == "researchos_app"
    assert db_admin.execute(
        "SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"
    ).fetchone() == (False, False, False)
    assert not db_app.execute(
        "SELECT has_table_privilege(current_user,'decision_revisions','UPDATE')"
    ).fetchone()[0]
    assert not db_app.execute(
        "SELECT has_table_privilege(current_user,'maintenance_checkpoints','SELECT')"
    ).fetchone()[0]


def test_requires_invite_and_origin(client):
    data = {"email": "new@example.com", "password": "ResearchOS-test-2026", "display_name": "测试"}
    assert client.post("/api/v1/auth/register", json=data).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/register", headers={"Origin": "http://localhost:3000"}, json=data
        ).status_code
        == 403
    )


def test_session_logout_and_private_response(account_factory):
    client, user = account_factory()
    response = client.get("/api/v1/me")
    assert response.status_code == 200 and response.json()["data"]["id"] == user["id"]
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/projects").status_code == 401


def test_write_requires_csrf(account_factory):
    client, _ = account_factory()
    client.headers["X-CSRF-Token"] = "invalid"
    assert client.post("/api/v1/projects", json={"title": "不能写入"}).status_code == 403


def test_dashboard_preferences_are_scoped_validated_and_ordered(account_factory):
    client, _ = account_factory()
    other, _ = account_factory("other@example.com")
    item, foreign = project(client), project(other)
    profile = client.get("/api/v1/research-profile").json()["data"]
    for value in (
        {item["id"]: {"pinned": ["unknown"]}},
        {item["id"]: {"pinned": ["tasks", "tasks"]}},
        {item["id"]: []},
        {"invalid": {"pinned": []}},
    ):
        response = client.patch(
            "/api/v1/research-profile",
            json={"expected_version": profile["version"], "dashboard_preferences": value},
        )
        assert response.status_code == 422, response.text
    assert (
        client.patch(
            "/api/v1/research-profile",
            json={
                "expected_version": profile["version"],
                "dashboard_preferences": {foreign["id"]: {"pinned": ["tasks"]}},
            },
        ).status_code
        == 404
    )
    response = client.patch(
        "/api/v1/research-profile",
        json={
            "expected_version": profile["version"],
            "dashboard_preferences": {item["id"]: {"pinned": ["tasks", "activity"]}},
        },
    )
    assert response.status_code == 200, response.text
    dashboard = client.get(f"/api/v1/dashboard?project_id={item['id']}").json()["data"]
    assert dashboard["module_order"] == ["tasks", "activity", "threads"]


def test_validation_does_not_echo_password(client):
    secret = "short-secret"
    response = client.post(
        "/api/v1/auth/register",
        headers={"Origin": "http://localhost:3000"},
        json={"email": "bad", "password": secret, "display_name": "x"},
    )
    assert response.status_code == 422 and secret not in response.text


def test_workspace_isolation_lists_details_and_writes(account_factory):
    alice, _ = account_factory("alice@example.com")
    bob, _ = account_factory("bob@example.com")
    item = project(alice)
    line = thread(alice, item)
    assert bob.get("/api/v1/projects").json()["data"] == []
    for path in (
        f"/api/v1/projects/{item['id']}",
        f"/api/v1/threads/{line['id']}",
        f"/api/v1/threads/{line['id']}/revisions",
    ):
        assert bob.get(path).status_code == 404
    assert (
        bob.post(
            f"/api/v1/projects/{item['id']}/threads", json={"title": "bad", "question": "bad"}
        ).status_code
        == 404
    )
    assert (
        bob.patch(f"/api/v1/projects/{item['id']}", json={"expected_version": 1, "title": "bad"}).status_code
        == 404
    )


def test_reject_client_workspace_injection(account_factory):
    client, _ = account_factory()
    assert (
        client.post("/api/v1/projects", json={"title": "bad", "workspace_id": str(uuid4())}).status_code
        == 422
    )


def test_thread_question_history_and_stale_version(account_factory):
    client, _ = account_factory()
    item = project(client)
    line = thread(client, item)
    response = client.patch(
        f"/api/v1/threads/{line['id']}", json={"expected_version": 1, "question": "新的研究问题"}
    )
    assert response.status_code == 200 and response.json()["data"]["current_revision"] == 2
    stale = client.patch(
        f"/api/v1/threads/{line['id']}", json={"expected_version": 1, "question": "过期覆盖"}
    )
    assert stale.status_code == 409
    history = client.get(f"/api/v1/threads/{line['id']}/revisions").json()["data"]
    assert len(history) == 2 and history[1]["question"] == line["question"]


def test_database_rejects_cross_workspace_thread(account_factory, db_app):
    alice, _ = account_factory("alice@example.com")
    _, bob = account_factory("bob@example.com")
    item = project(alice)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db_app.execute(
            "INSERT INTO research_threads(id,workspace_id,project_id,title,question) VALUES(%s,%s,%s,'bad','bad')",
            (uuid4(), bob["workspace_id"], item["id"]),
        )


def test_missing_current_revision_database_rejected(account_factory, db_app):
    client, _ = account_factory()
    item = project(client)
    line = thread(client, item)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db_app.execute("UPDATE research_threads SET current_revision=99 WHERE id=%s", (line["id"],))


def test_default_project_and_archive_restore(account_factory):
    client, _ = account_factory()
    first, second = project(client, "A"), project(client, "B")
    assert first["is_default"] and not second["is_default"]
    assert client.post(f"/api/v1/projects/{second['id']}/set-default").status_code == 200
    response = client.patch(
        f"/api/v1/projects/{second['id']}", json={"expected_version": 1, "status": "archived"}
    )
    assert response.status_code == 200 and not response.json()["data"]["is_default"]
    assert response.json()["data"]["archived_at"]
    assert client.post(f"/api/v1/projects/{second['id']}/set-default").status_code == 409
    assert (
        client.patch(
            f"/api/v1/projects/{second['id']}", json={"expected_version": 2, "status": "active"}
        ).status_code
        == 200
    )


def test_onboarding_idempotency_conflicting_request(account_factory, db_admin):
    client, _ = account_factory()
    body = {"project_title": "新课题", "question": "问题 A"}
    headers = {"Idempotency-Key": str(uuid4())}
    first = client.put("/api/v1/onboarding", headers=headers, json=body)
    second = client.put("/api/v1/onboarding", headers=headers, json=body)
    assert first.status_code == second.status_code == 200 and first.json() == second.json()
    assert (
        client.put("/api/v1/onboarding", headers=headers, json={**body, "question": "问题 B"}).status_code
        == 409
    )
    assert db_admin.execute("SELECT count(*) FROM projects").fetchone()[0] == 1


def test_stable_cursor_scope_and_pagination(account_factory):
    client, _ = account_factory()
    for index in range(4):
        project(client, str(index))
    page1 = client.get("/api/v1/projects?limit=2").json()
    page2 = client.get("/api/v1/projects", params={"limit": 2, "cursor": page1["meta"]["next_cursor"]}).json()
    assert len(page1["data"] + page2["data"]) == 4
    assert len({row["id"] for row in page1["data"] + page2["data"]}) == 4
    assert client.get("/api/v1/projects?cursor=bad").status_code == 422


def test_parallel_version_edits_one_conflict(account_factory):
    client, _ = account_factory()
    item = project(client)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda title: (
                    client.patch(
                        f"/api/v1/projects/{item['id']}", json={"expected_version": 1, "title": title}
                    ).status_code
                ),
                ["left", "right"],
            )
        )
    assert sorted(results) == [200, 409]
