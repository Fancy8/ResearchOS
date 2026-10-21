"""Impact checks and short-lived, scope-bound deletion previews."""

import base64
import hashlib
import hmac
import json
import time
from uuid import UUID

from sqlalchemy import func, select

from app import models
from app.core.config import get_settings
from app.core.errors import DomainError
from app.services.research import owned


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def signature(encoded):
    return hmac.new(get_settings().control_secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()


def preview_token(ctx, scope, target_id, impact):
    payload = {
        "user": str(ctx.user_id),
        "workspace": str(ctx.workspace_id),
        "scope": scope,
        "target": str(target_id) if target_id else None,
        "impact": fingerprint(impact),
        "expires": int(time.time()) + 600,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode().rstrip("=")
    return encoded + "." + signature(encoded)


def validate_preview(token, ctx, scope, target_id, impact):
    try:
        encoded, supplied = token.split(".")
        if not hmac.compare_digest(signature(encoded), supplied):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        expected = {
            "user": str(ctx.user_id),
            "workspace": str(ctx.workspace_id),
            "scope": scope,
            "target": str(target_id) if target_id else None,
            "impact": fingerprint(impact),
        }
        if payload.get("expires", 0) <= time.time() or any(
            payload.get(key) != value for key, value in expected.items()
        ):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise DomainError("DELETION_PREVIEW_EXPIRED", "删除影响已变化或预览已过期，请重新预览", 409) from None


async def deletion_impact(db, ctx, scope: str, target_id: UUID | None):
    counts = {}
    if scope == "account":
        for table in sorted(models.Base.metadata.tables.values(), key=lambda row: row.name):
            if "workspace_id" not in table.c or table.name in {"deletion_jobs", "maintenance_checkpoints"}:
                continue
            counts[table.name] = (
                await db.execute(
                    select(func.count()).select_from(table).where(table.c.workspace_id == ctx.workspace_id)
                )
            ).scalar_one()
        return {
            "scope": scope,
            "counts": counts,
            "blocked": False,
            "effects": [
                "冻结账户并撤销全部会话",
                "清理个人资料、所有修订和原始文件",
                "删除完成后无法恢复在线资料",
            ],
            "backup_retention_days": get_settings().backup_retention_days,
        }
    file = await owned(db, models.PaperFile, target_id, ctx)
    evidence = (
        await db.execute(
            select(func.count()).select_from(models.Evidence).where(models.Evidence.paper_file_id == file.id)
        )
    ).scalar_one()
    active_exports = (
        await db.execute(
            select(func.count())
            .select_from(models.ExportJob)
            .where(
                models.ExportJob.workspace_id == ctx.workspace_id,
                models.ExportJob.status.in_(["queued", "running"]),
            )
        )
    ).scalar_one()
    return {
        "scope": scope,
        "paper_file_id": str(file.id),
        "paper_id": str(file.paper_id),
        "version_no": file.version_no,
        "is_current": file.is_current,
        "availability_status": file.availability_status,
        "counts": {"evidence": evidence, "active_exports": active_exports},
        "blocked": bool(evidence or active_exports or file.availability_status == "deleting"),
        "effects": ["移除这一版本的原始 PDF", "文献记录保留；当前版本被删除后需重新上传"],
    }
