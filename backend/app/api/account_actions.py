from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import ConfigDict, EmailStr, Field
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.identity import require_origin
from app.core.auth_mail import queue_auth_mail
from app.core.errors import DomainError
from app.core.security import WorkspaceContext, current_context, digest, hasher
from app.core.throttle import auth_limit
from app.db.session import get_session
from app.models import AuthSession, AuthToken, User, Workspace
from app.responses import Envelope, Message
from app.schemas import StrictModel

router = APIRouter()


class EmailRequest(StrictModel):
    email: EmailStr


class TokenRequest(StrictModel):
    token: str = Field(min_length=1, max_length=128)


class PasswordReset(TokenRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    password: str = Field(min_length=12, max_length=128)


@router.post("/auth/password-reset-requests", status_code=202, response_model=Envelope[Message])
async def request_reset(
    body: EmailRequest, request: Request, db: AsyncSession = Depends(get_session, scope="function")
):
    require_origin(request)
    email = str(body.email).lower()
    await auth_limit("reset-request", request, email, maximum=3)
    row = (
        await db.execute(
            select(User, Workspace)
            .join(Workspace, Workspace.owner_user_id == User.id)
            .where(User.email == email, User.account_status == "active", Workspace.status == "active")
        )
    ).first()
    if row:
        user, workspace = row
        await db.execute(
            text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:scope,0))"),
            {"scope": f"resource:{workspace.id}"},
        )
        # Recheck after cleanup exclusion, since the request may have waited.
        await db.refresh(user)
        await db.refresh(workspace)
        if user.account_status == "active" and workspace.status == "active":
            await queue_auth_mail(db, user, workspace.id, "password_reset")
    return {"data": {"message": "如邮箱对应可用账户，我们会发送密码重置邮件。请检查收件箱。"}}


@router.post("/auth/email-verification-requests", status_code=202, response_model=Envelope[Message])
async def request_verification(
    request: Request,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    await auth_limit("verify-request", request, str(ctx.user_id), maximum=3)
    user = await db.get(User, ctx.user_id)
    if not user.email_verified_at:
        await queue_auth_mail(db, user, ctx.workspace_id, "email_verify")
    return {"data": {"message": "验证邮件已安排发送，请检查收件箱。"}}


async def consume(db, token, purpose):
    match = (
        await db.execute(
            select(AuthToken.user_id).where(
                AuthToken.token_hash == digest(token), AuthToken.purpose == purpose
            )
        )
    ).scalar_one_or_none()
    workspace_id = (
        (await db.execute(select(Workspace.id).where(Workspace.owner_user_id == match))).scalar_one_or_none()
        if match
        else None
    )
    if not workspace_id:
        raise DomainError("AUTH_TOKEN_INVALID", "链接已过期、已使用或无效，请重新申请", 400)
    await db.execute(
        text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:scope,0))"),
        {"scope": f"resource:{workspace_id}"},
    )
    auth = (
        await db.execute(
            select(AuthToken)
            .where(
                AuthToken.token_hash == digest(token),
                AuthToken.purpose == purpose,
                AuthToken.used_at.is_(None),
                AuthToken.expires_at > datetime.now(UTC),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    user = await db.get(User, match)
    workspace = await db.get(Workspace, workspace_id)
    if (
        not auth
        or not user
        or user.account_status != "active"
        or not workspace
        or workspace.status != "active"
    ):
        raise DomainError("AUTH_TOKEN_INVALID", "链接已过期、已使用或无效，请重新申请", 400)
    auth.used_at, auth.delivery_ciphertext = datetime.now(UTC), None
    return user


@router.post("/auth/reset-password", response_model=Envelope[Message])
async def reset_password(
    body: PasswordReset, request: Request, db: AsyncSession = Depends(get_session, scope="function")
):
    require_origin(request)
    await auth_limit("reset-token", request, digest(body.token))
    user = await consume(db, body.token, "password_reset")
    user.password_hash = await run_in_threadpool(hasher.hash, body.password)
    await db.execute(
        update(AuthSession).where(AuthSession.user_id == user.id).values(revoked_at=datetime.now(UTC))
    )
    await db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user.id, AuthToken.purpose == "password_reset", AuthToken.used_at.is_(None)
        )
        .values(used_at=datetime.now(UTC), delivery_ciphertext=None)
    )
    return {"data": {"message": "密码已重置，原登录会话已撤销。请使用新密码登录。"}}


@router.post("/auth/verify-email", response_model=Envelope[Message])
async def verify_email(
    body: TokenRequest, request: Request, db: AsyncSession = Depends(get_session, scope="function")
):
    require_origin(request)
    await auth_limit("verify-token", request, digest(body.token))
    user = await consume(db, body.token, "email_verify")
    user.email_verified_at = datetime.now(UTC)
    return {"data": {"message": "邮箱验证已完成。"}}
