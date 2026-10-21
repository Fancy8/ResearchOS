from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.protocol import entity, idempotent
from app.core.security import WorkspaceContext, current_context
from app.core.storage import s3_client
from app.db.session import get_session
from app.models import ExportJob, OutboxEvent, Workspace
from app.responses import Envelope, ExportPublic, PageEnvelope
from app.services.research import owned, paginate

router = APIRouter()


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_files: bool = True


def public_job(row):
    return {
        key: value
        for key, value in entity(row).items()
        if key not in {"storage_key", "attempt_token", "lease_owner"}
    }


@router.get("/exports", response_model=PageEnvelope[ExportPublic])
async def export_list(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    result = await paginate(db, ExportJob, ctx, limit, cursor)
    result["data"] = [
        {
            key: value
            for key, value in row.items()
            if key not in {"storage_key", "attempt_token", "lease_owner"}
        }
        for row in result["data"]
    ]
    return result


@router.post("/exports", status_code=202, response_model=Envelope[ExportPublic])
async def export_create(
    body: ExportRequest,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    async def action():
        await db.execute(select(Workspace).where(Workspace.id == ctx.workspace_id).with_for_update())
        active = (
            await db.execute(
                select(ExportJob.id).where(
                    ExportJob.workspace_id == ctx.workspace_id, ExportJob.status.in_(["queued", "running"])
                )
            )
        ).first()
        if active:
            raise DomainError("EXPORT_IN_PROGRESS", "已有导出任务，请等待它完成", 409)
        job = ExportJob(
            id=uuid4(),
            workspace_id=ctx.workspace_id,
            requested_by=ctx.user_id,
            include_files=body.include_files,
        )
        db.add(job)
        await db.flush()
        db.add(
            OutboxEvent(
                id=uuid4(),
                workspace_id=ctx.workspace_id,
                event_type="export_workspace",
                aggregate_id=job.id,
                payload={"job_id": str(job.id)},
            )
        )
        await db.flush()
        return {"data": public_job(job)}

    return await idempotent(db, ctx, idempotency_key, "export:create", body.model_dump(), action, 202)


@router.get("/exports/{identifier}", response_model=Envelope[ExportPublic])
async def export_get(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return {"data": public_job(await owned(db, ExportJob, identifier, ctx))}


@router.get(
    "/exports/{identifier}/download",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def export_download(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    job = await owned(db, ExportJob, identifier, ctx)
    if (
        job.status != "succeeded"
        or not job.storage_key
        or not job.expires_at
        or job.expires_at < datetime.now(UTC)
    ):
        raise DomainError("EXPORT_UNAVAILABLE", "导出尚未完成或已经过期", 409)
    response = await run_in_threadpool(
        s3_client().get_object, Bucket=get_settings().s3_bucket, Key=job.storage_key
    )

    def chunks():
        with response["Body"] as stream:
            while chunk := stream.read(1024 * 1024):
                yield chunk

    return StreamingResponse(
        chunks(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="ResearchOS-{identifier}.zip"',
            "X-Archive-SHA256": job.manifest_hash,
        },
    )
