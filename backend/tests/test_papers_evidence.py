import hashlib
from io import BytesIO
from uuid import uuid4

import psycopg
import pytest
from reportlab.pdfgen import canvas
from test_identity_research import project, thread

QUOTE = "Controlled experiment shows improved task completion."


def pdf_bytes(text=QUOTE, pages=1):
    buffer = BytesIO()
    document = canvas.Canvas(buffer)
    for number in range(pages):
        if text:
            document.drawString(60, 720, text)
        document.showPage()
    document.save()
    return buffer.getvalue()


def upload(client, data, paper_id=None):
    headers = {"Idempotency-Key": str(uuid4())}
    response = client.post(
        "/api/v1/papers/upload-init",
        headers=headers,
        json={
            "filename": "experiment.pdf",
            "title": "Experiment paper",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "paper_id": paper_id,
        },
    )
    assert response.status_code == 201, response.text
    values = response.json()["data"]
    sent = client.post(values["upload_url"], files={"file": ("experiment.pdf", data, "application/pdf")})
    assert sent.status_code == 200, sent.text
    completed = client.post(
        f"/api/v1/papers/{values['paper_id']}/upload-complete",
        headers={"Idempotency-Key": str(uuid4())},
        json={"upload_id": values["upload_id"]},
    )
    assert completed.status_code == 202, completed.text
    from app.workers.jobs import parse_pdf

    parse_pdf(completed.json()["data"]["job_id"])
    status = client.get(f"/api/v1/papers/{values['paper_id']}/parse-status?file_id={values['paper_file_id']}")
    assert status.json()["data"]["parse_status"] == "ready", status.text
    return values


def evidence(client, line, values, quote=QUOTE, capture="selected"):
    response = client.post(
        f"/api/v1/threads/{line['id']}/evidence",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "paper_id": values["paper_id"],
            "paper_file_id": values["paper_file_id"],
            "quote_text": quote,
            "interpretation": "Specified experimental condition only.",
            "source": {"page_start": 1, "page_end": 1, "capture_method": capture},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_upload_real_storage_parser_and_exact_source(account_factory, object_store):
    client, _ = account_factory()
    item = project(client)
    line = thread(client, item)
    values = upload(client, pdf_bytes())
    source = evidence(client, line, values)
    assert source["anchor_status"] == "located" and source["source_anchor"]["text_verified"]
    file = client.get(f"/api/v1/papers/{values['paper_id']}/file").json()["data"]
    assert client.get(file["url"]).content.startswith(b"%PDF-")
    assert "storage_key" not in str(client.get(f"/api/v1/papers/{values['paper_id']}/files").json())


def test_scanned_and_ambiguous_pdf_are_page_only(account_factory, object_store):
    client, _ = account_factory()
    item = project(client)
    line = thread(client, item)
    scanned = upload(client, pdf_bytes(text=""))
    source = evidence(client, line, scanned, quote="Manually transcribed result", capture="manual")
    assert source["anchor_status"] == "page_only" and not source["source_anchor"]["text_verified"]
    ambiguous = upload(client, pdf_bytes(text=QUOTE + " " + QUOTE))
    assert evidence(client, line, ambiguous)["anchor_status"] == "page_only"


def test_new_pdf_preserves_old_source_and_final_immutable(account_factory, object_store, db_app):
    client, _ = account_factory()
    item = project(client)
    line = thread(client, item)
    first = upload(client, pdf_bytes())
    source = evidence(client, line, first)
    second = upload(client, pdf_bytes(text="A different result."), first["paper_id"])
    current = client.get(f"/api/v1/papers/{first['paper_id']}/file").json()["data"]
    assert current["paper_file_id"] == second["paper_file_id"]
    old = client.get(f"/api/v1/papers/{first['paper_id']}/file?file_id={source['paper_file_id']}").json()[
        "data"
    ]
    assert not old["is_current"] and old["paper_file_id"] == first["paper_file_id"]
    repeated = client.post(
        first["upload_url"], files={"file": ("experiment.pdf", pdf_bytes(), "application/pdf")}
    )
    assert repeated.status_code == 409
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db_app.execute("UPDATE evidence SET quote_text='changed' WHERE id=%s", (source["id"],))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db_app.execute("DELETE FROM paper_files WHERE id=%s", (first["paper_file_id"],))


def test_evidence_relationship_snapshots_and_cross_thread_rejection(account_factory, object_store):
    client, _ = account_factory()
    item = project(client)
    line = thread(client, item)
    values = upload(client, pdf_bytes())
    source = evidence(client, line, values)
    hypothesis = client.post(
        f"/api/v1/threads/{line['id']}/hypotheses", json={"statement": "Could improve coverage"}
    ).json()["data"]
    linked = client.post(
        f"/api/v1/hypotheses/{hypothesis['id']}/evidence-links",
        json={"evidence_id": source["id"], "expected_version": 1, "relation": "challenge"},
    )
    assert linked.status_code == 200 and linked.json()["data"]["status"] == "proposed"
    other = thread(client, item)
    other_hypothesis = client.post(
        f"/api/v1/threads/{other['id']}/hypotheses", json={"statement": "Other line"}
    ).json()["data"]
    assert (
        client.post(
            f"/api/v1/hypotheses/{other_hypothesis['id']}/evidence-links",
            json={"evidence_id": source["id"], "expected_version": 1, "relation": "support"},
        ).status_code
        == 409
    )
    decision = client.post(
        f"/api/v1/threads/{line['id']}/decisions",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Compare",
            "decision_type": "adopt",
            "reason": "Need validation",
            "evidence_ids": [source["id"]],
        },
    ).json()["data"]
    assert (
        client.patch(
            f"/api/v1/evidence/{source['id']}",
            json={"expected_version": 1, "interpretation": "Changed later"},
        ).status_code
        == 200
    )
    snapshot = client.get(f"/api/v1/decisions/{decision['id']}/revisions/1").json()["data"]["evidence"][0]
    assert snapshot["interpretation_snapshot"] == source["interpretation"]


def test_upload_limits_and_bad_source(account_factory):
    client, _ = account_factory()
    for filename, size, expected in (
        ("file.txt", 20, 415),
        ("../file.pdf", 20, 415),
        ("file.pdf", 60 * 1024 * 1024, 413),
    ):
        response = client.post(
            "/api/v1/papers/upload-init",
            headers={"Idempotency-Key": str(uuid4())},
            json={"filename": filename, "size_bytes": size},
        )
        assert response.status_code == expected


def test_malformed_anchor_types_are_rejected_without_server_errors(account_factory, object_store):
    client, _ = account_factory()
    line = thread(client, project(client))
    values = upload(client, pdf_bytes())
    for change in (
        {"capture_method": {"unexpected": "object"}},
        {"coordinate_space": []},
        {"anchor_schema_version": True},
        {"rects": [{"page": True, "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}]},
        {"rects": [{"page": 1, "x": True, "y": 0.1, "width": 0.2, "height": 0.2}]},
    ):
        response = client.post(
            f"/api/v1/threads/{line['id']}/evidence",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "paper_id": values["paper_id"],
                "paper_file_id": values["paper_file_id"],
                "quote_text": QUOTE,
                "source": {"page_start": 1, "page_end": 1, **change},
            },
        )
        assert response.status_code == 422, response.text


def test_other_workspace_file_and_upload_cannot_be_read(account_factory, object_store):
    alice, _ = account_factory("alice@example.com")
    bob, _ = account_factory("bob@example.com")
    values = upload(alice, pdf_bytes())
    for path in (
        f"/api/v1/papers/{values['paper_id']}/file",
        f"/api/v1/uploads/{values['upload_id']}",
        f"/api/v1/papers/{values['paper_id']}/content?file_id={values['paper_file_id']}",
    ):
        assert bob.get(path).status_code == 404
