import hashlib
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import responses as dto
from app.core.errors import DomainError
from app.core.protocol import entity, pack_cursor, unpack_cursor
from app.core.security import WorkspaceContext, current_context
from app.db.session import get_session
from app.models import (
    ActivityEvent,
    Evidence,
    Hypothesis,
    Note,
    Paper,
    Project,
    ResearchDecision,
    ResearchProfile,
    ResearchThread,
    Task,
)
from app.responses import ActivityPublic, PageEnvelope
from app.services.research import owned, paginate

router = APIRouter()
MODULE_ORDER = {
    "literature_review": ["threads", "tasks", "activity"],
    "planning": ["threads", "tasks", "activity"],
    "experimentation": ["tasks", "threads", "activity"],
    "writing": ["tasks", "activity", "threads"],
    "custom": ["threads", "tasks", "activity"],
}


@router.get("/dashboard", response_model=dto.Envelope[dto.DashboardPublic])
async def dashboard(
    project_id: UUID | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    if project_id:
        project = await owned(db, Project, project_id, ctx)
    else:
        project = (
            await db.execute(
                select(Project)
                .where(Project.workspace_id == ctx.workspace_id, Project.status != "archived")
                .order_by(Project.is_default.desc(), Project.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    profile = await db.get(ResearchProfile, ctx.workspace_id)
    if not project:
        return {
            "data": {
                "project": None,
                "threads": [],
                "tasks": [],
                "activity": [],
                "counts": {},
                "module_order": ["threads", "tasks", "activity"],
            }
        }
    threads = list(
        (
            await db.execute(
                select(ResearchThread)
                .where(
                    ResearchThread.workspace_id == ctx.workspace_id,
                    ResearchThread.project_id == project.id,
                    ResearchThread.status != "archived",
                )
                .order_by(ResearchThread.updated_at.desc())
                .limit(6)
            )
        ).scalars()
    )
    tasks = list(
        (
            await db.execute(
                select(Task)
                .where(
                    Task.workspace_id == ctx.workspace_id,
                    Task.project_id == project.id,
                    Task.status != "done",
                )
                .order_by(Task.due_date.asc().nulls_last(), Task.created_at.desc())
                .limit(6)
            )
        ).scalars()
    )
    events = list(
        (
            await db.execute(
                select(ActivityEvent)
                .where(ActivityEvent.workspace_id == ctx.workspace_id, ActivityEvent.project_id == project.id)
                .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
                .limit(8)
            )
        ).scalars()
    )
    counts = {}
    for model, label in (
        (ResearchThread, "threads"),
        (Evidence, "evidence"),
        (Hypothesis, "hypotheses"),
        (Task, "tasks"),
    ):
        counts[label] = (
            await db.execute(
                select(func.count())
                .select_from(model)
                .where(model.workspace_id == ctx.workspace_id, model.project_id == project.id)
            )
        ).scalar_one()
    preferences = profile.dashboard_preferences.get(str(project.id), {})
    default = (
        MODULE_ORDER[project.research_stage] if profile.personalization_enabled else MODULE_ORDER["custom"]
    )
    pinned = [value for value in preferences.get("pinned", []) if value in default]
    order = pinned + [value for value in default if value not in pinned]
    return {
        "data": {
            "project": entity(project),
            "threads": [entity(row) for row in threads],
            "tasks": [entity(row) for row in tasks],
            "activity": [entity(row) for row in events],
            "counts": counts,
            "module_order": order,
        }
    }


@router.get("/activity", response_model=PageEnvelope[ActivityPublic])
async def events(
    project_id: UUID | None = None,
    thread_id: UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    filters = []
    if project_id:
        await owned(db, Project, project_id, ctx)
        filters.append(ActivityEvent.project_id == project_id)
    if thread_id:
        await owned(db, ResearchThread, thread_id, ctx)
        filters.append(ActivityEvent.thread_id == thread_id)
    return await paginate(db, ActivityEvent, ctx, limit, cursor, filters, f"{project_id}:{thread_id}")


@router.get("/search", response_model=dto.SearchPublic)
async def search(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    types: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    # Escape SQL wildcard input: users search literal keywords, not patterns.
    query = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    results = []
    specifications = [
        (Project, "project", [Project.title, Project.description]),
        (ResearchThread, "thread", [ResearchThread.title, ResearchThread.question]),
        (Paper, "paper", [Paper.title]),
        (Note, "note", [Note.title, Note.search_text]),
        (Task, "task", [Task.title]),
        (Evidence, "evidence", [Evidence.quote_text, Evidence.interpretation]),
        (Hypothesis, "hypothesis", [Hypothesis.statement]),
        (ResearchDecision, "decision", [ResearchDecision.title]),
    ]
    requested = sorted(set(types.split(","))) if types else [label for _, label, _ in specifications]
    if any(label not in {name for _, name, _ in specifications} for label in requested):
        raise DomainError("INVALID_SEARCH_TYPE", "搜索对象类型无效", 422)
    fingerprint = hashlib.sha256(f"{ctx.workspace_id}:{q}:{','.join(requested)}".encode()).hexdigest()[:16]
    position = unpack_cursor(cursor, fingerprint) if cursor else None
    for model, label, fields in specifications:
        if label not in requested:
            continue
        filters = [
            model.workspace_id == ctx.workspace_id,
            or_(*(field.ilike(query, escape="\\") for field in fields)),
        ]
        if model is Note:
            filters.append(Note.deleted_at.is_(None))
        if position:
            stamp, identifier = position
            filters.append(
                or_(model.created_at < stamp, and_(model.created_at == stamp, model.id < identifier))
            )
        rows = (
            await db.execute(
                select(model)
                .where(*filters)
                .order_by(model.created_at.desc(), model.id.desc())
                .limit(limit + 1)
            )
        ).scalars()
        for row in rows:
            title = getattr(row, "title", getattr(row, "statement", getattr(row, "quote_text", "")))
            results.append(
                {
                    "id": str(row.id),
                    "type": label,
                    "title": title[:250],
                    "created_at": row.created_at.isoformat(),
                    "thread_id": str(row.thread_id) if hasattr(row, "thread_id") else None,
                }
            )
    results.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
    more = len(results) > limit
    page = results[:limit]
    return {
        "data": page,
        "meta": {
            "has_more": more,
            "next_cursor": pack_cursor(
                datetime.fromisoformat(page[-1]["created_at"]), UUID(page[-1]["id"]), fingerprint
            )
            if more
            else None,
            "scope": "关键词检索，不包含 PDF 全文",
        },
    }
