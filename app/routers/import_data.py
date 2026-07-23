from datetime import date

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.daily_plan import get_or_create_settings, resolve_today
from app.services.import_service import import_workbook

router = APIRouter(prefix="/import", tags=["import"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def import_form(request: Request, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    return templates.TemplateResponse(
        request,
        "import/form.html",
        {"mission": settings.mission_statement, "default_date": resolve_today().isoformat()},
    )


@router.post("", response_class=HTMLResponse)
async def import_file(
    request: Request,
    file: UploadFile = File(...),
    daily_plan_date: str = Form(""),
    mode: str = Form("append"),
    db: Session = Depends(get_db),
):
    settings = get_or_create_settings(db)
    content = await file.read()
    plan_date = resolve_today()
    if daily_plan_date:
        try:
            plan_date = date.fromisoformat(daily_plan_date)
        except ValueError:
            pass

    try:
        result = import_workbook(db, content, plan_date, mode=mode)
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "import/form.html",
            {
                "mission": settings.mission_statement,
                "default_date": resolve_today().isoformat(),
                "error": str(exc),
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        request,
        "import/result.html",
        {
            "mission": settings.mission_statement,
            "result": result,
            "plan_date": plan_date,
        },
    )
