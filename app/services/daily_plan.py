from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    DailyPlan,
    DailyPlanItem,
    DateKind,
    LearningTask,
    MasterTask,
    Note,
    NoteableType,
    Settings,
    TaskStatus,
)
from app.config import DEFAULT_MISSION

UNORDERED_PRIORITY = 999_999


def is_sunday(d: date) -> bool:
    return d.weekday() == 6


def is_work_day(d: date) -> bool:
    return d.weekday() != 6


def next_work_day(d: date) -> date:
    n = d + timedelta(days=1)
    while is_sunday(n):
        n += timedelta(days=1)
    return n


def prev_work_day(d: date) -> date:
    p = d - timedelta(days=1)
    while is_sunday(p):
        p -= timedelta(days=1)
    return p


def resolve_today() -> date:
    today = date.today()
    if is_sunday(today):
        return next_work_day(today)
    return today


def priority_sort_key(priority: int) -> int:
    return priority if priority > 0 else UNORDERED_PRIORITY


def sort_master_tasks(tasks: list[MasterTask]) -> list[MasterTask]:
    return sorted(
        tasks,
        key=lambda t: (
            priority_sort_key(t.priority),
            t.target_completion_date or date.max,
            t.id,
        ),
    )


def sort_learning_tasks(tasks: list[LearningTask]) -> list[LearningTask]:
    return sorted(
        tasks,
        key=lambda t: (
            priority_sort_key(t.priority),
            t.target_completion_date or date.max,
            t.id,
        ),
    )


def get_or_create_settings(db: Session) -> Settings:
    settings = db.query(Settings).first()
    if not settings:
        settings = Settings(mission_statement=DEFAULT_MISSION)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def get_or_create_daily_plan(db: Session, plan_date: date, *, assign: bool = True) -> tuple[DailyPlan, bool]:
    plan = db.query(DailyPlan).filter(DailyPlan.plan_date == plan_date).first()
    created = False
    if not plan:
        plan = DailyPlan(plan_date=plan_date)
        db.add(plan)
        db.commit()
        db.refresh(plan)
        created = True
        if assign:
            assign_due_tasks(
                db,
                plan,
                viewing_today=plan_date == date.today() and not is_sunday(date.today()),
            )
    return plan, created


def get_notes_for(db: Session, noteable_type: str, noteable_id: int) -> list[Note]:
    return (
        db.query(Note)
        .filter(Note.noteable_type == noteable_type, Note.noteable_id == noteable_id)
        .order_by(Note.created_at)
        .all()
    )


def get_primary_note_body(db: Session, noteable_type: str, noteable_id: int) -> str:
    notes = get_notes_for(db, noteable_type, noteable_id)
    if not notes:
        return ""
    return notes[0].body


def set_primary_note(db: Session, noteable_type: str, noteable_id: int, body: str) -> None:
    body = (body or "").strip()
    notes = get_notes_for(db, noteable_type, noteable_id)
    if body:
        if notes:
            notes[0].body = body
            notes[0].updated_at = datetime.utcnow()
        else:
            db.add(Note(body=body, noteable_type=noteable_type, noteable_id=noteable_id))
    elif notes:
        for note in notes:
            db.delete(note)


def noteable_for_plan_item(item: DailyPlanItem) -> tuple[str, int] | None:
    if item.master_task_id:
        return NoteableType.MASTER_TASK.value, item.master_task_id
    if item.learning_task_id:
        return NoteableType.LEARNING_TASK.value, item.learning_task_id
    return None


def next_source_priority(db: Session, model) -> int:
    rows = db.query(model.priority).filter(model.priority > 0).all()
    if not rows:
        return 1
    return max(p[0] for p in rows) + 1


def _existing_plan_master_ids(plan: DailyPlan) -> set[int]:
    return {i.master_task_id for i in plan.items if i.master_task_id is not None}


def _existing_plan_learning_ids(plan: DailyPlan) -> set[int]:
    return {i.learning_task_id for i in plan.items if i.learning_task_id is not None}


def _due_master_query(db: Session, plan_date: date, viewing_today: bool):
    query = db.query(MasterTask).filter(
        MasterTask.status == TaskStatus.CURRENT.value,
        MasterTask.is_recurring.is_(False),
    )
    if viewing_today:
        query = query.filter(
            MasterTask.target_completion_date.isnot(None),
            (MasterTask.target_completion_date == plan_date)
            | (MasterTask.target_completion_date < plan_date),
        )
    else:
        query = query.filter(MasterTask.target_completion_date == plan_date)
    return query


def _recurring_master_query(db: Session, plan_date: date):
    """Current recurring masters whose start date is on or before plan_date."""
    candidates = (
        db.query(MasterTask)
        .filter(
            MasterTask.status == TaskStatus.CURRENT.value,
            MasterTask.is_recurring.is_(True),
        )
        .all()
    )
    return [m for m in candidates if (m.recurrence_start_date or plan_date) <= plan_date]


def _due_learning_query(db: Session, plan_date: date, viewing_today: bool):
    query = db.query(LearningTask).filter(LearningTask.status == TaskStatus.CURRENT.value)
    if viewing_today:
        query = query.filter(
            LearningTask.target_completion_date.isnot(None),
            (LearningTask.target_completion_date == plan_date)
            | (LearningTask.target_completion_date < plan_date),
        )
    else:
        query = query.filter(LearningTask.target_completion_date == plan_date)
    return query


def assign_due_tasks(db: Session, plan: DailyPlan, *, viewing_today: bool) -> None:
    """Add master and learning tasks due on plan_date (and overdue when viewing today)."""
    existing_masters = _existing_plan_master_ids(plan)
    existing_learning = _existing_plan_learning_ids(plan)

    masters = sort_master_tasks(_due_master_query(db, plan.plan_date, viewing_today).all())
    recurring = sort_master_tasks(_recurring_master_query(db, plan.plan_date))
    masters = sort_master_tasks(masters + recurring)
    learning = sort_learning_tasks(_due_learning_query(db, plan.plan_date, viewing_today).all())

    max_order = max((i.priority_order for i in plan.items), default=-1)

    for master in masters:
        if master.id in existing_masters:
            continue
        max_order += 1
        db.add(
            DailyPlanItem(
                daily_plan_id=plan.id,
                priority_order=max_order,
                master_task_id=master.id,
            )
        )
        existing_masters.add(master.id)

    for task in learning:
        if task.id in existing_learning:
            continue
        max_order += 1
        db.add(
            DailyPlanItem(
                daily_plan_id=plan.id,
                priority_order=max_order,
                learning_task_id=task.id,
            )
        )
        existing_learning.add(task.id)

    plan.last_assigned_at = datetime.utcnow()
    db.commit()


def maybe_catch_up_today(db: Session, plan: DailyPlan, plan_date: date) -> None:
    actual_today = date.today()
    if plan_date != actual_today or is_sunday(actual_today):
        return
    last = plan.last_assigned_at.date() if plan.last_assigned_at else None
    if last != actual_today:
        assign_due_tasks(db, plan, viewing_today=True)


def assign_task_to_plan(
    db: Session,
    plan_date: date,
    *,
    master: MasterTask | None = None,
    learning: LearningTask | None = None,
) -> DailyPlanItem | None:
    if not master and not learning:
        return None
    plan, _ = get_or_create_daily_plan(db, plan_date, assign=False)
    if master:
        if master.id in _existing_plan_master_ids(plan):
            return None
        max_order = max((i.priority_order for i in plan.items), default=-1)
        item = DailyPlanItem(
            daily_plan_id=plan.id,
            priority_order=max_order + 1,
            master_task_id=master.id,
        )
    else:
        if learning.id in _existing_plan_learning_ids(plan):
            return None
        max_order = max((i.priority_order for i in plan.items), default=-1)
        item = DailyPlanItem(
            daily_plan_id=plan.id,
            priority_order=max_order + 1,
            learning_task_id=learning.id,
        )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def assign_for_target_date_change(
    db: Session,
    target_date: date | None,
    *,
    master: MasterTask | None = None,
    learning: LearningTask | None = None,
) -> None:
    if not target_date:
        return
    actual_today = date.today()
    assign_task_to_plan(db, target_date, master=master, learning=learning)
    if target_date < actual_today and not is_sunday(actual_today):
        assign_task_to_plan(db, actual_today, master=master, learning=learning)


def complete_plan_item(db: Session, item: DailyPlanItem) -> None:
    if item.master_task and item.master_task.is_recurring:
        item.completed_at = datetime.utcnow()
        db.commit()
        return
    source = item.source_task
    if not source:
        return
    source.status = TaskStatus.COMPLETED.value
    source.completed_at = datetime.utcnow()
    db.commit()


def uncomplete_plan_item(db: Session, item: DailyPlanItem) -> None:
    if item.master_task and item.master_task.is_recurring:
        item.completed_at = None
        db.commit()
        return
    source = item.source_task
    if not source:
        return
    source.status = TaskStatus.CURRENT.value
    source.completed_at = None
    db.commit()


def archive_plan_item(db: Session, item: DailyPlanItem) -> None:
    source = item.source_task
    if source:
        source.status = TaskStatus.ARCHIVED.value
    db.delete(item)
    db.commit()


def delete_plan_item(db: Session, item: DailyPlanItem) -> None:
    source = item.source_task
    db.delete(item)
    if source:
        db.delete(source)
    db.commit()


def archive_source_task(db: Session, task: MasterTask | LearningTask) -> None:
    task.status = TaskStatus.ARCHIVED.value
    db.query(DailyPlanItem).filter(
        (DailyPlanItem.master_task_id == task.id)
        | (DailyPlanItem.learning_task_id == task.id)
    ).delete(synchronize_session=False)
    db.commit()


def complete_source_task(db: Session, task: MasterTask | LearningTask) -> None:
    task.status = TaskStatus.COMPLETED.value
    task.completed_at = datetime.utcnow()
    db.commit()


def uncomplete_source_task(db: Session, task: MasterTask | LearningTask) -> None:
    task.status = TaskStatus.CURRENT.value
    task.completed_at = None
    db.commit()


def rewrite_priorities(db: Session, model, ordered_ids: list[int]) -> None:
    for idx, task_id in enumerate(ordered_ids, start=1):
        row = db.get(model, int(task_id))
        if row:
            row.priority = idx
    db.commit()


def build_calendar_weeks(year: int, month: int) -> list[list[date | None]]:
    first = date(year, month, 1)
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)

    start_pad = (first.weekday() + 1) % 7

    days: list[date | None] = [None] * start_pad
    d = first
    while d <= last:
        days.append(d)
        d += timedelta(days=1)
    while len(days) % 7 != 0:
        days.append(None)

    return [days[i : i + 7] for i in range(0, len(days), 7)]
