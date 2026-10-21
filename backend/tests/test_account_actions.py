import re
from email import policy
from email.parser import BytesParser

from app.core.config import ROOT, get_settings
from app.workers.mail import send_auth_email


def mail_token(db_admin, account, purpose):
    row = db_admin.execute(
        "SELECT id,delivery_ciphertext FROM auth_tokens WHERE user_id=%s AND purpose=%s ORDER BY created_at DESC LIMIT 1",
        (account["id"], purpose),
    ).fetchone()
    assert row and row[1] and "localhost:3000" not in row[1]
    send_auth_email(str(row[0]))
    path = ROOT / f"runtime/mail-preview/researchos_test/test/{account['workspace_id']}/{row[0]}.eml"
    content = BytesParser(policy=policy.default).parsebytes(path.read_bytes()).get_content()
    token = re.search(r"#token=([\w-]+)", content).group(1)
    assert (
        db_admin.execute(
            "SELECT delivered_at,delivery_ciphertext FROM auth_tokens WHERE id=%s", (row[0],)
        ).fetchone()[1]
        is None
    )
    return token, row[0]


def test_registration_verification_one_time_and_purpose_isolation(account_factory, db_admin):
    client, account = account_factory()
    token, _ = mail_token(db_admin, account, "email_verify")
    assert (
        client.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": "Unexpected-new-password"}
        ).status_code
        == 400
    )
    verified = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 200
    assert client.get("/api/v1/me").json()["data"]["email_verified_at"]
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400


def test_reset_generic_response_delivered_token_revokes_sessions_and_preserves_password(
    account_factory, db_admin
):
    client, account = account_factory()
    known = client.post("/api/v1/auth/password-reset-requests", json={"email": "alice@example.com"})
    unknown = client.post("/api/v1/auth/password-reset-requests", json={"email": "unknown@example.com"})
    assert known.status_code == unknown.status_code == 202 and known.json()["data"] == unknown.json()["data"]
    token, _ = mail_token(db_admin, account, "password_reset")
    new_password = " ResearchOS-new-password "
    assert (
        client.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": new_password}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": new_password}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "alice@example.com", "password": "ResearchOS-test-2026"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "alice@example.com", "password": new_password}
        ).status_code
        == 200
    )


def test_expired_reset_rejected_and_email_preview_erased_on_account_deletion(
    account_factory, object_store, db_admin
):
    client, account = account_factory()
    token, identifier = mail_token(db_admin, account, "email_verify")
    db_admin.execute("UPDATE auth_tokens SET expires_at=now()-interval '1 second' WHERE id=%s", (identifier,))
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400
    from test_deletions import execute, preview, receipt

    from app.workers.deletions import delete_data

    job = execute(client, preview(client)).json()["data"]
    delete_data(job["id"])
    assert receipt(client, job).json()["data"]["status"] == "succeeded"
    assert not (ROOT / f"runtime/mail-preview/researchos_test/test/{account['workspace_id']}").exists()


def test_production_refuses_local_email_preview():
    import pytest
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="SMTP"):
        Settings(
            environment="production",
            cookie_secure=True,
            frontend_origin="https://researchos.example",
            s3_secret_key="different-storage-secret",
            database_url=get_settings().database_url,
            control_secret="A" * 48,
            mail_delivery="preview",
        )
