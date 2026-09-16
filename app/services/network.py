"""Domain logic for the network contact list.

The organising idea: the app derives when someone is due for contact rather
than asking for a follow-up date to be typed in. Sorting is therefore driven
by `NetworkContact.next_touch_at`, and the only routine write is
`log_contact`. See `docs/PLANNING.md`.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import (
    CADENCE_CHOICES,
    DEFAULT_CADENCE_DAYS,
    ContactMethod,
    ContactStatus,
    NetworkContact,
)

METHOD_VALUES = {item.value for item in ContactMethod}
STATUS_VALUES = {item.value for item in ContactStatus}

SNOOZE_DAYS = 7

# How many due contacts the Reach out panel shows before collapsing the rest.
# A month of unattended follow-ups can be a dozen people; showing them all
# reads as a backlog to avoid rather than a short list to work through.
REACH_OUT_VISIBLE = 3


def normalize_contact_method(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if value in METHOD_VALUES:
        return value
    return None


def normalize_cadence_days(raw: str | int | None) -> int:
    """Clamp cadence to one of the preset choices, falling back to the default."""
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_CADENCE_DAYS
    return value if value in CADENCE_CHOICES else DEFAULT_CADENCE_DAYS


def clip_text(raw: str | None, max_len: int) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    return text[:max_len]


def parse_contact_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def active_contacts(db: Session) -> list[NetworkContact]:
    """All open threads, ordered by how soon each is due.

    `next_touch_at` is a computed property rather than a column, so ordering
    happens in Python. The list is one person per row and personal in scale —
    tens, not thousands — so this stays cheap.
    """
    contacts = (
        db.query(NetworkContact)
        .filter(NetworkContact.status == ContactStatus.ACTIVE.value)
        .all()
    )
    return sorted(contacts, key=lambda c: (c.next_touch_at, c.name.lower()))


def closed_contacts(db: Session) -> list[NetworkContact]:
    contacts = (
        db.query(NetworkContact)
        .filter(NetworkContact.status == ContactStatus.CLOSED.value)
        .all()
    )
    return sorted(contacts, key=lambda c: (c.last_contact_at or date.min, c.name.lower()), reverse=True)


def split_by_due(contacts: list[NetworkContact]) -> tuple[list[NetworkContact], list[NetworkContact]]:
    """Partition open threads into due-now and still-quiet, preserving order."""
    due = [c for c in contacts if c.is_due]
    scheduled = [c for c in contacts if not c.is_due]
    return due, scheduled


def due_contacts(db: Session, limit: int | None = None) -> list[NetworkContact]:
    """Open threads that are due, most overdue first. Used by the Daily Plan nudge."""
    due, _ = split_by_due(active_contacts(db))
    return due[:limit] if limit else due


def log_contact(
    contact: NetworkContact,
    method: str | None = None,
    on: date | None = None,
) -> NetworkContact:
    """Record that contact was made — the one action that matters.

    Clears any override so the cadence takes over again, and sets
    `first_contact_at` the first time through so the thread's start date
    survives later contacts.
    """
    contacted_on = on or date.today()
    contact.last_contact_at = contacted_on
    if contact.first_contact_at is None:
        contact.first_contact_at = contacted_on
    normalized = normalize_contact_method(method)
    if normalized:
        contact.last_contact_method = normalized
    contact.next_touch_override = None
    contact.status = ContactStatus.ACTIVE.value
    return contact


def snooze_contact(contact: NetworkContact, days: int = SNOOZE_DAYS) -> NetworkContact:
    """Push the next touch out without claiming contact was made.

    Without this the only way to clear someone off the Reach out panel is to
    log a contact that never happened, which quietly corrupts the dates.
    """
    contact.next_touch_override = date.today() + timedelta(days=days)
    return contact


def close_thread(contact: NetworkContact) -> NetworkContact:
    """Mark a thread finished — "they told me there's nothing open".

    Deliberately reversible via `reopen_thread`, which is what lets the UI
    skip a confirmation dialog.
    """
    contact.status = ContactStatus.CLOSED.value
    contact.next_touch_override = None
    return contact


def reopen_thread(contact: NetworkContact) -> NetworkContact:
    """Re-open a closed thread and put the person straight back in the queue."""
    contact.status = ContactStatus.ACTIVE.value
    contact.next_touch_override = date.today()
    return contact
