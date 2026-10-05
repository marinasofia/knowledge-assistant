"""Owner and effective date per version, scheduled activation, declared precedence."""

from alembic import op

revision = "008"
down_revision = "007"


def upgrade():
    op.execute("""
    ALTER TABLE document_versions ADD COLUMN owner text, ADD COLUMN effective_from date;
    ALTER TABLE document_versions DROP CONSTRAINT document_versions_status_check;
    ALTER TABLE document_versions ADD CONSTRAINT document_versions_status_check
      CHECK(status IN ('queued','processing','ready','failed','scheduled','superseded'));
    CREATE TABLE document_precedence (
      id text NOT NULL, workspace_id text NOT NULL,
      prevailing_document_id text NOT NULL, yielding_document_id text NOT NULL,
      section text NOT NULL, note text NOT NULL, created_by text NOT NULL REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,yielding_document_id,section),
      CHECK(prevailing_document_id <> yielding_document_id),
      FOREIGN KEY(workspace_id,prevailing_document_id) REFERENCES documents(workspace_id,id),
      FOREIGN KEY(workspace_id,yielding_document_id) REFERENCES documents(workspace_id,id));
    GRANT SELECT, INSERT, DELETE ON document_precedence TO knowledge_app;
    ALTER TABLE document_precedence ENABLE ROW LEVEL SECURITY;
    ALTER TABLE document_precedence FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant ON document_precedence USING
      (workspace_id = nullif(current_setting('app.workspace',true),''))
      WITH CHECK (workspace_id = nullif(current_setting('app.workspace',true),''));
    """)


def downgrade():
    op.execute("""
    DROP TABLE document_precedence;
    UPDATE document_versions SET status='ready' WHERE status IN ('scheduled','superseded');
    ALTER TABLE document_versions DROP CONSTRAINT document_versions_status_check;
    ALTER TABLE document_versions ADD CONSTRAINT document_versions_status_check
      CHECK(status IN ('queued','processing','ready','failed'));
    ALTER TABLE document_versions DROP COLUMN owner, DROP COLUMN effective_from;
    """)
