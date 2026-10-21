"""Initialize the project-local authenticated database cluster and development roles."""

import json
import os
import secrets
import subprocess
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runtime"
BIN = RUN / "postgresql/pgsql/bin"
DATA = RUN / "pgdata"
CREDS = RUN / "local-credentials.json"


def main():
    os.environ["TEMP"] = str(RUN / "tmp")
    os.environ["TMP"] = os.environ["TEMP"]
    if CREDS.exists():
        values = json.loads(CREDS.read_text())
    else:
        values = {
            "admin_password": secrets.token_urlsafe(32),
            "app_password": secrets.token_urlsafe(32),
        }
        CREDS.write_text(json.dumps(values), encoding="utf-8")
    values.setdefault("cleanup_password", secrets.token_urlsafe(32))
    values.setdefault("control_secret", secrets.token_urlsafe(48))
    values.setdefault("bootstrap_password", secrets.token_urlsafe(48))
    values.setdefault("backup_password", secrets.token_urlsafe(32))
    CREDS.write_text(json.dumps(values), encoding="utf-8")
    if not (DATA / "PG_VERSION").exists():
        password = RUN / "initdb-password"
        password.write_text(values["admin_password"], encoding="utf-8")
        subprocess.run(
            [
                str(BIN / "initdb.exe"),
                "-D",
                str(DATA),
                "-U",
                "researchos_admin",
                "-A",
                "scram-sha-256",
                "--pwfile",
                str(password),
                "--encoding=UTF8",
                "--locale=C",
            ],
            check=True,
        )
        password.unlink()
    status = subprocess.run(
        [str(BIN / "pg_ctl.exe"), "-D", str(DATA), "status"],
        capture_output=True,
        check=False,
    )
    if status.returncode:
        subprocess.run(
            [
                str(BIN / "pg_ctl.exe"),
                "-D",
                str(DATA),
                "-l",
                str(RUN / "postgres.log"),
                "-o",
                "-h 127.0.0.1 -p 55432",
                "start",
            ],
            check=True,
        )
    admin_base = f"postgresql://researchos_admin:{quote(values['admin_password'])}@127.0.0.1:55432"
    bootstrap_base = f"postgresql://researchos_bootstrap:{quote(values['bootstrap_password'])}@127.0.0.1:55432"
    try:
        bootstrap = psycopg.connect(bootstrap_base + "/postgres", autocommit=True)
    except psycopg.OperationalError:
        bootstrap = None
    if bootstrap:
        initial_role = bootstrap.execute(
            "SELECT rolname FROM pg_roles WHERE oid=10"
        ).fetchone()[0]
        bootstrap.close()
    else:
        with psycopg.connect(admin_base + "/postgres", autocommit=True) as connection:
            initial_role = connection.execute(
                "SELECT rolname FROM pg_roles WHERE oid=10"
            ).fetchone()[0]
    if initial_role == "researchos_admin":
        # PostgreSQL's initial role (OID 10) must remain a superuser. Rename it;
        # create a separate migration owner instead of downgrading that role.
        with psycopg.connect(admin_base + "/postgres", autocommit=True) as connection:
            with connection.transaction():
                secondary = connection.execute(
                    "SELECT oid FROM pg_roles WHERE rolname='researchos_bootstrap'"
                ).fetchone()
                transition = connection.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname='researchos_transition'"
                ).fetchone()
                if secondary and not transition:
                    connection.execute(
                        "ALTER ROLE researchos_bootstrap RENAME TO researchos_transition"
                    )
                elif not transition:
                    connection.execute(
                        sql.SQL(
                            "CREATE ROLE researchos_transition LOGIN SUPERUSER PASSWORD {}"
                        ).format(sql.Literal(values["bootstrap_password"]))
                    )
        transition_base = f"postgresql://researchos_transition:{quote(values['bootstrap_password'])}@127.0.0.1:55432"
        with psycopg.connect(
            transition_base + "/postgres", autocommit=True
        ) as connection:
            with connection.transaction():
                connection.execute(
                    "ALTER ROLE researchos_admin RENAME TO researchos_bootstrap"
                )
                connection.execute(
                    sql.SQL("ALTER ROLE researchos_bootstrap PASSWORD {}").format(
                        sql.Literal(values["bootstrap_password"])
                    )
                )
                connection.execute(
                    sql.SQL(
                        "CREATE ROLE researchos_admin LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
                    ).format(sql.Literal(values["admin_password"]))
                )
    elif initial_role != "researchos_bootstrap":
        raise RuntimeError(
            "Unexpected bootstrap role; do not change an unrelated database cluster"
        )
    bootstrap = psycopg.connect(bootstrap_base + "/postgres", autocommit=True)
    with bootstrap as connection:
        if connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='researchos_transition'"
        ).fetchone():
            connection.execute("DROP ROLE researchos_transition")
        for role in ("researchos_app", "researchos_cleanup", "researchos_backup"):
            if not connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
            ).fetchone():
                password_value = (
                    values["cleanup_password"]
                    if role == "researchos_cleanup"
                    else values["backup_password"] if role == "researchos_backup" else values["app_password"]
                )
                connection.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password_value)
                    )
                )
        connection.execute(
            sql.SQL("ALTER ROLE researchos_cleanup PASSWORD {}").format(
                sql.Literal(values["cleanup_password"])
            )
        )
        connection.execute(
            "ALTER ROLE researchos_admin NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS"
        )
        connection.execute(sql.SQL("ALTER ROLE researchos_backup NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS PASSWORD {}").format(sql.Literal(values["backup_password"])))
        connection.execute("ALTER ROLE researchos_backup SET default_transaction_read_only=on")
        for database in ("researchos", "researchos_test"):
            if not connection.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
            ).fetchone():
                connection.execute(
                    sql.SQL("CREATE DATABASE {} OWNER researchos_admin").format(
                        sql.Identifier(database)
                    )
                )
            connection.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO researchos_admin").format(
                    sql.Identifier(database)
                )
            )
    for database in ("researchos", "researchos_test"):
        with psycopg.connect(
            bootstrap_base + "/" + database, autocommit=True
        ) as connection:
            connection.execute("ALTER SCHEMA public OWNER TO researchos_admin")
            relations = connection.execute(
                "SELECT c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m','f')"
            ).fetchall()
            for name, kind in relations:
                keyword = {
                    "S": "SEQUENCE",
                    "v": "VIEW",
                    "m": "MATERIALIZED VIEW",
                    "f": "FOREIGN TABLE",
                }.get(kind, "TABLE")
                connection.execute(
                    sql.SQL("ALTER {} public.{} OWNER TO researchos_admin").format(
                        sql.SQL(keyword), sql.Identifier(name)
                    )
                )
            for name in (
                "protect_immutable_history",
                "protect_evidence_source",
                "set_updated_at",
            ):
                if connection.execute(
                    "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname=%s AND p.pronargs=0",
                    (name,),
                ).fetchone():
                    connection.execute(
                        sql.SQL(
                            "ALTER FUNCTION public.{}() OWNER TO researchos_admin"
                        ).format(sql.Identifier(name))
                    )
    env = ROOT / ".env"
    if not env.exists():
        env.write_text(
            f"RESEARCHOS_DATABASE_URL=postgresql+psycopg://researchos_app:{values['app_password']}@127.0.0.1:55432/researchos\n"
            f"RESEARCHOS_ADMIN_DATABASE_URL=postgresql+psycopg://researchos_admin:{values['admin_password']}@127.0.0.1:55432/researchos\n"
            "RESEARCHOS_ENVIRONMENT=development\nRESEARCHOS_COOKIE_SECURE=false\nRESEARCHOS_INVITATION_REQUIRED=true\n",
            encoding="utf-8",
        )
    content = env.read_text(encoding="utf-8")
    if "RESEARCHOS_CLEANUP_DATABASE_URL=" not in content:
        content += f"RESEARCHOS_CLEANUP_DATABASE_URL=postgresql+psycopg://researchos_cleanup:{values['cleanup_password']}@127.0.0.1:55432/researchos\n"
    if "RESEARCHOS_CONTROL_SECRET=" not in content:
        content += f"RESEARCHOS_CONTROL_SECRET={values['control_secret']}\n"
    if "RESEARCHOS_BACKUP_DATABASE_URL=" not in content:
        content += f"RESEARCHOS_BACKUP_DATABASE_URL=postgresql+psycopg://researchos_backup:{values['backup_password']}@127.0.0.1:55432/researchos\n"
    env.write_text(content, encoding="utf-8")
    for database in ("researchos", "researchos_test"):
        with psycopg.connect(
            admin_base + "/" + database, autocommit=True
        ) as connection:
            connection.execute(
                "GRANT USAGE ON SCHEMA public TO researchos_app, researchos_cleanup"
            )
            connection.execute(
                "ALTER DEFAULT PRIVILEGES FOR ROLE researchos_admin IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO researchos_app,researchos_cleanup"
            )
    print(
        "Project PostgreSQL ready on 127.0.0.1:55432; credentials kept in gitignored runtime only"
    )


if __name__ == "__main__":
    main()
