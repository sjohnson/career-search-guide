"""Historical drift-capture revision — schema now defined in 001 baseline."""

revision = "005_make_alembic_authoritative"
down_revision = "004_add_users_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drift fixes from the create_all era are incorporated into 001_task_sync_refactor.
    # Databases stamped here already applied the original batch_alter changes.
    pass


def downgrade() -> None:
    pass
