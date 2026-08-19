"""Add network_contacts table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "006_add_network_contacts"
down_revision = "005_make_alembic_authoritative"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    return table in inspect(bind).get_table_names()


def upgrade() -> None:
    if _table_exists("network_contacts"):
        return

    op.create_table(
        "network_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("connection", sa.String(length=300), nullable=True),
        sa.Column("first_contact_at", sa.Date(), nullable=True),
        sa.Column("followup_contact_at", sa.Date(), nullable=True),
        sa.Column("method", sa.String(length=30), nullable=True),
        sa.Column("opportunities", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    if _table_exists("network_contacts"):
        op.drop_table("network_contacts")
