import hashlib
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app import responses as dto
from app.core.config import get_settings
from app.core.errors import DomainError, conflict, missing
from app.core.protocol import activity, entity, idempotent
from app.core.security import WorkspaceContext, current_context
from app.core.storage import get_object_bytes, put_object
from app.db.session import get_session
from app.models import (
    OutboxEvent,
    Paper,
    PaperFile,
    PaperPage,
    ProcessingJob,
    UploadSession,
)
from app.responses import DuplicatePublic, Envelope, FilePublic, PageEnvelope, PaperPublic
from app.schemas import PaperCreate, PaperPatch, UploadComplete, UploadInit
from app.services.papers import initialize_upload, queue_upload_validation
from app.services.research import owned, paginate

router = APIRouter()


@router.post(
    "/papers/{identifier}/files/{file_id}/parse-retry",
    status_code=202,
    response_model=dto.Envelope[dto.ParseRetryPublic],
)
async def parse_retry(
    identifier: UUID,
    file_id: UUID,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    async def action():
        await owned(db, Paper, identifier, ctx, lock=True)
        file = await owned(db, PaperFile, file_id, ctx, lock=True)
        if file.paper_id != identifier:
            missing()
        if file.availability_status != "available" or file.parse_status != "failed":
            raise DomainError(
                "PARSE_RETRY_REJECTED", "仅可重试可用文件的失败解析；进行中或已完成的解析无需重复", 409
            )
        upload = (
            await db.execute(select(UploadSession).where(UploadSession.paper_file_id == file.id))
        ).scalar_one_or_none()
        if upload and upload.status != "completed":
            upload.status = "validating"
            file.upload_status = "pending"
        file.parse_status = "queued"
        job = ProcessingJob(id=uuid4(), workspace_id=ctx.workspace_id, paper_file_id=file.id)
        db.add(job)
        db.add(
            OutboxEvent(
                id=uuid4(),
                workspace_id=ctx.workspace_id,
                event_type="parse_pdf",
                aggregate_id=job.id,
                payload={"job_id": str(job.id)},
            )
        )
        await db.flush()
        return {
            "data": {"job_id": str(job.id), "paper_file_id": str(file.id), "parse_status": file.parse_status}
        }

    return await idempotent(db, ctx, idempotency_key, f"parse:retry:{file_id}", {}, action, 202)


@router.get("/papers/duplicates", response_model=PageEnvelope[DuplicatePublic])
async def duplicate_files(
    sha256: str = Query(pattern=r"^[0-9a-f]{64}$"),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    result = await paginate(
        db,
        PaperFile,
        ctx,
        limit,
        cursor,
        [
            PaperFile.sha256 == sha256,
            PaperFile.upload_status == "uploaded",
            PaperFile.availability_status == "available",
        ],
        f"duplicates:{sha256}",
    )
    title_rows = await db.execute(
        select(Paper.id, Paper.title).where(
            Paper.workspace_id == ctx.workspace_id,
            Paper.id.in_([UUID(row["paper_id"]) for row in result["data"]]),
        )
    )
    titles = dict(title_rows.all())
    result["data"] = [
        {
            "paper_id": row["paper_id"],
            "paper_file_id": row["id"],
            "title": titles[UUID(row["paper_id"])],
            "version_no": row["version_no"],
        }
        for row in result["data"]
    ]
    return result


@router.get("/papers", response_model=PageEnvelope[PaperPublic])
async def papers(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    q: str = Query(default="", max_length=100),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    q = q.strip()
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    result = await paginate(
        db,
        Paper,
        ctx,
        limit,
        cursor,
        [Paper.title.ilike(pattern, escape="\\")] if q else [],
        f"q={q}" if q else "",
    )
    latest = (
        await db.execute(
            select(PaperFile)
            .where(
                PaperFile.workspace_id == ctx.workspace_id,
                PaperFile.paper_id.in_([UUID(row["id"]) for row in result["data"]]),
            )
            .distinct(PaperFile.paper_id)
            .order_by(PaperFile.paper_id, PaperFile.is_current.desc(), PaperFile.version_no.desc())
        )
    ).scalars()
    by_paper = {str(file.paper_id): file for file in latest}
    for item in result["data"]:
        file = by_paper.get(item["id"])
        item["file"] = (
            {
                name: getattr(file, name)
                for name in (
                    "version_no",
                    "parse_status",
                    "upload_status",
                    "availability_status",
                    "page_count",
                    "has_text_layer",
                )
            }
            if file
            else None
        )
    return result


@router.post("/papers", status_code=201, response_model=Envelope[PaperPublic])
async def paper_create(
    body: PaperCreate,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    paper = Paper(id=uuid4(), workspace_id=ctx.workspace_id, **body.model_dump())
    db.add(paper)
    await db.flush()
    await activity(db, ctx, "paper_created", paper)
    return {"data": entity(paper)}


@router.get("/papers/{identifier}", response_model=Envelope[PaperPublic])
async def paper_get(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return {"data": entity(await owned(db, Paper, identifier, ctx))}


@router.patch("/papers/{identifier}", response_model=Envelope[PaperPublic])
async def paper_patch(
    identifier: UUID,
    body: PaperPatch,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    paper = await owned(db, Paper, identifier, ctx, lock=True)
    if paper.version != body.expected_version:
        conflict(paper.version)
    for name, value in body.model_dump(exclude_unset=True, exclude={"expected_version"}).items():
        if value is None and name in {"title", "authors", "reading_status"}:
            raise DomainError("VALIDATION_ERROR", "字段不能为空", 422)
        setattr(paper, name, value)
    paper.version += 1
    await db.flush()
    await db.refresh(paper)
    return {"data": entity(paper)}


@router.post("/papers/upload-init", status_code=201, response_model=dto.Envelope[dto.UploadInitializedPublic])
async def upload_init(
    body: UploadInit,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    async def action():
        return await initialize_upload(db, ctx, body)

    return await idempotent(db, ctx, idempotency_key, "upload:init", body.model_dump(), action)


@router.post("/uploads/{identifier}/content", response_model=dto.Envelope[dto.UploadReceivedPublic])
async def upload_content(
    identifier: UUID,
    file: UploadFile = File(),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await db.execute(
        text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:scope,0))"),
        {"scope": f"resource:{ctx.workspace_id}"},
    )
    upload = await owned(db, UploadSession, identifier, ctx, lock=True)
    if upload.status != "pending" or upload.expires_at < datetime.now(UTC):
        raise DomainError("STATE_CONFLICT", "上传已确认或过期，不能覆盖", 409)
    buffer = BytesIO()
    while chunk := await file.read(1024 * 1024):
        buffer.write(chunk)
        if buffer.tell() > min(get_settings().max_upload_bytes, upload.expected_size):
            raise DomainError("FILE_TOO_LARGE", "实际上传超出声明大小", 413)
    data = buffer.getvalue()
    if len(data) != upload.expected_size or not data.startswith(b"%PDF-"):
        raise DomainError("INVALID_PDF", "文件大小或 PDF 内容标识不合法", 415)
    await run_in_threadpool(put_object, upload.staging_key, data)
    return {"data": {"upload_id": str(upload.id), "bytes_received": len(data)}}


@router.get("/uploads/{identifier}", response_model=dto.Envelope[dto.UploadStatusPublic])
async def upload_status(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    upload = await owned(db, UploadSession, identifier, ctx)
    return {
        "data": {
            "id": str(upload.id),
            "status": upload.status,
            "paper_id": str(upload.paper_id),
            "paper_file_id": str(upload.paper_file_id),
            "expires_at": upload.expires_at.isoformat(),
        }
    }


@router.post(
    "/papers/{identifier}/upload-complete",
    status_code=202,
    response_model=dto.Envelope[dto.UploadCompletedPublic],
)
async def upload_complete(
    identifier: UUID,
    body: UploadComplete,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    async def action():
        return await queue_upload_validation(db, ctx, identifier, body)

    return await idempotent(
        db, ctx, idempotency_key, f"upload:complete:{identifier}", body.model_dump(), action, 202
    )


@router.get("/papers/{identifier}/files", response_model=PageEnvelope[FilePublic])
async def files(
    identifier: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, Paper, identifier, ctx)
    return await paginate(
        db,
        PaperFile,
        ctx,
        limit,
        cursor,
        [PaperFile.paper_id == identifier],
        str(identifier),
        sort_field="version_no",
    )


async def accessible_file(db, ctx, identifier, file_id=None):
    await owned(db, Paper, identifier, ctx)
    if file_id:
        file = await owned(db, PaperFile, file_id, ctx)
        if file.paper_id != identifier:
            missing()
    else:
        file = (
            await db.execute(
                select(PaperFile).where(
                    PaperFile.workspace_id == ctx.workspace_id,
                    PaperFile.paper_id == identifier,
                    PaperFile.is_current.is_(True),
                )
            )
        ).scalar_one_or_none()
    if not file or file.upload_status != "uploaded" or file.availability_status != "available":
        raise DomainError("SOURCE_UNAVAILABLE", "PDF 尚未可用，请查看上传和解析状态", 409)
    return file


@router.get("/papers/{identifier}/file", response_model=dto.Envelope[dto.FileAddressPublic])
async def file_address(
    identifier: UUID,
    file_id: UUID | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    file = await accessible_file(db, ctx, identifier, file_id)
    return {
        "data": {
            "url": f"/api/v1/papers/{identifier}/content?file_id={file.id}",
            "paper_file_id": str(file.id),
            "version_no": file.version_no,
            "is_current": file.is_current,
            "page_count": file.page_count,
            "has_text_layer": file.has_text_layer,
        }
    }


@router.get(
    "/papers/{identifier}/content",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def file_content(
    identifier: UUID,
    file_id: UUID | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    file = await accessible_file(db, ctx, identifier, file_id)
    data = await run_in_threadpool(get_object_bytes, file.storage_key)
    checksum = await run_in_threadpool(lambda: hashlib.sha256(data).hexdigest())
    if len(data) != file.size_bytes or checksum != file.sha256:
        raise DomainError("SOURCE_INTEGRITY_FAILURE", "原始文件完整性校验失败，不能作为原文来源显示", 409)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=paper.pdf"},
    )


@router.get("/papers/{identifier}/parse-status", response_model=dto.Envelope[dto.ParseStatusPublic])
async def parse_status(
    identifier: UUID,
    file_id: UUID | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, Paper, identifier, ctx)
    filters = [PaperFile.workspace_id == ctx.workspace_id, PaperFile.paper_id == identifier]
    if file_id:
        filters.append(PaperFile.id == file_id)
    file = (
        await db.execute(select(PaperFile).where(*filters).order_by(PaperFile.version_no.desc()).limit(1))
    ).scalar_one_or_none()
    if not file:
        missing()
    job = (
        await db.execute(
            select(ProcessingJob)
            .where(ProcessingJob.workspace_id == ctx.workspace_id, ProcessingJob.paper_file_id == file.id)
            .order_by(ProcessingJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "data": {
            "paper_file_id": str(file.id),
            "upload_status": file.upload_status,
            "parse_status": file.parse_status,
            "page_count": file.page_count,
            "has_text_layer": file.has_text_layer,
            "error_code": job.error_code if job else None,
            "attempts": job.attempts if job else 0,
        }
    }


@router.get("/papers/{identifier}/files/{file_id}/pages/{page}", response_model=dto.Envelope[dto.PagePublic])
async def paper_page(
    identifier: UUID,
    file_id: UUID,
    page: int,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await accessible_file(db, ctx, identifier, file_id)
    row = (
        await db.execute(
            select(PaperPage).where(
                PaperPage.workspace_id == ctx.workspace_id,
                PaperPage.paper_file_id == file_id,
                PaperPage.page_number == page,
            )
        )
    ).scalar_one_or_none()
    if not row:
        missing()
    return {"data": entity(row)}


@router.post(
    "/papers/{identifier}/files/{file_id}/set-current", response_model=dto.Envelope[dto.CurrentFilePublic]
)
async def set_current(
    identifier: UUID,
    file_id: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, Paper, identifier, ctx, lock=True)
    file = await accessible_file(db, ctx, identifier, file_id)
    rows = list(
        (
            await db.execute(
                select(PaperFile).where(
                    PaperFile.workspace_id == ctx.workspace_id,
                    PaperFile.paper_id == identifier,
                    PaperFile.is_current.is_(True),
                )
            )
        ).scalars()
    )
    for row in rows:
        row.is_current = False
    await db.flush()
    file.is_current = True
    await db.flush()
    return {"data": {"paper_file_id": str(file.id), "version_no": file.version_no}}
