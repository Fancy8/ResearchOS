"""Provision local independent journal databases; never print credentials."""

import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

import psycopg
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    configured = dotenv_values(ROOT / ".env")
    if (
        os.environ.get(
            "RESEARCHOS_ENVIRONMENT",
            configured.get("RESEARCHOS_ENVIRONMENT", "development"),
        )
        == "production"
    ):
        raise ValueError("LOCAL_LEDGER_PROVISIONING_DEVELOPMENT_ONLY")
    credentials = ROOT / "runtime/local-credentials.json"
    values = json.loads(credentials.read_text(encoding="utf-8"))
    for name in ("ledger_admin", "ledger_writer", "ledger_reader"):
        values.setdefault(name + "_password", secrets.token_urlsafe(32))
    credentials.write_text(json.dumps(values), encoding="utf-8")
    base = f"postgresql://researchos_bootstrap:{quote(values['bootstrap_password'])}@127.0.0.1:55432/"
    with psycopg.connect(base + "postgres", autocommit=True) as db:
        for suffix in ("admin", "writer", "reader"):
            role = "researchos_ledger_" + suffix
            if not db.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
            ).fetchone():
                db.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(role),
                        sql.Literal(values["ledger_" + suffix + "_password"]),
                    )
                )
            db.execute(
                sql.SQL(
                    "ALTER ROLE {} NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(role))
            )
        for database in ("researchos_ledger", "researchos_ledger_test"):
            if not db.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
            ).fetchone():
                db.execute(
                    sql.SQL("CREATE DATABASE {} OWNER researchos_ledger_admin").format(
                        sql.Identifier(database)
                    )
                )
            db.execute(
                sql.SQL(
                    "REVOKE ALL ON DATABASE {} FROM PUBLIC,researchos_app,researchos_admin,researchos_cleanup,researchos_backup"
                ).format(sql.Identifier(database))
            )
            db.execute(
                sql.SQL(
                    "GRANT CONNECT ON DATABASE {} TO researchos_ledger_admin,researchos_ledger_writer,researchos_ledger_reader"
                ).format(sql.Identifier(database))
            )
    env = ROOT / ".env"
    content = env.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        content += "\n"
    for suffix in ("admin", "writer", "reader"):
        key = "RESEARCHOS_LEDGER_" + suffix.upper() + "_URL"
        if key + "=" not in content:
            content += f"{key}=postgresql+psycopg://researchos_ledger_{suffix}:{quote(values['ledger_' + suffix + '_password'])}@127.0.0.1:55432/researchos_ledger\n"
    env.write_text(content, encoding="utf-8")
    command.upgrade(Config(str(ROOT / "backend/ledger-alembic.ini")), "head")
    print(
        "Independent local journal roles and migration ready; production isolation is not certified"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 -- never expose provisioning SQL or credentials
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_class": type(error).__name__,
                    "code": "LEDGER_PROVISIONING_FAILED",
                }
            )
        )
        raise SystemExit(1) from None
