import asyncio

from fastapi.testclient import TestClient

from app.main import app


def test_login_limits_survive_new_client_and_hide_identity(client):
    headers = {"Origin": "http://localhost:3000"}
    for _ in range(8):
        response = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"email": "unknown@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 401
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as second:
        response = second.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"email": "UNKNOWN@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 429
        assert "unknown@example.com" not in response.text.lower()
    assert (
        client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"email": "another@example.com", "password": "wrong-password"},
        ).status_code
        == 401
    )


def test_deletion_reauth_limit_does_not_freeze_account(account_factory):
    client, _ = account_factory()
    preview = client.post("/api/v1/deletion-previews", json={"scope": "account"}).json()["data"]
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/deletions",
                json={
                    "scope": "account",
                    "preview_token": preview["preview_token"],
                    "password": "wrong-password",
                    "confirmation": "DELETE",
                },
            ).status_code
            == 403
        )
    assert (
        client.post(
            "/api/v1/deletions",
            json={
                "scope": "account",
                "preview_token": preview["preview_token"],
                "password": "ResearchOS-test-2026",
                "confirmation": "DELETE",
            },
        ).status_code
        == 429
    )
    assert client.get("/api/v1/me").status_code == 200
