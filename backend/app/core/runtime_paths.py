import re

from sqlalchemy import make_url

from app.core.config import ROOT, get_settings


def runtime_namespace(purpose, database=None):
    if purpose not in {"pdf-tmp", "export-tmp", "mail-preview", "deletion-ledger", "backups"}:
        raise ValueError("UNKNOWN_RUNTIME_NAMESPACE")
    database = database or make_url(get_settings().database_url).database
    if not database or not re.fullmatch(r"[a-zA-Z0-9_\-]{1,63}", database):
        raise ValueError("INVALID_DATABASE_NAMESPACE")
    return ROOT / "runtime" / purpose / database
