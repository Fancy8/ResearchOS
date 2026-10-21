from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

ProjectStage = Literal["literature_review", "planning", "experimentation", "writing", "custom"]
ProjectStatus = Literal["active", "paused", "archived"]
ThreadStatus = Literal["draft", "active", "paused", "archived"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Register(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    invitation_token: str | None = Field(default=None, max_length=128)


class Login(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ProjectCreate(StrictModel):
    title: str = Field(min_length=1, max_length=250)
    description: str = Field(default="", max_length=20000)
    research_stage: ProjectStage = "literature_review"


class ProjectPatch(StrictModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=250)
    description: str | None = Field(default=None, max_length=20000)
    research_stage: ProjectStage | None = None
    status: ProjectStatus | None = None


class ThreadCreate(StrictModel):
    title: str = Field(min_length=1, max_length=250)
    question: str = Field(min_length=1, max_length=20000)
    description: str = Field(default="", max_length=20000)
    status: ThreadStatus = "active"


class ThreadPatch(StrictModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=250)
    question: str | None = Field(default=None, min_length=1, max_length=20000)
    description: str | None = Field(default=None, max_length=20000)
    status: ThreadStatus | None = None


class DashboardPreferences(StrictModel):
    pinned: list[Literal["threads", "tasks", "activity"]] = Field(default_factory=list, max_length=3)

    @field_validator("pinned")
    @classmethod
    def unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("固定模块不能重复")
        return value


class ProfilePatch(StrictModel):
    expected_version: int = Field(ge=1)
    degree_stage: Literal["master", "phd", "other"] | None = None
    field_of_study: str | None = Field(default=None, max_length=250)
    reading_preferences: dict[str, Any] | None = None
    dashboard_preferences: dict[str, DashboardPreferences] | None = None
    personalization_enabled: bool | None = None

    @field_validator("dashboard_preferences")
    @classmethod
    def project_keys(cls, value):
        if value is not None:
            if len(value) > 100:
                raise ValueError("最多配置 100 个课题")
            for key in value:
                UUID(key)
        return value


class Onboarding(StrictModel):
    project_title: str = Field(min_length=1, max_length=250)
    question: str = Field(min_length=1, max_length=20000)
    research_stage: ProjectStage = "literature_review"
    field_of_study: str = Field(default="", max_length=250)


class OnboardingDraft(StrictModel):
    expected_draft_version: int = Field(ge=0)
    project_title: str = Field(default="", max_length=250)
    question: str = Field(default="", max_length=20000)
    research_stage: ProjectStage = "literature_review"
    field_of_study: str = Field(default="", max_length=250)


class VersionRequest(StrictModel):
    expected_version: int = Field(ge=1)


class IdLink(StrictModel):
    id: UUID


class HypothesisCreate(StrictModel):
    statement: str = Field(min_length=1, max_length=20000)
    status: Literal["proposed", "testing", "supported", "contradicted", "inconclusive"] = "proposed"


class HypothesisPatch(StrictModel):
    expected_version: int = Field(ge=1)
    statement: str | None = Field(default=None, min_length=1, max_length=20000)
    status: Literal["proposed", "testing", "supported", "contradicted", "inconclusive"] | None = None


class HypothesisLink(StrictModel):
    expected_version: int = Field(ge=1)
    evidence_id: UUID
    relation: Literal["support", "challenge", "background", "uncertain"]
    explanation: str = Field(default="", max_length=20000)


class DecisionCreate(StrictModel):
    title: str = Field(min_length=1, max_length=250)
    decision_type: Literal["adopt", "abandon", "adjust", "defer"]
    reason: str = Field(min_length=1, max_length=20000)
    content: str = Field(default="", max_length=50000)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)
    hypothesis_ids: list[UUID] = Field(default_factory=list, max_length=100)
    note_ids: list[UUID] = Field(default_factory=list, max_length=100)


class DecisionUpdate(DecisionCreate):
    expected_revision: int = Field(ge=1)


class TaskCreate(StrictModel):
    project_id: UUID
    thread_id: UUID | None = None
    decision_id: UUID | None = None
    source_revision_no: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=250)
    description: str = Field(default="", max_length=20000)
    status: Literal["todo", "doing", "done", "blocked"] = "todo"
    priority: Literal["low", "medium", "high"] = "medium"
    due_date: date | None = None


class TaskPatch(StrictModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=250)
    description: str | None = Field(default=None, max_length=20000)
    status: Literal["todo", "doing", "done", "blocked"] | None = None
    priority: Literal["low", "medium", "high"] | None = None
    due_date: date | None = None


class NoteCreate(StrictModel):
    title: str = Field(min_length=1, max_length=250)
    content: dict[str, Any] = Field(default_factory=lambda: {"type": "doc", "content": []})


class NotePut(NoteCreate):
    expected_version: int = Field(ge=1)


class PaperCreate(StrictModel):
    title: str = Field(min_length=1, max_length=1000)
    authors: list[str] = Field(default_factory=list, max_length=100)
    publication_year: int | None = Field(default=None, ge=1500, le=2200)
    doi: str | None = Field(default=None, max_length=300)


class PaperPatch(StrictModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    authors: list[str] | None = Field(default=None, max_length=100)
    publication_year: int | None = Field(default=None, ge=1500, le=2200)
    doi: str | None = Field(default=None, max_length=300)
    reading_status: Literal["unread", "reading", "read"] | None = None


class UploadInit(StrictModel):
    paper_id: UUID | None = None
    filename: str = Field(min_length=1, max_length=250)
    size_bytes: int = Field(gt=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    project_id: UUID | None = None


class UploadComplete(StrictModel):
    upload_id: UUID


class EvidenceCreate(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    paper_id: UUID
    paper_file_id: UUID
    quote_text: str = Field(min_length=1, max_length=50000)
    interpretation: str = Field(default="", max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    source: dict[str, Any]


class EvidencePatch(StrictModel):
    expected_version: int = Field(ge=1)
    interpretation: str | None = Field(default=None, max_length=20000)
    tags: list[str] | None = Field(default=None, max_length=30)


class EvidenceReuse(StrictModel):
    target_thread_id: UUID
