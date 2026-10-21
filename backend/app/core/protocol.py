import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, text

from app.core.errors import DomainError
from app.models import ActivityEvent, ApiIdempotencyKey


def entity(row):
    return jsonable_encoder({column.name: getattr(row, column.name) for column in row.__table__.columns})


async def activity(db, ctx, event_type, target, project_id=None, thread_id=None, payload=None):
    db.add(
        ActivityEvent(
            id=uuid4(),
            workspace_id=ctx.workspace_id,
            actor_user_id=ctx.user_id,
            project_id=project_id,
            thread_id=thread_id,
            event_type=event_type,
            target_type=target.__tablename__,
            target_id=target.id,
            event_payload=payload or {},
        )
    )


def pack_cursor(created_at, identifier, fingerprint):
    stamp = created_at.isoformat() if isinstance(created_at, datetime) else created_at
    value = json.dumps([stamp, str(identifier), fingerprint]).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def unpack_cursor(cursor, fingerprint, numeric=False):
    try:
        if len(cursor) > 2048:
            raise ValueError()
        stamp, identifier, scope = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if scope != fingerprint or not isinstance(identifier, str):
            raise ValueError()
        if numeric:
            if type(stamp) is not int or not 1 <= stamp <= 2147483647:
                raise ValueError()
            return stamp, UUID(identifier)
        if not isinstance(stamp, str):
            raise ValueError()
        timestamp = datetime.fromisoformat(stamp)
        if timestamp.tzinfo is None:
            raise ValueError()
        return timestamp, UUID(identifier)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise DomainError("INVALID_CURSOR", "分页参数无效", 422) from None


async def idempotent(db, ctx, key, operation, body, action, status=201):
    if not key or not 1 <= len(key) <= 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "请提供有效幂等键", 422)
    fingerprint = hashlib.sha256(
        json.dumps(jsonable_encoder(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    lock_scope = f"{ctx.workspace_id}:{ctx.user_id}:{operation}:{key}"
    # Transaction-level advisory lock serializes equal keys without committing a reservation.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:value,0))"), {"value": lock_scope})
    existing = (
        await db.execute(
            select(ApiIdempotencyKey).where(
                ApiIdempotencyKey.workspace_id == ctx.workspace_id,
                ApiIdempotencyKey.actor_user_id == ctx.user_id,
                ApiIdempotencyKey.operation == operation,
                ApiIdempotencyKey.key == key,
            )
        )
    ).scalar_one_or_none()
    if existing:
        if existing.request_hash != fingerprint:
            raise DomainError("IDEMPOTENCY_CONFLICT", "同一请求键不能用于不同操作内容", 409)
        return existing.response_body
    result = jsonable_encoder(await action())
    db.add(
        ApiIdempotencyKey(
            id=uuid4(),
            workspace_id=ctx.workspace_id,
            actor_user_id=ctx.user_id,
            operation=operation,
            key=key,
            request_hash=fingerprint,
            response_status=status,
            response_body=result,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db.flush()
    return result
