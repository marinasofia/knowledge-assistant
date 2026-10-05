"""Section paths and content keys that identify a passage across versions."""

from alembic import op

revision = "007"
down_revision = "006"


def upgrade():
    op.execute("""
    ALTER TABLE chunks ADD COLUMN section_path text NOT NULL DEFAULT '',
      ADD COLUMN content_key text NOT NULL DEFAULT '';
    UPDATE chunks SET section_path=section;
    CREATE INDEX chunks_content_key_idx ON chunks(workspace_id,content_key);
    """)


def downgrade():
    op.execute("""
    DROP INDEX chunks_content_key_idx;
    ALTER TABLE chunks DROP COLUMN section_path, DROP COLUMN content_key;
    """)
