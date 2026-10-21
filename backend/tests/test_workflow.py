from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from test_identity_research import project, thread


def create(client, path, body):
    response = client.post(path, json=body, headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def workflow(client):
    item = project(client)
    line = thread(client, item)
    note = create(
        client,
        "/api/v1/notes",
        {
            "title": "方法比较",
            "content": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "原始依据"}]}],
            },
        },
    )
    hypothesis = create(
        client, f"/api/v1/threads/{line['id']}/hypotheses", {"statement": "查询价值可能改善完成率"}
    )
    body = {
        "title": "开展对照",
        "decision_type": "adopt",
        "reason": "需要与等预算方法比较",
        "hypothesis_ids": [hypothesis["id"]],
        "note_ids": [note["id"]],
    }
    decision = create(client, f"/api/v1/threads/{line['id']}/decisions", body)
    return item, line, note, hypothesis, body, decision


def test_decision_snapshots_survive_note_hypothesis_edits(account_factory):
    client, _ = account_factory()
    item, line, note, hypothesis, body, decision = workflow(client)
    assert (
        client.patch(
            f"/api/v1/hypotheses/{hypothesis['id']}",
            json={"expected_version": 1, "statement": "新判断", "status": "inconclusive"},
        ).status_code
        == 200
    )
    content = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "新依据"}]}],
    }
    assert (
        client.put(
            f"/api/v1/notes/{note['id']}",
            json={"title": note["title"], "expected_version": 1, "content": content},
        ).status_code
        == 200
    )
    old = client.get(f"/api/v1/decisions/{decision['id']}/revisions/1").json()["data"]
    assert old["hypotheses"][0]["statement_snapshot"] == hypothesis["statement"]
    assert old["notes"][0]["content_snapshot"] == note["content"]
    assert old["reason"] == body["reason"]


def test_decision_concurrency_and_immutable_role(account_factory, db_app):
    client, _ = account_factory()
    _, _, _, _, body, decision = workflow(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(
            pool.map(
                lambda reason: (
                    client.post(
                        f"/api/v1/decisions/{decision['id']}/revisions",
                        json={**body, "expected_revision": 1, "reason": reason},
                        headers={"Idempotency-Key": str(uuid4())},
                    ).status_code
                ),
                ["依据 A", "依据 B"],
            )
        )
    assert sorted(codes) == [201, 409]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db_app.execute(
            "UPDATE decision_revisions SET reason='overwrite' WHERE decision_id=%s", (decision["id"],)
        )


def test_task_revision_provenance_complete_reopen(account_factory):
    client, _ = account_factory()
    item, line, _, _, body, decision = workflow(client)
    task = create(
        client,
        "/api/v1/tasks",
        {
            "project_id": item["id"],
            "thread_id": line["id"],
            "decision_id": decision["id"],
            "title": "完成对照",
            "due_date": "2026-10-20",
        },
    )
    create(
        client,
        f"/api/v1/decisions/{decision['id']}/revisions",
        {**body, "expected_revision": 1, "reason": "改进实验"},
    )
    assert client.get(f"/api/v1/tasks/{task['id']}").json()["data"]["source_revision_no"] == 1
    done = client.patch(f"/api/v1/tasks/{task['id']}", json={"expected_version": 1, "status": "done"})
    assert done.status_code == 200 and done.json()["data"]["completed_at"]
    reopened = client.patch(
        f"/api/v1/tasks/{task['id']}", json={"expected_version": 2, "status": "todo", "due_date": None}
    )
    assert reopened.status_code == 200 and reopened.json()["data"]["completed_at"] is None


def test_note_conflict_soft_delete_restore(account_factory):
    client, _ = account_factory()
    note = create(client, "/api/v1/notes", {"title": "笔记"})
    assert (
        client.put(
            f"/api/v1/notes/{note['id']}",
            json={"title": "保存", "content": {"type": "doc", "content": []}, "expected_version": 1},
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/v1/notes/{note['id']}",
            json={"title": "过期覆盖", "content": {"type": "doc", "content": []}, "expected_version": 1},
        ).status_code
        == 409
    )
    assert (
        client.request("DELETE", f"/api/v1/notes/{note['id']}", json={"expected_version": 2}).status_code
        == 200
    )
    assert client.get(f"/api/v1/notes/{note['id']}").status_code == 404
    assert client.post(f"/api/v1/notes/{note['id']}/restore", json={"expected_version": 3}).status_code == 200


def test_note_rejects_script_and_javascript_links(account_factory):
    client, _ = account_factory()
    for content in (
        {"type": "doc", "content": [{"type": "script", "text": "bad"}]},
        {
            "type": "doc",
            "content": [
                {
                    "type": "text",
                    "text": "bad",
                    "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                }
            ],
        },
    ):
        assert client.post("/api/v1/notes", json={"title": "bad", "content": content}).status_code == 422


def test_search_dashboard_and_activity_isolation(account_factory):
    alice, _ = account_factory("alice@example.com")
    bob, _ = account_factory("bob@example.com")
    item, line, *_ = workflow(alice)
    dashboard = alice.get(f"/api/v1/dashboard?project_id={item['id']}").json()["data"]
    assert dashboard["counts"]["threads"] == 1
    assert dashboard["counts"]["hypotheses"] == 1
    assert bob.get(f"/api/v1/dashboard?project_id={item['id']}").status_code == 404
    assert alice.get("/api/v1/search?q=方法").json()["data"]
    assert bob.get("/api/v1/search?q=方法").json()["data"] == []
    assert bob.get(f"/api/v1/activity?thread_id={line['id']}").status_code == 404


def test_decision_failure_rolls_back_everything(account_factory, db_admin):
    client, _ = account_factory()
    item = project(client)
    line = thread(client, item)
    response = client.post(
        f"/api/v1/threads/{line['id']}/decisions",
        headers={"Idempotency-Key": str(uuid4())},
        json={"title": "bad", "decision_type": "adopt", "reason": "bad", "hypothesis_ids": [str(uuid4())]},
    )
    assert response.status_code == 404
    assert db_admin.execute("SELECT count(*) FROM research_decisions").fetchone()[0] == 0
    assert db_admin.execute("SELECT count(*) FROM decision_revisions").fetchone()[0] == 0


def test_task_cross_project_rejected(account_factory):
    client, _ = account_factory()
    first, second = project(client, "A"), project(client, "B")
    line = thread(client, first)
    response = client.post(
        "/api/v1/tasks",
        headers={"Idempotency-Key": str(uuid4())},
        json={"project_id": second["id"], "thread_id": line["id"], "title": "bad"},
    )
    assert response.status_code == 409
