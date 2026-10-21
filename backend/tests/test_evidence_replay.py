from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from test_identity_research import project, thread
from test_papers_evidence import QUOTE, pdf_bytes, upload


def body(file, **changes):
    return {
        "paper_id": file["paper_id"],
        "paper_file_id": file["paper_file_id"],
        "quote_text": QUOTE,
        "interpretation": "Original interpretation",
        "source": {
            "page_start": 1,
            "page_end": 1,
            "capture_method": "selected",
            "rects": [],
            "coordinate_space": "unrotated-cropbox-top-left-normalized",
        },
        **changes,
    }


def test_evidence_receipt_keeps_original_file_after_new_current_and_interpretation_edit(
    account_factory, object_store
):
    client, _ = account_factory()
    line = thread(client, project(client))
    original = upload(client, pdf_bytes())
    path = f"/api/v1/threads/{line['id']}/evidence"
    headers = {"Idempotency-Key": str(uuid4())}
    first = client.post(path, headers=headers, json=body(original))
    assert first.status_code == 201, first.text
    evidence = first.json()["data"]
    assert (
        client.patch(
            f"/api/v1/evidence/{evidence['id']}",
            json={
                "expected_version": 1,
                "interpretation": "Later explanation",
            },
        ).status_code
        == 200
    )
    second = upload(client, pdf_bytes("New version result"), original["paper_id"])
    assert (
        client.get(f"/api/v1/papers/{original['paper_id']}/file").json()["data"]["paper_file_id"]
        == second["paper_file_id"]
    )
    replay = client.post(path, headers=headers, json=body(original))
    assert replay.status_code == 201 and replay.json() == first.json()
    actual = client.get(f"/api/v1/evidence/{evidence['id']}").json()["data"]
    assert (
        actual["paper_file_id"] == original["paper_file_id"]
        and actual["source_anchor"] == evidence["source_anchor"]
    )
    assert actual["version"] == 2 and actual["interpretation"] == "Later explanation"
    assert actual["anchor_status"] == "located"
    assert len(client.get(path).json()["data"]) == 1
    events = client.get("/api/v1/activity?limit=100").json()["data"]
    assert (
        sum(
            event["target_id"] == evidence["id"] and event["event_type"] == "evidence_created"
            for event in events
        )
        == 1
    )


def test_concurrent_evidence_receipt_creates_one_record_and_association_set(
    account_factory, object_store, db_admin
):
    client, _ = account_factory()
    line = thread(client, project(client))
    file = upload(client, pdf_bytes())
    path = f"/api/v1/threads/{line['id']}/evidence"
    headers = {"Idempotency-Key": str(uuid4())}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: client.post(path, headers=headers, json=body(file)), range(3)))
    assert all(result.status_code == 201 for result in results)
    assert all(result.json() == results[0].json() for result in results)
    identifier = results[0].json()["data"]["id"]
    assert len(client.get(path).json()["data"]) == 1
    assert (
        db_admin.execute("SELECT count(*) FROM activity_events WHERE target_id=%s", (identifier,)).fetchone()[
            0
        ]
        == 1
    )
    assert (
        db_admin.execute(
            "SELECT count(*) FROM thread_papers WHERE thread_id=%s AND paper_id=%s",
            (line["id"], file["paper_id"]),
        ).fetchone()[0]
        == 1
    )
    assert (
        db_admin.execute(
            "SELECT count(*) FROM project_papers WHERE project_id=%s AND paper_id=%s",
            (line["project_id"], file["paper_id"]),
        ).fetchone()[0]
        == 1
    )


def test_rejected_evidence_key_and_associations_roll_back_then_correct_safely(
    account_factory, object_store, db_admin
):
    client, _ = account_factory()
    other, _ = account_factory("evidence-replay-other@example.com")
    line = thread(client, project(client))
    file = upload(client, pdf_bytes())
    path = f"/api/v1/threads/{line['id']}/evidence"
    headers = {"Idempotency-Key": str(uuid4())}
    rejected = client.post(path, headers=headers, json=body(file, source={"page_start": 99, "page_end": 99}))
    assert rejected.status_code == 422
    assert (
        db_admin.execute(
            "SELECT count(*) FROM api_idempotency_keys WHERE key=%s", (headers["Idempotency-Key"],)
        ).fetchone()[0]
        == 0
    )
    assert (
        db_admin.execute("SELECT count(*) FROM thread_papers WHERE thread_id=%s", (line["id"],)).fetchone()[0]
        == 0
    )
    first = client.post(path, headers=headers, json=body(file))
    assert first.status_code == 201
    altered = client.post(path, headers=headers, json=body(file, interpretation="Different request"))
    assert altered.status_code == 409 and altered.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert other.post(path, headers=headers, json=body(file)).status_code == 404
    evidence = first.json()["data"]
    assert (
        client.patch(
            f"/api/v1/evidence/{evidence['id']}", json={"expected_version": 1, "paper_file_id": str(uuid4())}
        ).status_code
        == 422
    )


def test_evidence_key_is_thread_scoped_and_cannot_replace_client_path_snapshot(account_factory, object_store):
    client, _ = account_factory()
    item = project(client)
    first, second = thread(client, item), thread(client, item)
    file = upload(client, pdf_bytes())
    headers = {"Idempotency-Key": str(uuid4())}
    results = [
        client.post(f"/api/v1/threads/{line['id']}/evidence", headers=headers, json=body(file))
        for line in (first, second)
    ]
    assert all(result.status_code == 201 for result in results)
    rows = [result.json()["data"] for result in results]
    assert rows[0]["id"] != rows[1]["id"]
    assert [row["thread_id"] for row in rows] == [first["id"], second["id"]]
    assert all(row["paper_file_id"] == file["paper_file_id"] for row in rows)
