from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.daily_plan import get_or_create_settings

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def settings_form(request: Request, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    return templates.TemplateResponse(
        request,
        "settings/form.html",
        {"settings": settings, "mission": settings.mission_statement},
    )


@router.post("")
def update_settings(
    mission_statement: str = Form(...),
    db: Session = Depends(get_db),
):
    settings = get_or_create_settings(db)
    settings.mission_statement = mission_statement.strip()
    db.commit()
    return RedirectResponse(url="/", status_code=303)
