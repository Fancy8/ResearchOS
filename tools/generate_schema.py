"""Generate typed ORM and immutable initial migration SQL from the audited design.

Only CREATE TABLE/index/trigger blocks of S3 are consumed, plus the reviewed
enterprise additions in tools/schema_additions.sql. This is a development-time
generator; application startup never reads the source documents.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def split_parts(body):
    parts, start, level, quoted = [], 0, 0, False
    i = 0
    while i < len(body):
        char = body[i]
        if char == "'":
            if quoted and i + 1 < len(body) and body[i + 1] == "'":
                i += 2
                continue
            quoted = not quoted
        if not quoted:
            level += (char == "(") - (char == ")")
            if char == "," and level == 0:
                parts.append(body[start:i].strip())
                start = i + 1
        i += 1
    parts.append(body[start:].strip())
    return parts


EXTRA_COLUMNS = {
    "users": ["account_status TEXT NOT NULL DEFAULT 'active' CHECK (account_status IN ('active','disabled','deleting'))", "email_verified_at TIMESTAMPTZ"],
    "workspaces": ["status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','deleting'))"],
    "research_profiles": ["version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)", "onboarding_state JSONB NOT NULL DEFAULT '{}'::jsonb"],
    "projects": ["version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)"],
    "research_threads": ["version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)", "current_revision INTEGER NOT NULL DEFAULT 1 CHECK (current_revision > 0)"],
    "papers": ["version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)"],
    "paper_files": ["storage_version_id TEXT", "availability_status TEXT NOT NULL DEFAULT 'available' CHECK (availability_status IN ('available','missing','deleting'))", "parser_version TEXT", "has_text_layer BOOLEAN"],
    "evidence": ["created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT", "tags JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(tags)='array')"],
    "hypotheses": ["version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)", "current_revision INTEGER NOT NULL DEFAULT 1 CHECK (current_revision > 0)"],
    "hypothesis_evidence_links": ["version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)", "updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"],
    "decision_revisions": ["title_snapshot TEXT NOT NULL CHECK (length(btrim(title_snapshot)) > 0)", "decision_type_snapshot TEXT NOT NULL CHECK (decision_type_snapshot IN ('adopt','abandon','adjust','defer'))"],
    "decision_revision_evidence_links": ["evidence_version INTEGER NOT NULL", "paper_file_id UUID NOT NULL", "page_start INTEGER NOT NULL", "page_end INTEGER NOT NULL", "source_anchor_snapshot JSONB NOT NULL"],
    "tasks": ["version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)", "source_revision_no INTEGER"],
    "notes": ["last_saved_at TIMESTAMPTZ NOT NULL DEFAULT now()"],
    "activity_events": ["event_schema_version INTEGER NOT NULL DEFAULT 1"],
    "processing_jobs": ["lease_owner TEXT", "lease_expires_at TIMESTAMPTZ", "attempt_token UUID", "heartbeat_at TIMESTAMPTZ", "parser_version TEXT", "next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now()"],
    "export_jobs": ["snapshot_at TIMESTAMPTZ", "schema_version INTEGER NOT NULL DEFAULT 1", "lease_owner TEXT", "lease_expires_at TIMESTAMPTZ", "attempt_token UUID", "heartbeat_at TIMESTAMPTZ", "attempts INTEGER NOT NULL DEFAULT 0", "max_attempts INTEGER NOT NULL DEFAULT 3", "next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now()", "manifest_hash TEXT", "progress INTEGER NOT NULL DEFAULT 0"],
}

CLASS_NAMES = dict(zip(
    "users workspaces research_profiles projects research_threads papers paper_files paper_pages project_papers thread_papers evidence hypotheses hypothesis_evidence_links research_decisions decision_revisions decision_revision_evidence_links tasks notes project_notes thread_notes note_papers note_evidence_links activity_events processing_jobs export_jobs auth_sessions auth_tokens upload_sessions api_idempotency_keys outbox_events thread_revisions hypothesis_revisions decision_revision_hypothesis_links decision_revision_note_links deletion_jobs".split(),
    "User Workspace ResearchProfile Project ResearchThread Paper PaperFile PaperPage ProjectPaper ThreadPaper Evidence Hypothesis HypothesisEvidenceLink ResearchDecision DecisionRevision DecisionRevisionEvidenceLink Task Note ProjectNote ThreadNote NotePaper NoteEvidenceLink ActivityEvent ProcessingJob ExportJob AuthSession AuthToken UploadSession ApiIdempotencyKey OutboxEvent ThreadRevision HypothesisRevision DecisionRevisionHypothesisLink DecisionRevisionNoteLink DeletionJob".split(),
))

TYPES = {
    "UUID": ("uuid.UUID", "UUID(as_uuid=True)"),
    "TEXT": ("str", "Text"), "INTEGER": ("int", "Integer"),
    "BIGINT": ("int", "BigInteger"), "BOOLEAN": ("bool", "Boolean"),
    "TIMESTAMPTZ": ("datetime", "DateTime(timezone=True)"),
    "DATE": ("date", "Date"), "JSONB": ("Any", "JSONB"),
}


def constraint(item, table, number):
    label = f"{table}_{number}"
    named = re.match(r"CONSTRAINT\s+(\w+)\s+(.*)", item, re.S)
    if named:
        label, item = named.groups()
    if item.startswith("CHECK"):
        expression = item[item.find("(") + 1:item.rfind(")")]
        return f"CheckConstraint({expression!r}, name={('ck_' + label)!r})"
    if item.startswith("UNIQUE") or item.startswith("PRIMARY KEY"):
        fields = re.search(r"\((.*?)\)", item, re.S).group(1)
        fields = [field.strip() for field in fields.split(",")]
        kind = "UniqueConstraint" if item.startswith("UNIQUE") else "PrimaryKeyConstraint"
        return f"{kind}({', '.join(repr(field) for field in fields)}, name={('uq_' if kind == 'UniqueConstraint' else 'pk_') + label!r})"
    if item.startswith("FOREIGN KEY"):
        match = re.search(r"FOREIGN KEY\s*\((.*?)\)\s*REFERENCES\s+(\w+)\s*\((.*?)\)(.*)", item, re.S)
        fields, target, targets, suffix = match.groups()
        fields = [field.strip() for field in fields.split(",")]
        targets = [f"{target}.{field.strip()}" for field in targets.split(",")]
        deletion = re.search(r"ON DELETE (RESTRICT|CASCADE|SET NULL)", suffix)
        args = f"{fields!r}, {targets!r}, name={('fk_' + label)!r}"
        if deletion:
            args += f", ondelete={deletion.group(1)!r}"
        if "DEFERRABLE" in suffix:
            args += ", deferrable=True, initially='DEFERRED', use_alter=True"
        return f"ForeignKeyConstraint({args})"
    raise ValueError(f"Unsupported constraint {item}")


def main():
    source = (ROOT / "docs/sources/数据库.txt").read_text(encoding="utf-8")
    blocks = re.findall(r"```\s*\n(.*?)\n```", source, re.S)
    core_blocks = [block for block in blocks if re.search(r"CREATE TABLE \w+", block)]
    assert len(core_blocks) == 10
    sql = "\n\n".join(core_blocks)
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"CREATE TABLE (\w+)\s*\((.*?)\);", lambda match: (
        f"CREATE TABLE {match[1]} (\n{match[2]},\n" +
        ",\n".join(EXTRA_COLUMNS[match[1]]) + "\n);"
        if match[1] in EXTRA_COLUMNS else match[0]), sql, flags=re.S)
    additions = (ROOT / "tools/schema_additions.sql").read_text(encoding="utf-8")
    all_tables_sql = sql + "\n" + additions.split("-- POST_TABLE_CONSTRAINTS")[0]
    index_blocks = [block for block in blocks if block.strip().startswith("-- M011")]
    index_sql = sql + "\n" + additions + "\n" + "\n".join(index_blocks)
    table_indexes = {}
    for match in re.finditer(r"CREATE (UNIQUE )?INDEX (\w+)\s+ON (\w+)(?: USING (\w+))?\s*\((.*?)\)\s*(?:WHERE (.*?))?;", index_sql, re.S):
        unique, index_name, table_name, using, columns, where = match.groups()
        column_parts = split_parts(columns)
        operators = {}
        expressions = []
        for column in column_parts:
            operator = re.fullmatch(r"(\w+)\s+(\w+_ops)", column)
            if operator:
                expressions.append(repr(operator[1]))
                operators[operator[1]] = operator[2]
            else:
                expressions.append(f"text({column!r})")
        args = [repr(index_name)] + expressions
        if operators:
            args.append(f"postgresql_ops={operators!r}")
        if unique:
            args.append("unique=True")
        if using:
            args.append(f"postgresql_using={using.lower()!r}")
        if where:
            args.append(f"postgresql_where=text({where.strip()!r})")
        table_indexes.setdefault(table_name, []).append(f"Index({', '.join(args)})")
    post_constraints = {}
    for match in re.finditer(r"ALTER TABLE (\w+) ADD (CONSTRAINT .*?);", additions, re.S):
        post_constraints.setdefault(match[1], []).append(match[2])
    tables = re.findall(r"CREATE TABLE (\w+)\s*\((.*?)\);", all_tables_sql, re.S)
    assert len(tables) == 35 and set(name for name, _ in tables) == set(CLASS_NAMES)
    code = ['"""Typed SQLAlchemy 2.0 domain models. Generated from reviewed schema; edit the schema generator first."""',
            "from __future__ import annotations", "import uuid", "from datetime import date, datetime", "from typing import Any",
            "from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint, Text, UniqueConstraint, text",
            "from sqlalchemy.dialects.postgresql import JSONB, UUID", "from sqlalchemy.orm import Mapped, mapped_column", "from app.db.base import Base", ""]
    for name, body in tables:
        code.extend([f"class {CLASS_NAMES[name]}(Base):", f"    __tablename__ = {name!r}"])
        parts = split_parts(body) + post_constraints.get(name, [])
        table_pk = set()
        for part in parts:
            if part.startswith("PRIMARY KEY"):
                table_pk.update(field.strip() for field in re.search(r"\((.*?)\)", part, re.S)[1].split(","))
        constraints = []
        for number, part in enumerate(parts):
            if part.startswith(("CONSTRAINT", "CHECK", "UNIQUE", "PRIMARY KEY", "FOREIGN KEY")):
                constraints.append(constraint(part, name, number))
                continue
            match = re.match(r"(\w+)\s+(UUID|TEXT|INTEGER|BIGINT|BOOLEAN|TIMESTAMPTZ|DATE|JSONB)\b(.*)", part, re.S)
            if not match:
                raise ValueError(part)
            field, sql_type, suffix = match.groups()
            py_type, sa_type = TYPES[sql_type]
            primary = "PRIMARY KEY" in suffix or field in table_pk
            nullable = "NOT NULL" not in suffix and not primary
            args = [sa_type, f"nullable={nullable}"]
            if primary:
                args.append("primary_key=True")
            if "UNIQUE" in suffix:
                args.append("unique=True")
            reference = re.search(r"REFERENCES\s+(\w+)\((\w+)\)\s+ON DELETE (RESTRICT|CASCADE|SET NULL)", suffix)
            if reference:
                args.insert(1, f"ForeignKey({(reference[1]+'.'+reference[2])!r}, ondelete={reference[3]!r})")
            default = re.search(r"DEFAULT\s+(.*?)(?=\s+(?:CHECK|UNIQUE|PRIMARY KEY|REFERENCES)\b|$)", suffix, re.S)
            if default:
                args.append(f"server_default=text({default[1].strip()!r})")
            inline_check = re.search(r"CHECK\s*(\(.*\))\s*$", suffix, re.S)
            if inline_check:
                constraints.append(constraint("CHECK " + inline_check[1], name, number))
            annotation = f"{py_type} | None" if nullable else py_type
            code.append(f"    {field}: Mapped[{annotation}] = mapped_column({', '.join(args)})")
        constraints.extend(table_indexes.get(name, []))
        if constraints:
            code.append("    __table_args__ = (\n        " + ",\n        ".join(constraints) + ",\n    )")
        code.extend(["", ""])
    destination = BACKEND / "app/models.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(code), encoding="utf-8")
    index_blocks = [block for block in blocks if block.strip().startswith("-- M011")]
    triggers = [block for block in blocks if "CREATE OR REPLACE FUNCTION set_updated_at" in block][0]
    sys.path.insert(0, str(BACKEND))
    from app.models import Base
    from sqlalchemy.schema import CreateTable, CreateIndex, AddConstraint
    from sqlalchemy.dialects.postgresql import dialect
    pg = dialect()
    initial_names = {name for name, _ in re.findall(r"CREATE TABLE (\w+)\s*\((.*?)\);", sql, re.S)}
    primary_sql, supplemental_sql, delayed_sql, indexes_sql = [], [], [], []
    for name, _ in tables:
        table = Base.metadata.tables[name]
        statement = str(CreateTable(table).compile(dialect=pg)) + ";"
        (primary_sql if name in initial_names else supplemental_sql).append(statement)
        for item in table.constraints:
            if getattr(item, "use_alter", False):
                delayed_sql.append(str(AddConstraint(item).compile(dialect=pg)) + ";")
        for item in table.indexes:
            indexes_sql.append(str(CreateIndex(item).compile(dialect=pg)) + ";")
    protection_sql = additions[additions.index("CREATE OR REPLACE FUNCTION protect_immutable_history"):]
    phase_sql = ["\n".join(primary_sql), "\n".join(supplemental_sql),
                 "\n".join(delayed_sql) + "\n" + protection_sql,
                 "CREATE EXTENSION IF NOT EXISTS pg_trgm;\n" + "\n".join(indexes_sql) + "\n" + triggers]
    # Four audited migration steps preserve dependency order within each phase.
    migration_dir = BACKEND / "alembic/versions"
    migration_dir.mkdir(parents=True, exist_ok=True)
    for index, script in enumerate(phase_sql, 1):
        revision = f"{index:04d}"
        migration = f'''"""Initial ResearchOS schema phase {index}."""
from alembic import op
revision = {revision!r}
down_revision = {f"{index-1:04d}"!r} if {index} > 1 else None
branch_labels = None
depends_on = None

def upgrade():
    op.execute({script!r})

def downgrade():
    raise RuntimeError("Initial schema rollback is destructive; restore an isolated database backup instead.")
'''
        migration_path = migration_dir / f"{revision}_initial_phase.py"
        if not migration_path.exists():
            migration_path.write_text(migration, encoding="utf-8")
    snapshot = "\n".join(line.rstrip() for line in "\n\n".join(phase_sql).splitlines()) + "\n"
    (BACKEND / "schema.sql").write_text(snapshot, encoding="utf-8")
    print(f"Generated {len(tables)} typed models and 4 dependency-ordered migrations")


if __name__ == "__main__":
    if list((BACKEND / "alembic/versions").glob("000[5-9]_*.py")):
        raise SystemExit("Initial scaffold is frozen. Evolve ORM/schema through forward migrations; do not regenerate the historical baseline.")
    main()
