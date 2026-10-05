"""Review history, outdated answers, and answers published for reuse."""

from alembic import op

revision = "006"
down_revision = "005"


def upgrade():
    op.execute("""
    ALTER TABLE review_requests DROP CONSTRAINT review_requests_status_check;
    ALTER TABLE review_requests ADD CONSTRAINT review_requests_status_check
      CHECK(status IN ('open','claimed','answered','declined','outdated'));
    ALTER TABLE review_requests ADD COLUMN published boolean NOT NULL DEFAULT false;
    CREATE TABLE review_events (
      id text NOT NULL, workspace_id text NOT NULL, review_id text NOT NULL,
      action text NOT NULL, actor_id text REFERENCES users(id), resolution text,
      citations jsonb NOT NULL DEFAULT '[]', created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(workspace_id,id),
      FOREIGN KEY(workspace_id,review_id) REFERENCES review_requests(workspace_id,id));
    CREATE INDEX review_events_review_idx ON review_events(workspace_id,review_id,created_at);
    GRANT SELECT, INSERT ON review_events TO knowledge_app;
    ALTER TABLE review_events ENABLE ROW LEVEL SECURITY;
    ALTER TABLE review_events FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant ON review_events USING
      (workspace_id = nullif(current_setting('app.workspace',true),''))
      WITH CHECK (workspace_id = nullif(current_setting('app.workspace',true),''));
    """)


def downgrade():
    op.execute("""
    DROP TABLE review_events;
    ALTER TABLE review_requests DROP COLUMN published;
    UPDATE review_requests SET status='answered' WHERE status='outdated';
    ALTER TABLE review_requests DROP CONSTRAINT review_requests_status_check;
    ALTER TABLE review_requests ADD CONSTRAINT review_requests_status_check
      CHECK(status IN ('open','claimed','answered','declined'));
    """)
