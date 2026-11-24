"""Posting rules: industry, required-title, title-stack and signal term lists; rejection log.

Adzuna results are now checked against relevance rules before storing (see
app.services.posting_rules). adzuna_settings gains four term lists, and
adzuna_fetches records how many results each rule dropped, with samples.

Blank lists in existing settings rows are filled from the app's defaults
(code defaults plus the gitignored posting_rules.local.toml, if present), so
lists the user already edited are kept. Personal terms stay out of this
public repo by living in the local file.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.services.posting_rules import default_rule_lists

revision = "009_posting_rules"
down_revision = "008_job_postings"
branch_labels = None
depends_on = None

NEW_SETTINGS_COLUMNS = ("industry_exclude", "title_stack_exclude", "signal_terms", "title_require")


def _column_names(table: str) -> set[str]:
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    existing = _column_names("adzuna_settings")
    with op.batch_alter_table("adzuna_settings") as batch_op:
        for name in NEW_SETTINGS_COLUMNS:
            if name not in existing:
                batch_op.add_column(sa.Column(name, sa.Text(), nullable=False, server_default=""))

    if "rejections" not in _column_names("adzuna_fetches"):
        with op.batch_alter_table("adzuna_fetches") as batch_op:
            batch_op.add_column(sa.Column("rejections", sa.JSON(), nullable=True))

    defaults = default_rule_lists()
    settings = sa.table("adzuna_settings", *(sa.column(name, sa.Text()) for name in defaults))
    for name, terms in defaults.items():
        column = settings.c[name]
        op.execute(
            settings.update()
            .where(sa.func.trim(sa.func.coalesce(column, "")) == "")
            .values({name: "\n".join(terms)})
        )


def downgrade() -> None:
    # Seeded values in title_exclude and company_blocklist (columns from 008)
    # are left in place: they can't be told apart from the user's own edits.
    if "rejections" in _column_names("adzuna_fetches"):
        with op.batch_alter_table("adzuna_fetches") as batch_op:
            batch_op.drop_column("rejections")
    existing = _column_names("adzuna_settings")
    with op.batch_alter_table("adzuna_settings") as batch_op:
        for name in reversed(NEW_SETTINGS_COLUMNS):
            if name in existing:
                batch_op.drop_column(name)
