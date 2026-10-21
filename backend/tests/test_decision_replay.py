from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from test_identity_research import project, thread
from test_workflow import create, workflow


def test_decision_create_receipt_survives_basis_edits_and_note_trash(account_factory):
    client, _ = account_factory()
    _, line, note, hypothesis, body, _ = workflow(client)
    path = f"/api/v1/threads/{line['id']}/decisions"
    headers = {"Idempotency-Key": str(uuid4())}
    first = client.post(path, headers=headers, json={**body, "title": "Replay creation"})
    assert first.status_code == 201
    decision = first.json()["data"]
    assert (
        client.put(
            f"/api/v1/notes/{note['id']}",
            json={
                "expected_version": 1,
                "title": "Edited note",
                "content": {"type": "doc", "content": []},
            },
        ).status_code
        == 200
    )
    assert (
        client.request("DELETE", f"/api/v1/notes/{note['id']}", json={"expected_version": 2}).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/hypotheses/{hypothesis['id']}",
            json={
                "expected_version": 1,
                "statement": "Changed hypothesis",
                "status": "contradicted",
            },
        ).status_code
        == 200
    )
    replay = client.post(path, headers=headers, json={**body, "title": "Replay creation"})
    assert replay.status_code == 201 and replay.json() == first.json()
    saved = client.get(f"/api/v1/decisions/{decision['id']}/revisions/1").json()["data"]
    assert saved["notes"][0]["content_snapshot"] == note["content"]
    assert saved["notes"][0]["note_version"] == 1
    assert saved["hypotheses"][0]["statement_snapshot"] == hypothesis["statement"]
    events = client.get("/api/v1/activity?limit=100").json()["data"]
    assert (
        sum(
            event["target_id"] == decision["id"] and event["event_type"] == "decision_created"
            for event in events
        )
        == 1
    )


def test_revision_receipt_replays_after_later_revision_without_resnapshot(account_factory):
    client, _ = account_factory()
    item, line, note, _, body, decision = workflow(client)
    task = create(
        client,
        "/api/v1/tasks",
        {
            "title": "Original source",
            "project_id": item["id"],
            "thread_id": line["id"],
            "decision_id": decision["id"],
        },
    )
    path = f"/api/v1/decisions/{decision['id']}/revisions"
    request = {**body, "expected_revision": 1, "reason": "Original revision request"}
    headers = {"Idempotency-Key": str(uuid4())}
    first = client.post(path, headers=headers, json=request)
    assert first.status_code == 201 and first.json()["data"]["current_revision"] == 2
    assert (
        client.put(
            f"/api/v1/notes/{note['id']}",
            json={
                "expected_version": 1,
                "title": "Later note",
                "content": {"type": "doc", "content": []},
            },
        ).status_code
        == 200
    )
    create(
        client,
        path,
        {
            "expected_revision": 2,
            "title": "Later revision",
            "decision_type": "defer",
            "reason": "Another request",
        },
    )
    replay = client.post(path, headers=headers, json=request)
    assert replay.status_code == 201 and replay.json() == first.json()
    assert client.get(f"/api/v1/decisions/{decision['id']}").json()["data"]["current_revision"] == 3
    old = client.get(f"/api/v1/decisions/{decision['id']}/revisions/2").json()["data"]
    assert old["reason"] == request["reason"] and old["notes"][0]["content_snapshot"] == note["content"]
    assert len(client.get(f"/api/v1/decisions/{decision['id']}/revisions").json()["data"]) == 3
    assert client.get(f"/api/v1/tasks/{task['id']}").json()["data"]["source_revision_no"] == 1
    events = client.get("/api/v1/activity?limit=100").json()["data"]
    assert (
        sum(
            event["target_id"] == decision["id"]
            and event["event_type"] == "decision_revised"
            and event["event_payload"]["revision_no"] == 2
            for event in events
        )
        == 1
    )


def test_concurrent_decision_same_key_commits_one_revision_and_event(account_factory, db_admin):
    client, _ = account_factory()
    line = thread(client, project(client))
    path = f"/api/v1/threads/{line['id']}/decisions"
    headers = {"Idempotency-Key": str(uuid4())}
    body = {"title": "Concurrent decision", "reason": "One intent", "decision_type": "adopt"}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: client.post(path, headers=headers, json=body), range(3)))
    assert all(result.status_code == 201 for result in results)
    assert all(result.json() == results[0].json() for result in results)
    identifier = results[0].json()["data"]["id"]
    assert (
        db_admin.execute(
            "SELECT count(*) FROM decision_revisions WHERE decision_id=%s", (identifier,)
        ).fetchone()[0]
        == 1
    )
    assert (
        db_admin.execute("SELECT count(*) FROM activity_events WHERE target_id=%s", (identifier,)).fetchone()[
            0
        ]
        == 1
    )


def test_rejected_decision_rolls_back_key_but_accepted_key_cannot_change_body_or_space(
    account_factory, db_admin
):
    client, _ = account_factory()
    other, _ = account_factory("decision-replay-other@example.com")
    line = thread(client, project(client))
    path = f"/api/v1/threads/{line['id']}/decisions"
    headers = {"Idempotency-Key": str(uuid4())}
    body = {
        "title": "Rejected then corrected",
        "reason": "Correct the unavailable basis",
        "decision_type": "adopt",
    }
    rejected = client.post(path, headers=headers, json={**body, "note_ids": [str(uuid4())]})
    assert rejected.status_code == 404
    assert (
        db_admin.execute(
            "SELECT count(*) FROM api_idempotency_keys WHERE key=%s", (headers["Idempotency-Key"],)
        ).fetchone()[0]
        == 0
    )
    first = client.post(path, headers=headers, json=body)
    assert first.status_code == 201
    changed = client.post(path, headers=headers, json={**body, "reason": "Different request"})
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert other.post(path, headers=headers, json=body).status_code == 404
    assert client.post(path, headers=headers, json=body).json() == first.json()
