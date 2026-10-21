"""Encrypted, durable verification/reset message delivery."""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("auth_tokens", sa.Column("delivery_ciphertext", sa.Text(), nullable=True))
    op.add_column("auth_tokens", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("auth_tokens", sa.Column("delivery_error_code", sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError("Authentication delivery uses forward migrations")
