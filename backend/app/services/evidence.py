import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import DomainError, conflict
from app.core.protocol import activity, entity
from app.models import Evidence, PaperFile, PaperPage, ResearchThread, ThreadPaper
from app.services.papers import associate_project
from app.services.research import owned


async def create_evidence(db, ctx, thread_id, body):
    line = await owned(db, ResearchThread, thread_id, ctx)
    file = await owned(db, PaperFile, body.paper_file_id, ctx)
    if (
        file.paper_id != body.paper_id
        or file.upload_status != "uploaded"
        or file.availability_status != "available"
    ):
        raise DomainError("SOURCE_UNAVAILABLE", "证据来源文件不可用或不匹配", 409)
    source = body.source
    capture_value = source.get("capture_method", "selected")
    if not isinstance(capture_value, str) or capture_value not in {"selected", "manual"}:
        raise DomainError("INVALID_SOURCE", "摘录方式无效", 422)
    schema_version = source.get("anchor_schema_version", 1)
    if type(schema_version) is not int or schema_version != 1:
        raise DomainError("INVALID_SOURCE", "来源定位版本无效", 422)
    coordinate = source.get("coordinate_space")
    if coordinate is not None and (
        not isinstance(coordinate, str) or coordinate != "unrotated-cropbox-top-left-normalized"
    ):
        raise DomainError("INVALID_SOURCE", "来源坐标系无效", 422)
    if set(source) - {
        "page_start",
        "page_end",
        "anchor_schema_version",
        "text_quote",
        "rects",
        "coordinate_space",
        "capture_method",
    }:
        raise DomainError("INVALID_SOURCE", "来源字段无效", 422)
    start, end = source.get("page_start"), source.get("page_end")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not file.page_count
        or not 1 <= start <= end <= file.page_count
        or end - start > 10
    ):
        raise DomainError("INVALID_SOURCE", "来源页码无效", 422)
    if not body.quote_text.strip():
        raise DomainError("INVALID_SOURCE", "证据摘录不能为空", 422)
    rects = source.get("rects", [])
    if not isinstance(rects, list) or len(rects) > 500:
        raise DomainError("INVALID_SOURCE", "定位矩形无效", 422)
    for rect in rects:
        if not isinstance(rect, dict) or set(rect) != {"page", "x", "y", "width", "height"}:
            raise DomainError("INVALID_SOURCE", "定位矩形字段无效", 422)
        if (
            type(rect["page"]) is not int
            or rect["page"] not in range(start, end + 1)
            or any(
                type(rect[name]) not in (int, float) or not 0 <= rect[name] <= 1
                for name in ("x", "y", "width", "height")
            )
            or rect["x"] + rect["width"] > 1.001
            or rect["y"] + rect["height"] > 1.001
        ):
            raise DomainError("INVALID_SOURCE", "定位坐标越界", 422)
    pages = list(
        (
            await db.execute(
                select(PaperPage)
                .where(
                    PaperPage.workspace_id == ctx.workspace_id,
                    PaperPage.paper_file_id == file.id,
                    PaperPage.page_number.between(start, end),
                )
                .order_by(PaperPage.page_number)
            )
        ).scalars()
    )

    def normalized(text):
        return re.sub(r"\s+", " ", text).strip()

    quote = normalized(body.quote_text)
    text = normalized("\n".join(page.text_content for page in pages))
    matches = [match.start() for match in re.finditer(re.escape(quote), text)] if quote else []
    capture = source.get("capture_method", "selected")
    # Server-authoritative text anchor; client rectangles are hints, never proof.
    located = capture == "selected" and len(matches) == 1 and file.parse_status == "ready"
    anchor = {
        "anchor_schema_version": 1,
        "file_sha256": file.sha256,
        "parser_version": file.parser_version,
        "text_quote": {"exact": body.quote_text},
        "normalized_offset": matches[0] if located else None,
        "rects": rects,
        "coordinate_space": source.get("coordinate_space"),
        "capture_method": capture,
        "text_verified": bool(matches),
    }
    await associate_project(db, ctx, line.project_id, body.paper_id)
    await db.execute(
        insert(ThreadPaper)
        .values(
            workspace_id=ctx.workspace_id,
            project_id=line.project_id,
            thread_id=line.id,
            paper_id=body.paper_id,
        )
        .on_conflict_do_nothing()
    )
    item = Evidence(
        id=uuid4(),
        workspace_id=ctx.workspace_id,
        project_id=line.project_id,
        thread_id=line.id,
        paper_id=body.paper_id,
        paper_file_id=file.id,
        quote_text=body.quote_text,
        interpretation=body.interpretation,
        tags=body.tags,
        page_start=start,
        page_end=end,
        source_anchor=anchor,
        anchor_status="located" if located else "page_only",
        created_by=ctx.user_id,
    )
    db.add(item)
    await db.flush()
    await activity(
        db,
        ctx,
        "evidence_created",
        item,
        item.project_id,
        item.thread_id,
        {"paper_file_id": str(file.id), "evidence_id": str(item.id), "anchor_status": item.anchor_status},
    )
    return {"data": entity(item)}


async def patch_evidence(db, ctx, identifier, body):
    item = await owned(db, Evidence, identifier, ctx, lock=True)
    if item.version != body.expected_version:
        conflict(item.version)
    for name, value in body.model_dump(exclude_unset=True, exclude={"expected_version"}).items():
        if value is None:
            raise DomainError("VALIDATION_ERROR", "解释与标签不能为 null", 422)
        setattr(item, name, value)
    item.version += 1
    await db.flush()
    await db.refresh(item)
    await activity(
        db, ctx, "evidence_interpreted", item, item.project_id, item.thread_id, {"version": item.version}
    )
    return {"data": entity(item)}
