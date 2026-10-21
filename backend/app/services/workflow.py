from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.core.errors import DomainError, conflict, missing
from app.core.protocol import activity, entity
from app.models import (
    DecisionRevision,
    DecisionRevisionEvidenceLink,
    DecisionRevisionHypothesisLink,
    DecisionRevisionNoteLink,
    Evidence,
    Hypothesis,
    HypothesisEvidenceLink,
    HypothesisRevision,
    Note,
    Project,
    ResearchDecision,
    ResearchThread,
    Task,
)
from app.services.research import owned


async def save_hypothesis_revision(db, ctx, item):
    links = list(
        (
            await db.execute(
                select(HypothesisEvidenceLink)
                .where(
                    HypothesisEvidenceLink.workspace_id == ctx.workspace_id,
                    HypothesisEvidenceLink.hypothesis_id == item.id,
                )
                .order_by(HypothesisEvidenceLink.evidence_id)
            )
        ).scalars()
    )
    snapshot = [entity(row) for row in links]
    db.add(
        HypothesisRevision(
            id=uuid4(),
            workspace_id=ctx.workspace_id,
            project_id=item.project_id,
            thread_id=item.thread_id,
            hypothesis_id=item.id,
            revision_no=item.current_revision,
            statement=item.statement,
            status=item.status,
            evidence_links_snapshot=snapshot,
            created_by=ctx.user_id,
        )
    )
    await db.flush()


async def create_hypothesis(db, ctx, thread_id, body):
    line = await owned(db, ResearchThread, thread_id, ctx)
    item = Hypothesis(
        id=uuid4(),
        workspace_id=ctx.workspace_id,
        project_id=line.project_id,
        thread_id=thread_id,
        **body.model_dump(),
    )
    db.add(item)
    await db.flush()
    await save_hypothesis_revision(db, ctx, item)
    await activity(db, ctx, "hypothesis_created", item, item.project_id, item.thread_id)
    return {"data": entity(item)}


async def patch_hypothesis(db, ctx, identifier, body):
    item = await owned(db, Hypothesis, identifier, ctx, lock=True)
    if item.version != body.expected_version:
        conflict(item.version)
    values = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    if any(value is None for value in values.values()):
        raise DomainError("VALIDATION_ERROR", "假设字段不能为空", 422)
    for key, value in values.items():
        setattr(item, key, value)
    item.version += 1
    item.current_revision += 1
    await db.flush()
    await save_hypothesis_revision(db, ctx, item)
    await db.refresh(item)
    await activity(
        db,
        ctx,
        "hypothesis_updated",
        item,
        item.project_id,
        item.thread_id,
        {"revision_no": item.current_revision, "status": item.status},
    )
    return {"data": entity(item)}


async def set_hypothesis_link(db, ctx, identifier, body, remove=False):
    item = await owned(db, Hypothesis, identifier, ctx, lock=True)
    if item.version != body.expected_version:
        conflict(item.version)
    evidence = await owned(db, Evidence, body.evidence_id, ctx)
    if evidence.thread_id != item.thread_id:
        raise DomainError("ASSOCIATION_CONFLICT", "证据必须属于同一研究线索", 409)
    link = (
        await db.execute(
            select(HypothesisEvidenceLink).where(
                HypothesisEvidenceLink.workspace_id == ctx.workspace_id,
                HypothesisEvidenceLink.hypothesis_id == identifier,
                HypothesisEvidenceLink.evidence_id == body.evidence_id,
            )
        )
    ).scalar_one_or_none()
    if remove:
        if not link:
            missing()
        await db.delete(link)
    elif link:
        link.relation, link.explanation = body.relation, body.explanation
        link.version += 1
    else:
        db.add(
            HypothesisEvidenceLink(
                workspace_id=ctx.workspace_id,
                project_id=item.project_id,
                thread_id=item.thread_id,
                hypothesis_id=item.id,
                evidence_id=evidence.id,
                relation=body.relation,
                explanation=body.explanation,
            )
        )
    item.version += 1
    item.current_revision += 1
    await db.flush()
    await save_hypothesis_revision(db, ctx, item)
    await db.refresh(item)
    await activity(
        db,
        ctx,
        "evidence_unlinked" if remove else "evidence_linked",
        item,
        item.project_id,
        item.thread_id,
        {"evidence_id": str(evidence.id), "relation": body.relation, "revision_no": item.current_revision},
    )
    return {"data": entity(item)}


async def append_decision_revision(db, ctx, item, body):
    revision = DecisionRevision(
        id=uuid4(),
        workspace_id=ctx.workspace_id,
        project_id=item.project_id,
        thread_id=item.thread_id,
        decision_id=item.id,
        revision_no=item.current_revision,
        reason=body.reason,
        content=body.content,
        title_snapshot=body.title,
        decision_type_snapshot=body.decision_type,
        created_by=ctx.user_id,
    )
    db.add(revision)
    await db.flush()
    for identifier in sorted(set(body.evidence_ids)):
        source = await owned(db, Evidence, identifier, ctx, lock=True)
        if source.thread_id != item.thread_id:
            raise DomainError("ASSOCIATION_CONFLICT", "决策证据必须属于同一研究线索", 409)
        db.add(
            DecisionRevisionEvidenceLink(
                workspace_id=ctx.workspace_id,
                project_id=item.project_id,
                thread_id=item.thread_id,
                decision_revision_id=revision.id,
                evidence_id=source.id,
                quote_snapshot=source.quote_text,
                interpretation_snapshot=source.interpretation,
                evidence_version=source.version,
                paper_file_id=source.paper_file_id,
                page_start=source.page_start,
                page_end=source.page_end,
                source_anchor_snapshot=source.source_anchor,
            )
        )
    for identifier in sorted(set(body.hypothesis_ids)):
        source = await owned(db, Hypothesis, identifier, ctx, lock=True)
        if source.thread_id != item.thread_id:
            raise DomainError("ASSOCIATION_CONFLICT", "决策假设必须属于同一研究线索", 409)
        db.add(
            DecisionRevisionHypothesisLink(
                workspace_id=ctx.workspace_id,
                project_id=item.project_id,
                thread_id=item.thread_id,
                decision_revision_id=revision.id,
                hypothesis_id=source.id,
                statement_snapshot=source.statement,
                status_snapshot=source.status,
                hypothesis_revision_no=source.current_revision,
            )
        )
    for identifier in sorted(set(body.note_ids)):
        source = await owned(db, Note, identifier, ctx, lock=True)
        if source.deleted_at:
            missing()
        db.add(
            DecisionRevisionNoteLink(
                workspace_id=ctx.workspace_id,
                project_id=item.project_id,
                thread_id=item.thread_id,
                decision_revision_id=revision.id,
                note_id=source.id,
                note_version=source.version,
                content_snapshot=source.content,
            )
        )
    await db.flush()
    return revision


async def create_decision(db, ctx, thread_id, body):
    line = await owned(db, ResearchThread, thread_id, ctx)
    item = ResearchDecision(
        id=uuid4(),
        workspace_id=ctx.workspace_id,
        project_id=line.project_id,
        thread_id=thread_id,
        title=body.title,
        decision_type=body.decision_type,
    )
    db.add(item)
    await db.flush()
    revision = await append_decision_revision(db, ctx, item, body)
    await activity(
        db,
        ctx,
        "decision_created",
        item,
        item.project_id,
        item.thread_id,
        {
            "revision_no": item.current_revision,
            "revision_id": str(revision.id),
            "evidence_ids": [str(value) for value in body.evidence_ids],
        },
    )
    return {"data": entity(item)}


async def revise_decision(db, ctx, identifier, body):
    item = await owned(db, ResearchDecision, identifier, ctx, lock=True)
    if item.current_revision != body.expected_revision:
        conflict(item.current_revision)
    item.current_revision += 1
    item.title, item.decision_type = body.title, body.decision_type
    revision = await append_decision_revision(db, ctx, item, body)
    await db.refresh(item)
    await activity(
        db,
        ctx,
        "decision_revised",
        item,
        item.project_id,
        item.thread_id,
        {
            "revision_no": item.current_revision,
            "revision_id": str(revision.id),
            "evidence_ids": [str(value) for value in body.evidence_ids],
        },
    )
    return {"data": entity(item)}


async def create_task(db, ctx, body):
    await owned(db, Project, body.project_id, ctx)
    if body.thread_id:
        line = await owned(db, ResearchThread, body.thread_id, ctx)
        if line.project_id != body.project_id:
            raise DomainError("ASSOCIATION_CONFLICT", "任务课题与研究线索不一致", 409)
    revision_no = body.source_revision_no
    if body.decision_id:
        decision = await owned(db, ResearchDecision, body.decision_id, ctx)
        if decision.project_id != body.project_id or decision.thread_id != body.thread_id:
            raise DomainError("ASSOCIATION_CONFLICT", "任务与原决策归属不一致", 409)
        revision_no = revision_no or decision.current_revision
        exists = (
            await db.execute(
                select(DecisionRevision.id).where(
                    DecisionRevision.decision_id == decision.id,
                    DecisionRevision.workspace_id == ctx.workspace_id,
                    DecisionRevision.revision_no == revision_no,
                )
            )
        ).first()
        if not exists:
            missing()
    elif revision_no:
        raise DomainError("VALIDATION_ERROR", "来源版本需要同时指定决策", 422)
    values = body.model_dump(exclude={"source_revision_no"})
    item = Task(
        id=uuid4(),
        workspace_id=ctx.workspace_id,
        source_revision_no=revision_no,
        completed_at=datetime.now(UTC) if body.status == "done" else None,
        **values,
    )
    db.add(item)
    await db.flush()
    await activity(
        db,
        ctx,
        "task_from_decision" if body.decision_id else "task_created",
        item,
        item.project_id,
        item.thread_id,
        {
            "decision_id": str(body.decision_id) if body.decision_id else None,
            "source_revision_no": revision_no,
        },
    )
    return {"data": entity(item)}


async def patch_task(db, ctx, identifier, body):
    item = await owned(db, Task, identifier, ctx, lock=True)
    if item.version != body.expected_version:
        conflict(item.version)
    previous = item.status
    for key, value in body.model_dump(exclude_unset=True, exclude={"expected_version"}).items():
        if value is None and key != "due_date":
            raise DomainError("VALIDATION_ERROR", "任务字段不能为空", 422)
        setattr(item, key, value)
    item.completed_at = (item.completed_at or datetime.now(UTC)) if item.status == "done" else None
    item.version += 1
    await db.flush()
    await db.refresh(item)
    await activity(
        db,
        ctx,
        "task_completed"
        if item.status == "done" and previous != "done"
        else "task_reopened"
        if previous == "done" and item.status != "done"
        else "task_updated",
        item,
        item.project_id,
        item.thread_id,
        {"status": item.status, "source_revision_no": item.source_revision_no},
    )
    return {"data": entity(item)}


def note_plaintext(document):
    allowed = {
        "doc",
        "paragraph",
        "heading",
        "text",
        "bulletList",
        "orderedList",
        "listItem",
        "blockquote",
        "codeBlock",
        "hardBreak",
        "horizontalRule",
        "inlineMath",
        "blockMath",
    }
    count, chunks = 0, []

    def visit(node, depth):
        nonlocal count
        count += 1
        if depth > 50 or count > 20000 or not isinstance(node, dict) or node.get("type") not in allowed:
            raise DomainError("INVALID_NOTE_DOCUMENT", "笔记结构包含不支持的内容或过大", 422)
        if set(node) - {"type", "content", "text", "attrs", "marks"}:
            raise DomainError("INVALID_NOTE_DOCUMENT", "笔记结构字段无效", 422)
        if (
            not isinstance(node.get("attrs", {}), dict)
            or not isinstance(node.get("content", []), list)
            or not isinstance(node.get("marks", []), list)
        ):
            raise DomainError("INVALID_NOTE_DOCUMENT", "笔记结构字段类型无效", 422)
        if node["type"] in {"inlineMath", "blockMath"}:
            latex = node.get("attrs", {}).get("latex")
            if not isinstance(latex, str) or not latex.strip() or len(latex) > 5000:
                raise DomainError(
                    "INVALID_NOTE_DOCUMENT", "公式需包含有效的 LaTeX 文本（最多 5000 字符）", 422
                )
            chunks.append(latex)
        if "text" in node:
            if not isinstance(node["text"], str):
                raise DomainError("INVALID_NOTE_DOCUMENT", "正文必须为文本", 422)
            chunks.append(node["text"])
        for mark in node.get("marks", []):
            if not isinstance(mark, dict) or mark.get("type") not in {
                "bold",
                "italic",
                "strike",
                "code",
                "underline",
                "link",
            }:
                raise DomainError("INVALID_NOTE_DOCUMENT", "不支持的文本格式", 422)
            if mark.get("type") == "link":
                attrs = mark.get("attrs", {})
                href = attrs.get("href", "") if isinstance(attrs, dict) else None
                if (
                    not isinstance(href, str)
                    or not href.startswith(("https://", "http://", "/"))
                    or href.startswith("//")
                ):
                    raise DomainError("INVALID_NOTE_DOCUMENT", "链接协议无效", 422)
        for child in node.get("content", []):
            visit(child, depth + 1)

    if document.get("type") != "doc":
        raise DomainError("INVALID_NOTE_DOCUMENT", "笔记必须是完整文档", 422)
    visit(document, 0)
    value = "\n".join(chunks)
    if len(value) > 200000:
        raise DomainError("INVALID_NOTE_DOCUMENT", "笔记超出支持大小", 422)
    return value


async def create_note(db, ctx, body):
    plain = note_plaintext(body.content)
    item = Note(
        id=uuid4(), workspace_id=ctx.workspace_id, title=body.title, content=body.content, search_text=plain
    )
    db.add(item)
    await db.flush()
    await activity(db, ctx, "note_created", item)
    return {"data": entity(item)}


async def save_note(db, ctx, identifier, body):
    item = await owned(db, Note, identifier, ctx, lock=True)
    if item.deleted_at:
        missing()
    if item.version != body.expected_version:
        conflict(item.version)
    item.search_text = note_plaintext(body.content)
    item.content, item.title = body.content, body.title
    item.version += 1
    item.last_saved_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(item)
    await activity(db, ctx, "note_saved", item, payload={"version": item.version})
    return {"data": entity(item)}
