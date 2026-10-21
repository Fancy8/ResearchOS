import os
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from uuid import UUID, uuid4

from sqlalchemy import select, text

from app.core.auth_mail import cipher
from app.core.config import get_settings
from app.core.runtime_paths import runtime_namespace
from app.models import AuthToken, Workspace
from app.workers.celery_app import celery_app
from app.workers.jobs import WorkerSession, sync_engine


@celery_app.task(name="researchos.send_auth_email", bind=True, max_retries=3)
def send_auth_email(task, token_id):
    import json

    identifier = UUID(str(token_id))
    with sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        workspace_id = connection.execute(
            select(Workspace.id)
            .join(AuthToken, Workspace.owner_user_id == AuthToken.user_id)
            .where(AuthToken.id == identifier)
        ).scalar_one_or_none()
        if not workspace_id:
            return
        scope = f"resource:{workspace_id}"
        connection.execute(
            text("SELECT pg_advisory_lock_shared(hashtextextended(:scope,0))"), {"scope": scope}
        )
        try:
            if (
                connection.execute(
                    select(Workspace.status).where(Workspace.id == workspace_id)
                ).scalar_one_or_none()
                != "active"
            ):
                return
            with WorkerSession.begin() as db:
                token = db.execute(
                    select(AuthToken).where(AuthToken.id == identifier).with_for_update()
                ).scalar_one_or_none()
                if (
                    not token
                    or token.delivered_at
                    or token.used_at
                    or token.expires_at < datetime.now(UTC)
                    or not token.delivery_ciphertext
                ):
                    return
                settings = get_settings()
                envelope = json.loads(cipher().decrypt(token.delivery_ciphertext.encode()))
                message = EmailMessage()
                message["From"], message["To"] = settings.smtp_from, envelope["to"]
                message["Subject"] = (
                    "ResearchOS · 重置密码" if token.purpose == "password_reset" else "ResearchOS · 验证邮箱"
                )
                message["Message-ID"] = f"<{identifier}@researchos>"
                message.set_content(
                    f"请在有效期内打开下面的链接并确认操作：\n\n{envelope['link']}\n\n如非本人申请，可以忽略此邮件。"
                )
                try:
                    if settings.mail_delivery == "preview":
                        directory = (
                            runtime_namespace("mail-preview") / settings.environment / str(workspace_id)
                        )
                        directory.mkdir(parents=True, exist_ok=True)
                        temporary = directory / f"{identifier}-{uuid4()}.tmp"
                        try:
                            temporary.write_bytes(message.as_bytes())
                            os.replace(temporary, directory / f"{identifier}.eml")
                        finally:
                            temporary.unlink(missing_ok=True)
                    else:
                        context = ssl.create_default_context()
                        factory = smtplib.SMTP_SSL if settings.smtp_tls == "implicit" else smtplib.SMTP
                        arguments = {"context": context} if settings.smtp_tls == "implicit" else {}
                        with factory(
                            settings.smtp_host, settings.smtp_port, timeout=15, **arguments
                        ) as server:
                            if settings.smtp_tls == "starttls":
                                server.starttls(context=context)
                            if settings.smtp_username:
                                server.login(settings.smtp_username, settings.smtp_password or "")
                            server.send_message(message)
                    token.delivered_at, token.delivery_ciphertext, token.delivery_error_code = (
                        datetime.now(UTC),
                        None,
                        None,
                    )
                except Exception:
                    token.delivery_error_code = "MAIL_DELIVERY_UNAVAILABLE"
            if token.delivery_error_code:
                raise task.retry(
                    exc=RuntimeError("MAIL_DELIVERY_UNAVAILABLE"), countdown=2 ** (task.request.retries + 1)
                ) from None
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock_shared(hashtextextended(:scope,0))"), {"scope": scope}
            )
