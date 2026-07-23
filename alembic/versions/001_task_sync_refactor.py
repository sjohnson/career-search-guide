"""Task sync refactor — schema migration handled at app startup."""

from alembic import op

revision = "001_task_sync_refactor"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Data migration is handled at app startup by app.services.schema_migration
    # so existing SQLite files migrate automatically without a separate alembic run.
    pass


def downgrade() -> None:
    pass
