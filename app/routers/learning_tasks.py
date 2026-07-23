from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LearningTask, NoteableType, TaskStatus
from app.services.daily_plan import (
    assign_for_target_date_change,
    archive_source_task,
    complete_source_task,
    get_or_create_settings,
    get_primary_note_body,
    rewrite_priorities,
    set_primary_note,
    sort_learning_tasks,
    uncomplete_source_task,
)

router = APIRouter(prefix="/learning-tasks", tags=["learning_tasks"])
templates = Jinja2Templates(directory="app/templates")


def _split_tasks(tasks: list[LearningTask]) -> tuple[list[LearningTask], list[LearningTask], list[LearningTask]]:
    active = [t for t in tasks if t.status == TaskStatus.CURRENT.value]
    completed = [t for t in tasks if t.status == TaskStatus.COMPLETED.value]
    archived = [t for t in tasks if t.status == TaskStatus.ARCHIVED.value]
    return sort_learning_tasks(active), sort_learning_tasks(completed), sort_learning_tasks(archived)


@router.get("", response_class=HTMLResponse)
def list_learning_tasks(request: Request, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    all_tasks = db.query(LearningTask).all()
    active, completed, archived = _split_tasks(all_tasks)
    notes = {t.id: get_primary_note_body(db, NoteableType.LEARNING_TASK.value, t.id) for t in all_tasks}
    today = date.today()
    return templates.TemplateResponse(
        request,
        "learning_tasks/list.html",
        {
            "active_tasks": active,
            "completed_tasks": completed,
            "archived_tasks": archived,
            "notes": notes,
            "mission": settings.mission_statement,
            "cal_year": today.year,
            "cal_month": today.month,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_learning_task(request: Request, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    return templates.TemplateResponse(
        request,
        "learning_tasks/form.html",
        {"task": None, "notes_text": "", "mission": settings.mission_statement},
    )


@router.post("")
def create_learning_task(
    task: str = Form(...),
    resource: str = Form(""),
    target_completion_date: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    parsed_date = None
    if target_completion_date:
        try:
            parsed_date = date.fromisoformat(target_completion_date)
        except ValueError:
            parsed_date = None
    learning = LearningTask(
        task=task.strip(),
        resource=resource.strip() or None,
        priority=0,
        target_completion_date=parsed_date,
        status=TaskStatus.CURRENT.value,
    )
    db.add(learning)
    db.flush()
    set_primary_note(db, NoteableType.LEARNING_TASK.value, learning.id, notes)
    db.commit()
    assign_for_target_date_change(db, parsed_date, learning=learning)
    return RedirectResponse(url="/learning-tasks", status_code=303)


@router.get("/{task_id}/edit", response_class=HTMLResponse)
def edit_learning_task(request: Request, task_id: int, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    learning = db.get(LearningTask, task_id)
    if not learning:
        return RedirectResponse(url="/learning-tasks", status_code=303)
    notes_text = get_primary_note_body(db, NoteableType.LEARNING_TASK.value, learning.id)
    return templates.TemplateResponse(
        request,
        "learning_tasks/form.html",
        {"task": learning, "notes_text": notes_text, "mission": settings.mission_statement},
    )


@router.post("/{task_id}")
def update_learning_task(
    task_id: int,
    task: str = Form(...),
    resource: str = Form(""),
    target_completion_date: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    learning = db.get(LearningTask, task_id)
    if not learning:
        return RedirectResponse(url="/learning-tasks", status_code=303)
    learning.task = task.strip()
    learning.resource = resource.strip() or None
    parsed_date = None
    if target_completion_date:
        try:
            parsed_date = date.fromisoformat(target_completion_date)
        except ValueError:
            parsed_date = None
    learning.target_completion_date = parsed_date
    set_primary_note(db, NoteableType.LEARNING_TASK.value, learning.id, notes)
    db.commit()
    assign_for_target_date_change(db, parsed_date, learning=learning)
    return RedirectResponse(url="/learning-tasks", status_code=303)


@router.post("/{task_id}/delete")
def delete_learning_task(task_id: int, db: Session = Depends(get_db)):
    learning = db.get(LearningTask, task_id)
    if learning:
        db.delete(learning)
        db.commit()
    return RedirectResponse(url="/learning-tasks", status_code=303)


@router.post("/{task_id}/archive")
def archive_learning_task(task_id: int, db: Session = Depends(get_db)):
    learning = db.get(LearningTask, task_id)
    if learning:
        archive_source_task(db, learning)
    return RedirectResponse(url="/learning-tasks", status_code=303)


@router.post("/{task_id}/complete")
def complete_learning_task(task_id: int, db: Session = Depends(get_db)):
    learning = db.get(LearningTask, task_id)
    if learning:
        complete_source_task(db, learning)
    return RedirectResponse(url="/learning-tasks", status_code=303)


@router.post("/{task_id}/uncomplete")
def uncomplete_learning_task(task_id: int, db: Session = Depends(get_db)):
    learning = db.get(LearningTask, task_id)
    if learning:
        uncomplete_source_task(db, learning)
    return RedirectResponse(url="/learning-tasks", status_code=303)


@router.post("/reorder")
async def reorder_learning_tasks(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    order = body.get("order", [])
    rewrite_priorities(db, LearningTask, order)
    return {"ok": True}


@router.patch("/{task_id}/target-date", response_class=HTMLResponse)
def patch_target_date(
    request: Request,
    task_id: int,
    target_completion_date: str = Form(""),
    db: Session = Depends(get_db),
):
    learning = db.get(LearningTask, task_id)
    if not learning:
        return HTMLResponse("", status_code=404)
    parsed = None
    if target_completion_date:
        try:
            parsed = date.fromisoformat(target_completion_date)
        except ValueError:
            parsed = None
    learning.target_completion_date = parsed
    db.commit()
    assign_for_target_date_change(db, parsed, learning=learning)
    today = date.today()
    ref = learning.target_completion_date or today
    return templates.TemplateResponse(
        request,
        "shared/partials/target_date_cell.html",
        {
            "task": learning,
            "task_type": "learning",
            "task_id": learning.id,
            "cal_year": ref.year,
            "cal_month": ref.month,
        },
    )


@router.get("/{task_id}/date-picker", response_class=HTMLResponse)
def date_picker(
    request: Request,
    task_id: int,
    cal_year: int,
    cal_month: int,
    db: Session = Depends(get_db),
):
    learning = db.get(LearningTask, task_id)
    if not learning:
        return HTMLResponse("", status_code=404)
    from app.services.daily_plan import build_calendar_weeks

    return templates.TemplateResponse(
        request,
        "shared/partials/date_picker_popover.html",
        {
            "task_type": "learning",
            "task_id": task_id,
            "cal_year": cal_year,
            "cal_month": cal_month,
            "calendar_weeks": build_calendar_weeks(cal_year, cal_month),
            "selected_date": learning.target_completion_date,
        },
    )
