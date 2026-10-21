"""Adapted from FastAPI full-stack template config; see THIRD_PARTY_NOTICES."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import make_url

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="RESEARCHOS_", extra="ignore", hide_input_in_errors=True
    )
    environment: Literal["development", "test", "production"] = "development"
    database_url: str
    admin_database_url: str | None = None
    cleanup_database_url: str | None = None
    backup_database_url: str | None = None
    ledger_writer_url: str | None = Field(default=None, repr=False)
    ledger_reader_url: str | None = Field(default=None, repr=False)
    ledger_admin_url: str | None = Field(default=None, repr=False)
    ledger_source_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    ledger_origin_database: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_\-]{1,63}$")
    control_secret: str
    backup_retention_days: int | None = Field(default=None, ge=1, le=3650)
    backup_retention_approved: bool = False
    backup_schedule_enabled: bool = False
    backup_daily_hour_utc: int = Field(default=19, ge=0, le=23)
    backup_catalog_directory: Path | None = None
    mail_delivery: Literal["preview", "smtp"] = "preview"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "ResearchOS <researchos@localhost>"
    smtp_tls: Literal["starttls", "implicit"] = "starttls"
    frontend_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
    session_days: int = 7
    session_idle_hours: int = 12
    invitation_required: bool = True
    max_upload_bytes: int = 50 * 1024 * 1024
    max_pdf_pages: int = 500
    workspace_quota_bytes: int = 2 * 1024 * 1024 * 1024
    export_snapshot_seconds: int = Field(default=300, ge=30, le=3600)
    orphan_grace_hours: int = Field(default=24, ge=2, le=720)
    maintenance_cycle_seconds: int = Field(default=20, ge=1, le=120)
    s3_endpoint: str = "http://127.0.0.1:55000"
    s3_bucket: str = "researchos-private"
    s3_access_key: str = "researchos-local"
    s3_secret_key: str = "researchos-local-only"
    redis_url: str = "redis://127.0.0.1:56379/0"

    @model_validator(mode="after")
    def production_requirements(self):
        if bool(self.ledger_source_id) != bool(self.ledger_origin_database):
            raise ValueError(
                "Restored deployments require both original ledger source ID and logical database name"
            )
        if self.ledger_writer_url and self.ledger_reader_url:
            writer, reader = make_url(self.ledger_writer_url), make_url(self.ledger_reader_url)
            if (
                writer.drivername != "postgresql+psycopg"
                or reader.drivername != writer.drivername
                or writer.username != "researchos_ledger_writer"
                or reader.username != "researchos_ledger_reader"
                or (writer.host, writer.port or 5432, writer.database)
                != (reader.host, reader.port or 5432, reader.database)
            ):
                raise ValueError(
                    "Deletion journal reader/writer must address the same independent authority with separate roles"
                )
        if self.backup_retention_days and not self.backup_retention_approved:
            raise ValueError("Backup retention requires an approved operational policy")
        if self.environment == "production":
            if not self.cookie_secure or not self.frontend_origin.startswith("https://"):
                raise ValueError("Production requires HTTPS and secure cookies")
            if not self.invitation_required:
                raise ValueError("Public registration requires a separate product review")
            if self.s3_secret_key == "researchos-local-only":
                raise ValueError("Production storage credentials must be configured")
            if len(self.control_secret) < 32:
                raise ValueError("Production control secret must have at least 32 characters")
            if self.mail_delivery != "smtp" or not self.smtp_host:
                raise ValueError(
                    "Production requires configured SMTP; local preview delivery is development only"
                )
            if not self.ledger_writer_url or not self.ledger_reader_url:
                raise ValueError("Production requires a configured independent deletion authority")
            authority, business = make_url(self.ledger_reader_url), make_url(self.database_url)
            if (authority.host, authority.port or 5432) == (business.host, business.port or 5432):
                raise ValueError(
                    "Production deletion authority requires a separate PostgreSQL service and failure domain"
                )
        if not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("ResearchOS requires PostgreSQL with psycopg")
        return self

    @property
    def cookie_name(self):
        return "__Host-session" if self.cookie_secure else "researchos_dev_session"


@lru_cache
def get_settings():
    return Settings()
