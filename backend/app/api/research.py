from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import responses as dto
from app.core.errors import DomainError
from app.core.protocol import activity, entity, idempotent
from app.core.security import WorkspaceContext, current_context
from app.db.session import get_session
from app.models import Project, ResearchProfile, ResearchThread, ThreadRevision, Workspace
from app.responses import Envelope, PageEnvelope, ProjectPublic, ThreadPublic, ThreadRevisionPublic
from app.schemas import Onboarding, OnboardingDraft, ProjectCreate, ProjectPatch, ThreadCreate, ThreadPatch
from app.services.research import (
    create_project,
    create_thread,
    owned,
    paginate,
    update_project,
    update_thread,
)

router = APIRouter()


@router.get("/projects", response_model=PageEnvelope[ProjectPublic])
async def projects(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await paginate(db, Project, ctx, limit, cursor)


@router.post("/projects", status_code=201, response_model=Envelope[ProjectPublic])
async def project_create(
    body: ProjectCreate,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    if idempotency_key is None:
        return await create_project(db, ctx, body)
    return await idempotent(
        db,
        ctx,
        idempotency_key,
        "project:create",
        body.model_dump(),
        lambda: create_project(db, ctx, body),
    )


@router.get("/projects/current", response_model=Envelope[ProjectPublic | None])
async def current_project(
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    row = (
        await db.execute(
            select(Project)
            .where(Project.workspace_id == ctx.workspace_id, Project.status != "archived")
            .order_by(Project.is_default.desc(), Project.created_at.desc(), Project.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {"data": entity(row) if row else None}


@router.get("/projects/{identifier}", response_model=Envelope[ProjectPublic])
async def project_get(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return {"data": entity(await owned(db, Project, identifier, ctx))}


@router.patch("/projects/{identifier}", response_model=Envelope[ProjectPublic])
async def project_patch(
    identifier: UUID,
    body: ProjectPatch,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await update_project(db, ctx, identifier, body)


@router.post("/projects/{identifier}/set-default", response_model=Envelope[ProjectPublic])
async def set_default(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await db.execute(select(Workspace).where(Workspace.id == ctx.workspace_id).with_for_update())
    item = await owned(db, Project, identifier, ctx, lock=True)
    if item.status == "archived":
        raise DomainError("STATE_CONFLICT", "已归档课题不能设置为默认", 409)
    old = list(
        (
            await db.execute(
                select(Project).where(Project.workspace_id == ctx.workspace_id, Project.is_default.is_(True))
            )
        ).scalars()
    )
    for row in old:
        row.is_default = False
    await db.flush()
    item.is_default = True
    await db.flush()
    await activity(db, ctx, "project_default_changed", item, item.id)
    return {"data": entity(item)}


@router.get("/projects/{identifier}/threads", response_model=PageEnvelope[ThreadPublic])
async def threads(
    identifier: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, Project, identifier, ctx)
    return await paginate(
        db, ResearchThread, ctx, limit, cursor, [ResearchThread.project_id == identifier], str(identifier)
    )


@router.post("/projects/{identifier}/threads", status_code=201, response_model=Envelope[ThreadPublic])
async def thread_create(
    identifier: UUID,
    body: ThreadCreate,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    if idempotency_key is None:
        return await create_thread(db, ctx, identifier, body)
    return await idempotent(
        db,
        ctx,
        idempotency_key,
        f"thread:create:{identifier}",
        body.model_dump(),
        lambda: create_thread(db, ctx, identifier, body),
    )


@router.get("/threads/{identifier}", response_model=Envelope[ThreadPublic])
async def thread_get(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return {"data": entity(await owned(db, ResearchThread, identifier, ctx))}


@router.patch("/threads/{identifier}", response_model=Envelope[ThreadPublic])
async def thread_patch(
    identifier: UUID,
    body: ThreadPatch,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await update_thread(db, ctx, identifier, body)


@router.get("/threads/{identifier}/revisions", response_model=PageEnvelope[ThreadRevisionPublic])
async def revisions(
    identifier: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, ResearchThread, identifier, ctx)
    return await paginate(
        db,
        ThreadRevision,
        ctx,
        limit,
        cursor,
        [ThreadRevision.thread_id == identifier],
        str(identifier),
        sort_field="revision_no",
    )


@router.get(
    "/onboarding", response_model=dto.Envelope[dto.OnboardingPublic], response_model_exclude_unset=True
)
async def onboarding(
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return {"data": (await db.get(ResearchProfile, ctx.workspace_id)).onboarding_state}


@router.put(
    "/onboarding/draft", response_model=dto.Envelope[dto.OnboardingPublic], response_model_exclude_unset=True
)
async def save_onboarding_draft(
    body: OnboardingDraft,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    from app.core.errors import DomainError, conflict

    profile = (
        await db.execute(
            select(ResearchProfile).where(ResearchProfile.workspace_id == ctx.workspace_id).with_for_update()
        )
    ).scalar_one()
    state = profile.onboarding_state
    if state.get("completed"):
        raise DomainError("ONBOARDING_COMPLETED", "首次设置已经完成，请在课题页面编辑", 409)
    version = state.get("draft_version", 0)
    if body.expected_draft_version != version:
        conflict(version)
    profile.onboarding_state = {
        "completed": False,
        "draft_version": version + 1,
        "draft": body.model_dump(exclude={"expected_draft_version"}),
    }
    profile.version += 1
    await db.flush()
    return {"data": profile.onboarding_state}


@router.put(
    "/onboarding", response_model=dto.Envelope[dto.OnboardingPublic], response_model_exclude_unset=True
)
async def finish_onboarding(
    body: Onboarding,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    async def action():
        profile = (
            await db.execute(
                select(ResearchProfile)
                .where(ResearchProfile.workspace_id == ctx.workspace_id)
                .with_for_update()
            )
        ).scalar_one()
        if profile.onboarding_state.get("completed"):
            return {"data": profile.onboarding_state}
        project = await create_project(
            db, ctx, ProjectCreate(title=body.project_title, research_stage=body.research_stage)
        )
        thread = await create_thread(
            db,
            ctx,
            UUID(project["data"]["id"]),
            ThreadCreate(title=body.question[:120], question=body.question),
        )
        profile.field_of_study = body.field_of_study
        profile.version += 1
        profile.onboarding_state = {
            "completed": True,
            "project_id": project["data"]["id"],
            "thread_id": thread["data"]["id"],
        }
        await db.flush()
        return {"data": profile.onboarding_state}

    return await idempotent(db, ctx, idempotency_key, "onboarding", body.model_dump(), action, 200)
