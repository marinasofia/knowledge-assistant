"""Turn review requests into a state machine with answers and version provenance."""

from alembic import op

revision = "005"
down_revision = "004"


def upgrade():
    op.execute("""
    ALTER TABLE review_requests DROP CONSTRAINT review_requests_status_check;
    ALTER TABLE review_requests
      ADD COLUMN message_id text,
      ADD COLUMN revision integer NOT NULL DEFAULT 0,
      ADD COLUMN claimed_by text REFERENCES users(id),
      ADD COLUMN resolved_by text REFERENCES users(id),
      ADD COLUMN resolved_at timestamptz,
      ADD COLUMN resolution text,
      ADD CONSTRAINT review_message_fk FOREIGN KEY(workspace_id,message_id)
        REFERENCES messages(workspace_id,id) ON DELETE SET NULL (message_id);
    UPDATE review_requests SET status='declined', resolved_at=created_at,
      resolution='Closed before review answers were recorded.' WHERE status='resolved';
    ALTER TABLE review_requests ADD CONSTRAINT review_requests_status_check
      CHECK(status IN ('open','claimed','answered','declined'));
    ALTER TABLE review_requests ADD CONSTRAINT review_resolution_present
      CHECK(status NOT IN ('answered','declined') OR resolution IS NOT NULL);
    CREATE TABLE review_citations (
      id text NOT NULL, workspace_id text NOT NULL, review_id text NOT NULL,
      chunk_id text NOT NULL, version_id text NOT NULL, section text NOT NULL,
      quote text NOT NULL,
      PRIMARY KEY(workspace_id,id),
      FOREIGN KEY(workspace_id,review_id) REFERENCES review_requests(workspace_id,id),
      FOREIGN KEY(workspace_id,version_id) REFERENCES document_versions(workspace_id,id));
    GRANT SELECT, INSERT, UPDATE, DELETE ON review_citations TO knowledge_app;
    ALTER TABLE review_citations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE review_citations FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant ON review_citations USING
      (workspace_id = nullif(current_setting('app.workspace',true),''))
      WITH CHECK (workspace_id = nullif(current_setting('app.workspace',true),''));
    """)


def downgrade():
    op.execute("""
    DROP TABLE review_citations;
    ALTER TABLE review_requests DROP CONSTRAINT review_resolution_present;
    ALTER TABLE review_requests DROP CONSTRAINT review_requests_status_check;
    UPDATE review_requests SET status='resolved' WHERE status IN ('answered','declined');
    UPDATE review_requests SET status='open' WHERE status='claimed';
    ALTER TABLE review_requests DROP CONSTRAINT review_message_fk,
      DROP COLUMN message_id, DROP COLUMN revision, DROP COLUMN claimed_by,
      DROP COLUMN resolved_by, DROP COLUMN resolved_at, DROP COLUMN resolution;
    ALTER TABLE review_requests ADD CONSTRAINT review_requests_status_check
      CHECK(status IN ('open','resolved'));
    """)
