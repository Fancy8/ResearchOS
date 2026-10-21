import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.core.security import digest
from app.models import AuthToken, OutboxEvent


def cipher():
    key = hashlib.sha256(("auth-delivery:" + get_settings().control_secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


async def queue_auth_mail(db, user, workspace_id, purpose):
    token, identifier = secrets.token_urlsafe(32), uuid4()
    action = "reset" if purpose == "password_reset" else "verify"
    link = f"{get_settings().frontend_origin}/account-action?action={action}#token={token}"
    envelope = {"to": user.email, "link": link, "purpose": purpose}
    db.add(
        AuthToken(
            id=identifier,
            purpose=purpose,
            user_id=user.id,
            email=user.email,
            token_hash=digest(token),
            expires_at=datetime.now(UTC) + timedelta(minutes=30 if purpose == "password_reset" else 1440),
            delivery_ciphertext=cipher().encrypt(json.dumps(envelope).encode()).decode(),
        )
    )
    db.add(
        OutboxEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            event_type="send_auth_email",
            aggregate_id=identifier,
            payload={"token_id": str(identifier)},
        )
    )
