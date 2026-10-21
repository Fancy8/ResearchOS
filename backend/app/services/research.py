import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, or_, select

from app.core.errors import DomainError, conflict, missing
from app.core.protocol import activity, entity, pack_cursor, unpack_cursor
from app.models import Project, ResearchThread, ThreadRevision, Workspace


async def owned(db, model, identifier, ctx, lock=False):
    query = select(model).where(model.id == identifier, model.workspace_id == ctx.workspace_id)
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        missing()
    return row


async def paginate(db, model, ctx, limit, cursor, filters=None, scope="", sort_field=None):
    clauses = [model.workspace_id == ctx.workspace_id] + (filters or [])
    ordering = getattr(model, sort_field or "created_at")
    if sort_field:
        scope = f"{scope}:order={sort_field}"
    fingerprint = hashlib.sha256(f"{ctx.workspace_id}:{model.__tablename__}:{scope}".encode()).hexdigest()[
        :16
    ]
    if cursor:
        timestamp, identifier = unpack_cursor(cursor, fingerprint, numeric=bool(sort_field))
        clauses.append(or_(ordering < timestamp, and_(ordering == timestamp, model.id < identifier)))
    rows = list(
        (
            await db.execute(
                select(model).where(*clauses).order_by(ordering.desc(), model.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    more, rows = len(rows) > limit, rows[:limit]
    return {
        "data": [entity(row) for row in rows],
        "meta": {
            "has_more": more,
            "next_cursor": pack_cursor(
                getattr(rows[-1], sort_field or "created_at"), rows[-1].id, fingerprint
            )
            if more
            else None,
        },
    }


async def create_project(db, ctx, body):
    # Workspace lock serializes first/default project creation and set-default requests.
    await db.execute(select(Workspace).where(Workspace.id == ctx.workspace_id).with_for_update())
    existing = (await db.execute(select(Project.id).where(Project.workspace_id == ctx.workspace_id))).first()
    project = Project(
        id=uuid4(), workspace_id=ctx.workspace_id, is_default=not bool(existing), **body.model_dump()
    )
    db.add(project)
    await db.flush()
    await activity(db, ctx, "project_created", project, project.id)
    return {"data": entity(project)}


async def update_project(db, ctx, identifier, body):
    await db.execute(select(Workspace).where(Workspace.id == ctx.workspace_id).with_for_update())
    item = await owned(db, Project, identifier, ctx, lock=True)
    if item.version != body.expected_version:
        conflict(item.version)
    values = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    if any(value is None for value in values.values()):
        raise DomainError("VALIDATION_ERROR", "课题字段不能为空", 422)
    for key, value in values.items():
        setattr(item, key, value)
    item.archived_at = datetime.now(UTC) if item.status == "archived" else None
    if item.status == "archived":
        item.is_default = False
    item.version += 1
    await db.flush()
    await db.refresh(item)
    await activity(
        db, ctx, "project_updated", item, item.id, payload={"version": item.version, "fields": list(values)}
    )
    return {"data": entity(item)}


async def thread_revision(db, ctx, item):
    db.add(
        ThreadRevision(
            id=uuid4(),
            workspace_id=ctx.workspace_id,
            project_id=item.project_id,
            thread_id=item.id,
            revision_no=item.current_revision,
            title=item.title,
            question=item.question,
            description=item.description,
            status=item.status,
            created_by=ctx.user_id,
        )
    )
    await db.flush()


async def create_thread(db, ctx, project_id, body):
    project = await owned(db, Project, project_id, ctx)
    if project.status == "archived":
        raise DomainError("STATE_CONFLICT", "请先恢复已归档课题", 409)
    item = ResearchThread(
        id=uuid4(),
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        archived_at=datetime.now(UTC) if body.status == "archived" else None,
        **body.model_dump(),
    )
    db.add(item)
    await db.flush()
    await thread_revision(db, ctx, item)
    await activity(db, ctx, "thread_created", item, project_id, item.id)
    return {"data": entity(item)}


async def update_thread(db, ctx, identifier, body):
    item = await owned(db, ResearchThread, identifier, ctx, lock=True)
    if item.version != body.expected_version:
        conflict(item.version)
    values = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    if any(value is None for value in values.values()):
        raise DomainError("VALIDATION_ERROR", "线索字段不能为空", 422)
    for key, value in values.items():
        setattr(item, key, value)
    item.archived_at = datetime.now(UTC) if item.status == "archived" else None
    item.version += 1
    item.current_revision += 1
    await db.flush()
    await thread_revision(db, ctx, item)
    await db.refresh(item)
    await activity(
        db,
        ctx,
        "thread_updated",
        item,
        item.project_id,
        item.id,
        {"revision_no": item.current_revision, "version": item.version},
    )
    return {"data": entity(item)}
