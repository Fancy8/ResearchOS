"""Read the recovered synthetic research flow through the actual API/test client."""
import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from sqlalchemy import make_url  # noqa: E402

if get_settings().environment != "test" or not make_url(get_settings().database_url).database.startswith("researchos_restore_test_"):
    raise RuntimeError("Recovery probe only accepts isolated synthetic test databases")
path = Path(sys.argv[1]).resolve()
if not path.is_relative_to(ROOT):
    raise RuntimeError("Probe inputs must remain inside the project")
values = json.loads(path.read_text())
with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
    if values.get("recover"):
        import re
        from app.core.auth_mail import cipher
        import psycopg
        request = client.post("/api/v1/auth/password-reset-requests", headers={"Origin": "http://localhost:3000"}, json={"email": values["email"]})
        assert request.status_code == 202
        with psycopg.connect(get_settings().admin_database_url.replace("postgresql+psycopg", "postgresql")) as db:
            encrypted = db.execute("SELECT delivery_ciphertext FROM auth_tokens WHERE email=%s AND purpose='password_reset' AND used_at IS NULL ORDER BY created_at DESC LIMIT 1", (values["email"],)).fetchone()[0]
        envelope = json.loads(cipher().decrypt(encrypted.encode()))
        token = re.search(r"#token=([\w-]+)", envelope["link"]).group(1)
        reset = client.post("/api/v1/auth/reset-password", headers={"Origin": "http://localhost:3000"}, json={"token": token, "password": values["password"]})
        assert reset.status_code == 200
    login = client.post("/api/v1/auth/login", headers={"Origin": "http://localhost:3000"}, json={"email": values["email"], "password": values["password"]})
    assert login.status_code == 200
    current = client.get(f"/api/v1/papers/{values['paper']}/file").json()["data"]
    assert current["paper_file_id"] == values["new_file"]
    old = client.get(f"/api/v1/papers/{values['paper']}/content?file_id={values['old_file']}")
    assert old.status_code == 200 and old.content.startswith(b"%PDF-")
    history = client.get(f"/api/v1/decisions/{values['decision']}/revisions/1")
    assert history.status_code == 200 and history.json()["data"]["reason"] == "Original reason"
    task = client.get(f"/api/v1/tasks/{values['task']}")
    assert task.status_code == 200 and task.json()["data"]["source_revision_no"] == 1
    print(json.dumps({"old_source_readable": True, "history_readable": True, "task_revision_preserved": True, "original_sha256": hashlib.sha256(old.content).hexdigest()}))
