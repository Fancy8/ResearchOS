"""Separate privilege to activate an inventory; an empty journal is never implicit."""

from alembic import op

revision = "l0002"
down_revision = "l0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE public.ledger_activation (
        source_id text PRIMARY KEY REFERENCES public.ledger_heads(source_id),
        reviewed_sequence bigint NOT NULL CHECK (reviewed_sequence >= 0),
        reviewed_hash text NOT NULL CHECK (reviewed_hash ~ '^[0-9a-f]{64}$'),
        signature text NOT NULL CHECK (signature ~ '^[0-9a-f]{64}$'),
        activated_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(
        "REVOKE ALL ON public.ledger_activation FROM PUBLIC,researchos_ledger_writer,researchos_ledger_reader"
    )
    op.execute(
        "GRANT SELECT ON public.ledger_activation TO researchos_ledger_writer,researchos_ledger_reader"
    )


def downgrade():
    raise RuntimeError("Deletion journal migrations are forward only")
