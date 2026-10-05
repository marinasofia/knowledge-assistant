"""Workspace data, durable jobs, and tenant policies."""

from alembic import op

revision = "001"
down_revision = None


def upgrade():
    op.execute("""
    CREATE EXTENSION IF NOT EXISTS vector;
    DO $$ BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='knowledge_app') THEN
        CREATE ROLE knowledge_app LOGIN PASSWORD 'local-runtime-only' NOSUPERUSER NOBYPASSRLS;
      END IF;
    END $$;
    CREATE TABLE users (id text PRIMARY KEY, name text NOT NULL);
    CREATE TABLE workspaces (id text PRIMARY KEY, name text NOT NULL);
    CREATE TABLE memberships (
      user_id text REFERENCES users(id), workspace_id text REFERENCES workspaces(id),
      role text NOT NULL CHECK(role IN ('admin','member')), PRIMARY KEY(user_id,workspace_id));
    CREATE TABLE sessions (
      token_hash text PRIMARY KEY, user_id text REFERENCES users(id), csrf text NOT NULL,
      expires_at timestamptz NOT NULL);
    CREATE TABLE usage_buckets (
      key text PRIMARY KEY, day date NOT NULL, used integer NOT NULL DEFAULT 0);
    CREATE TABLE documents (
      id text NOT NULL, workspace_id text REFERENCES workspaces(id), title text NOT NULL,
      active_version text, latest_version text, deleted boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(workspace_id,id));
    CREATE TABLE document_versions (
      id text NOT NULL, workspace_id text NOT NULL, document_id text NOT NULL,
      number integer NOT NULL, status text NOT NULL CHECK(status IN ('queued','processing','ready','failed')),
      content_hash text NOT NULL, storage_key text NOT NULL, error text,
      embedding_model text NOT NULL DEFAULT 'none', extraction_version text NOT NULL DEFAULT 'utf8-sections-v1',
      created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(workspace_id,id),
      UNIQUE(workspace_id,document_id,number),
      FOREIGN KEY(workspace_id,document_id) REFERENCES documents(workspace_id,id));
    CREATE TABLE chunks (
      id text NOT NULL, workspace_id text NOT NULL, version_id text NOT NULL,
      section text NOT NULL, ordinal integer NOT NULL, content text NOT NULL,
      embedding vector(384), search tsvector GENERATED ALWAYS AS
        (to_tsvector('english',content)) STORED,
      PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,version_id,ordinal),
      FOREIGN KEY(workspace_id,version_id) REFERENCES document_versions(workspace_id,id));
    CREATE INDEX chunks_search_idx ON chunks USING gin(search);
    CREATE TABLE ingestion_jobs (
      id text NOT NULL, workspace_id text NOT NULL, version_id text NOT NULL,
      status text NOT NULL DEFAULT 'queued', attempts integer NOT NULL DEFAULT 0,
      lease_token text, lease_until timestamptz, available_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,version_id),
      FOREIGN KEY(workspace_id,version_id) REFERENCES document_versions(workspace_id,id));
    CREATE TABLE conversations (
      id text NOT NULL, workspace_id text NOT NULL, user_id text REFERENCES users(id), title text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(workspace_id,id));
    CREATE TABLE messages (
      id text NOT NULL, workspace_id text NOT NULL, conversation_id text NOT NULL,
      question text NOT NULL, answer jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(workspace_id,id),
      FOREIGN KEY(workspace_id,conversation_id) REFERENCES conversations(workspace_id,id));
    CREATE TABLE citations (
      id text NOT NULL, workspace_id text NOT NULL, message_id text NOT NULL,
      chunk_id text NOT NULL, quote text NOT NULL, PRIMARY KEY(workspace_id,id),
      FOREIGN KEY(workspace_id,message_id) REFERENCES messages(workspace_id,id));
    CREATE TABLE feedback (
      id text NOT NULL, workspace_id text NOT NULL, message_id text NOT NULL, user_id text NOT NULL,
      helpful boolean NOT NULL, PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,message_id,user_id),
      FOREIGN KEY(workspace_id,message_id) REFERENCES messages(workspace_id,id));
    CREATE TABLE review_requests (
      id text NOT NULL, workspace_id text NOT NULL, user_id text NOT NULL,
      question text NOT NULL, note text NOT NULL, status text NOT NULL DEFAULT 'open'
      CHECK(status IN ('open','resolved')), created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(workspace_id,id));
    CREATE TABLE audit_events (
      id text NOT NULL, workspace_id text NOT NULL, user_id text NOT NULL,
      action text NOT NULL, target_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(workspace_id,id));
    GRANT USAGE ON SCHEMA public TO knowledge_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO knowledge_app;
    REVOKE ALL ON alembic_version FROM knowledge_app;
    """)
    for table in [
        "documents",
        "document_versions",
        "chunks",
        "ingestion_jobs",
        "conversations",
        "messages",
        "citations",
        "feedback",
        "review_requests",
        "audit_events",
    ]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY tenant ON {table} USING
          (workspace_id = nullif(current_setting('app.workspace',true),''))
          WITH CHECK (workspace_id = nullif(current_setting('app.workspace',true),''))""")


def downgrade():
    for table in [
        "audit_events",
        "review_requests",
        "feedback",
        "citations",
        "messages",
        "conversations",
        "ingestion_jobs",
        "chunks",
        "document_versions",
        "documents",
        "usage_buckets",
        "sessions",
        "memberships",
        "workspaces",
        "users",
    ]:
        op.execute(f"DROP TABLE {table}")
