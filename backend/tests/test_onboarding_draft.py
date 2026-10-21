from uuid import uuid4


def test_partial_draft_resume_conflict_and_final_idempotency(account_factory):
    client, _ = account_factory()
    draft = {
        "expected_draft_version": 0,
        "project_title": "未完成课题",
        "question": "",
        "research_stage": "planning",
    }
    response = client.put("/api/v1/onboarding/draft", json=draft)
    assert response.status_code == 200
    assert client.get("/api/v1/onboarding").json()["data"]["draft"]["project_title"] == "未完成课题"
    assert client.get("/api/v1/projects").json()["data"] == []
    assert client.put("/api/v1/onboarding/draft", json=draft).status_code == 409
    draft.update(expected_draft_version=1, question="研究问题")
    assert client.put("/api/v1/onboarding/draft", json=draft).status_code == 200
    body = {key: value for key, value in draft.items() if key != "expected_draft_version"}
    key = str(uuid4())
    first = client.put("/api/v1/onboarding", headers={"Idempotency-Key": key}, json=body)
    assert first.status_code == 200
    assert (
        client.put("/api/v1/onboarding", headers={"Idempotency-Key": key}, json=body).json() == first.json()
    )
    assert len(client.get("/api/v1/projects").json()["data"]) == 1
    assert client.put("/api/v1/onboarding/draft", json=draft).status_code == 409
