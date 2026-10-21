import secrets
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app import responses as dto
from app.core.errors import DomainError
from app.core.security import WorkspaceContext, current_context, digest, verify_password
from app.core.throttle import auth_limit
from app.db.session import get_session
from app.models import (
    AuthSession,
    DeletionJob,
    ExportJob,
    OutboxEvent,
    PaperFile,
    ProcessingJob,
    User,
    Workspace,
)
from app.recovery.journal import current_checkpoint, origin_database
from app.services.deletion import deletion_impact, preview_token, validate_preview
from app.workers.deletions import write_ledger

router = APIRouter()


class DeletionScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["account", "file"]
    target_id: UUID | None = None

    @model_validator(mode="after")
    def valid_target(self):
        if (self.scope == "file") != (self.target_id is not None):
            raise ValueError("文件删除需提供目标；账户删除无需目标")
        return self


class DeletionRequest(DeletionScope):
    preview_token: str = Field(min_length=1, max_length=4096)
    password: str = Field(min_length=1, max_length=128)
    confirmation: Literal["DELETE"]


def public_job(job):
    return {
        "id": str(job.id),
        "scope": job.scope,
        "status": job.status,
        "requested_at": job.requested_at,
        "online_finished_at": job.online_finished_at,
        "backup_expiry_at": job.backup_expiry_at,
        "error_code": job.error_code,
        "backup_status": "备份目标过期时间已配置，实际清除需核对备份清理结果"
        if job.backup_expiry_at
        else "尚未配置备份保留期，不能承诺备份已清除",
    }


@router.post("/deletion-previews", response_model=dto.Envelope[dto.DeletionPreviewPublic])
async def deletion_preview(
    body: DeletionScope,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    impact = await deletion_impact(db, ctx, body.scope, body.target_id)
    return {
        "data": {
            **impact,
            "preview_token": preview_token(ctx, body.scope, body.target_id, impact),
            "expires_in_seconds": 600,
        }
    }


@router.post("/deletions", status_code=202, response_model=dto.Envelope[dto.DeletionCreatedPublic])
async def deletion_create(
    body: DeletionRequest,
    response: Response,
    request: Request,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    from app.core.config import get_settings

    await auth_limit("deletion-reauth", request, str(ctx.user_id), maximum=5)

    if not get_settings().cleanup_database_url:
        raise DomainError("CLEANUP_NOT_CONFIGURED", "清理服务未配置，未执行删除", 503)
    user = await db.get(User, ctx.user_id)
    if not await run_in_threadpool(verify_password, body.password, user.password_hash):
        raise DomainError("REAUTH_FAILED", "密码验证失败，未执行删除", 403)
    await db.execute(select(Workspace).where(Workspace.id == ctx.workspace_id).with_for_update())
    impact = await deletion_impact(db, ctx, body.scope, body.target_id)
    validate_preview(body.preview_token, ctx, body.scope, body.target_id, impact)
    if impact["blocked"]:
        raise DomainError("DELETION_DEPENDENCIES", "文件被证据引用或有活跃导出，请先处理依赖", 409, impact)
    from sqlalchemy import make_url

    database = origin_database(make_url(get_settings().database_url).database)
    try:
        await run_in_threadpool(current_checkpoint, database)
    except (ValueError, RuntimeError):
        raise DomainError(
            "DELETION_JOURNAL_UNAVAILABLE", "删除日志暂不可用，本次未接受删除，请稍后重试", 503
        ) from None
    receipt = secrets.token_urlsafe(32)
    job = DeletionJob(
        id=uuid4(),
        workspace_id=ctx.workspace_id,
        requested_by=ctx.user_id,
        scope=body.scope,
        target_id=body.target_id,
        receipt_hash=digest(receipt),
    )
    db.add(job)
    if body.scope == "account":
        user.account_status = "deleting"
        (await db.get(Workspace, ctx.workspace_id)).status = "deleting"
        await db.execute(
            update(AuthSession).where(AuthSession.user_id == ctx.user_id).values(revoked_at=datetime.now(UTC))
        )
        await db.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.workspace_id == ctx.workspace_id,
                ProcessingJob.status.in_(["queued", "running"]),
            )
            .values(status="failed", error_code="WORKSPACE_FROZEN", finished_at=datetime.now(UTC))
        )
        await db.execute(
            update(ExportJob)
            .where(ExportJob.workspace_id == ctx.workspace_id, ExportJob.status.in_(["queued", "running"]))
            .values(status="failed", error_code="WORKSPACE_FROZEN", finished_at=datetime.now(UTC))
        )
        response.delete_cookie(get_settings().cookie_name, path="/")
        response.delete_cookie("researchos_csrf", path="/")
    else:
        file = await db.get(PaperFile, body.target_id)
        file.availability_status, file.is_current = "deleting", False
        await db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.paper_file_id == file.id, ProcessingJob.status.in_(["queued", "running"]))
            .values(status="failed", error_code="FILE_DELETING", finished_at=datetime.now(UTC))
        )
    db.add(
        OutboxEvent(
            id=uuid4(),
            workspace_id=ctx.workspace_id,
            event_type="delete_data",
            aggregate_id=job.id,
            payload={"job_id": str(job.id)},
        )
    )
    await db.flush()
    # The business intent/outbox commits first. A crash cannot leave an
    # authority-only deletion without a durable job. 202 requires both stores.
    await db.commit()
    try:
        await run_in_threadpool(write_ledger, job, ctx.workspace_id, ctx.user_id)
    except (ValueError, RuntimeError, OSError):
        raise DomainError(
            "DELETION_JOURNAL_PENDING",
            "删除已排队，独立日志尚待确认，请保留回执并查看进度",
            503,
            {"id": str(job.id), "receipt": receipt, "scope": body.scope},
        ) from None
    return {"data": {**public_job(job), "receipt": receipt}}


@router.get("/deletions/{identifier}", response_model=dto.Envelope[dto.DeletionPublic])
async def deletion_get(
    identifier: UUID,
    x_deletion_receipt: str = Header(default="", max_length=128),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    job = await db.get(DeletionJob, identifier)
    if (
        not job
        or not job.receipt_hash
        or not secrets.compare_digest(job.receipt_hash, digest(x_deletion_receipt))
    ):
        raise DomainError("NOT_FOUND", "删除记录不存在", 404)
    return {"data": public_job(job)}
