"""Unemployment tab: work-search contacts logged per claim week.

One row per contact, grouped by `week_ending` (the Saturday that ends a
Sunday-Saturday Utah DWS claim week).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "010_unemployment_contacts"
down_revision = "009_posting_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "unemployment_contacts" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "unemployment_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("contact_date", sa.Date(), nullable=True),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("contact_details", sa.String(length=500), nullable=False),
        sa.Column("position_title", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=100), nullable=False),
        sa.Column("result", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_unemployment_contacts_week_ending", "unemployment_contacts", ["week_ending"])


def downgrade() -> None:
    if "unemployment_contacts" in inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_unemployment_contacts_week_ending", table_name="unemployment_contacts")
        op.drop_table("unemployment_contacts")
