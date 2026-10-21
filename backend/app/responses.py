"""Public response contracts. Private identity/storage/lease fields are never DTO fields."""

from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar, get_args, get_type_hints
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, create_model

from app import models

T = TypeVar("T")


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Envelope(ResponseModel, Generic[T]):
    data: T


class Pagination(ResponseModel):
    has_more: bool
    next_cursor: str | None


class PageEnvelope(ResponseModel, Generic[T]):
    data: list[T]
    meta: Pagination


class ErrorDetails(ResponseModel):
    code: str
    message: str
    details: Any = None


class ErrorEnvelope(ResponseModel):
    error: ErrorDetails
    request_id: str


def public_row(model, excluded=(), extra=None):
    hints = get_type_hints(model)
    fields = {
        column.name: (get_args(hints[column.name])[0], ...)
        for column in model.__table__.columns
        if column.name not in excluded
    }
    fields.update(extra or {})
    return create_model(model.__name__ + "Public", __base__=ResponseModel, **fields)


ProjectPublic = public_row(models.Project)
ThreadPublic = public_row(models.ResearchThread)
ThreadRevisionPublic = public_row(models.ThreadRevision)
TaskPublic = public_row(models.Task)
NotePublic = public_row(models.Note, extra={"content": (dict[str, Any], ...)})
EvidencePublic = public_row(
    models.Evidence, extra={"tags": (list[str], ...), "source_anchor": (dict[str, Any], ...)}
)
HypothesisLinkPublic = public_row(models.HypothesisEvidenceLink)
HypothesisPublic = public_row(
    models.Hypothesis, extra={"evidence_links": (list[HypothesisLinkPublic] | None, None)}
)
HypothesisRevisionPublic = public_row(models.HypothesisRevision)
DecisionEvidencePublic = public_row(models.DecisionRevisionEvidenceLink)
DecisionHypothesisPublic = public_row(models.DecisionRevisionHypothesisLink)
DecisionNotePublic = public_row(models.DecisionRevisionNoteLink)
DecisionRevisionPublic = public_row(
    models.DecisionRevision,
    extra={
        "evidence": (list[DecisionEvidencePublic] | None, None),
        "hypotheses": (list[DecisionHypothesisPublic] | None, None),
        "notes": (list[DecisionNotePublic] | None, None),
    },
)
DecisionPublic = public_row(
    models.ResearchDecision, extra={"revision": (DecisionRevisionPublic | None, None)}
)
FilePublic = public_row(models.PaperFile, excluded={"storage_key", "storage_version_id"})
ProfilePublic = public_row(models.ResearchProfile)


class FileSummary(ResponseModel):
    version_no: int
    parse_status: str
    upload_status: str
    availability_status: str
    page_count: int | None
    has_text_layer: bool | None


PaperPublic = public_row(
    models.Paper, extra={"authors": (list[str], ...), "file": (FileSummary | None, None)}
)


class Identity(ResponseModel):
    id: UUID
    email: str
    display_name: str
    workspace_id: UUID
    onboarding: "OnboardingPublic"
    email_verified_at: datetime | None


class Message(ResponseModel):
    message: str


ActivityPublic = public_row(models.ActivityEvent, extra={"event_payload": (dict[str, Any], ...)})
ExportPublic = public_row(
    models.ExportJob,
    excluded={"storage_key", "attempt_token", "lease_owner", "lease_expires_at", "heartbeat_at"},
)


class DuplicatePublic(ResponseModel):
    paper_id: UUID
    paper_file_id: UUID
    title: str
    version_no: int


class NoteAssociationPublic(ResponseModel):
    id: UUID
    title: str
    thread_id: UUID | None


class HealthPublic(ResponseModel):
    status: Literal["ready"]
    service: Literal["ResearchOS"]
    version: str


class RegistrationPublic(ResponseModel):
    id: UUID
    email: str
    workspace_id: UUID


class LoginPublic(ResponseModel):
    user_id: UUID
    workspace_id: UUID
    display_name: str
    csrf_token: str


class LogoutPublic(ResponseModel):
    logged_out: bool


class OnboardingDraftPublic(ResponseModel):
    project_title: str
    question: str
    research_stage: str
    field_of_study: str


class OnboardingPublic(ResponseModel):
    completed: bool = False
    draft_version: int | None = None
    draft: OnboardingDraftPublic | None = None
    project_id: UUID | None = None
    thread_id: UUID | None = None


class DashboardPublic(ResponseModel):
    project: ProjectPublic | None
    threads: list[ThreadPublic]
    tasks: list[TaskPublic]
    activity: list[ActivityPublic]
    counts: dict[str, int]
    module_order: list[Literal["threads", "tasks", "activity"]]


class SearchResultPublic(ResponseModel):
    id: UUID
    type: Literal["project", "thread", "paper", "note", "task", "evidence", "hypothesis", "decision"]
    title: str
    created_at: datetime
    thread_id: UUID | None


class SearchPagination(Pagination):
    scope: str


class SearchPublic(ResponseModel):
    data: list[SearchResultPublic]
    meta: SearchPagination


class ProjectPaperAssociationPublic(ResponseModel):
    project_id: UUID
    paper_id: UUID


class ThreadPaperAssociationPublic(ResponseModel):
    thread_id: UUID
    paper_id: UUID


class RemovedPublic(ResponseModel):
    removed: bool


class NoteAssociationMutationPublic(RemovedPublic):
    note_id: UUID
    target_id: UUID


class NoteDeletedPublic(ResponseModel):
    id: UUID
    deleted: bool
    version: int


class AccountDeletionPreview(ResponseModel):
    scope: Literal["account"]
    counts: dict[str, int]
    blocked: bool
    effects: list[str]
    backup_retention_days: int | None
    preview_token: str
    expires_in_seconds: int


class FileDeletionPreview(ResponseModel):
    scope: Literal["file"]
    paper_file_id: UUID
    paper_id: UUID
    version_no: int
    is_current: bool
    availability_status: str
    counts: dict[str, int]
    blocked: bool
    effects: list[str]
    preview_token: str
    expires_in_seconds: int


DeletionPreviewPublic = Annotated[AccountDeletionPreview | FileDeletionPreview, Field(discriminator="scope")]


class DeletionPublic(ResponseModel):
    id: UUID
    scope: Literal["account", "file"]
    status: str
    requested_at: datetime
    online_finished_at: datetime | None
    backup_expiry_at: datetime | None
    error_code: str | None
    backup_status: str


class DeletionCreatedPublic(DeletionPublic):
    receipt: str


class DuplicateReferencePublic(ResponseModel):
    paper_id: UUID
    paper_file_id: UUID
    version_no: int


class UploadInitializedPublic(ResponseModel):
    upload_id: UUID
    paper_id: UUID
    paper_file_id: UUID
    upload_url: str
    expires_at: datetime
    duplicates: list[DuplicateReferencePublic]
    size_limit: int


class UploadReceivedPublic(ResponseModel):
    upload_id: UUID
    bytes_received: int


class UploadStatusPublic(ResponseModel):
    id: UUID
    status: str
    paper_id: UUID
    paper_file_id: UUID
    expires_at: datetime


class UploadCompletedPublic(ResponseModel):
    upload_id: UUID
    job_id: UUID
    status: str
    paper_file_id: UUID
    message: str


class ParseRetryPublic(ResponseModel):
    job_id: UUID
    paper_file_id: UUID
    parse_status: str


class FileAddressPublic(ResponseModel):
    url: str
    paper_file_id: UUID
    version_no: int
    is_current: bool
    page_count: int | None
    has_text_layer: bool | None


class ParseStatusPublic(ResponseModel):
    paper_file_id: UUID
    upload_status: str
    parse_status: str
    page_count: int | None
    has_text_layer: bool | None
    error_code: str | None
    attempts: int


class CurrentFilePublic(ResponseModel):
    paper_file_id: UUID
    version_no: int


PagePublic = public_row(models.PaperPage, extra={"layout_data": (dict[str, Any], ...)})

Identity.model_rebuild()
