"""Dedicated read-only backup principal, separate from application and migration."""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("GRANT USAGE ON SCHEMA public TO researchos_backup")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM researchos_backup")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO researchos_backup")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE researchos_admin IN SCHEMA public GRANT SELECT ON TABLES TO researchos_backup"
    )


def downgrade():
    raise RuntimeError("Backup role separation uses forward migrations")
