"""Record when a deleted document's files and passages were cleaned up."""

from alembic import op

revision = "004"
down_revision = "003"


def upgrade():
    op.execute("ALTER TABLE document_versions ADD COLUMN cleaned_at timestamptz")


def downgrade():
    op.execute("ALTER TABLE document_versions DROP COLUMN cleaned_at")
