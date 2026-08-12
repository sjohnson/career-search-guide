from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import IMPORT_MAX_UPLOAD_BYTES
from app.database import get_db
from app.services.daily_plan import get_or_create_settings, resolve_today
from app.services.import_service import import_workbook
from app.templating import templates

router = APIRouter(prefix="/import", tags=["import"])

ALLOWED_XLSX_CONTENT_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    }
)


def _validate_upload(file: UploadFile, content: bytes) -> str | None:
    filename = (file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        return "Upload must be an .xlsx file."

    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type and content_type not in ALLOWED_XLSX_CONTENT_TYPES:
        return "Invalid file type. Upload an Excel .xlsx export."

    if len(content) > IMPORT_MAX_UPLOAD_BYTES:
        return "File is too large (max 10 MB)."

    if len(content) == 0:
        return "Uploaded file is empty."

    return None


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
    content = await file.read(IMPORT_MAX_UPLOAD_BYTES + 1)
    upload_error = _validate_upload(file, content)
    if upload_error:
        return templates.TemplateResponse(
            request,
            "import/form.html",
            {
                "mission": settings.mission_statement,
                "default_date": resolve_today().isoformat(),
                "error": upload_error,
            },
            status_code=400,
        )

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
