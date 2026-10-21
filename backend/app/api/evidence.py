from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.protocol import entity, idempotent
from app.core.security import WorkspaceContext, current_context
from app.db.session import get_session
from app.models import Evidence, ResearchThread
from app.responses import Envelope, EvidencePublic, PageEnvelope
from app.schemas import EvidenceCreate, EvidencePatch, EvidenceReuse
from app.services.evidence import create_evidence, patch_evidence
from app.services.research import owned, paginate

router = APIRouter()


@router.get("/threads/{identifier}/evidence", response_model=PageEnvelope[EvidencePublic])
async def list_evidence(
    identifier: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await owned(db, ResearchThread, identifier, ctx)
    return await paginate(
        db, Evidence, ctx, limit, cursor, [Evidence.thread_id == identifier], str(identifier)
    )


@router.post("/threads/{identifier}/evidence", status_code=201, response_model=Envelope[EvidencePublic])
async def evidence_create(
    identifier: UUID,
    body: EvidenceCreate,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    async def action():
        return await create_evidence(db, ctx, identifier, body)

    return await idempotent(
        db, ctx, idempotency_key, f"evidence:create:{identifier}", body.model_dump(), action
    )


@router.get("/evidence/{identifier}", response_model=Envelope[EvidencePublic])
async def evidence_get(
    identifier: UUID,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return {"data": entity(await owned(db, Evidence, identifier, ctx))}


@router.patch("/evidence/{identifier}", response_model=Envelope[EvidencePublic])
async def evidence_patch(
    identifier: UUID,
    body: EvidencePatch,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return await patch_evidence(db, ctx, identifier, body)


@router.post("/evidence/{identifier}/reuse", status_code=201, response_model=Envelope[EvidencePublic])
async def evidence_reuse(
    identifier: UUID,
    body: EvidenceReuse,
    idempotency_key: str | None = Header(default=None),
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    original = await owned(db, Evidence, identifier, ctx)
    source = {
        "page_start": original.page_start,
        "page_end": original.page_end,
        "capture_method": original.source_anchor.get("capture_method", "selected"),
    }
    request = EvidenceCreate(
        paper_id=original.paper_id,
        paper_file_id=original.paper_file_id,
        quote_text=original.quote_text,
        interpretation=original.interpretation,
        tags=original.tags,
        source=source,
    )

    async def action():
        return await create_evidence(db, ctx, body.target_thread_id, request)

    return await idempotent(
        db, ctx, idempotency_key, f"evidence:reuse:{identifier}", body.model_dump(), action
    )
