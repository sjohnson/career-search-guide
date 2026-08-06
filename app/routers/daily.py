from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DailyPlanItem, DateKind, MasterTask, NoteableType, TaskStatus
from app.services.daily_plan import (
    archive_plan_item,
    assign_for_target_date_change,
    build_calendar_weeks,
    complete_plan_item,
    remove_plan_item,
    get_or_create_daily_plan,
    get_or_create_settings,
    get_primary_note_body,
    is_sunday,
    maybe_catch_up_today,
    next_source_priority,
    next_work_day,
    noteable_for_plan_item,
    prev_work_day,
    resolve_today,
    set_primary_note,
    uncomplete_plan_item,
)

router = APIRouter(tags=["daily"])
templates = Jinja2Templates(directory="app/templates")


def _format_heading(plan_date: date) -> str:
    return f"{plan_date.strftime('%A, %B')} {plan_date.day}, {plan_date.year}"


def _plan_item_notes(db: Session, item: DailyPlanItem) -> dict[int, str]:
    notes: dict[int, str] = {}
    ref = noteable_for_plan_item(item)
    if ref:
        notes[item.id] = get_primary_note_body(db, ref[0], ref[1])
    return notes


def _collect_notes(db: Session, items: list[DailyPlanItem]) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in items:
        result.update(_plan_item_notes(db, item))
    return result


@router.get("/", response_class=HTMLResponse)
def daily_root():
    today = resolve_today()
    return RedirectResponse(url=f"/daily/{today.isoformat()}", status_code=303)


@router.get("/daily/{plan_date}", response_class=HTMLResponse)
def daily_plan_view(
    request: Request,
    plan_date: date,
    cal_year: int | None = None,
    cal_month: int | None = None,
    db: Session = Depends(get_db),
):
    settings = get_or_create_settings(db)
    actual_today = date.today()
    today = resolve_today()

    if is_sunday(plan_date):
        return templates.TemplateResponse(
            request,
            "daily/rest_day.html",
            {
                "plan_date": plan_date,
                "today": today,
                "mission": settings.mission_statement,
                "next_work": next_work_day(plan_date),
            },
        )

    plan, _ = get_or_create_daily_plan(db, plan_date, assign=False)
    maybe_catch_up_today(db, plan, plan_date)
    db.refresh(plan)

    active_items = [i for i in plan.items if not i.is_completed]
    completed_items = [i for i in plan.items if i.is_completed]
    task_notes = _collect_notes(db, plan.items)

    cy = cal_year or plan_date.year
    cm = cal_month or plan_date.month

    return templates.TemplateResponse(
        request,
        "daily/show.html",
        {
            "plan": plan,
            "plan_date": plan_date,
            "heading": _format_heading(plan_date),
            "prev_date": prev_work_day(plan_date),
            "next_date": next_work_day(plan_date),
            "active_tasks": active_items,
            "completed_tasks": completed_items,
            "task_notes": task_notes,
            "mission": settings.mission_statement,
            "today": today,
            "cal_year": cy,
            "cal_month": cm,
            "calendar_weeks": build_calendar_weeks(cy, cm),
            "is_sunday": is_sunday,
            "viewing_today": plan_date == actual_today and not is_sunday(actual_today),
        },
    )


@router.get("/daily/{plan_date}/calendar", response_class=HTMLResponse)
def calendar_partial(
    request: Request,
    plan_date: date,
    cal_year: int,
    cal_month: int,
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "daily/partials/calendar.html",
        {
            "plan_date": plan_date,
            "cal_year": cal_year,
            "cal_month": cal_month,
            "calendar_weeks": build_calendar_weeks(cal_year, cal_month),
            "is_sunday": is_sunday,
        },
    )


@router.post("/daily/{plan_date}/tasks")
def create_daily_task(
    plan_date: date,
    title: str = Form(...),
    notes: str = Form(""),
    date_kind: str = Form(DateKind.GOAL.value),
    target_date: str = Form(""),
    is_recurring: str = Form(""),
    db: Session = Depends(get_db),
):
    parsed_target = plan_date
    if target_date:
        try:
            parsed_target = date.fromisoformat(target_date)
        except ValueError:
            parsed_target = plan_date

    recurring = is_recurring in {"1", "true", "on", "yes"}
    if recurring and not target_date:
        parsed_target = plan_date

    kind = date_kind if date_kind in {DateKind.GOAL.value, DateKind.REQUIREMENT.value} else DateKind.GOAL.value
    master = MasterTask(
        task=title.strip(),
        priority=next_source_priority(db, MasterTask),
        target_completion_date=parsed_target,
        date_kind=kind,
        is_recurring=recurring,
        status=TaskStatus.CURRENT.value,
    )
    db.add(master)
    db.flush()
    set_primary_note(db, NoteableType.MASTER_TASK.value, master.id, notes)

    plan, _ = get_or_create_daily_plan(db, plan_date, assign=False)
    max_order = max((i.priority_order for i in plan.items), default=-1)
    db.add(
        DailyPlanItem(
            daily_plan_id=plan.id,
            priority_order=max_order + 1,
            master_task_id=master.id,
        )
    )
    db.commit()
    return RedirectResponse(url=f"/daily/{plan_date.isoformat()}", status_code=303)


@router.post("/daily/items/{item_id}/complete")
def complete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(DailyPlanItem, item_id)
    if not item:
        return RedirectResponse(url="/", status_code=303)
    complete_plan_item(db, item)
    return RedirectResponse(url=f"/daily/{item.daily_plan.plan_date.isoformat()}", status_code=303)


@router.post("/daily/items/{item_id}/uncomplete")
def uncomplete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(DailyPlanItem, item_id)
    if not item:
        return RedirectResponse(url="/", status_code=303)
    uncomplete_plan_item(db, item)
    return RedirectResponse(url=f"/daily/{item.daily_plan.plan_date.isoformat()}", status_code=303)


@router.post("/daily/items/{item_id}/archive")
def archive_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(DailyPlanItem, item_id)
    if not item:
        return RedirectResponse(url="/", status_code=303)
    plan_date = item.daily_plan.plan_date
    archive_plan_item(db, item)
    return RedirectResponse(url=f"/daily/{plan_date.isoformat()}", status_code=303)


@router.post("/daily/items/{item_id}/delete")
def delete_item(
    item_id: int,
    delete_source: str = Form(""),
    db: Session = Depends(get_db),
):
    item = db.get(DailyPlanItem, item_id)
    if not item:
        return RedirectResponse(url="/", status_code=303)
    plan_date = item.daily_plan.plan_date
    also_delete_source = delete_source in {"1", "true", "on", "yes"}
    remove_plan_item(db, item, delete_source=also_delete_source)
    return RedirectResponse(url=f"/daily/{plan_date.isoformat()}", status_code=303)


@router.post("/daily/items/{item_id}/update")
def update_item(
    item_id: int,
    title: str = Form(...),
    notes: str = Form(""),
    date_kind: str = Form(DateKind.GOAL.value),
    target_date: str = Form(""),
    db: Session = Depends(get_db),
):
    item = db.get(DailyPlanItem, item_id)
    if not item or not item.master_task:
        return RedirectResponse(url="/", status_code=303)

    master = item.master_task
    master.task = title.strip()
    master.date_kind = (
        date_kind if date_kind in {DateKind.GOAL.value, DateKind.REQUIREMENT.value} else DateKind.GOAL.value
    )
    if target_date:
        try:
            master.target_completion_date = date.fromisoformat(target_date)
        except ValueError:
            pass
    else:
        master.target_completion_date = None

    set_primary_note(db, NoteableType.MASTER_TASK.value, master.id, notes)
    db.commit()
    assign_for_target_date_change(db, master.target_completion_date, master=master)
    return RedirectResponse(url=f"/daily/{item.daily_plan.plan_date.isoformat()}", status_code=303)


@router.post("/daily/{plan_date}/reorder")
async def reorder_items(plan_date: date, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    order = body.get("order", [])
    plan, _ = get_or_create_daily_plan(db, plan_date, assign=False)
    item_map = {i.id: i for i in plan.items}
    for idx, item_id in enumerate(order):
        iid = int(item_id)
        if iid in item_map:
            item_map[iid].priority_order = idx
    db.commit()
    return {"ok": True}
