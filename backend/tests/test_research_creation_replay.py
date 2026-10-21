from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from test_identity_research import project


def request_case(client, kind):
    parent = project(client, "Creation parent") if kind == "thread" else None
    paths = {"project": "/projects", "note": "/notes"}
    path = f"/projects/{parent['id']}/threads" if parent else paths[kind]
    body = {"title": "Stable creation"}
    if kind == "thread":
        body["question"] = "Which observation supports the question?"
    return path, body


def post(client, path, body, key):
    return client.post(f"/api/v1{path}", headers={"Idempotency-Key": key}, json=body)


@pytest.mark.parametrize("kind", ["project", "thread", "note"])
def test_same_key_concurrent_creation_is_one_entity_event_and_initial_revision(
    account_factory, db_admin, kind
):
    client, _ = account_factory()
    path, body = request_case(client, kind)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: post(client, path, body, key), range(3)))
    assert all(result.status_code == 201 for result in results)
    assert all(result.json() == results[0].json() for result in results)
    identifier = results[0].json()["data"]["id"]
    assert (
        db_admin.execute(
            "SELECT count(*) FROM activity_events WHERE target_id=%s AND event_type=%s",
            (identifier, f"{kind}_created"),
        ).fetchone()[0]
        == 1
    )
    assert (
        db_admin.execute("SELECT count(*) FROM api_idempotency_keys WHERE key=%s", (key,)).fetchone()[0] == 1
    )
    if kind == "thread":
        assert (
            db_admin.execute(
                "SELECT count(*) FROM thread_revisions WHERE thread_id=%s", (identifier,)
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize("kind", ["project", "thread", "note"])
def test_old_creation_receipt_survives_later_edits_without_reverting_current_entity(account_factory, kind):
    client, _ = account_factory()
    path, body = request_case(client, kind)
    key = str(uuid4())
    first = post(client, path, body, key)
    assert first.status_code == 201
    value = first.json()["data"]
    resource = {"project": "projects", "thread": "threads", "note": "notes"}[kind]
    detail = f"/api/v1/{resource}/{value['id']}"
    changes = {"title": "Later confirmed title", "expected_version": value["version"]}
    if kind == "note":
        changes["content"] = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Later confirmed text"}]}],
        }
    changed = client.request("PUT" if kind == "note" else "PATCH", detail, json=changes)
    assert changed.status_code == 200, changed.text
    replay = post(client, path, body, key)
    assert replay.status_code == 201 and replay.json() == first.json()
    assert client.get(detail).json() == changed.json()
    modified = post(client, path, {**body, "title": "Different valid body"}, key)
    assert modified.status_code == 409 and modified.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_creation_scope_is_private_and_bound_to_operation_and_parent(account_factory):
    alice, _ = account_factory("creation-alice@example.com")
    bob, _ = account_factory("creation-bob@example.com")
    key = str(uuid4())
    a = post(alice, "/projects", {"title": "Alice project"}, key).json()["data"]
    b = post(bob, "/projects", {"title": "Bob project"}, key).json()["data"]
    note = post(alice, "/notes", {"title": "Different operation"}, key).json()["data"]
    assert len({a["id"], b["id"], note["id"]}) == 3
    assert bob.get(f"/api/v1/projects/{a['id']}").status_code == 404
    other_parent = project(alice, "Another parent")
    body = {"title": "Same question", "question": "Same content, different parent"}
    first = post(alice, f"/projects/{a['id']}/threads", body, key)
    second = post(alice, f"/projects/{other_parent['id']}/threads", body, key)
    assert first.status_code == second.status_code == 201
    assert first.json()["data"]["id"] != second.json()["data"]["id"]
    assert post(bob, f"/projects/{a['id']}/threads", body, key).status_code == 404


def test_rejected_creation_rolls_back_receipt_and_invalid_provided_keys_fail_closed(
    account_factory, db_admin
):
    client, _ = account_factory()
    key = str(uuid4())
    path = f"/projects/{uuid4()}/threads"
    body = {"title": "Missing parent", "question": "Not created"}
    assert post(client, path, body, key).status_code == 404
    assert (
        db_admin.execute("SELECT count(*) FROM api_idempotency_keys WHERE key=%s", (key,)).fetchone()[0] == 0
    )
    assert post(client, "/projects", {"title": ""}, key).status_code == 422
    assert post(client, "/projects", {"title": "Corrected title"}, key).status_code == 201
    for invalid in ["", "x" * 129]:
        response = post(client, "/notes", {"title": "Invalid provided key"}, invalid)
        assert response.status_code == 422 and response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    # Existing clients without a key retain the documented creation behavior.
    for _ in range(2):
        assert client.post("/api/v1/notes", json={"title": "Explicit unkeyed client"}).status_code == 201
