"""Deletion receipts and nullable identity references for controlled cleanup."""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deletion_jobs", sa.Column("receipt_hash", sa.Text(), nullable=True))
    op.create_foreign_key("fk_deletion_jobs_workspace_id_workspaces", "deletion_jobs", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_deletion_jobs_requested_by_users", "deletion_jobs", "users", ["requested_by"], ["id"], ondelete="SET NULL")


def downgrade():
    raise RuntimeError("Deletion receipts and identity cleanup constraints require forward migration")
