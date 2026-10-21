from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import responses as dto
from app.core.errors import DomainError, missing
from app.core.protocol import activity
from app.core.security import WorkspaceContext, current_context
from app.db.session import get_session
from app.models import (
    Evidence,
    Note,
    NoteEvidenceLink,
    NotePaper,
    Paper,
    Project,
    ProjectNote,
    ProjectPaper,
    ResearchThread,
    ThreadNote,
    ThreadPaper,
)
from app.responses import NoteAssociationPublic, NotePublic, PageEnvelope, PaperPublic
from app.schemas import IdLink
from app.services.papers import associate_project
from app.services.research import owned, paginate

router = APIRouter()


@router.get("/projects/{identifier}/paper-links", response_model=PageEnvelope[PaperPublic])
async def project_papers(
    identifier: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, Project, identifier, ctx)
    linked = exists().where(
        ProjectPaper.workspace_id == ctx.workspace_id,
        ProjectPaper.project_id == identifier,
        ProjectPaper.paper_id == Paper.id,
    )
    return await paginate(db, Paper, ctx, limit, cursor, [linked], f"project-papers:{identifier}")


@router.post(
    "/projects/{identifier}/paper-links", response_model=dto.Envelope[dto.ProjectPaperAssociationPublic]
)
async def project_paper_link(
    identifier: UUID,
    body: IdLink,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await associate_project(db, ctx, identifier, body.id)
    paper = await owned(db, Paper, body.id, ctx)
    await activity(db, ctx, "paper_linked", paper, identifier)
    return {"data": {"project_id": str(identifier), "paper_id": str(body.id)}}


@router.delete(
    "/projects/{identifier}/paper-links/{paper_id}", response_model=dto.Envelope[dto.RemovedPublic]
)
async def project_paper_unlink(
    identifier: UUID,
    paper_id: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, Project, identifier, ctx)
    paper = await owned(db, Paper, paper_id, ctx)
    link = await db.get(ProjectPaper, (ctx.workspace_id, identifier, paper_id))
    if not link:
        missing()
    dependent = (
        (
            await db.execute(
                select(ThreadPaper.thread_id)
                .where(
                    ThreadPaper.workspace_id == ctx.workspace_id,
                    ThreadPaper.project_id == identifier,
                    ThreadPaper.paper_id == paper_id,
                )
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    if dependent:
        raise DomainError(
            "DEPENDENCY_EXISTS",
            "请先处理引用这篇文献的研究线索；原文件不会删除",
            409,
            {"thread_ids": [str(value) for value in dependent]},
        )
    await db.delete(link)
    await activity(db, ctx, "paper_unlinked", paper, identifier)
    return {"data": {"removed": True}}


@router.get("/threads/{identifier}/paper-links", response_model=PageEnvelope[PaperPublic])
async def thread_papers(
    identifier: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, ResearchThread, identifier, ctx)
    linked = exists().where(
        ThreadPaper.workspace_id == ctx.workspace_id,
        ThreadPaper.thread_id == identifier,
        ThreadPaper.paper_id == Paper.id,
    )
    return await paginate(db, Paper, ctx, limit, cursor, [linked], f"thread-papers:{identifier}")


@router.post(
    "/threads/{identifier}/paper-links", response_model=dto.Envelope[dto.ThreadPaperAssociationPublic]
)
async def thread_paper_link(
    identifier: UUID,
    body: IdLink,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    line = await owned(db, ResearchThread, identifier, ctx)
    await associate_project(db, ctx, line.project_id, body.id)
    await db.execute(
        insert(ThreadPaper)
        .values(
            workspace_id=ctx.workspace_id, project_id=line.project_id, thread_id=identifier, paper_id=body.id
        )
        .on_conflict_do_nothing()
    )
    paper = await owned(db, Paper, body.id, ctx)
    await activity(db, ctx, "paper_linked", paper, line.project_id, line.id)
    return {"data": {"thread_id": str(identifier), "paper_id": str(body.id)}}


@router.delete("/threads/{identifier}/paper-links/{paper_id}", response_model=dto.Envelope[dto.RemovedPublic])
async def thread_paper_unlink(
    identifier: UUID,
    paper_id: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    line = await owned(db, ResearchThread, identifier, ctx)
    paper = await owned(db, Paper, paper_id, ctx)
    link = await db.get(ThreadPaper, (ctx.workspace_id, line.project_id, line.id, paper_id))
    if not link:
        missing()
    if (
        await db.execute(
            select(Evidence.id)
            .where(
                Evidence.workspace_id == ctx.workspace_id,
                Evidence.thread_id == identifier,
                Evidence.paper_id == paper_id,
            )
            .limit(1)
        )
    ).first():
        raise DomainError("DEPENDENCY_EXISTS", "这篇文献已经产生研究证据，不能移除来源关系", 409)
    await db.delete(link)
    await activity(db, ctx, "paper_unlinked", paper, line.project_id, line.id)
    return {"data": {"removed": True}}


NOTE_RELATIONS = {
    "project": (Project, ProjectNote, "project_id"),
    "thread": (ResearchThread, ThreadNote, "thread_id"),
    "paper": (Paper, NotePaper, "paper_id"),
    "evidence": (Evidence, NoteEvidenceLink, "evidence_id"),
}


async def live_note(db, ctx, identifier, lock=False):
    note = await owned(db, Note, identifier, ctx, lock=lock)
    if note.deleted_at:
        missing()
    return note


async def note_link(db, ctx, note_id, target_id, kind, remove=False):
    note = await live_note(db, ctx, note_id, lock=True)
    target_model, link_model, column = NOTE_RELATIONS[kind]
    target = await owned(db, target_model, target_id, ctx)
    existing = (
        await db.execute(
            select(link_model).where(
                link_model.workspace_id == ctx.workspace_id,
                link_model.note_id == note_id,
                getattr(link_model, column) == target_id,
            )
        )
    ).scalar_one_or_none()
    if remove:
        if not existing:
            missing()
        if (
            kind == "project"
            and (
                await db.execute(
                    select(ThreadNote.note_id)
                    .where(
                        ThreadNote.workspace_id == ctx.workspace_id,
                        ThreadNote.note_id == note_id,
                        ThreadNote.project_id == target_id,
                    )
                    .limit(1)
                )
            ).first()
        ):
            raise DomainError("DEPENDENCY_EXISTS", "先移除该课题内的笔记线索关联", 409)
        await db.delete(existing)
    elif not existing:
        values = {"workspace_id": ctx.workspace_id, "note_id": note_id, column: target_id}
        if kind == "thread":
            values["project_id"] = target.project_id
            await db.execute(
                insert(ProjectNote)
                .values(workspace_id=ctx.workspace_id, project_id=target.project_id, note_id=note_id)
                .on_conflict_do_nothing()
            )
        await db.execute(insert(link_model).values(**values).on_conflict_do_nothing())
    await activity(
        db,
        ctx,
        "note_unlinked" if remove else "note_linked",
        note,
        target.id if kind == "project" else getattr(target, "project_id", None),
        target.id if kind == "thread" else getattr(target, "thread_id", None),
        {"target_type": kind, "target_id": str(target_id)},
    )
    return {"data": {"note_id": str(note_id), "target_id": str(target_id), "removed": remove}}


@router.get("/notes/{identifier}/links", response_model=PageEnvelope[NoteAssociationPublic])
async def note_links(
    identifier: UUID,
    kind: Literal["project", "thread", "paper", "evidence"] = Query(...),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await live_note(db, ctx, identifier)
    model, link, column = NOTE_RELATIONS[kind]
    linked = exists().where(
        link.workspace_id == ctx.workspace_id, link.note_id == identifier, getattr(link, column) == model.id
    )
    result = await paginate(db, model, ctx, limit, cursor, [linked], f"note-links:{identifier}:{kind}")
    result["data"] = [
        {
            "id": row["id"],
            "title": row.get("title", row.get("quote_text", "")),
            "thread_id": row.get("thread_id"),
        }
        for row in result["data"]
    ]
    return result


@router.get("/projects/{identifier}/note-links", response_model=PageEnvelope[NotePublic])
async def project_notes(
    identifier: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, Project, identifier, ctx)
    linked = exists().where(
        ProjectNote.workspace_id == ctx.workspace_id,
        ProjectNote.project_id == identifier,
        ProjectNote.note_id == Note.id,
    )
    return await paginate(
        db, Note, ctx, limit, cursor, [linked, Note.deleted_at.is_(None)], f"project-notes:{identifier}"
    )


@router.post(
    "/notes/{identifier}/project-links", response_model=dto.Envelope[dto.NoteAssociationMutationPublic]
)
async def link_project(
    identifier: UUID,
    body: IdLink,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await note_link(db, ctx, identifier, body.id, "project")


@router.delete(
    "/notes/{identifier}/project-links/{target_id}",
    response_model=dto.Envelope[dto.NoteAssociationMutationPublic],
)
async def unlink_project(
    identifier: UUID,
    target_id: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await note_link(db, ctx, identifier, target_id, "project", True)


@router.post(
    "/notes/{identifier}/thread-links", response_model=dto.Envelope[dto.NoteAssociationMutationPublic]
)
async def link_thread(
    identifier: UUID,
    body: IdLink,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await note_link(db, ctx, identifier, body.id, "thread")


@router.delete(
    "/notes/{identifier}/thread-links/{target_id}",
    response_model=dto.Envelope[dto.NoteAssociationMutationPublic],
)
async def unlink_thread(
    identifier: UUID,
    target_id: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await note_link(db, ctx, identifier, target_id, "thread", True)


@router.post(
    "/notes/{identifier}/paper-links", response_model=dto.Envelope[dto.NoteAssociationMutationPublic]
)
async def link_paper(
    identifier: UUID,
    body: IdLink,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await note_link(db, ctx, identifier, body.id, "paper")


@router.delete(
    "/notes/{identifier}/paper-links/{target_id}",
    response_model=dto.Envelope[dto.NoteAssociationMutationPublic],
)
async def unlink_paper(
    identifier: UUID,
    target_id: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await note_link(db, ctx, identifier, target_id, "paper", True)


@router.post(
    "/notes/{identifier}/evidence-links", response_model=dto.Envelope[dto.NoteAssociationMutationPublic]
)
async def link_evidence(
    identifier: UUID,
    body: IdLink,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await note_link(db, ctx, identifier, body.id, "evidence")


@router.delete(
    "/notes/{identifier}/evidence-links/{target_id}",
    response_model=dto.Envelope[dto.NoteAssociationMutationPublic],
)
async def unlink_evidence(
    identifier: UUID,
    target_id: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await note_link(db, ctx, identifier, target_id, "evidence", True)
