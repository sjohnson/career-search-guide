from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    CADENCE_CHOICES,
    CADENCE_LABELS,
    CONTACT_METHOD_LABELS,
    ContactMethod,
    NetworkContact,
    NoteableType,
    Opportunity,
    OpportunityLifecycle,
)
from app.services.daily_plan import get_or_create_settings, get_primary_note_body, set_primary_note
from app.services.network import (
    REACH_OUT_VISIBLE,
    active_contacts,
    clip_text,
    close_thread,
    closed_contacts,
    log_contact,
    normalize_cadence_days,
    normalize_contact_method,
    parse_contact_date,
    reopen_thread,
    snooze_contact,
    split_by_due,
)
from app.templating import templates

router = APIRouter(prefix="/network", tags=["network"])


def _opportunity_choices(db: Session) -> list[Opportunity]:
    return (
        db.query(Opportunity)
        .filter(Opportunity.lifecycle_status == OpportunityLifecycle.ACTIVE.value)
        .order_by(Opportunity.company.asc())
        .all()
    )


def _notes_for(db: Session, contacts: list[NetworkContact]) -> dict[int, str]:
    return {
        contact.id: get_primary_note_body(db, NoteableType.NETWORK_CONTACT.value, contact.id)
        for contact in contacts
    }


def _sections_context(db: Session) -> dict:
    """Everything the three page sections need.

    Built as one context so a mutation can repaint all three regions at once
    via out-of-band swaps — a single action can move someone between any two
    of them (logging a contact moves Reach out → Scheduled, closing moves
    either into Closed), and repainting the lot avoids the stale-row bugs that
    per-row swaps keep producing here.
    """
    open_threads = active_contacts(db)
    due, scheduled = split_by_due(open_threads)
    closed = closed_contacts(db)

    return {
        "due_visible": due[:REACH_OUT_VISIBLE],
        "due_overflow": due[REACH_OUT_VISIBLE:],
        "due_count": len(due),
        "scheduled": scheduled,
        "closed": closed,
        "notes": _notes_for(db, open_threads + closed),
        "method_labels": CONTACT_METHOD_LABELS,
        "contact_methods": ContactMethod,
        "cadence_choices": CADENCE_CHOICES,
        "cadence_labels": CADENCE_LABELS,
    }


def _form_context(db: Session) -> dict:
    return {
        "contact_methods": ContactMethod,
        "method_labels": CONTACT_METHOD_LABELS,
        "cadence_choices": CADENCE_CHOICES,
        "cadence_labels": CADENCE_LABELS,
        "opportunities": _opportunity_choices(db),
    }


def _sections_response(request: Request, db: Session):
    """Repaint all three sections via hx-swap-oob."""
    return templates.TemplateResponse(
        request,
        "network/partials/sections_swap.html",
        _sections_context(db),
    )


@router.get("", response_class=HTMLResponse)
def list_network_contacts(request: Request, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    return templates.TemplateResponse(
        request,
        "network/list.html",
        {"mission": settings.mission_statement, **_sections_context(db)},
    )


@router.post("/quick-add")
def quick_add_contact(
    request: Request,
    name: str = Form(...),
    affiliation: str = Form(""),
    db: Session = Depends(get_db),
):
    """Two-field add. Everything else is editable later.

    A person with no contact logged is due immediately, so a quick-add lands
    straight in the Reach out panel — which is the point.
    """
    name_value = clip_text(name, 60)
    if name_value:
        db.add(
            NetworkContact(
                name=name_value,
                affiliation=clip_text(affiliation, 120),
            )
        )
        db.commit()
    if request.headers.get("hx-request"):
        return _sections_response(request, db)
    return RedirectResponse(url="/network", status_code=303)


@router.post("/{contact_id}/log-contact")
def log_contact_route(
    request: Request,
    contact_id: int,
    method: str = Form(""),
    db: Session = Depends(get_db),
):
    contact = db.get(NetworkContact, contact_id)
    if contact:
        log_contact(contact, method)
        db.commit()
    if request.headers.get("hx-request"):
        return _sections_response(request, db)
    return RedirectResponse(url="/network", status_code=303)


@router.post("/{contact_id}/snooze")
def snooze_contact_route(request: Request, contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(NetworkContact, contact_id)
    if contact:
        snooze_contact(contact)
        db.commit()
    if request.headers.get("hx-request"):
        return _sections_response(request, db)
    return RedirectResponse(url="/network", status_code=303)


@router.post("/{contact_id}/close")
def close_thread_route(request: Request, contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(NetworkContact, contact_id)
    if contact:
        close_thread(contact)
        db.commit()
    if request.headers.get("hx-request"):
        return _sections_response(request, db)
    return RedirectResponse(url="/network", status_code=303)


@router.post("/{contact_id}/reopen")
def reopen_thread_route(request: Request, contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(NetworkContact, contact_id)
    if contact:
        reopen_thread(contact)
        db.commit()
    if request.headers.get("hx-request"):
        return _sections_response(request, db)
    return RedirectResponse(url="/network", status_code=303)


@router.post("/{contact_id}/cadence")
def update_cadence(
    request: Request,
    contact_id: int,
    cadence_days: str = Form(""),
    db: Session = Depends(get_db),
):
    contact = db.get(NetworkContact, contact_id)
    if contact:
        contact.cadence_days = normalize_cadence_days(cadence_days)
        db.commit()
    if request.headers.get("hx-request"):
        return _sections_response(request, db)
    return RedirectResponse(url="/network", status_code=303)


@router.get("/new", response_class=HTMLResponse)
def new_network_contact(request: Request, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    return templates.TemplateResponse(
        request,
        "network/form.html",
        {
            "contact": None,
            "notes_text": "",
            "mission": settings.mission_statement,
            **_form_context(db),
        },
    )


def _apply_form(contact: NetworkContact, **fields) -> None:
    contact.affiliation = clip_text(fields["affiliation"], 120)
    contact.linkedin_url = clip_text(fields["linkedin_url"], 500)
    contact.opportunity_id = fields["opportunity_id"]
    contact.first_contact_at = parse_contact_date(fields["first_contact_at"])
    contact.last_contact_at = parse_contact_date(fields["last_contact_at"])
    contact.last_contact_method = normalize_contact_method(fields["last_contact_method"])
    contact.cadence_days = normalize_cadence_days(fields["cadence_days"])
    contact.next_touch_override = parse_contact_date(fields["next_touch_override"])


def _parse_opportunity_id(raw: str) -> int | None:
    try:
        return int(raw) or None
    except (TypeError, ValueError):
        return None


@router.post("")
def create_network_contact(
    name: str = Form(...),
    affiliation: str = Form(""),
    linkedin_url: str = Form(""),
    opportunity_id: str = Form(""),
    first_contact_at: str = Form(""),
    last_contact_at: str = Form(""),
    last_contact_method: str = Form(""),
    cadence_days: str = Form(""),
    next_touch_override: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    name_value = clip_text(name, 60)
    if not name_value:
        return RedirectResponse(url="/network/new", status_code=303)
    contact = NetworkContact(name=name_value)
    _apply_form(
        contact,
        affiliation=affiliation,
        linkedin_url=linkedin_url,
        opportunity_id=_parse_opportunity_id(opportunity_id),
        first_contact_at=first_contact_at,
        last_contact_at=last_contact_at,
        last_contact_method=last_contact_method,
        cadence_days=cadence_days,
        next_touch_override=next_touch_override,
    )
    db.add(contact)
    db.flush()
    set_primary_note(db, NoteableType.NETWORK_CONTACT.value, contact.id, notes)
    db.commit()
    return RedirectResponse(url="/network", status_code=303)


@router.get("/{contact_id}/edit", response_class=HTMLResponse)
def edit_network_contact(request: Request, contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(NetworkContact, contact_id)
    if not contact:
        return RedirectResponse(url="/network", status_code=303)
    settings = get_or_create_settings(db)
    notes_text = get_primary_note_body(db, NoteableType.NETWORK_CONTACT.value, contact.id)
    return templates.TemplateResponse(
        request,
        "network/form.html",
        {
            "contact": contact,
            "notes_text": notes_text,
            "mission": settings.mission_statement,
            **_form_context(db),
        },
    )


@router.post("/{contact_id}")
def update_network_contact(
    contact_id: int,
    name: str = Form(...),
    affiliation: str = Form(""),
    linkedin_url: str = Form(""),
    opportunity_id: str = Form(""),
    first_contact_at: str = Form(""),
    last_contact_at: str = Form(""),
    last_contact_method: str = Form(""),
    cadence_days: str = Form(""),
    next_touch_override: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    contact = db.get(NetworkContact, contact_id)
    if not contact:
        return RedirectResponse(url="/network", status_code=303)
    name_value = clip_text(name, 60)
    if not name_value:
        return RedirectResponse(url=f"/network/{contact_id}/edit", status_code=303)
    contact.name = name_value
    _apply_form(
        contact,
        affiliation=affiliation,
        linkedin_url=linkedin_url,
        opportunity_id=_parse_opportunity_id(opportunity_id),
        first_contact_at=first_contact_at,
        last_contact_at=last_contact_at,
        last_contact_method=last_contact_method,
        cadence_days=cadence_days,
        next_touch_override=next_touch_override,
    )
    set_primary_note(db, NoteableType.NETWORK_CONTACT.value, contact.id, notes)
    db.commit()
    return RedirectResponse(url="/network", status_code=303)


@router.post("/{contact_id}/delete")
def delete_network_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(NetworkContact, contact_id)
    if contact:
        set_primary_note(db, NoteableType.NETWORK_CONTACT.value, contact.id, "")
        db.delete(contact)
        db.commit()
    return RedirectResponse(url="/network", status_code=303)
