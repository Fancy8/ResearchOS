"""Issue a local invitation. Print the token only to the requesting operator."""
import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
import secrets
import sys
from uuid import uuid4

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import get_settings
from app.core.security import digest

parser = argparse.ArgumentParser()
parser.add_argument("email")
args = parser.parse_args()
token = secrets.token_urlsafe(32)
with psycopg.connect(get_settings().admin_database_url.replace("postgresql+psycopg", "postgresql")) as connection:
    connection.execute("INSERT INTO auth_tokens(id,purpose,email,token_hash,expires_at) VALUES(%s,'invite',%s,%s,%s)",
        (uuid4(), args.email.lower(), digest(token), datetime.now(UTC) + timedelta(days=7)))
print(token)
