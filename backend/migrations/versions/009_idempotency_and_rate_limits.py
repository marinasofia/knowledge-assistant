"""Idempotency keys for retried writes and fixed-window rate limits."""

from alembic import op

revision = "009"
down_revision = "008"


def upgrade():
    op.execute("""
    CREATE TABLE idempotency_keys (
      workspace_id text NOT NULL, user_id text NOT NULL, key text NOT NULL,
      request_hash text NOT NULL, status_code integer, response jsonb,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(workspace_id,user_id,key));
    GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_keys TO knowledge_app;
    ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
    ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant ON idempotency_keys USING
      (workspace_id = nullif(current_setting('app.workspace',true),''))
      WITH CHECK (workspace_id = nullif(current_setting('app.workspace',true),''));
    CREATE TABLE rate_limits (
      key text PRIMARY KEY, window_start timestamptz NOT NULL, count integer NOT NULL);
    GRANT SELECT, INSERT, UPDATE, DELETE ON rate_limits TO knowledge_app;
    """)


def downgrade():
    op.execute("DROP TABLE rate_limits; DROP TABLE idempotency_keys;")
