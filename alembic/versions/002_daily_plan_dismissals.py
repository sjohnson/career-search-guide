"""Add daily_plan_dismissals table for remove-from-day without re-assign."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "002_daily_plan_dismissals"
down_revision = "001_task_sync_refactor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "daily_plan_dismissals" in inspect(bind).get_table_names():
        return

    op.create_table(
        "daily_plan_dismissals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("daily_plan_id", sa.Integer(), sa.ForeignKey("daily_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("master_task_id", sa.Integer(), sa.ForeignKey("master_tasks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("learning_task_id", sa.Integer(), sa.ForeignKey("learning_tasks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("daily_plan_id", "master_task_id", name="uq_dismiss_plan_master"),
        sa.UniqueConstraint("daily_plan_id", "learning_task_id", name="uq_dismiss_plan_learning"),
        sa.CheckConstraint(
            "(master_task_id IS NOT NULL AND learning_task_id IS NULL) OR "
            "(master_task_id IS NULL AND learning_task_id IS NOT NULL)",
            name="ck_dismiss_single_source",
        ),
    )


def downgrade() -> None:
    op.drop_table("daily_plan_dismissals")
