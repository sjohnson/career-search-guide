"""Store gathered job postings and Adzuna fetch history.

Adzuna results previously lived only in an in-memory cache, lost on restart.
`job_postings` keeps every result that passes the location filter (plus
postings captured by hand), so they can be triaged in the UI and handed to
ai-job-search. `adzuna_fetches` records each refresh, including how many API
calls it spent, which drives the quota guard.

adzuna_settings gains server-side filters (what_exclude, title_only), a
pages-per-bucket setting, and in-app title/company filters.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "008_job_postings"
down_revision = "007_network_person_shape"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    return table in inspect(op.get_bind()).get_table_names()


def _column_names(table: str) -> set[str]:
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def _settings_columns() -> list[sa.Column]:
    return [
        sa.Column("search_what_exclude", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("search_title_only", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("max_pages", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("title_exclude", sa.Text(), nullable=False, server_default=""),
        sa.Column("company_blocklist", sa.Text(), nullable=False, server_default=""),
    ]


def upgrade() -> None:
    if not _table_exists("job_postings"):
        op.create_table(
            "job_postings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source", sa.String(length=30), nullable=False),
            sa.Column("source_id", sa.String(length=1000), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("company", sa.String(length=255), nullable=False),
            sa.Column("location", sa.String(length=255), nullable=True),
            sa.Column("remote_status", sa.String(length=30), nullable=True),
            sa.Column("salary_min", sa.Integer(), nullable=True),
            sa.Column("salary_max", sa.Integer(), nullable=True),
            sa.Column("salary_currency", sa.String(length=10), nullable=True),
            sa.Column("salary_is_predicted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("contract_time", sa.String(length=30), nullable=True),
            sa.Column("category", sa.String(length=100), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("source_url", sa.String(length=1000), nullable=True),
            sa.Column("posting_url", sa.String(length=1000), nullable=True),
            sa.Column("posting_url_captured_at", sa.DateTime(), nullable=True),
            sa.Column("dedupe_key", sa.String(length=800), nullable=False),
            sa.Column("posted_at", sa.DateTime(), nullable=True),
            sa.Column("search_hits", sa.JSON(), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("opened_at", sa.DateTime(), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(), nullable=True),
            sa.Column(
                "opportunity_id",
                sa.Integer(),
                sa.ForeignKey("opportunities.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.UniqueConstraint("source", "source_id", name="uq_job_postings_source_id"),
        )
        op.create_index("ix_job_postings_dedupe_key", "job_postings", ["dedupe_key"])

    if not _table_exists("adzuna_fetches"):
        op.create_table(
            "adzuna_fetches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("fetched_at", sa.DateTime(), nullable=False),
            sa.Column("api_calls", sa.Integer(), nullable=False),
            sa.Column("query_counts", sa.JSON(), nullable=False),
            sa.Column("received_count", sa.Integer(), nullable=False),
            sa.Column("new_count", sa.Integer(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("settings_fingerprint", sa.String(length=100), nullable=True),
        )
        op.create_index("ix_adzuna_fetches_fetched_at", "adzuna_fetches", ["fetched_at"])

    existing = _column_names("adzuna_settings")
    with op.batch_alter_table("adzuna_settings") as batch_op:
        for column in _settings_columns():
            if column.name not in existing:
                batch_op.add_column(column)


def downgrade() -> None:
    existing = _column_names("adzuna_settings")
    with op.batch_alter_table("adzuna_settings") as batch_op:
        for column in reversed(_settings_columns()):
            if column.name in existing:
                batch_op.drop_column(column.name)

    if _table_exists("adzuna_fetches"):
        op.drop_index("ix_adzuna_fetches_fetched_at", table_name="adzuna_fetches")
        op.drop_table("adzuna_fetches")
    if _table_exists("job_postings"):
        op.drop_index("ix_job_postings_dedupe_key", table_name="job_postings")
        op.drop_table("job_postings")
