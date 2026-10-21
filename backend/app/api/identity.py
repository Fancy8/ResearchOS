from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app import responses as dto
from app.core.auth_mail import queue_auth_mail
from app.core.config import get_settings
from app.core.errors import DomainError, conflict
from app.core.protocol import entity
from app.core.security import (
    DUMMY_HASH,
    WorkspaceContext,
    current_context,
    digest,
    hasher,
    new_session,
    verify_password,
)
from app.core.throttle import auth_limit
from app.db.session import get_session
from app.models import AuthSession, AuthToken, ResearchProfile, User, Workspace
from app.responses import Envelope, Identity, ProfilePublic
from app.schemas import Login, ProfilePatch, Register

router = APIRouter()


def require_origin(request):
    if request.headers.get("origin") != get_settings().frontend_origin:
        raise DomainError("CSRF_REJECTED", "请求来源无效", 403)


@router.post("/auth/register", status_code=201, response_model=dto.Envelope[dto.RegistrationPublic])
async def register(
    body: Register, request: Request, db: AsyncSession = Depends(get_session, scope="function")
):
    require_origin(request)
    email = str(body.email).lower()
    await auth_limit("register", request, email)
    if get_settings().invitation_required:
        invite = (
            await db.execute(
                select(AuthToken)
                .where(
                    AuthToken.token_hash == digest(body.invitation_token or ""),
                    AuthToken.purpose == "invite",
                    AuthToken.used_at.is_(None),
                    AuthToken.expires_at > datetime.now(UTC),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not invite or invite.email and invite.email.lower() != email:
            raise DomainError("INVITATION_REQUIRED", "需要有效且匹配邮箱的邀请码", 403)
        invite.used_at = datetime.now(UTC)
    if (await db.execute(select(User.id).where(User.email == email))).first():
        raise DomainError("REGISTRATION_REJECTED", "该注册请求无法完成，请尝试登录或找回密码", 409)
    user = User(
        id=uuid4(),
        email=email,
        display_name=body.display_name.strip(),
        password_hash=await run_in_threadpool(hasher.hash, body.password),
    )
    db.add(user)
    await db.flush()
    workspace = Workspace(id=uuid4(), owner_user_id=user.id)
    db.add(workspace)
    await db.flush()
    db.add(ResearchProfile(workspace_id=workspace.id))
    await queue_auth_mail(db, user, workspace.id, "email_verify")
    await db.flush()
    return {"data": {"id": str(user.id), "email": email, "workspace_id": str(workspace.id)}}


@router.post("/auth/login", response_model=dto.Envelope[dto.LoginPublic])
async def login(
    body: Login,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session, scope="function"),
):
    require_origin(request)
    await auth_limit("login", request, str(body.email).lower())
    user = (await db.execute(select(User).where(User.email == str(body.email).lower()))).scalar_one_or_none()
    valid = await run_in_threadpool(
        verify_password, body.password, user.password_hash if user else DUMMY_HASH
    )
    if not user or not valid or user.account_status != "active":
        raise DomainError("LOGIN_REJECTED", "邮箱或密码不正确", 401)
    old_token = request.cookies.get(get_settings().cookie_name)
    if old_token:
        old = (
            await db.execute(select(AuthSession).where(AuthSession.token_hash == digest(old_token)))
        ).scalar_one_or_none()
        if old:
            old.revoked_at = datetime.now(UTC)
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = await run_in_threadpool(hasher.hash, body.password)
    auth_session, token, csrf = new_session(user.id)
    db.add(auth_session)
    await db.flush()
    response.set_cookie(
        get_settings().cookie_name,
        token,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
        max_age=get_settings().session_days * 86400,
    )
    response.set_cookie(
        "researchos_csrf",
        csrf,
        httponly=False,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
        max_age=get_settings().session_days * 86400,
    )
    workspace = (await db.execute(select(Workspace).where(Workspace.owner_user_id == user.id))).scalar_one()
    return {
        "data": {
            "user_id": str(user.id),
            "workspace_id": str(workspace.id),
            "display_name": user.display_name,
            "csrf_token": csrf,
        }
    }


@router.post("/auth/logout", response_model=dto.Envelope[dto.LogoutPublic])
async def logout(
    response: Response,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    session = await db.get(AuthSession, ctx.session_id)
    session.revoked_at = datetime.now(UTC)
    response.delete_cookie(
        get_settings().cookie_name,
        path="/",
        secure=get_settings().cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie("researchos_csrf", path="/", secure=get_settings().cookie_secure, samesite="lax")
    return {"data": {"logged_out": True}}


@router.get("/me", response_model=Envelope[Identity], response_model_exclude_unset=True)
async def me(
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    user = await db.get(User, ctx.user_id)
    profile = await db.get(ResearchProfile, ctx.workspace_id)
    return {
        "data": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "workspace_id": str(ctx.workspace_id),
            "onboarding": profile.onboarding_state,
            "email_verified_at": user.email_verified_at,
        }
    }


@router.get("/research-profile", response_model=Envelope[ProfilePublic])
async def profile(
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    return {"data": entity(await db.get(ResearchProfile, ctx.workspace_id))}


@router.patch("/research-profile", response_model=Envelope[ProfilePublic])
async def update_profile(
    body: ProfilePatch,
    ctx: WorkspaceContext = Depends(current_context),
    db: AsyncSession = Depends(get_session, scope="function"),
):
    item = (
        await db.execute(
            select(ResearchProfile).where(ResearchProfile.workspace_id == ctx.workspace_id).with_for_update()
        )
    ).scalar_one()
    if item.version != body.expected_version:
        conflict(item.version)
    for name, value in body.model_dump(exclude_unset=True, exclude={"expected_version"}).items():
        if value is None and name not in {"degree_stage", "field_of_study"}:
            raise DomainError("VALIDATION_ERROR", "配置字段不能为空", 422)
        if name == "dashboard_preferences":
            from uuid import UUID

            from app.models import Project
            from app.services.research import owned

            for project_id in value:
                await owned(db, Project, UUID(project_id), ctx)
        setattr(item, name, value)
    item.version += 1
    await db.flush()
    await db.refresh(item)
    return {"data": entity(item)}
