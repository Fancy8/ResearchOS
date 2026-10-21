from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import responses as dto
from app.core.errors import DomainError, conflict, missing
from app.core.protocol import activity, entity, idempotent
from app.core.security import WorkspaceContext, current_context
from app.db.session import get_session
from app.models import (
    DecisionRevision,
    DecisionRevisionEvidenceLink,
    DecisionRevisionHypothesisLink,
    DecisionRevisionNoteLink,
    Hypothesis,
    HypothesisEvidenceLink,
    HypothesisRevision,
    Note,
    ResearchDecision,
    ResearchThread,
    Task,
)
from app.responses import (
    DecisionPublic,
    DecisionRevisionPublic,
    Envelope,
    HypothesisPublic,
    HypothesisRevisionPublic,
    NotePublic,
    PageEnvelope,
    TaskPublic,
)
from app.schemas import (
    DecisionCreate,
    DecisionUpdate,
    HypothesisCreate,
    HypothesisLink,
    HypothesisPatch,
    NoteCreate,
    NotePut,
    TaskCreate,
    TaskPatch,
    VersionRequest,
)
from app.services.research import owned, paginate
from app.services.workflow import (
    create_decision,
    create_hypothesis,
    create_note,
    create_task,
    patch_hypothesis,
    patch_task,
    revise_decision,
    save_note,
    set_hypothesis_link,
)

router = APIRouter()


@router.get("/threads/{identifier}/hypotheses", response_model=PageEnvelope[HypothesisPublic])
async def hypotheses(
    identifier: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, ResearchThread, identifier, ctx)
    return await paginate(
        db, Hypothesis, ctx, limit, cursor, [Hypothesis.thread_id == identifier], str(identifier)
    )


@router.post("/threads/{identifier}/hypotheses", status_code=201, response_model=Envelope[HypothesisPublic])
async def hypothesis_create(
    identifier: UUID,
    body: HypothesisCreate,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await create_hypothesis(db, ctx, identifier, body)


@router.get("/hypotheses/{identifier}", response_model=Envelope[HypothesisPublic])
async def hypothesis_get(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    item = await owned(db, Hypothesis, identifier, ctx)
    links = (
        await db.execute(
            select(HypothesisEvidenceLink).where(
                HypothesisEvidenceLink.workspace_id == ctx.workspace_id,
                HypothesisEvidenceLink.hypothesis_id == identifier,
            )
        )
    ).scalars()
    return {"data": {**entity(item), "evidence_links": [entity(row) for row in links]}}


@router.patch("/hypotheses/{identifier}", response_model=Envelope[HypothesisPublic])
async def hypothesis_patch(
    identifier: UUID,
    body: HypothesisPatch,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await patch_hypothesis(db, ctx, identifier, body)


@router.get("/hypotheses/{identifier}/revisions", response_model=PageEnvelope[HypothesisRevisionPublic])
async def hypothesis_revisions(
    identifier: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, Hypothesis, identifier, ctx)
    return await paginate(
        db,
        HypothesisRevision,
        ctx,
        limit,
        cursor,
        [HypothesisRevision.hypothesis_id == identifier],
        str(identifier),
        sort_field="revision_no",
    )


@router.post("/hypotheses/{identifier}/evidence-links", response_model=dto.Envelope[dto.HypothesisPublic])
async def hypothesis_link(
    identifier: UUID,
    body: HypothesisLink,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await set_hypothesis_link(db, ctx, identifier, body)


@router.patch(
    "/hypotheses/{identifier}/evidence-links/{evidence_id}", response_model=dto.Envelope[dto.HypothesisPublic]
)
async def hypothesis_link_patch(
    identifier: UUID,
    evidence_id: UUID,
    body: HypothesisLink,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    if evidence_id != body.evidence_id:
        missing()
    return await set_hypothesis_link(db, ctx, identifier, body)


@router.delete(
    "/hypotheses/{identifier}/evidence-links/{evidence_id}", response_model=dto.Envelope[dto.HypothesisPublic]
)
async def hypothesis_unlink(
    identifier: UUID,
    evidence_id: UUID,
    body: VersionRequest,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await set_hypothesis_link(
        db,
        ctx,
        identifier,
        HypothesisLink(expected_version=body.expected_version, evidence_id=evidence_id, relation="uncertain"),
        remove=True,
    )


@router.get("/threads/{identifier}/decisions", response_model=PageEnvelope[DecisionPublic])
async def decisions(
    identifier: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, ResearchThread, identifier, ctx)
    return await paginate(
        db, ResearchDecision, ctx, limit, cursor, [ResearchDecision.thread_id == identifier], str(identifier)
    )


@router.post("/threads/{identifier}/decisions", status_code=201, response_model=Envelope[DecisionPublic])
async def decision_create(
    identifier: UUID,
    body: DecisionCreate,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    async def action():
        return await create_decision(db, ctx, identifier, body)

    return await idempotent(
        db, ctx, idempotency_key, f"decision:create:{identifier}", body.model_dump(), action
    )


async def revision_data(db, ctx, revision):
    value = entity(revision)
    for model, label in (
        (DecisionRevisionEvidenceLink, "evidence"),
        (DecisionRevisionHypothesisLink, "hypotheses"),
        (DecisionRevisionNoteLink, "notes"),
    ):
        rows = (
            await db.execute(
                select(model).where(
                    model.workspace_id == ctx.workspace_id, model.decision_revision_id == revision.id
                )
            )
        ).scalars()
        value[label] = [entity(row) for row in rows]
    return value


@router.get("/decisions/{identifier}", response_model=Envelope[DecisionPublic])
async def decision_get(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    item = await owned(db, ResearchDecision, identifier, ctx)
    revision = (
        await db.execute(
            select(DecisionRevision).where(
                DecisionRevision.workspace_id == ctx.workspace_id,
                DecisionRevision.decision_id == identifier,
                DecisionRevision.revision_no == item.current_revision,
            )
        )
    ).scalar_one()
    return {"data": {**entity(item), "revision": await revision_data(db, ctx, revision)}}


@router.get("/decisions/{identifier}/revisions", response_model=PageEnvelope[DecisionRevisionPublic])
async def decision_revisions(
    identifier: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, ResearchDecision, identifier, ctx)
    return await paginate(
        db,
        DecisionRevision,
        ctx,
        limit,
        cursor,
        [DecisionRevision.decision_id == identifier],
        str(identifier),
        sort_field="revision_no",
    )


@router.get(
    "/decisions/{identifier}/revisions/{revision_no}", response_model=Envelope[DecisionRevisionPublic]
)
async def decision_revision(
    identifier: UUID,
    revision_no: int,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, ResearchDecision, identifier, ctx)
    revision = (
        await db.execute(
            select(DecisionRevision).where(
                DecisionRevision.workspace_id == ctx.workspace_id,
                DecisionRevision.decision_id == identifier,
                DecisionRevision.revision_no == revision_no,
            )
        )
    ).scalar_one_or_none()
    if not revision:
        missing()
    return {"data": await revision_data(db, ctx, revision)}


@router.post("/decisions/{identifier}/revisions", status_code=201, response_model=Envelope[DecisionPublic])
async def decision_revise(
    identifier: UUID,
    body: DecisionUpdate,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    async def action():
        return await revise_decision(db, ctx, identifier, body)

    return await idempotent(
        db, ctx, idempotency_key, f"decision:revise:{identifier}", body.model_dump(), action
    )


@router.get("/tasks", response_model=PageEnvelope[TaskPublic])
async def tasks(
    project_id: UUID | None = None,
    thread_id: UUID | None = None,
    status: Literal["todo", "doing", "done", "blocked"] | None = None,
    priority: Literal["low", "medium", "high"] | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    filters = []
    if due_from and due_to and due_from > due_to:
        raise DomainError("VALIDATION_ERROR", "截止日期起始值不能晚于结束值", 422)
    if project_id:
        from app.models import Project

        await owned(db, Project, project_id, ctx)
        filters.append(Task.project_id == project_id)
    if thread_id:
        await owned(db, ResearchThread, thread_id, ctx)
        filters.append(Task.thread_id == thread_id)
    if status:
        filters.append(Task.status == status)
    if priority:
        filters.append(Task.priority == priority)
    if due_from:
        filters.append(Task.due_date >= due_from)
    if due_to:
        filters.append(Task.due_date <= due_to)
    return await paginate(
        db,
        Task,
        ctx,
        limit,
        cursor,
        filters,
        f"{project_id}:{thread_id}:{status}:{priority}:{due_from}:{due_to}",
    )


@router.post("/tasks", status_code=201, response_model=Envelope[TaskPublic])
async def task_create(
    body: TaskCreate,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    async def action():
        return await create_task(db, ctx, body)

    return await idempotent(db, ctx, idempotency_key, "task:create", body.model_dump(), action)


@router.post(
    "/decisions/{identifier}/revisions/{revision_no}/tasks",
    status_code=201,
    response_model=dto.Envelope[dto.TaskPublic],
)
async def task_from_revision(
    identifier: UUID,
    revision_no: int,
    body: TaskCreate,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    decision = await owned(db, ResearchDecision, identifier, ctx)
    fixed = body.model_copy(
        update={
            "project_id": decision.project_id,
            "thread_id": decision.thread_id,
            "decision_id": identifier,
            "source_revision_no": revision_no,
        }
    )

    async def action():
        return await create_task(db, ctx, fixed)

    return await idempotent(
        db, ctx, idempotency_key, f"task:from:{identifier}:{revision_no}", fixed.model_dump(), action
    )


@router.get("/tasks/{identifier}", response_model=Envelope[TaskPublic])
async def task_get(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return {"data": entity(await owned(db, Task, identifier, ctx))}


@router.patch("/tasks/{identifier}", response_model=Envelope[TaskPublic])
async def task_patch(
    identifier: UUID,
    body: TaskPatch,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await patch_task(db, ctx, identifier, body)


@router.get("/notes", response_model=PageEnvelope[NotePublic])
async def notes(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    deleted: bool = False,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await paginate(
        db,
        Note,
        ctx,
        limit,
        cursor,
        [Note.deleted_at.is_not(None) if deleted else Note.deleted_at.is_(None)],
        str(deleted),
    )


@router.post("/notes", status_code=201, response_model=Envelope[NotePublic])
async def note_create(
    body: NoteCreate,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    if idempotency_key is None:
        return await create_note(db, ctx, body)
    return await idempotent(
        db,
        ctx,
        idempotency_key,
        "note:create",
        body.model_dump(),
        lambda: create_note(db, ctx, body),
    )


@router.get("/notes/{identifier}", response_model=Envelope[NotePublic])
async def note_get(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    item = await owned(db, Note, identifier, ctx)
    if item.deleted_at:
        missing()
    return {"data": entity(item)}


@router.put("/notes/{identifier}", response_model=Envelope[NotePublic])
async def note_save(
    identifier: UUID,
    body: NotePut,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await save_note(db, ctx, identifier, body)


@router.delete("/notes/{identifier}", response_model=dto.Envelope[dto.NoteDeletedPublic])
async def note_delete(
    identifier: UUID,
    body: VersionRequest,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    item = await owned(db, Note, identifier, ctx, lock=True)
    if item.version != body.expected_version:
        conflict(item.version)
    item.deleted_at = datetime.now(UTC)
    item.version += 1
    await db.flush()
    await activity(db, ctx, "note_deleted", item)
    return {"data": {"id": str(identifier), "deleted": True, "version": item.version}}


@router.post("/notes/{identifier}/restore", response_model=Envelope[NotePublic])
async def note_restore(
    identifier: UUID,
    body: VersionRequest,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    item = await owned(db, Note, identifier, ctx, lock=True)
    if item.version != body.expected_version:
        conflict(item.version)
    item.deleted_at = None
    item.version += 1
    await db.flush()
    await db.refresh(item)
    await activity(db, ctx, "note_restored", item)
    return {"data": entity(item)}
