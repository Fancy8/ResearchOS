import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.session import get_session
from app.models import AuthSession, User, Workspace

hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(value, stored):
    try:
        return hasher.verify(stored, value)
    except (VerificationError, InvalidHashError):
        return False


@dataclass(frozen=True)
class WorkspaceContext:
    user_id: UUID
    workspace_id: UUID
    session_id: UUID


async def current_context(request: Request, db: AsyncSession = Depends(get_session, scope="function")):
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise DomainError("AUTH_REQUIRED", "请先登录", 401)
    now = datetime.now(UTC)
    scope_id = (
        await db.execute(
            select(Workspace.id)
            .join(User, User.id == Workspace.owner_user_id)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(AuthSession.token_hash == digest(token))
        )
    ).scalar_one_or_none()
    if scope_id:
        # Every authenticated transaction participates in cleanup exclusion.
        # Re-read status after taking the lock: a queued request may have waited.
        lock = (
            "pg_advisory_xact_lock"
            if request.method == "POST" and request.url.path == "/api/v1/deletions"
            else "pg_advisory_xact_lock_shared"
        )
        await db.execute(
            text(f"SELECT {lock}(hashtextextended(:scope,0))"),
            {"scope": f"resource:{scope_id}"},
        )
    row = (
        await db.execute(
            select(AuthSession, User, Workspace)
            .join(User, User.id == AuthSession.user_id)
            .join(Workspace, Workspace.owner_user_id == User.id)
            .where(
                AuthSession.token_hash == digest(token),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
                User.account_status == "active",
                Workspace.status == "active",
            )
        )
    ).first()
    if not row:
        raise DomainError("AUTH_REQUIRED", "登录已失效，请重新登录", 401)
    session, user, workspace = row
    if session.last_seen_at < now - timedelta(hours=settings.session_idle_hours):
        raise DomainError("AUTH_REQUIRED", "会话已过期", 401)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        csrf = request.headers.get("x-csrf-token", "")
        if origin != settings.frontend_origin or not secrets.compare_digest(digest(csrf), session.csrf_hash):
            raise DomainError("CSRF_REJECTED", "请求校验失败，请刷新页面", 403)
    session.last_seen_at = now
    return WorkspaceContext(user.id, workspace.id, session.id)


def new_session(user_id):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session = AuthSession(
        id=uuid4(),
        user_id=user_id,
        token_hash=digest(token),
        csrf_hash=digest(csrf),
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().session_days),
    )
    return session, token, csrf
