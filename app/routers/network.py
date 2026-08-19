from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CONTACT_METHOD_LABELS, ContactMethod, NoteableType, NetworkContact
from app.services.daily_plan import get_or_create_settings, get_primary_note_body, set_primary_note
from app.services.network import (
    clip_text,
    normalize_contact_method,
    opportunity_link_parts,
    parse_contact_date,
    sort_network_contacts,
)
from app.templating import templates

router = APIRouter(prefix="/network", tags=["network"])


def _form_context() -> dict:
    return {
        "contact_methods": ContactMethod,
        "method_labels": CONTACT_METHOD_LABELS,
    }


def _list_context(db: Session) -> dict:
    settings = get_or_create_settings(db)
    contacts = sort_network_contacts(db.query(NetworkContact)).all()
    notes = {
        contact.id: get_primary_note_body(db, NoteableType.NETWORK_CONTACT.value, contact.id)
        for contact in contacts
    }
    opportunity_links = {contact.id: opportunity_link_parts(contact.opportunities) for contact in contacts}
    return {
        "contacts": contacts,
        "notes": notes,
        "opportunity_links": opportunity_links,
        "method_labels": CONTACT_METHOD_LABELS,
        "mission": settings.mission_statement,
    }


@router.get("", response_class=HTMLResponse)
def list_network_contacts(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "network/list.html",
        _list_context(db),
    )


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
            **_form_context(),
        },
    )


@router.post("")
def create_network_contact(
    name: str = Form(...),
    connection: str = Form(""),
    first_contact_at: str = Form(""),
    followup_contact_at: str = Form(""),
    method: str = Form(""),
    opportunities: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    name_value = clip_text(name, 60)
    if not name_value:
        return RedirectResponse(url="/network/new", status_code=303)
    contact = NetworkContact(
        name=name_value,
        connection=clip_text(connection, 300),
        first_contact_at=parse_contact_date(first_contact_at),
        followup_contact_at=parse_contact_date(followup_contact_at),
        method=normalize_contact_method(method),
        opportunities=clip_text(opportunities, 300),
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
            **_form_context(),
        },
    )


@router.post("/{contact_id}")
def update_network_contact(
    contact_id: int,
    name: str = Form(...),
    connection: str = Form(""),
    first_contact_at: str = Form(""),
    followup_contact_at: str = Form(""),
    method: str = Form(""),
    opportunities: str = Form(""),
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
    contact.connection = clip_text(connection, 300)
    contact.first_contact_at = parse_contact_date(first_contact_at)
    contact.followup_contact_at = parse_contact_date(followup_contact_at)
    contact.method = normalize_contact_method(method)
    contact.opportunities = clip_text(opportunities, 300)
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
