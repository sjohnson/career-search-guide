"""Add equity and collaboration_focused to opportunities."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "003_opportunity_equity_fields"
down_revision = "002_daily_plan_dismissals"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    return column in {col["name"] for col in inspect(bind).get_columns(table)}


def upgrade() -> None:
    if not _column_exists("opportunities", "equity"):
        op.add_column(
            "opportunities",
            sa.Column("equity", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
    if not _column_exists("opportunities", "collaboration_focused"):
        op.add_column(
            "opportunities",
            sa.Column(
                "collaboration_focused",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    if _column_exists("opportunities", "collaboration_focused"):
        op.drop_column("opportunities", "collaboration_focused")
    if _column_exists("opportunities", "equity"):
        op.drop_column("opportunities", "equity")
