"""Initial schema baseline — full current model definitions."""

from alembic import op
import sqlalchemy as sa

revision = "001_task_sync_refactor"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adzuna_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("search_what", sa.String(length=255), nullable=False),
        sa.Column("search_what_and", sa.String(length=255), nullable=False),
        sa.Column("search_what_or", sa.String(length=255), nullable=False),
        sa.Column("salary_min", sa.Integer(), nullable=False),
        sa.Column("slc_where", sa.String(length=255), nullable=False),
        sa.Column("slc_distance", sa.Integer(), nullable=False),
        sa.Column("va_where", sa.String(length=255), nullable=False),
        sa.Column("va_distance", sa.Integer(), nullable=False),
        sa.Column("charlotte_where", sa.String(length=255), nullable=False),
        sa.Column("charlotte_distance", sa.Integer(), nullable=False),
        sa.Column("results_limit", sa.Integer(), nullable=False),
        sa.Column("stack_default", sa.String(length=100), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "daily_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_assigned_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_date", name="uq_daily_plans_plan_date"),
    )
    op.create_table(
        "learning_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task", sa.String(length=500), nullable=False),
        sa.Column("resource", sa.String(length=500), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("target_completion_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "master_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task", sa.String(length=500), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("target_completion_date", sa.Date(), nullable=True),
        sa.Column("date_kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("is_recurring", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("noteable_type", sa.String(length=50), nullable=False),
        sa.Column("noteable_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notes_noteable", "notes", ["noteable_type", "noteable_id"], unique=False)
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("posting_url", sa.String(length=1000), nullable=True),
        sa.Column("connections", sa.String(length=500), nullable=True),
        sa.Column("referred_by", sa.String(length=255), nullable=True),
        sa.Column("location_text", sa.String(length=255), nullable=True),
        sa.Column("remote_status", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("stack", sa.String(length=200), nullable=True),
        sa.Column("mission_fit", sa.String(length=100), nullable=True),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("salary_currency", sa.String(length=10), nullable=True),
        sa.Column("pipeline_stage", sa.String(length=30), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=20), nullable=False),
        sa.Column("highlight_rank", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.Date(), nullable=True),
        sa.Column("equity", sa.Boolean(), nullable=False),
        sa.Column("collaboration_focused", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mission_statement", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "daily_plan_dismissals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("daily_plan_id", sa.Integer(), nullable=False),
        sa.Column("master_task_id", sa.Integer(), nullable=True),
        sa.Column("learning_task_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(master_task_id IS NOT NULL AND learning_task_id IS NULL) OR "
            "(master_task_id IS NULL AND learning_task_id IS NOT NULL)",
            name="ck_dismiss_single_source",
        ),
        sa.ForeignKeyConstraint(["daily_plan_id"], ["daily_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["learning_task_id"], ["learning_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["master_task_id"], ["master_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("daily_plan_id", "learning_task_id", name="uq_dismiss_plan_learning"),
        sa.UniqueConstraint("daily_plan_id", "master_task_id", name="uq_dismiss_plan_master"),
    )
    op.create_table(
        "daily_plan_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("daily_plan_id", sa.Integer(), nullable=False),
        sa.Column("priority_order", sa.Integer(), nullable=False),
        sa.Column("master_task_id", sa.Integer(), nullable=True),
        sa.Column("learning_task_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "(master_task_id IS NOT NULL AND learning_task_id IS NULL) OR "
            "(master_task_id IS NULL AND learning_task_id IS NOT NULL)",
            name="ck_plan_item_single_source",
        ),
        sa.ForeignKeyConstraint(["daily_plan_id"], ["daily_plans.id"]),
        sa.ForeignKeyConstraint(["learning_task_id"], ["learning_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["master_task_id"], ["master_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("daily_plan_id", "learning_task_id", name="uq_plan_learning"),
        sa.UniqueConstraint("daily_plan_id", "master_task_id", name="uq_plan_master"),
    )


def downgrade() -> None:
    op.drop_table("daily_plan_items")
    op.drop_table("daily_plan_dismissals")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_table("settings")
    op.drop_table("opportunities")
    op.drop_index("ix_notes_noteable", table_name="notes")
    op.drop_table("notes")
    op.drop_table("master_tasks")
    op.drop_table("learning_tasks")
    op.drop_table("daily_plans")
    op.drop_table("adzuna_settings")
