"""Separate immutable-history and runtime privileges from migration ownership."""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    GRANT USAGE ON SCHEMA public TO researchos_app,researchos_cleanup;
    GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO researchos_app,researchos_cleanup;
    REVOKE INSERT,UPDATE,DELETE ON alembic_version FROM researchos_app,researchos_cleanup;
    REVOKE UPDATE,DELETE ON decision_revisions,decision_revision_evidence_links,
        decision_revision_hypothesis_links,decision_revision_note_links,
        thread_revisions,hypothesis_revisions,activity_events FROM researchos_app;
    """)


def downgrade():
    raise RuntimeError("Do not restore broad history modification privileges")
