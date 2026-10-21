"""Typed ORM initially scaffolded from the design; evolve through reviewed Alembic migrations."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    account_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint("length(btrim(email)) > 3", name="ck_ck_users_email"),
        CheckConstraint("account_status IN ('active','disabled','deleting')", name="ck_users_7"),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'我的科研空间'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name="fk_fk_workspace_owner", ondelete="RESTRICT"
        ),
        CheckConstraint("status IN ('active','deleting')", name="ck_workspaces_5"),
    )


class ResearchProfile(Base):
    __tablename__ = "research_profiles"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    degree_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_of_study: Mapped[str | None] = mapped_column(Text, nullable=True)
    reading_preferences: Mapped[Any] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    dashboard_preferences: Mapped[Any] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    personalization_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    onboarding_state: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_research_profiles_7", ondelete="CASCADE"
        ),
        CheckConstraint(
            "\n        degree_stage IS NULL OR degree_stage IN\n        ('master', 'phd', 'other')\n    ",
            name="ck_research_profiles_8",
        ),
        CheckConstraint("jsonb_typeof(reading_preferences) = 'object'", name="ck_research_profiles_9"),
        CheckConstraint("jsonb_typeof(dashboard_preferences) = 'object'", name="ck_research_profiles_10"),
        CheckConstraint("version > 0", name="ck_research_profiles_11"),
    )


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    research_stage: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'literature_review'")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_projects_10"),
        ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_projects_11", ondelete="RESTRICT"),
        CheckConstraint("length(btrim(title)) > 0", name="ck_projects_12"),
        CheckConstraint(
            "research_stage IN (\n        'literature_review', 'planning',\n        'experimentation', 'writing', 'custom'\n    )",
            name="ck_projects_13",
        ),
        CheckConstraint("status IN ('active', 'paused', 'archived')", name="ck_projects_14"),
        CheckConstraint("version > 0", name="ck_projects_15"),
        CheckConstraint("(status='archived')=(archived_at IS NOT NULL)", name="ck_ck_project_archive_time"),
        Index(
            "uq_projects_one_default",
            text("workspace_id"),
            unique=True,
            postgresql_where=text("is_default = true"),
        ),
        Index("ix_projects_workspace_updated", text("workspace_id"), text("updated_at DESC")),
        Index(
            "ix_projects_title_trgm",
            "title",
            postgresql_ops={"title": "gin_trgm_ops"},
            postgresql_using="gin",
        ),
    )


class ResearchThread(Base):
    __tablename__ = "research_threads"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "id", name="uq_research_threads_10"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_research_threads_11",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="ck_research_threads_12"),
        CheckConstraint("length(btrim(question)) > 0", name="ck_research_threads_13"),
        CheckConstraint(
            "status IN (\n        'draft', 'active', 'paused', 'archived'\n    )",
            name="ck_research_threads_14",
        ),
        CheckConstraint("version > 0", name="ck_research_threads_15"),
        CheckConstraint("current_revision > 0", name="ck_research_threads_16"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "id", "current_revision"],
            [
                "thread_revisions.workspace_id",
                "thread_revisions.project_id",
                "thread_revisions.thread_id",
                "thread_revisions.revision_no",
            ],
            name="fk_fk_thread_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        CheckConstraint("(status='archived')=(archived_at IS NOT NULL)", name="ck_ck_thread_archive_time"),
        Index(
            "ix_threads_project_status",
            text("workspace_id"),
            text("project_id"),
            text("status"),
            text("updated_at DESC"),
        ),
        Index(
            "ix_threads_title_trgm", "title", postgresql_ops={"title": "gin_trgm_ops"}, postgresql_using="gin"
        ),
        Index(
            "ix_threads_question_trgm",
            "question",
            postgresql_ops={"question": "gin_trgm_ops"},
            postgresql_using="gin",
        ),
    )


class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'未命名文献'"))
    authors: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doi: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    reading_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unread'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_papers_10"),
        ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_papers_11", ondelete="RESTRICT"),
        CheckConstraint(
            "publication_year IS NULL OR\n           publication_year BETWEEN 1500 AND 2200",
            name="ck_papers_12",
        ),
        CheckConstraint("jsonb_typeof(authors) = 'array'", name="ck_papers_13"),
        CheckConstraint("reading_status IN ('unread', 'reading', 'read')", name="ck_papers_14"),
        CheckConstraint("version > 0", name="ck_papers_15"),
        Index("ix_papers_workspace_created", text("workspace_id"), text("created_at DESC")),
        Index("ix_papers_workspace_reading", text("workspace_id"), text("reading_status")),
        Index(
            "ix_papers_workspace_doi",
            text("workspace_id"),
            text("lower(doi)"),
            postgresql_where=text("doi IS NOT NULL"),
        ),
        Index(
            "ix_papers_title_trgm", "title", postgresql_ops={"title": "gin_trgm_ops"}, postgresql_using="gin"
        ),
    )


class PaperFile(Base):
    __tablename__ = "paper_files"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paper_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'application/pdf'"))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    upload_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    parse_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    storage_version_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    availability_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'available'"))
    parser_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_text_layer: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    __table_args__ = (
        UniqueConstraint("paper_id", "version_no", name="uq_paper_files_15"),
        UniqueConstraint("workspace_id", "id", name="uq_paper_files_16"),
        UniqueConstraint("workspace_id", "paper_id", "id", name="uq_paper_files_17"),
        ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["papers.workspace_id", "papers.id"],
            name="fk_paper_files_18",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version_no >= 1", name="ck_paper_files_19"),
        CheckConstraint("size_bytes > 0", name="ck_paper_files_20"),
        CheckConstraint("mime_type = 'application/pdf'", name="ck_paper_files_21"),
        CheckConstraint(
            "sha256 IS NULL OR\n           sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_paper_files_22"
        ),
        CheckConstraint(
            "upload_status IN (\n        'pending', 'uploaded', 'failed'\n    )", name="ck_paper_files_23"
        ),
        CheckConstraint(
            "parse_status IN (\n        'pending', 'queued', 'processing',\n        'ready', 'failed'\n    )",
            name="ck_paper_files_24",
        ),
        CheckConstraint("page_count IS NULL OR page_count > 0", name="ck_paper_files_25"),
        CheckConstraint(
            "\n        NOT is_current OR upload_status = 'uploaded'\n    ", name="ck_paper_files_26"
        ),
        CheckConstraint(
            "availability_status IN ('available','missing','deleting')", name="ck_paper_files_28"
        ),
        Index(
            "uq_paper_files_current",
            text("paper_id"),
            unique=True,
            postgresql_where=text("is_current = true"),
        ),
        Index("ix_paper_files_versions", text("workspace_id"), text("paper_id"), text("version_no DESC")),
        Index(
            "ix_paper_files_hash",
            text("workspace_id"),
            text("sha256"),
            postgresql_where=text("sha256 IS NOT NULL"),
        ),
    )


class PaperPage(Base):
    __tablename__ = "paper_pages"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paper_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paper_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, primary_key=True)
    text_content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    layout_data: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    __table_args__ = (
        PrimaryKeyConstraint("paper_file_id", "page_number", name="pk_paper_pages_6"),
        ForeignKeyConstraint(
            ["workspace_id", "paper_id", "paper_file_id"],
            ["paper_files.workspace_id", "paper_files.paper_id", "paper_files.id"],
            name="fk_paper_pages_7",
            ondelete="RESTRICT",
        ),
        CheckConstraint("page_number >= 1", name="ck_paper_pages_8"),
        CheckConstraint("jsonb_typeof(layout_data) = 'object'", name="ck_paper_pages_9"),
    )


class ProjectPaper(Base):
    __tablename__ = "project_papers"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "project_id", "paper_id", name="pk_project_papers_4"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_papers_5",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["papers.workspace_id", "papers.id"],
            name="fk_project_papers_6",
            ondelete="RESTRICT",
        ),
        Index("ix_project_papers_by_paper", text("workspace_id"), text("paper_id")),
    )


class ThreadPaper(Base):
    __tablename__ = "thread_papers"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id", "project_id", "thread_id", "paper_id", name="pk_thread_papers_5"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id"],
            ["research_threads.workspace_id", "research_threads.project_id", "research_threads.id"],
            name="fk_thread_papers_6",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "paper_id"],
            ["project_papers.workspace_id", "project_papers.project_id", "project_papers.paper_id"],
            name="fk_thread_papers_7",
            ondelete="RESTRICT",
        ),
        Index("ix_thread_papers_by_paper", text("workspace_id"), text("paper_id")),
    )


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paper_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paper_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    quote_text: Mapped[str] = mapped_column(Text, nullable=False)
    interpretation: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    source_anchor: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    anchor_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'page_only'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    tags: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_evidence_15"),
        UniqueConstraint("workspace_id", "project_id", "thread_id", "id", name="uq_evidence_16"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "paper_id"],
            [
                "thread_papers.workspace_id",
                "thread_papers.project_id",
                "thread_papers.thread_id",
                "thread_papers.paper_id",
            ],
            name="fk_evidence_17",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "paper_id", "paper_file_id"],
            ["paper_files.workspace_id", "paper_files.paper_id", "paper_files.id"],
            name="fk_evidence_18",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(quote_text)) > 0", name="ck_evidence_19"),
        CheckConstraint("page_start >= 1", name="ck_evidence_20"),
        CheckConstraint("page_end >= page_start", name="ck_evidence_21"),
        CheckConstraint("version >= 1", name="ck_evidence_22"),
        CheckConstraint("jsonb_typeof(source_anchor) = 'object'", name="ck_evidence_23"),
        CheckConstraint(
            "anchor_status IN (\n        'located', 'page_only', 'unresolved'\n    )", name="ck_evidence_24"
        ),
        CheckConstraint("jsonb_typeof(tags)='array'", name="ck_evidence_26"),
        Index("ix_evidence_thread_created", text("workspace_id"), text("thread_id"), text("created_at DESC")),
        Index("ix_evidence_file_page", text("workspace_id"), text("paper_file_id"), text("page_start")),
    )


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'proposed'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "thread_id", "id", name="uq_hypotheses_8"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id"],
            ["research_threads.workspace_id", "research_threads.project_id", "research_threads.id"],
            name="fk_hypotheses_9",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(statement)) > 0", name="ck_hypotheses_10"),
        CheckConstraint(
            "status IN (\n        'proposed', 'testing', 'supported',\n        'contradicted', 'inconclusive'\n    )",
            name="ck_hypotheses_11",
        ),
        CheckConstraint("version > 0", name="ck_hypotheses_12"),
        CheckConstraint("current_revision > 0", name="ck_hypotheses_13"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "id", "current_revision"],
            [
                "hypothesis_revisions.workspace_id",
                "hypothesis_revisions.project_id",
                "hypothesis_revisions.thread_id",
                "hypothesis_revisions.hypothesis_id",
                "hypothesis_revisions.revision_no",
            ],
            name="fk_fk_hypothesis_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("ix_hypotheses_thread_status", text("workspace_id"), text("thread_id"), text("status")),
    )


class HypothesisEvidenceLink(Base):
    __tablename__ = "hypothesis_evidence_links"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    relation: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id", "hypothesis_id", "evidence_id", name="pk_hypothesis_evidence_links_8"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "hypothesis_id"],
            ["hypotheses.workspace_id", "hypotheses.project_id", "hypotheses.thread_id", "hypotheses.id"],
            name="fk_hypothesis_evidence_links_9",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "evidence_id"],
            ["evidence.workspace_id", "evidence.project_id", "evidence.thread_id", "evidence.id"],
            name="fk_hypothesis_evidence_links_10",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "relation IN (\n        'support', 'challenge', 'background', 'uncertain'\n    )",
            name="ck_hypothesis_evidence_links_11",
        ),
        CheckConstraint("version > 0", name="ck_hypothesis_evidence_links_12"),
        Index("ix_hyp_evidence_reverse", text("workspace_id"), text("evidence_id")),
    )


class ResearchDecision(Base):
    __tablename__ = "research_decisions"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    decision_type: Mapped[str] = mapped_column(Text, nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "thread_id", "id", name="uq_research_decisions_9"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id"],
            ["research_threads.workspace_id", "research_threads.project_id", "research_threads.id"],
            name="fk_research_decisions_10",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="ck_research_decisions_11"),
        CheckConstraint(
            "decision_type IN (\n        'adopt', 'abandon', 'adjust', 'defer'\n    )",
            name="ck_research_decisions_12",
        ),
        CheckConstraint("current_revision >= 1", name="ck_research_decisions_13"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "id", "current_revision"],
            [
                "decision_revisions.workspace_id",
                "decision_revisions.project_id",
                "decision_revisions.thread_id",
                "decision_revisions.decision_id",
                "decision_revisions.revision_no",
            ],
            name="fk_fk_decision_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index(
            "ix_decisions_thread_updated", text("workspace_id"), text("thread_id"), text("updated_at DESC")
        ),
    )


class DecisionRevision(Base):
    __tablename__ = "decision_revisions"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    title_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    decision_type_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        UniqueConstraint("decision_id", "revision_no", name="uq_decision_revisions_10"),
        UniqueConstraint("workspace_id", "project_id", "thread_id", "id", name="uq_decision_revisions_11"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "decision_id"],
            [
                "research_decisions.workspace_id",
                "research_decisions.project_id",
                "research_decisions.thread_id",
                "research_decisions.id",
            ],
            name="fk_decision_revisions_12",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_decision_revisions_13", ondelete="RESTRICT"
        ),
        CheckConstraint("revision_no >= 1", name="ck_decision_revisions_14"),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_decision_revisions_15"),
        CheckConstraint("length(btrim(title_snapshot)) > 0", name="ck_decision_revisions_16"),
        CheckConstraint(
            "decision_type_snapshot IN ('adopt','abandon','adjust','defer')", name="ck_decision_revisions_17"
        ),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "thread_id",
            "decision_id",
            "revision_no",
            name="uq_uq_decision_revision_pointer",
        ),
    )


class DecisionRevisionEvidenceLink(Base):
    __tablename__ = "decision_revision_evidence_links"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    quote_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    interpretation_snapshot: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    evidence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    paper_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    source_anchor_snapshot: Mapped[Any] = mapped_column(JSONB, nullable=False)
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "decision_revision_id",
            "evidence_id",
            name="pk_decision_revision_evidence_links_7",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "decision_revision_id"],
            [
                "decision_revisions.workspace_id",
                "decision_revisions.project_id",
                "decision_revisions.thread_id",
                "decision_revisions.id",
            ],
            name="fk_decision_revision_evidence_links_8",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "evidence_id"],
            ["evidence.workspace_id", "evidence.project_id", "evidence.thread_id", "evidence.id"],
            name="fk_decision_revision_evidence_links_9",
            ondelete="RESTRICT",
        ),
        Index("ix_revision_evidence_reverse", text("workspace_id"), text("evidence_id")),
    )


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'todo'"))
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'medium'"))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    source_revision_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_tasks_13"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_tasks_14",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id"],
            ["research_threads.workspace_id", "research_threads.project_id", "research_threads.id"],
            name="fk_tasks_15",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "decision_id"],
            [
                "research_decisions.workspace_id",
                "research_decisions.project_id",
                "research_decisions.thread_id",
                "research_decisions.id",
            ],
            name="fk_tasks_16",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="ck_tasks_17"),
        CheckConstraint("status IN (\n        'todo', 'doing', 'done', 'blocked'\n    )", name="ck_tasks_18"),
        CheckConstraint("priority IN ('low', 'medium', 'high')", name="ck_tasks_19"),
        CheckConstraint("\n        decision_id IS NULL OR thread_id IS NOT NULL\n    ", name="ck_tasks_20"),
        CheckConstraint("\n        (status = 'done') = (completed_at IS NOT NULL)\n    ", name="ck_tasks_21"),
        CheckConstraint("version > 0", name="ck_tasks_22"),
        CheckConstraint(
            "(decision_id IS NULL) = (source_revision_no IS NULL)", name="ck_ck_task_source_revision"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "decision_id", "source_revision_no"],
            [
                "decision_revisions.workspace_id",
                "decision_revisions.project_id",
                "decision_revisions.thread_id",
                "decision_revisions.decision_id",
                "decision_revisions.revision_no",
            ],
            name="fk_fk_task_source_revision",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_tasks_project_status_due",
            text("workspace_id"),
            text("project_id"),
            text("status"),
            text("due_date"),
        ),
        Index(
            "ix_tasks_thread",
            text("workspace_id"),
            text("thread_id"),
            postgresql_where=text("thread_id IS NOT NULL"),
        ),
        Index(
            "ix_tasks_decision",
            text("workspace_id"),
            text("decision_id"),
            postgresql_where=text("decision_id IS NOT NULL"),
        ),
        Index(
            "ix_tasks_workspace_due",
            text("workspace_id"),
            text("due_date"),
            postgresql_where=text("status <> 'done'"),
        ),
        Index(
            "ix_tasks_title_trgm", "title", postgresql_ops={"title": "gin_trgm_ops"}, postgresql_using="gin"
        ),
    )


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[Any] = mapped_column(
        JSONB, nullable=False, server_default=text('\'{"type":"doc","content":[]}\'::jsonb')
    )
    search_text: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_notes_9"),
        ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_notes_10", ondelete="RESTRICT"),
        CheckConstraint("length(btrim(title)) > 0", name="ck_notes_11"),
        CheckConstraint("version >= 1", name="ck_notes_12"),
        CheckConstraint("jsonb_typeof(content) = 'object'", name="ck_notes_13"),
        Index(
            "ix_notes_workspace_updated",
            text("workspace_id"),
            text("updated_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_notes_title_trgm", "title", postgresql_ops={"title": "gin_trgm_ops"}, postgresql_using="gin"
        ),
        Index(
            "ix_notes_search_text_trgm",
            "search_text",
            postgresql_ops={"search_text": "gin_trgm_ops"},
            postgresql_using="gin",
        ),
    )


class ProjectNote(Base):
    __tablename__ = "project_notes"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "project_id", "note_id", name="pk_project_notes_3"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_notes_4",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "note_id"],
            ["notes.workspace_id", "notes.id"],
            name="fk_project_notes_5",
            ondelete="RESTRICT",
        ),
        Index("ix_project_notes_by_note", text("workspace_id"), text("note_id")),
    )


class ThreadNote(Base):
    __tablename__ = "thread_notes"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "project_id", "thread_id", "note_id", name="pk_thread_notes_4"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id"],
            ["research_threads.workspace_id", "research_threads.project_id", "research_threads.id"],
            name="fk_thread_notes_5",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "note_id"],
            ["project_notes.workspace_id", "project_notes.project_id", "project_notes.note_id"],
            name="fk_thread_notes_6",
            ondelete="RESTRICT",
        ),
        Index("ix_thread_notes_by_note", text("workspace_id"), text("note_id")),
    )


class NotePaper(Base):
    __tablename__ = "note_papers"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "note_id", "paper_id", name="pk_note_papers_3"),
        ForeignKeyConstraint(
            ["workspace_id", "note_id"],
            ["notes.workspace_id", "notes.id"],
            name="fk_note_papers_4",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["papers.workspace_id", "papers.id"],
            name="fk_note_papers_5",
            ondelete="RESTRICT",
        ),
        Index("ix_note_papers_by_paper", text("workspace_id"), text("paper_id")),
    )


class NoteEvidenceLink(Base):
    __tablename__ = "note_evidence_links"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "note_id", "evidence_id", name="pk_note_evidence_links_3"),
        ForeignKeyConstraint(
            ["workspace_id", "note_id"],
            ["notes.workspace_id", "notes.id"],
            name="fk_note_evidence_links_4",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "evidence_id"],
            ["evidence.workspace_id", "evidence.id"],
            name="fk_note_evidence_links_5",
            ondelete="RESTRICT",
        ),
        Index("ix_note_evidence_reverse", text("workspace_id"), text("evidence_id")),
    )


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_payload: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    event_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_activity_events_10", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_activity_events_11",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id"],
            ["research_threads.workspace_id", "research_threads.project_id", "research_threads.id"],
            name="fk_activity_events_12",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name="fk_activity_events_13", ondelete="RESTRICT"
        ),
        CheckConstraint("length(btrim(event_type)) > 0", name="ck_activity_events_14"),
        CheckConstraint("length(btrim(target_type)) > 0", name="ck_activity_events_15"),
        CheckConstraint(
            "\n        thread_id IS NULL OR project_id IS NOT NULL\n    ", name="ck_activity_events_16"
        ),
        CheckConstraint("jsonb_typeof(event_payload) = 'object'", name="ck_activity_events_17"),
        Index("ix_activity_workspace_time", text("workspace_id"), text("created_at DESC"), text("id DESC")),
        Index("ix_activity_project_time", text("workspace_id"), text("project_id"), text("created_at DESC")),
        Index("ix_activity_thread_time", text("workspace_id"), text("thread_id"), text("created_at DESC")),
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paper_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    job_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'parse_pdf'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_processing_jobs_11", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "paper_file_id"],
            ["paper_files.workspace_id", "paper_files.id"],
            name="fk_processing_jobs_12",
            ondelete="RESTRICT",
        ),
        CheckConstraint("job_type = 'parse_pdf'", name="ck_processing_jobs_13"),
        CheckConstraint(
            "status IN (\n        'queued', 'running', 'succeeded', 'failed'\n    )",
            name="ck_processing_jobs_14",
        ),
        CheckConstraint("attempts >= 0", name="ck_processing_jobs_15"),
        CheckConstraint("max_attempts >= 1", name="ck_processing_jobs_16"),
        Index(
            "ix_processing_jobs_queue",
            text("status"),
            text("created_at"),
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index(
            "uq_processing_one_active",
            text("paper_file_id"),
            text("job_type"),
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )


class ExportJob(Base):
    __tablename__ = "export_jobs"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    include_files: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    manifest_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_export_jobs_10", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(["requested_by"], ["users.id"], name="fk_export_jobs_11", ondelete="RESTRICT"),
        CheckConstraint(
            "status IN (\n        'queued', 'running', 'succeeded',\n        'failed', 'expired'\n    )",
            name="ck_export_jobs_12",
        ),
        Index("ix_exports_workspace_created", text("workspace_id"), text("created_at DESC")),
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    csrf_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        Index("ix_session_token_active", text("token_hash"), postgresql_where=text("revoked_at IS NULL")),
    )


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    delivery_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        CheckConstraint("purpose IN ('invite','email_verify','password_reset')", name="ck_auth_tokens_1"),
    )


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paper_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paper_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    staging_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','validating','completed','failed','expired')", name="ck_upload_sessions_5"
        ),
        CheckConstraint("expected_size > 0", name="ck_upload_sessions_7"),
        ForeignKeyConstraint(
            ["workspace_id", "paper_id", "paper_file_id"],
            ["paper_files.workspace_id", "paper_files.paper_id", "paper_files.id"],
            name="fk_upload_sessions_12",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_upload_pending",
            text("expires_at"),
            postgresql_where=text("status IN ('pending','validating')"),
        ),
    )


class ApiIdempotencyKey(Base):
    __tablename__ = "api_idempotency_keys"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'completed'"))
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("length(key) BETWEEN 1 AND 128", name="ck_api_idempotency_keys_4"),
        UniqueConstraint(
            "workspace_id", "actor_user_id", "operation", "key", name="uq_api_idempotency_keys_11"
        ),
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_outbox_events_7"),
        Index(
            "ix_outbox_pending",
            text("next_attempt_at"),
            text("created_at"),
            postgresql_where=text("dispatched_at IS NULL"),
        ),
    )


class ThreadRevision(Base):
    __tablename__ = "thread_revisions"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        CheckConstraint("revision_no > 0", name="ck_thread_revisions_4"),
        UniqueConstraint("thread_id", "revision_no", name="uq_thread_revisions_11"),
        UniqueConstraint(
            "workspace_id", "project_id", "thread_id", "revision_no", name="uq_thread_revisions_12"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id"],
            ["research_threads.workspace_id", "research_threads.project_id", "research_threads.id"],
            name="fk_thread_revisions_13",
            ondelete="RESTRICT",
        ),
    )


class HypothesisRevision(Base):
    __tablename__ = "hypothesis_revisions"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_links_snapshot: Mapped[Any] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        CheckConstraint("revision_no > 0", name="ck_hypothesis_revisions_5"),
        UniqueConstraint("hypothesis_id", "revision_no", name="uq_hypothesis_revisions_11"),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "thread_id",
            "hypothesis_id",
            "revision_no",
            name="uq_hypothesis_revisions_12",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "hypothesis_id"],
            ["hypotheses.workspace_id", "hypotheses.project_id", "hypotheses.thread_id", "hypotheses.id"],
            name="fk_hypothesis_revisions_13",
            ondelete="RESTRICT",
        ),
    )


class DecisionRevisionHypothesisLink(Base):
    __tablename__ = "decision_revision_hypothesis_links"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True
    )
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    statement_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    status_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "decision_revision_id",
            "hypothesis_id",
            name="pk_decision_revision_hypothesis_links_8",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "decision_revision_id"],
            [
                "decision_revisions.workspace_id",
                "decision_revisions.project_id",
                "decision_revisions.thread_id",
                "decision_revisions.id",
            ],
            name="fk_decision_revision_hypothesis_links_9",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "hypothesis_id", "hypothesis_revision_no"],
            [
                "hypothesis_revisions.workspace_id",
                "hypothesis_revisions.project_id",
                "hypothesis_revisions.thread_id",
                "hypothesis_revisions.hypothesis_id",
                "hypothesis_revisions.revision_no",
            ],
            name="fk_decision_revision_hypothesis_links_10",
            ondelete="RESTRICT",
        ),
    )


class DecisionRevisionNoteLink(Base):
    __tablename__ = "decision_revision_note_links"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True
    )
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    note_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_snapshot: Mapped[Any] = mapped_column(JSONB, nullable=False)
    __table_args__ = (
        CheckConstraint("note_version > 0", name="ck_decision_revision_note_links_5"),
        PrimaryKeyConstraint(
            "workspace_id", "decision_revision_id", "note_id", name="pk_decision_revision_note_links_7"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "thread_id", "decision_revision_id"],
            [
                "decision_revisions.workspace_id",
                "decision_revisions.project_id",
                "decision_revisions.thread_id",
                "decision_revisions.id",
            ],
            name="fk_decision_revision_note_links_8",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "note_id"],
            ["notes.workspace_id", "notes.id"],
            name="fk_decision_revision_note_links_9",
            ondelete="RESTRICT",
        ),
    )


class DeletionJob(Base):
    __tablename__ = "deletion_jobs"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    receipt_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    online_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    backup_expiry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','succeeded','failed')", name="ck_deletion_jobs_3"),
    )


class MaintenanceCheckpoint(Base):
    __tablename__ = "maintenance_checkpoints"
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    state: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        CheckConstraint("jsonb_typeof(state)='object'", name="state_object"),
        CheckConstraint("length(name) BETWEEN 1 AND 128", name="name_length"),
    )
