"""Baseline revision — legacy data migrations run via app.services.schema_migration on startup."""

from alembic import op

revision = "001_task_sync_refactor"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One-time legacy/data migrations remain in app.services.schema_migration.
    # New schema changes belong in numbered Alembic versions under alembic/versions/.
    pass


def downgrade() -> None:
    pass
