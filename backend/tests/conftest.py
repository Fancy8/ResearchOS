import asyncio
import json
import os
import secrets
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import make_url

from alembic import command

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
values = dotenv_values(ROOT / ".env")
app_url = os.environ.get("RESEARCHOS_TEST_DATABASE_URL", values.get("RESEARCHOS_DATABASE_URL", ""))
admin_url = os.environ.get(
    "RESEARCHOS_TEST_ADMIN_DATABASE_URL", values.get("RESEARCHOS_ADMIN_DATABASE_URL", "")
)
app_url = app_url.rsplit("/", 1)[0] + "/researchos_test"
admin_url = admin_url.rsplit("/", 1)[0] + "/researchos_test"
os.environ["RESEARCHOS_DATABASE_URL"] = app_url
os.environ["RESEARCHOS_ADMIN_DATABASE_URL"] = admin_url
os.environ["RESEARCHOS_ENVIRONMENT"] = "test"
os.environ["RESEARCHOS_MAIL_DELIVERY"] = "preview"
os.environ["RESEARCHOS_BACKUP_SCHEDULE_ENABLED"] = "false"
if values.get("RESEARCHOS_BACKUP_DATABASE_URL"):
    os.environ["RESEARCHOS_BACKUP_DATABASE_URL"] = (
        values["RESEARCHOS_BACKUP_DATABASE_URL"].rsplit("/", 1)[0] + "/researchos_test"
    )
temporary = ROOT / "runtime/tmp"
temporary.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(temporary)
os.environ["TMP"] = str(temporary)
if values.get("RESEARCHOS_CLEANUP_DATABASE_URL"):
    os.environ["RESEARCHOS_CLEANUP_DATABASE_URL"] = (
        values["RESEARCHOS_CLEANUP_DATABASE_URL"].rsplit("/", 1)[0] + "/researchos_test"
    )
os.environ["RESEARCHOS_S3_BUCKET"] = "researchos-test-private"
for suffix in ("WRITER", "READER", "ADMIN"):
    name = "RESEARCHOS_LEDGER_" + suffix + "_URL"
    if values.get(name):
        os.environ[name] = values[name].rsplit("/", 1)[0] + "/researchos_ledger_test"

from app.core.security import digest  # noqa: E402
from app.main import app  # noqa: E402


def pytest_configure(config):
    target = Path(config.option.basetemp).resolve() if config.option.basetemp else ROOT / "runtime/pytest-tmp"
    if not target.is_relative_to(ROOT) or target == ROOT:
        raise pytest.UsageError("ResearchOS test temporary files must remain under the project root")
    config.option.basetemp = target


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    assert admin_url.endswith("/researchos_test")
    command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
    command.upgrade(Config(str(ROOT / "backend/ledger-alembic.ini")), "head")


@pytest.fixture(autouse=True)
def clean_test_data(migrated_database):
    from app.core.throttle import client as rate_client

    test_settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    assert test_settings.environment == "test"
    authority = test_settings.ledger_admin_url.replace("postgresql+psycopg", "postgresql")
    assert authority.endswith("/researchos_ledger_test")
    with psycopg.connect(authority, autocommit=True) as db:
        assert db.execute("SELECT current_database()").fetchone()[0] == "researchos_ledger_test"
        db.execute("TRUNCATE public.ledger_entries,public.ledger_heads,public.ledger_activation")
    from app.recovery.journal import activate_source, initialize_source

    initialize_source("researchos_test")
    activate_source("researchos_test")
    limits = list(rate_client().scan_iter(match="researchos:test:auth-limit:*"))
    if limits:
        rate_client().delete(*limits)
    with psycopg.connect(
        admin_url.replace("postgresql+psycopg", "postgresql"), autocommit=True
    ) as connection:
        assert connection.execute("SELECT current_database()").fetchone()[0] == "researchos_test"
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename<>'alembic_version'"
            )
        ]
        connection.execute("TRUNCATE " + ",".join('"' + name + '"' for name in tables) + " CASCADE")


@pytest.fixture
def db_admin():
    with psycopg.connect(
        admin_url.replace("postgresql+psycopg", "postgresql"), autocommit=True
    ) as connection:
        yield connection


@pytest.fixture
def ledger_admin():
    from app.core.config import get_settings

    raw = get_settings().ledger_admin_url
    assert make_url(raw).database == "researchos_ledger_test"
    with psycopg.connect(raw.replace("postgresql+psycopg", "postgresql"), autocommit=True) as db:
        yield db


@pytest.fixture
def db_app():
    with psycopg.connect(app_url.replace("postgresql+psycopg", "postgresql"), autocommit=True) as connection:
        yield connection


@pytest.fixture
def client():
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as value:
        yield value


@pytest.fixture
def account_factory(db_admin):
    clients = []

    def create(email="alice@example.com"):
        token = secrets.token_urlsafe(32)
        db_admin.execute(
            "INSERT INTO auth_tokens(id,purpose,email,token_hash,expires_at) VALUES(%s,'invite',%s,%s,%s)",
            (uuid4(), email, digest(token), datetime.now(UTC) + timedelta(hours=1)),
        )
        client = TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop})
        client.__enter__()
        clients.append(client)
        headers = {"Origin": "http://localhost:3000"}
        result = client.post(
            "/api/v1/auth/register",
            headers=headers,
            json={
                "email": email,
                "password": "ResearchOS-test-2026",
                "display_name": "研究用户",
                "invitation_token": token,
            },
        )
        assert result.status_code == 201, result.text
        login = client.post(
            "/api/v1/auth/login", headers=headers, json={"email": email, "password": "ResearchOS-test-2026"}
        )
        assert login.status_code == 200, login.text
        client.headers.update(
            {"Origin": "http://localhost:3000", "X-CSRF-Token": login.json()["data"]["csrf_token"]}
        )
        return client, result.json()["data"]

    yield create
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def object_store():
    from app.core.config import get_settings
    from app.core.storage import s3_client

    client = s3_client()
    bucket = get_settings().s3_bucket
    if bucket not in {row["Name"] for row in client.list_buckets()["Buckets"]}:
        client.create_bucket(Bucket=bucket)
    yield client


@pytest.fixture
def recovery_target(object_store, request):
    from app.core.config import get_settings

    settings = get_settings()
    source = make_url(admin_url)
    credentials = json.loads((ROOT / "runtime/local-credentials.json").read_text())
    bootstrap = source.set(
        username="researchos_bootstrap", password=credentials["bootstrap_password"], database="postgres"
    )
    database = "researchos_restore_test_" + uuid4().hex[:10]
    bucket = "researchos-restore-test-" + uuid4().hex[:10]
    with psycopg.connect(
        bootstrap.render_as_string(hide_password=False).replace("postgresql+psycopg", "postgresql"),
        autocommit=True,
    ) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER researchos_admin").format(sql.Identifier(database))
        )
    target = {
        "admin": source.set(database=database),
        "app": make_url(app_url).set(database=database),
        "cleanup": make_url(settings.cleanup_database_url).set(database=database),
        "name": database,
        "bucket": bucket,
    }
    original = settings.admin_database_url
    try:
        if getattr(request, "param", True):
            settings.admin_database_url = target["admin"].render_as_string(hide_password=False)
            revision = request.param if isinstance(getattr(request, "param", None), str) else "head"
            command.upgrade(Config(str(ROOT / "backend/alembic.ini")), revision)
    finally:
        settings.admin_database_url = original
    object_store.create_bucket(Bucket=bucket)
    try:
        yield target
    finally:
        for page in object_store.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for row in page.get("Contents", []):
                object_store.delete_object(Bucket=bucket, Key=row["Key"])
        object_store.delete_bucket(Bucket=bucket)
        from app.core.runtime_paths import runtime_namespace

        for purpose in ("pdf-tmp", "export-tmp", "mail-preview"):
            directory = runtime_namespace(purpose, database).resolve()
            assert directory.is_relative_to(ROOT) and directory.name == database
            if directory.exists():
                shutil.rmtree(directory)
        with psycopg.connect(
            bootstrap.render_as_string(hide_password=False).replace("postgresql+psycopg", "postgresql"),
            autocommit=True,
        ) as connection:
            assert database.startswith("researchos_restore_test_")
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
