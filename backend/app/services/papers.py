from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.core.errors import DomainError
from app.models import (
    OutboxEvent,
    Paper,
    PaperFile,
    ProcessingJob,
    Project,
    ProjectPaper,
    UploadSession,
    Workspace,
)
from app.services.research import owned


async def associate_project(db, ctx, project_id, paper_id):
    await owned(db, Project, project_id, ctx)
    await owned(db, Paper, paper_id, ctx)
    await db.execute(
        insert(ProjectPaper)
        .values(workspace_id=ctx.workspace_id, project_id=project_id, paper_id=paper_id)
        .on_conflict_do_nothing()
    )


async def initialize_upload(db, ctx, body):
    settings = get_settings()
    if body.size_bytes > settings.max_upload_bytes:
        raise DomainError("FILE_TOO_LARGE", "PDF 超出当前上传大小限制", 413)
    if (
        not body.filename.lower().endswith(".pdf")
        or PurePath(body.filename).name != body.filename
        or "\\" in body.filename
    ):
        raise DomainError("UNSUPPORTED_FILE", "只支持合法命名的 PDF 文件", 415)
    await db.execute(select(Workspace).where(Workspace.id == ctx.workspace_id).with_for_update())
    total = (
        await db.execute(
            select(func.coalesce(func.sum(PaperFile.size_bytes), 0)).where(
                PaperFile.workspace_id == ctx.workspace_id,
                PaperFile.upload_status != "failed",
                PaperFile.availability_status != "missing",
            )
        )
    ).scalar_one()
    if total + body.size_bytes > settings.workspace_quota_bytes:
        raise DomainError("QUOTA_EXCEEDED", "科研空间文件额度不足", 413)
    if body.paper_id:
        paper = await owned(db, Paper, body.paper_id, ctx, lock=True)
    else:
        paper = Paper(id=uuid4(), workspace_id=ctx.workspace_id, title=body.title or body.filename[:-4])
        db.add(paper)
        await db.flush()
    version = (
        await db.execute(
            select(func.coalesce(func.max(PaperFile.version_no), 0)).where(PaperFile.paper_id == paper.id)
        )
    ).scalar_one() + 1
    file_id, upload_id = uuid4(), uuid4()
    file = PaperFile(
        id=file_id,
        workspace_id=ctx.workspace_id,
        paper_id=paper.id,
        version_no=version,
        storage_key=f"final/{ctx.workspace_id}/{paper.id}/{file_id}.pdf",
        original_filename=body.filename,
        size_bytes=body.size_bytes,
    )
    db.add(file)
    await db.flush()
    upload = UploadSession(
        id=upload_id,
        workspace_id=ctx.workspace_id,
        paper_id=paper.id,
        paper_file_id=file_id,
        staging_key=f"staging/{ctx.workspace_id}/{upload_id}.pdf",
        expected_size=body.size_bytes,
        expected_sha256=body.sha256,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(upload)
    if body.project_id:
        await associate_project(db, ctx, body.project_id, paper.id)
    duplicates = []
    if body.sha256:
        candidates = list(
            (
                await db.execute(
                    select(PaperFile)
                    .where(
                        PaperFile.workspace_id == ctx.workspace_id,
                        PaperFile.sha256 == body.sha256,
                        PaperFile.upload_status == "uploaded",
                        PaperFile.availability_status == "available",
                    )
                    .limit(10)
                )
            ).scalars()
        )
        duplicates = [
            {"paper_id": str(row.paper_id), "paper_file_id": str(row.id), "version_no": row.version_no}
            for row in candidates
        ]
    await db.flush()
    return {
        "data": {
            "upload_id": str(upload.id),
            "paper_id": str(paper.id),
            "paper_file_id": str(file.id),
            "upload_url": f"/api/v1/uploads/{upload.id}/content",
            "expires_at": upload.expires_at.isoformat(),
            "duplicates": duplicates,
            "size_limit": settings.max_upload_bytes,
        }
    }


async def queue_upload_validation(db, ctx, paper_id, body):
    await owned(db, Paper, paper_id, ctx)
    upload = await owned(db, UploadSession, body.upload_id, ctx, lock=True)
    if upload.paper_id != paper_id:
        raise DomainError("ASSOCIATION_CONFLICT", "上传与文献不一致", 409)
    if upload.status not in {"pending", "validating", "completed"}:
        raise DomainError("STATE_CONFLICT", "上传状态不能确认", 409)
    if upload.expires_at < datetime.now(UTC) and upload.status == "pending":
        raise DomainError("UPLOAD_EXPIRED", "上传已过期，请重新初始化", 409)
    job = (
        await db.execute(
            select(ProcessingJob)
            .where(ProcessingJob.paper_file_id == upload.paper_file_id)
            .order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    created_job = job is None
    if not job and upload.status != "pending":
        raise DomainError("STATE_CONFLICT", "已确认上传的任务记录不可用，请先核对文件状态", 409)
    if not job:
        job = ProcessingJob(id=uuid4(), workspace_id=ctx.workspace_id, paper_file_id=upload.paper_file_id)
        db.add(job)
        await db.flush()
        db.add(
            OutboxEvent(
                id=uuid4(),
                workspace_id=ctx.workspace_id,
                event_type="parse_pdf",
                aggregate_id=job.id,
                payload={"job_id": str(job.id)},
            )
        )
    upload.status = "validating" if upload.status != "completed" else "completed"
    file = await owned(db, PaperFile, upload.paper_file_id, ctx)
    if created_job and file.upload_status != "uploaded":
        file.parse_status = "queued"
    await db.flush()
    return {
        "data": {
            "upload_id": str(upload.id),
            "job_id": str(job.id),
            "status": job.status,
            "paper_file_id": str(file.id),
            "message": "后台验证与解析已接收"
            if created_job
            else "原处理任务已找到，请读取文件状态；失败解析需要明确重试",
        }
    }
