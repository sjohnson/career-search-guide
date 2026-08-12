"""Add users table for session authentication."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "004_add_users_table"
down_revision = "003_opportunity_equity_fields"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    return table in inspect(bind).get_table_names()


def upgrade() -> None:
    if _table_exists("users"):
        return

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    if _table_exists("users"):
        op.drop_index("ix_users_email", table_name="users")
        op.drop_table("users")
