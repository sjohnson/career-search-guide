"""Unemployment tab: weekly work-search contacts for Utah DWS claims."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import unemployment
from app.services.daily_plan import get_or_create_settings
from app.templating import templates

router = APIRouter(prefix="/unemployment", tags=["unemployment"])


def _shared_context() -> dict:
    return {
        "method_suggestions": unemployment.METHOD_SUGGESTIONS,
        "result_suggestions": unemployment.RESULT_SUGGESTIONS,
        "required_contacts": unemployment.REQUIRED_CONTACTS,
        "short_date": unemployment.short_date,
    }


def _parse_week(raw: str | None) -> date | None:
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


@router.get("", response_class=HTMLResponse)
def unemployment_page(request: Request, week: str | None = None, db: Session = Depends(get_db)):
    today = date.today()
    extra = _parse_week(week)
    weeks = unemployment.weeks_to_show(db, today, extra=extra)
    earliest = weeks[-1].week_ending
    return templates.TemplateResponse(
        request,
        "unemployment/list.html",
        {
            "mission": get_or_create_settings(db).mission_statement,
            "weeks": weeks,
            "current_week_ending": unemployment.week_ending_for(today),
            "earlier_week": earliest - timedelta(days=7),
            **_shared_context(),
        },
    )


@router.post("/weeks/{week_ending}", response_class=HTMLResponse)
def save_week(
    request: Request,
    week_ending: str,
    row_id: list[str] = Form([]),
    contact_date: list[str] = Form([]),
    company: list[str] = Form([]),
    contact_details: list[str] = Form([]),
    position_title: list[str] = Form([]),
    method: list[str] = Form([]),
    result: list[str] = Form([]),
    db: Session = Depends(get_db),
):
    parsed = _parse_week(week_ending)
    if parsed is None or unemployment.week_ending_for(parsed) != parsed:
        return HTMLResponse("<p class='error'>Unknown week.</p>", status_code=404)

    def at(values: list[str], i: int) -> str:
        return values[i] if i < len(values) else ""

    rows = [
        unemployment.ContactRow(
            id=int(at(row_id, i)) if at(row_id, i).isdigit() else None,
            contact_date=at(contact_date, i),
            company=at(company, i),
            contact_details=at(contact_details, i),
            position_title=at(position_title, i),
            method=at(method, i),
            result=at(result, i),
        )
        for i in range(max(map(len, (row_id, contact_date, company, contact_details, position_title, method, result))))
    ]
    week = unemployment.save_week(db, parsed, rows)
    return templates.TemplateResponse(
        request,
        "unemployment/partials/week.html",
        {
            "week": week,
            "current_week_ending": unemployment.week_ending_for(date.today()),
            "saved": not week.errors,
            **_shared_context(),
        },
    )
