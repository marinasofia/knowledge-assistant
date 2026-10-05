"""Ensure active and latest pointers belong to the same document and workspace."""

from alembic import op

revision = "003"
down_revision = "002"


def upgrade():
    op.execute(
        "ALTER TABLE document_versions ADD CONSTRAINT version_document_key UNIQUE(workspace_id,document_id,id)"
    )
    for column in ["active_version", "latest_version"]:
        op.execute(f"""ALTER TABLE documents ADD CONSTRAINT documents_{column}_fk
          FOREIGN KEY(workspace_id,id,{column}) REFERENCES document_versions(workspace_id,document_id,id)
          DEFERRABLE INITIALLY DEFERRED""")


def downgrade():
    for column in ["active_version", "latest_version"]:
        op.execute(f"ALTER TABLE documents DROP CONSTRAINT documents_{column}_fk")
    op.execute("ALTER TABLE document_versions DROP CONSTRAINT version_document_key")
