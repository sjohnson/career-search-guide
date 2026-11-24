"""Work-search contacts for Utah DWS weekly unemployment claims.

A claim week runs Sunday through Saturday and is named by its Saturday. Each
week's table shows at least REQUIRED_CONTACTS rows (blank ones padded in), and
more can be added. Saving a week replaces its rows with what was submitted:
blank rows are dropped, so clearing every field of a row deletes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import UnemploymentContact

REQUIRED_CONTACTS = 4

FIELDS = ("contact_date", "company", "contact_details", "position_title", "method", "result")
_MAX_LENGTHS = {"company": 255, "contact_details": 500, "position_title": 255, "method": 100, "result": 500}

# Suggestions only (an HTML datalist); any text is accepted.
METHOD_SUGGESTIONS = [
    "Online application",
    "Company website",
    "Email",
    "Phone",
    "In person",
    "LinkedIn message",
    "Recruiter",
    "Networking",
    "Job fair",
]
RESULT_SUGGESTIONS = [
    "Applied; awaiting response",
    "No response",
    "Interview scheduled",
    "Interviewed; awaiting decision",
    "Not selected",
    "Position filled",
    "Offer received",
    "Follow-up planned",
]


def week_ending_for(day: date) -> date:
    """The Saturday that ends the Sunday-Saturday week containing `day`."""
    # Monday=0 ... Saturday=5, Sunday=6
    return day + timedelta(days=(5 - day.weekday()) % 7)


def short_date(day: date) -> str:
    return f"{day:%b} {day.day}"


def week_start(week_ending: date) -> date:
    return week_ending - timedelta(days=6)


@dataclass
class ContactRow:
    id: int | None = None
    contact_date: str = ""
    company: str = ""
    contact_details: str = ""
    position_title: str = ""
    method: str = ""
    result: str = ""

    @property
    def is_blank(self) -> bool:
        return not any(getattr(self, name).strip() for name in FIELDS)

    @property
    def is_complete(self) -> bool:
        return all(getattr(self, name).strip() for name in FIELDS)


@dataclass
class Week:
    week_ending: date
    rows: list[ContactRow]
    saved_count: int
    complete_count: int
    errors: list[str] = field(default_factory=list)

    @property
    def start(self) -> date:
        return week_start(self.week_ending)


def _to_row(contact: UnemploymentContact) -> ContactRow:
    return ContactRow(
        id=contact.id,
        contact_date=contact.contact_date.isoformat() if contact.contact_date else "",
        company=contact.company,
        contact_details=contact.contact_details,
        position_title=contact.position_title,
        method=contact.method,
        result=contact.result,
    )


def _padded(rows: list[ContactRow]) -> list[ContactRow]:
    return rows + [ContactRow() for _ in range(max(0, REQUIRED_CONTACTS - len(rows)))]


def contacts_for_week(db: Session, week_ending: date) -> list[UnemploymentContact]:
    return (
        db.query(UnemploymentContact)
        .filter(UnemploymentContact.week_ending == week_ending)
        .order_by(UnemploymentContact.sort_order, UnemploymentContact.id)
        .all()
    )


def build_week(db: Session, week_ending: date) -> Week:
    saved = [_to_row(c) for c in contacts_for_week(db, week_ending)]
    return Week(
        week_ending=week_ending,
        rows=_padded(saved),
        saved_count=len(saved),
        complete_count=sum(r.is_complete for r in saved),
    )


def weeks_to_show(db: Session, today: date, extra: date | None = None) -> list[Week]:
    """This week, any earlier week with saved contacts, and `extra` (a week
    the user navigated to), newest first."""
    endings = {week_ending_for(today)}
    endings.update(we for (we,) in db.query(UnemploymentContact.week_ending).distinct())
    if extra:
        endings.add(week_ending_for(extra))
    return [build_week(db, we) for we in sorted(endings, reverse=True)]


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def save_week(db: Session, week_ending: date, rows: list[ContactRow]) -> Week:
    """Validate and store a week's rows, replacing what was saved. On a
    validation error nothing is written and the submitted rows come back
    with the errors, so no typing is lost."""
    errors: list[str] = []
    kept = [r for r in rows if not r.is_blank]
    start = week_start(week_ending)
    for number, row in enumerate(kept, start=1):
        for name, limit in _MAX_LENGTHS.items():
            setattr(row, name, getattr(row, name).strip()[:limit])
        if row.contact_date:
            parsed = _parse_date(row.contact_date)
            if parsed is None:
                errors.append(f"Row {number}: the date isn't valid.")
            elif not start <= parsed <= week_ending:
                errors.append(
                    f"Row {number}: {short_date(parsed)} is outside this week "
                    f"({short_date(start)}–{short_date(week_ending)})."
                )
    if errors:
        return Week(week_ending=week_ending, rows=_padded(rows), saved_count=0, complete_count=0, errors=errors)

    existing = {c.id: c for c in contacts_for_week(db, week_ending)}
    keep_ids: set[int] = set()
    for order, row in enumerate(kept):
        contact = existing.get(row.id) if row.id else None
        if contact is None:
            contact = UnemploymentContact(week_ending=week_ending)
            db.add(contact)
        else:
            keep_ids.add(contact.id)
        contact.sort_order = order
        contact.contact_date = _parse_date(row.contact_date) if row.contact_date else None
        for name in FIELDS[1:]:
            setattr(contact, name, getattr(row, name))
    for contact_id, contact in existing.items():
        if contact_id not in keep_ids:
            db.delete(contact)
    db.commit()
    return build_week(db, week_ending)
