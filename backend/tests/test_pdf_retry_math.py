from uuid import uuid4

from test_papers_evidence import pdf_bytes, upload

from app.workers.exports import markdown_note


def test_failed_parse_can_retry_same_bytes_without_duplicate_job(account_factory, object_store, db_admin):
    client, _ = account_factory()
    values = upload(client, pdf_bytes())
    db_admin.execute("UPDATE paper_files SET parse_status='failed' WHERE id=%s", (values["paper_file_id"],))
    path = f"/api/v1/papers/{values['paper_id']}/files/{values['paper_file_id']}/parse-retry"
    key = str(uuid4())
    first = client.post(path, headers={"Idempotency-Key": key}, json={})
    assert first.status_code == 202, first.text
    assert client.post(path, headers={"Idempotency-Key": key}, json={}).json() == first.json()
    assert client.post(path, headers={"Idempotency-Key": str(uuid4())}, json={}).status_code == 409
    from app.workers.jobs import parse_pdf

    parse_pdf(first.json()["data"]["job_id"])
    status = client.get(f"/api/v1/papers/{values['paper_id']}/parse-status")
    assert status.json()["data"]["parse_status"] == "ready"
    assert (
        db_admin.execute(
            "SELECT count(*) FROM paper_files WHERE paper_id=%s", (values["paper_id"],)
        ).fetchone()[0]
        == 1
    )


def test_math_is_saved_searchable_exported_and_bad_structure_rejected(account_factory):
    client, _ = account_factory()
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "公式说明"}]},
            {"type": "blockMath", "attrs": {"latex": "a^2+b^2=c^2"}},
        ],
    }
    response = client.post("/api/v1/notes", json={"title": "研究公式", "content": document})
    assert response.status_code == 201, response.text
    saved = client.get(f"/api/v1/notes/{response.json()['data']['id']}").json()["data"]
    assert saved["content"] == document
    assert client.get("/api/v1/search?q=a^2").json()["data"][0]["id"] == saved["id"]
    assert "$$\na^2+b^2=c^2\n$$" in markdown_note(document)
    for bad in (
        {"type": "doc", "content": "invalid"},
        {"type": "doc", "content": [{"type": "blockMath", "attrs": {"latex": {"not": "text"}}}]},
        {"type": "doc", "content": [{"type": "paragraph", "marks": ["invalid"]}]},
    ):
        assert client.post("/api/v1/notes", json={"title": "拒绝结构", "content": bad}).status_code == 422
