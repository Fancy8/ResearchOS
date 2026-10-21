"""Durable, cleanup-only pagination checkpoints for artifact reconciliation."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "maintenance_checkpoints",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("state", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("jsonb_typeof(state)='object'", name="state_object"),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 128", name="name_length"),
    )
    op.create_index("ix_maintenance_checkpoints_workspace_id", "maintenance_checkpoints", ["workspace_id"])
    op.execute("REVOKE ALL ON maintenance_checkpoints FROM researchos_app")
    op.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON maintenance_checkpoints TO researchos_cleanup")


def downgrade():
    raise RuntimeError("Maintenance checkpoints use forward migrations")
