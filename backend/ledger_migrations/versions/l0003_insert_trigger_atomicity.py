"""Only a completed insert may advance the head, including ON CONFLICT paths."""

from alembic import op

revision = "l0003"
down_revision = "l0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP TRIGGER ledger_append ON public.ledger_entries")
    op.execute(
        "CREATE TRIGGER ledger_append AFTER INSERT ON public.ledger_entries FOR EACH ROW EXECUTE FUNCTION public.advance_ledger_head()"
    )


def downgrade():
    raise RuntimeError("Deletion journal migrations are forward only")
