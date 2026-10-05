"""Idle session expiry and retention of resolved reviews."""

from alembic import op

revision = "010"
down_revision = "009"


def upgrade():
    op.execute("""
    ALTER TABLE sessions ADD COLUMN last_seen_at timestamptz NOT NULL DEFAULT now();
    GRANT DELETE ON review_events TO knowledge_app;
    """)


def downgrade():
    op.execute("""
    REVOKE DELETE ON review_events FROM knowledge_app;
    ALTER TABLE sessions DROP COLUMN last_seen_at;
    """)
