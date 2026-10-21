"""Legacy inventory gaps prohibit restoring snapshots before a reviewed cutover."""

from alembic import op

revision = "l0004"
down_revision = "l0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE public.ledger_activation ADD COLUMN not_before timestamptz")


def downgrade():
    raise RuntimeError("Deletion journal migrations are forward only")
