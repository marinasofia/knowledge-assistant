"""Bound concurrency across API processes."""

from alembic import op

revision = "002"
down_revision = "001"


def upgrade():
    op.execute(
        "CREATE TABLE generation_leases(id text PRIMARY KEY, expires_at timestamptz NOT NULL)"
    )
    op.execute("GRANT SELECT, INSERT, DELETE ON generation_leases TO knowledge_app")


def downgrade():
    op.execute("DROP TABLE generation_leases")
