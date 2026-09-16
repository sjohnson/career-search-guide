"""Reshape network_contacts around the person, with a computed follow-up cadence.

The old shape modelled a contact *event*: `first_contact_at` plus a single
`followup_contact_at` that had to be typed by hand, and an overloaded
`connection` string holding both "how I know them" and a LinkedIn URL. In
practice the follow-up date was never filled in, so the tab never surfaced
anyone as due.

The new shape stores the last contact plus a per-person cadence, and derives
the next-touch date (see `NetworkContact.next_touch_at`). See
`docs/PLANNING.md` for the full design.

Backfill notes:
- `connection` splits on ';' into `affiliation` and `linkedin_url`.
- `last_contact_at` takes `first_contact_at`, NOT max(first, followup):
  `followup_contact_at` recorded a *planned* date, and whether it happened is
  not knowable from the data. It becomes `next_touch_override` instead.
- The free-text `opportunities` column is appended to the contact's note
  rather than guessed into `opportunity_id`; real links are set from the UI.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "007_network_person_shape"
down_revision = "006_add_network_contacts"
branch_labels = None
depends_on = None

TABLE = "network_contacts"

DROPPED_COLUMNS = ["connection", "followup_contact_at", "method", "opportunities"]


def _new_columns() -> list[sa.Column]:
    """Fresh Column objects per call — a Column instance cannot be reused
    across operations, and SQLAlchemy 2.0 removed Column.copy()."""
    return [
        sa.Column("affiliation", sa.String(length=120), nullable=True),
        sa.Column("linkedin_url", sa.String(length=500), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), nullable=True),
        sa.Column("last_contact_at", sa.Date(), nullable=True),
        sa.Column("last_contact_method", sa.String(length=30), nullable=True),
        sa.Column("cadence_days", sa.Integer(), nullable=False, server_default=sa.text("14")),
        sa.Column("next_touch_override", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
    ]


def _column_names(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in inspect(bind).get_columns(table)}


def _split_connection(raw: str | None) -> tuple[str | None, str | None]:
    """Split the overloaded `connection` field into affiliation + LinkedIn URL.

    Handles all three shapes present in the data: "Verisys; https://…",
    "Robert Half" (no URL), and a bare URL with no affiliation.
    """
    if not raw or not raw.strip():
        return None, None

    affiliations: list[str] = []
    url: str | None = None
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if part.lower().startswith(("http://", "https://")):
            if url is None:
                url = part[:500]
        else:
            affiliations.append(part)

    affiliation = "; ".join(affiliations)[:120] if affiliations else None
    return affiliation, url


def upgrade() -> None:
    existing = _column_names(TABLE)

    # Phase 1 — add the new columns. Done in batch mode so the foreign key to
    # opportunities is created too; SQLite cannot ADD CONSTRAINT in place.
    with op.batch_alter_table(TABLE) as batch_op:
        for column in _new_columns():
            if column.name not in existing:
                batch_op.add_column(column)
        if "opportunity_id" not in existing:
            batch_op.create_foreign_key(
                "fk_network_contacts_opportunity_id",
                "opportunities",
                ["opportunity_id"],
                ["id"],
                ondelete="SET NULL",
            )

    # Phase 2 — backfill from the columns about to be dropped.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, connection, first_contact_at, followup_contact_at, "
            "method, opportunities FROM network_contacts"
        )
    ).fetchall()

    for row in rows:
        affiliation, linkedin_url = _split_connection(row.connection)
        bind.execute(
            sa.text(
                "UPDATE network_contacts SET "
                "affiliation = :affiliation, "
                "linkedin_url = :linkedin_url, "
                "last_contact_at = :last_contact_at, "
                "last_contact_method = :last_contact_method, "
                "next_touch_override = :next_touch_override, "
                "cadence_days = 14, "
                "status = 'active' "
                "WHERE id = :id"
            ),
            {
                "id": row.id,
                "affiliation": affiliation,
                "linkedin_url": linkedin_url,
                "last_contact_at": row.first_contact_at,
                "last_contact_method": row.method,
                "next_touch_override": row.followup_contact_at,
            },
        )

        # Preserve the free-text opportunities string in the contact's note.
        legacy = (row.opportunities or "").strip()
        if not legacy:
            continue
        addition = f"Opportunities (migrated): {legacy}"
        note = bind.execute(
            sa.text(
                "SELECT id, body FROM notes "
                "WHERE noteable_type = 'network_contact' AND noteable_id = :id "
                "ORDER BY id LIMIT 1"
            ),
            {"id": row.id},
        ).fetchone()
        if note is None:
            bind.execute(
                sa.text(
                    "INSERT INTO notes (body, noteable_type, noteable_id, created_at, updated_at) "
                    "VALUES (:body, 'network_contact', :id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"body": addition, "id": row.id},
            )
        else:
            body = f"{note.body.rstrip()}\n\n{addition}" if note.body.strip() else addition
            bind.execute(
                sa.text("UPDATE notes SET body = :body, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
                {"body": body, "id": note.id},
            )

    # Phase 3 — drop the superseded columns.
    with op.batch_alter_table(TABLE) as batch_op:
        for name in DROPPED_COLUMNS:
            if name in existing:
                batch_op.drop_column(name)


def downgrade() -> None:
    existing = _column_names(TABLE)

    with op.batch_alter_table(TABLE) as batch_op:
        if "connection" not in existing:
            batch_op.add_column(sa.Column("connection", sa.String(length=300), nullable=True))
        if "followup_contact_at" not in existing:
            batch_op.add_column(sa.Column("followup_contact_at", sa.Date(), nullable=True))
        if "method" not in existing:
            batch_op.add_column(sa.Column("method", sa.String(length=30), nullable=True))
        if "opportunities" not in existing:
            batch_op.add_column(sa.Column("opportunities", sa.String(length=300), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE network_contacts SET "
            "connection = TRIM(COALESCE(affiliation, '') || "
            "  CASE WHEN linkedin_url IS NULL THEN '' "
            "       WHEN affiliation IS NULL THEN linkedin_url "
            "       ELSE '; ' || linkedin_url END), "
            "followup_contact_at = next_touch_override, "
            "method = last_contact_method"
        )
    )
    bind.execute(sa.text("UPDATE network_contacts SET connection = NULL WHERE connection = ''"))

    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_constraint("fk_network_contacts_opportunity_id", type_="foreignkey")
        for name in [
            "status",
            "next_touch_override",
            "cadence_days",
            "last_contact_method",
            "last_contact_at",
            "opportunity_id",
            "linkedin_url",
            "affiliation",
        ]:
            if name in _column_names(TABLE):
                batch_op.drop_column(name)
