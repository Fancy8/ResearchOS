"""Current append-only deletion authority, outside business database backups.

The journal database and its administrators are a separate trust boundary. A
business restore never creates, restores or silently initializes that authority.
"""

import hashlib
import hmac
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from sqlalchemy import make_url

from app.core.config import get_settings

ZERO = "0" * 64


def origin_database(physical=None):
    return get_settings().ledger_origin_database or physical or make_url(get_settings().database_url).database


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def signed(kind, value):
    return hmac.new(
        get_settings().control_secret.encode(), kind.encode() + b"\0" + encoded(value), hashlib.sha256
    ).hexdigest()


def source_identity(database, *, source_url=None, bucket=None):
    if get_settings().ledger_source_id:
        if database != get_settings().ledger_origin_database:
            raise ValueError("LEDGER_SOURCE_CONTEXT_MISMATCH")
        return get_settings().ledger_source_id
    source = make_url(source_url or get_settings().database_url)
    return signed(
        "researchos-ledger-source-v1",
        {
            "host": (source.host or "localhost").lower(),
            "port": source.port or 5432,
            "database": database,
            "bucket": bucket or get_settings().s3_bucket,
        },
    )


def checkpoint(source, sequence, digest):
    result = {"source_id": source, "sequence": sequence, "entry_hash": digest}
    return {**result, "signature": signed("researchos-ledger-head-v1", result)}


def check_head(head, source):
    if (
        not head
        or head.get("source_id") != source
        or type(head.get("sequence")) is not int
        or head["sequence"] < 0
    ):
        raise ValueError("LEDGER_SOURCE_NOT_INITIALIZED")
    if head != checkpoint(source, head["sequence"], head["entry_hash"]):
        raise ValueError("LEDGER_HEAD_INTEGRITY_FAILURE")
    if head["sequence"] == 0 and head["entry_hash"] != ZERO:
        raise ValueError("LEDGER_HEAD_INTEGRITY_FAILURE")


def checked_document(document, database):
    value = dict(document)
    signature = value.pop("signature", "")
    expected = hmac.new(get_settings().control_secret.encode(), encoded(value), hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise ValueError("LEDGER_DOCUMENT_SIGNATURE_FAILURE")
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("database") != database
        or value.get("scope") not in {"file", "account"}
        or set(value)
        != {
            "schema_version",
            "job_id",
            "scope",
            "workspace_hash",
            "user_hash",
            "file_hash",
            "requested_at",
            "database",
        }
    ):
        raise ValueError("LEDGER_DOCUMENT_INVALID")
    if not isinstance(value["job_id"], str) or not isinstance(value["requested_at"], str):
        raise ValueError("LEDGER_DOCUMENT_INVALID")
    value["job_id"] = str(UUID(value["job_id"]))
    for key in ("workspace_hash", "user_hash", "file_hash"):
        item = value[key]
        if item is not None and (
            not isinstance(item, str) or len(item) != 64 or any(c not in "0123456789abcdef" for c in item)
        ):
            raise ValueError("LEDGER_DOCUMENT_INVALID")
    if not value["workspace_hash"] or (value["scope"] == "file") != bool(value["file_hash"]):
        raise ValueError("LEDGER_DOCUMENT_INVALID")
    stamp = datetime.fromisoformat(value["requested_at"])
    if stamp.tzinfo is None:
        raise ValueError("LEDGER_DOCUMENT_INVALID")
    value["requested_at"] = stamp.astimezone(UTC).isoformat()
    return {
        **value,
        "signature": hmac.new(
            get_settings().control_secret.encode(), encoded(value), hashlib.sha256
        ).hexdigest(),
    }


@contextmanager
def connection(writer=False):
    settings = get_settings()
    raw = settings.ledger_writer_url if writer else settings.ledger_reader_url
    if not raw:
        raise ValueError("LEDGER_AUTHORITY_NOT_CONFIGURED")
    target, business = make_url(raw), make_url(settings.database_url)
    role = "researchos_ledger_writer" if writer else "researchos_ledger_reader"
    if (
        target.drivername != "postgresql+psycopg"
        or target.username != role
        or (target.host, target.port or 5432, target.database)
        == (business.host, business.port or 5432, business.database)
    ):
        raise ValueError("LEDGER_AUTHORITY_MUST_BE_SEPARATE")
    try:
        db = psycopg.connect(
            raw.replace("postgresql+psycopg", "postgresql"),
            autocommit=True,
            connect_timeout=5,
            row_factory=dict_row,
            options="-c timezone=UTC -c lock_timeout=5000 -c statement_timeout=30000",
        )
        with db:
            if db.execute("SELECT current_user AS name").fetchone()["name"] != role:
                raise ValueError("LEDGER_ROLE_MISMATCH")
            yield db
    except psycopg.Error:
        # Driver messages can contain connection details or private parameters.
        raise RuntimeError("LEDGER_AUTHORITY_UNAVAILABLE") from None


def initialize_source(database):
    """Operator-only initialization after reviewing/migrating the legacy inventory."""
    source = source_identity(database)
    with connection(writer=True) as db:
        db.execute(
            "SELECT public.register_ledger_source(%s,%s)", (source, checkpoint(source, 0, ZERO)["signature"])
        )
    return source


def activation_for(db, source):
    value = db.execute(
        "SELECT source_id,reviewed_sequence,reviewed_hash,not_before,signature FROM public.ledger_activation WHERE source_id=%s",
        (source,),
    ).fetchone()
    if not value:
        raise ValueError("LEDGER_INVENTORY_NOT_REVIEWED")
    if value["not_before"] is not None:
        value["not_before"] = value["not_before"].astimezone(UTC).isoformat()
    body = {key: item for key, item in value.items() if key != "signature"}
    if value["signature"] != signed("researchos-ledger-activation-v1", body):
        raise ValueError("LEDGER_ACTIVATION_INTEGRITY_FAILURE")
    return value


def activate_source(database, not_before=None):
    """Runtime writer cannot activate a reviewed inventory; migration owner is required."""
    source = source_identity(database)
    raw = get_settings().ledger_admin_url
    if not raw or make_url(raw).username != "researchos_ledger_admin":
        raise ValueError("LEDGER_MIGRATION_OWNER_REQUIRED")
    with connection() as reader, reader.transaction():
        reader.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))", ("ledger:" + source,))
        head = VerifiedJournal(reader, source, database, require_review=False).head
        body = {
            "source_id": source,
            "reviewed_sequence": head["sequence"],
            "reviewed_hash": head["entry_hash"],
            "not_before": not_before.astimezone(UTC).isoformat() if not_before else None,
        }
        with psycopg.connect(raw.replace("postgresql+psycopg", "postgresql"), autocommit=True) as db:
            db.execute(
                "INSERT INTO public.ledger_activation(source_id,reviewed_sequence,reviewed_hash,not_before,signature) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    source,
                    head["sequence"],
                    head["entry_hash"],
                    body["not_before"],
                    signed("researchos-ledger-activation-v1", body),
                ),
            )


def require_activated(database):
    with connection() as db:
        activation_for(db, source_identity(database))


def append_document(document):
    database = document["database"]
    document = checked_document(document, database)
    source = source_identity(database)
    with connection(writer=True) as db, db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("ledger:" + source,))
        head = db.execute("SELECT * FROM public.ledger_heads WHERE source_id=%s", (source,)).fetchone()
        check_head(head, source)
        existing = db.execute(
            "SELECT payload FROM public.ledger_entries WHERE source_id=%s AND job_id=%s",
            (source, document["job_id"]),
        ).fetchone()
        if existing:
            if existing["payload"] != document:
                raise ValueError("LEDGER_DUPLICATE_REQUEST_MISMATCH")
            return
        value = {
            "source_id": source,
            "sequence": head["sequence"] + 1,
            "previous_hash": head["entry_hash"],
            "payload": document,
        }
        digest = hashlib.sha256(encoded(value)).hexdigest()
        db.execute(
            """INSERT INTO public.ledger_entries
            (source_id,sequence,job_id,payload,previous_hash,entry_hash,signature,head_signature)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                source,
                value["sequence"],
                document["job_id"],
                Jsonb(document),
                value["previous_hash"],
                digest,
                signed("researchos-ledger-entry-v1", value),
                checkpoint(source, value["sequence"], digest)["signature"],
            ),
        )


class VerifiedJournal:
    def __init__(self, db, source, database, minimum=None, require_review=True):
        self.db, self.source, self.database = db, source, database
        self.head = db.execute("SELECT * FROM public.ledger_heads WHERE source_id=%s", (source,)).fetchone()
        check_head(self.head, source)
        activation = (
            activation_for(db, source) if require_review else {"reviewed_sequence": 0, "reviewed_hash": ZERO}
        )
        if activation["reviewed_sequence"] > self.head["sequence"]:
            raise ValueError("LEDGER_BEHIND_REVIEWED_INVENTORY")
        review_seen = activation["reviewed_sequence"] == 0 and activation["reviewed_hash"] == ZERO
        if minimum:
            check_head(minimum, source)
            if minimum["sequence"] > self.head["sequence"]:
                raise ValueError("LEDGER_BEHIND_BACKUP_CHECKPOINT")
        count, previous, minimum_seen = 0, ZERO, not minimum or minimum["sequence"] == 0
        for row in self.rows():
            count += 1
            value = {
                "source_id": source,
                "sequence": count,
                "previous_hash": previous,
                "payload": row["payload"],
            }
            digest = hashlib.sha256(encoded(value)).hexdigest()
            if (
                row["sequence"] != count
                or row["previous_hash"] != previous
                or row["entry_hash"] != digest
                or row["signature"] != signed("researchos-ledger-entry-v1", value)
                or str(row["job_id"]) != row["payload"]["job_id"]
                or checked_document(row["payload"], database) != row["payload"]
                or row["head_signature"] != checkpoint(source, count, digest)["signature"]
            ):
                raise ValueError("LEDGER_CHAIN_INTEGRITY_FAILURE")
            previous = digest
            if count == activation["reviewed_sequence"]:
                if digest != activation["reviewed_hash"]:
                    raise ValueError("LEDGER_REVIEWED_INVENTORY_MISMATCH")
                review_seen = True
            if minimum and count == minimum["sequence"]:
                if digest != minimum["entry_hash"]:
                    raise ValueError("LEDGER_BACKUP_CHECKPOINT_MISMATCH")
                minimum_seen = True
        if (
            count != self.head["sequence"]
            or previous != self.head["entry_hash"]
            or not minimum_seen
            or not review_seen
        ):
            raise ValueError("LEDGER_INVENTORY_INCOMPLETE")

    def rows(self):
        # Server-side cursor bounds memory; the shared source lock stabilizes both passes.
        with self.db.cursor(name="ledger_scan") as cursor:
            cursor.execute(
                "SELECT * FROM public.ledger_entries WHERE source_id=%s ORDER BY sequence", (self.source,)
            )
            yield from cursor

    def documents(self):
        for row in self.rows():
            yield dict(row["payload"])


@contextmanager
def frozen_journal(database, *, minimum=None, source=None, backup_snapshot_at=None):
    source = source or source_identity(database)
    with connection() as db:
        # READ COMMITTED obtains its first data snapshot after the source lock;
        # a snapshot taken before waiting for a writer could omit its last commit.
        with db.transaction():
            db.execute("SET TRANSACTION READ ONLY")
            db.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))", ("ledger:" + source,))
            journal = VerifiedJournal(db, source, database, minimum)
            policy = activation_for(db, source)
            if backup_snapshot_at is not None and policy["not_before"] is not None:
                stamp = datetime.fromisoformat(backup_snapshot_at)
                if stamp.tzinfo is None or stamp < datetime.fromisoformat(policy["not_before"]):
                    raise ValueError("LEDGER_LEGACY_SNAPSHOT_PREDATES_TRUSTED_BASELINE")
            yield journal


def current_checkpoint(database):
    with frozen_journal(database) as journal:
        return dict(journal.head)
