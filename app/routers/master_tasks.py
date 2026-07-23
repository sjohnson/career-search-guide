from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DateKind, MasterTask, NoteableType, TaskStatus
from app.services.daily_plan import (
    assign_for_target_date_change,
    archive_source_task,
    complete_source_task,
    get_or_create_settings,
    get_primary_note_body,
    rewrite_priorities,
    set_primary_note,
    sort_master_tasks,
    uncomplete_source_task,
)

router = APIRouter(prefix="/master-tasks", tags=["master_tasks"])
templates = Jinja2Templates(directory="app/templates")


def _split_tasks(tasks: list[MasterTask]) -> tuple[list[MasterTask], list[MasterTask], list[MasterTask]]:
    active = [t for t in tasks if t.status == TaskStatus.CURRENT.value]
    completed = [t for t in tasks if t.status == TaskStatus.COMPLETED.value]
    archived = [t for t in tasks if t.status == TaskStatus.ARCHIVED.value]
    return sort_master_tasks(active), sort_master_tasks(completed), sort_master_tasks(archived)


@router.get("", response_class=HTMLResponse)
def list_master_tasks(request: Request, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    all_tasks = db.query(MasterTask).all()
    active, completed, archived = _split_tasks(all_tasks)
    notes = {t.id: get_primary_note_body(db, NoteableType.MASTER_TASK.value, t.id) for t in all_tasks}
    today = date.today()
    return templates.TemplateResponse(
        request,
        "master_tasks/list.html",
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
def new_master_task(request: Request, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    return templates.TemplateResponse(
        request,
        "master_tasks/form.html",
        {"task": None, "notes_text": "", "mission": settings.mission_statement},
    )


@router.post("")
def create_master_task(
    task: str = Form(...),
    target_completion_date: str = Form(""),
    date_kind: str = Form(DateKind.GOAL.value),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    parsed_date = None
    if target_completion_date:
        try:
            parsed_date = date.fromisoformat(target_completion_date)
        except ValueError:
            parsed_date = None
    kind = date_kind if date_kind in {DateKind.GOAL.value, DateKind.REQUIREMENT.value} else DateKind.GOAL.value
    master = MasterTask(
        task=task.strip(),
        priority=0,
        target_completion_date=parsed_date,
        date_kind=kind,
        status=TaskStatus.CURRENT.value,
    )
    db.add(master)
    db.flush()
    set_primary_note(db, NoteableType.MASTER_TASK.value, master.id, notes)
    db.commit()
    assign_for_target_date_change(db, parsed_date, master=master)
    return RedirectResponse(url="/master-tasks", status_code=303)


@router.get("/{task_id}/edit", response_class=HTMLResponse)
def edit_master_task(request: Request, task_id: int, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    master = db.get(MasterTask, task_id)
    if not master:
        return RedirectResponse(url="/master-tasks", status_code=303)
    notes_text = get_primary_note_body(db, NoteableType.MASTER_TASK.value, master.id)
    return templates.TemplateResponse(
        request,
        "master_tasks/form.html",
        {"task": master, "notes_text": notes_text, "mission": settings.mission_statement},
    )


@router.post("/{task_id}")
def update_master_task(
    task_id: int,
    task: str = Form(...),
    target_completion_date: str = Form(""),
    date_kind: str = Form(DateKind.GOAL.value),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    master = db.get(MasterTask, task_id)
    if not master:
        return RedirectResponse(url="/master-tasks", status_code=303)
    master.task = task.strip()
    master.date_kind = (
        date_kind if date_kind in {DateKind.GOAL.value, DateKind.REQUIREMENT.value} else DateKind.GOAL.value
    )
    parsed_date = None
    if target_completion_date:
        try:
            parsed_date = date.fromisoformat(target_completion_date)
        except ValueError:
            parsed_date = None
    master.target_completion_date = parsed_date
    set_primary_note(db, NoteableType.MASTER_TASK.value, master.id, notes)
    db.commit()
    assign_for_target_date_change(db, parsed_date, master=master)
    return RedirectResponse(url="/master-tasks", status_code=303)


@router.post("/{task_id}/delete")
def delete_master_task(task_id: int, db: Session = Depends(get_db)):
    master = db.get(MasterTask, task_id)
    if master:
        db.delete(master)
        db.commit()
    return RedirectResponse(url="/master-tasks", status_code=303)


@router.post("/{task_id}/archive")
def archive_master_task(task_id: int, db: Session = Depends(get_db)):
    master = db.get(MasterTask, task_id)
    if master:
        archive_source_task(db, master)
    return RedirectResponse(url="/master-tasks", status_code=303)


@router.post("/{task_id}/complete")
def complete_master_task(task_id: int, db: Session = Depends(get_db)):
    master = db.get(MasterTask, task_id)
    if master:
        complete_source_task(db, master)
    return RedirectResponse(url="/master-tasks", status_code=303)


@router.post("/{task_id}/uncomplete")
def uncomplete_master_task(task_id: int, db: Session = Depends(get_db)):
    master = db.get(MasterTask, task_id)
    if master:
        uncomplete_source_task(db, master)
    return RedirectResponse(url="/master-tasks", status_code=303)


@router.post("/reorder")
async def reorder_master_tasks(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    order = body.get("order", [])
    rewrite_priorities(db, MasterTask, order)
    return {"ok": True}


@router.patch("/{task_id}/target-date", response_class=HTMLResponse)
def patch_target_date(
    request: Request,
    task_id: int,
    target_completion_date: str = Form(""),
    db: Session = Depends(get_db),
):
    master = db.get(MasterTask, task_id)
    if not master:
        return HTMLResponse("", status_code=404)
    parsed = None
    if target_completion_date:
        try:
            parsed = date.fromisoformat(target_completion_date)
        except ValueError:
            parsed = None
    master.target_completion_date = parsed
    db.commit()
    assign_for_target_date_change(db, parsed, master=master)
    today = date.today()
    ref = master.target_completion_date or today
    return templates.TemplateResponse(
        request,
        "shared/partials/target_date_cell.html",
        {
            "task": master,
            "task_type": "master",
            "task_id": master.id,
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
    master = db.get(MasterTask, task_id)
    if not master:
        return HTMLResponse("", status_code=404)
    from app.services.daily_plan import build_calendar_weeks

    return templates.TemplateResponse(
        request,
        "shared/partials/date_picker_popover.html",
        {
            "task_type": "master",
            "task_id": task_id,
            "cal_year": cal_year,
            "cal_month": cal_month,
            "calendar_weeks": build_calendar_weeks(cal_year, cal_month),
            "selected_date": master.target_completion_date,
        },
    )


@router.patch("/{task_id}/date-kind", response_class=HTMLResponse)
def patch_date_kind(
    request: Request,
    task_id: int,
    date_kind: str = Form(DateKind.GOAL.value),
    db: Session = Depends(get_db),
):
    master = db.get(MasterTask, task_id)
    if not master:
        return HTMLResponse("", status_code=404)
    master.date_kind = (
        date_kind if date_kind in {DateKind.GOAL.value, DateKind.REQUIREMENT.value} else DateKind.GOAL.value
    )
    db.commit()
    return templates.TemplateResponse(
        request,
        "shared/partials/date_kind_cell.html",
        {"task": master, "task_type": "master", "task_id": master.id},
    )
