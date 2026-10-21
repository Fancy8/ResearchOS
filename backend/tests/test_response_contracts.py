from uuid import uuid4

from app.main import app


def test_every_success_has_a_concrete_schema_and_private_fields_are_excluded():
    spec = app.openapi()
    forbidden = {
        "password_hash",
        "token_hash",
        "storage_key",
        "storage_version_id",
        "staging_key",
        "expected_sha256",
        "receipt_hash",
        "attempt_token",
        "lease_owner",
        "lease_expires_at",
        "delivery_ciphertext",
        "heartbeat_at",
    }
    visited = set()

    def inspect_schema(schema):
        assert schema, "Success response schema must not be empty"
        if "$ref" in schema:
            ref = schema["$ref"]
            if ref in visited:
                return
            visited.add(ref)
            inspect_schema(spec["components"]["schemas"][ref.rsplit("/", 1)[-1]])
        assert not (forbidden & schema.get("properties", {}).keys())
        for value in schema.get("properties", {}).values():
            inspect_schema(value)
        for kind in ("anyOf", "oneOf", "allOf"):
            for value in schema.get(kind, []):
                inspect_schema(value)
        if "items" in schema:
            inspect_schema(schema["items"])

    operations = 0
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            for status, response in operation["responses"].items():
                if not status.startswith("2"):
                    continue
                content = response.get("content", {})
                assert content, f"{method} {path}: success media type is missing"
                if path.endswith("/download"):
                    assert set(content) == {"application/zip"}
                    assert content["application/zip"]["schema"] == {"type": "string", "format": "binary"}
                elif path.endswith("/content") and method == "get":
                    assert set(content) == {"application/pdf"}
                    assert content["application/pdf"]["schema"] == {"type": "string", "format": "binary"}
                else:
                    assert set(content) == {"application/json"}
                    inspect_schema(content["application/json"]["schema"])
                operations += 1
    assert operations >= 80


def test_typed_onboarding_preserves_unset_fields_and_dashboard_search_contract(account_factory):
    client, _ = account_factory()
    assert client.get("/api/v1/onboarding").json() == {"data": {}}
    assert client.get("/api/v1/me").json()["data"]["onboarding"] == {}
    empty = client.get("/api/v1/dashboard").json()["data"]
    assert empty["project"] is None and empty["counts"] == {}
    draft = {"expected_draft_version": 0, "project_title": "契约课题"}
    saved = client.put("/api/v1/onboarding/draft", json=draft)
    assert saved.status_code == 200, saved.text
    state = saved.json()["data"]
    assert set(state) == {"completed", "draft_version", "draft"}
    assert set(state["draft"]) == {"project_title", "question", "research_stage", "field_of_study"}
    completed = client.put(
        "/api/v1/onboarding",
        headers={"Idempotency-Key": str(uuid4())},
        json={"project_title": "契约课题", "question": "契约研究问题"},
    )
    assert completed.status_code == 200, completed.text
    assert set(completed.json()["data"]) == {"completed", "project_id", "thread_id"}
    result = client.get("/api/v1/dashboard")
    assert result.status_code == 200, result.text
    assert result.json()["data"]["project"]["id"] == completed.json()["data"]["project_id"]
    found = client.get("/api/v1/search", params={"q": "契约"})
    assert found.status_code == 200, found.text
    assert len(found.json()["data"]) == 2
    assert "scope" in found.json()["meta"]
    assert client.get("/api/health").json()["status"] == "ready"


def test_framework_errors_follow_public_error_envelope_and_preserve_allow(client):
    for method, path, status, code in (
        ("GET", "/api/v1/no-such-resource", 404, "NOT_FOUND"),
        ("POST", "/api/health", 405, "METHOD_NOT_ALLOWED"),
    ):
        response = client.request(method, path)
        assert response.status_code == status
        body = response.json()
        assert set(body) == {"error", "request_id"}
        assert body["error"]["code"] == code
        assert response.headers["x-request-id"] == body["request_id"]
        assert response.headers["cache-control"] == "no-store"
        if status == 405:
            assert "GET" in response.headers["allow"]
