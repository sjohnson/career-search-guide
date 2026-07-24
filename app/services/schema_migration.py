"""Migrate legacy daily_tasks schema to daily_plan_items + new task fields."""

from datetime import date, datetime

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import engine
from app.models import (
    DailyPlanItem,
    DateKind,
    MasterTask,
    Note,
    NoteableType,
    TaskStatus,
)


def _table_exists(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _column_exists(insp, table: str, column: str) -> bool:
    if not _table_exists(insp, table):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def _add_column_if_missing(conn, insp, table: str, column: str, ddl: str) -> None:
    if not _column_exists(insp, table, column):
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def _migrate_priority_zeros(db: Session, model) -> None:
    rows = db.query(model).order_by(model.created_at, model.id).all()
    max_prio = max((r.priority for r in rows if r.priority > 0), default=0)
    for row in rows:
        if row.priority == 0:
            max_prio += 1
            row.priority = max_prio


def run_schema_migration(db: Session) -> None:
    insp = inspect(engine)

    with engine.begin() as conn:
        if _table_exists(insp, "master_tasks"):
            _add_column_if_missing(
                conn, insp, "master_tasks", "date_kind", "date_kind VARCHAR(20) DEFAULT 'goal'"
            )
            _add_column_if_missing(
                conn,
                insp,
                "master_tasks",
                "status",
                "status VARCHAR(20) DEFAULT 'current'",
            )
        if _table_exists(insp, "learning_tasks"):
            _add_column_if_missing(
                conn,
                insp,
                "learning_tasks",
                "target_completion_date",
                "target_completion_date DATE",
            )
            _add_column_if_missing(
                conn,
                insp,
                "learning_tasks",
                "status",
                "status VARCHAR(20) DEFAULT 'current'",
            )
            _add_column_if_missing(
                conn, insp, "learning_tasks", "completed_at", "completed_at DATETIME"
            )
        if _table_exists(insp, "daily_plans"):
            _add_column_if_missing(
                conn, insp, "daily_plans", "last_assigned_at", "last_assigned_at DATETIME"
            )

    insp = inspect(engine)

    if _table_exists(insp, "daily_tasks"):
        if _table_exists(insp, "daily_plan_items"):
            db.execute(text("DROP TABLE daily_plan_items"))
            db.commit()
        _migrate_daily_tasks_to_plan_items(db)

    db.commit()

    from app.models import LearningTask

    for model in (MasterTask, LearningTask):
        _migrate_completed_at_to_status(db, model)
        _migrate_priority_zeros(db, model)
    db.commit()

    _migrate_opportunities(db)
    db.commit()


def _parse_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.split(".")[0])
        except ValueError:
            return None
    return None


def _parse_date_value(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _migrate_completed_at_to_status(db: Session, model) -> None:
    for row in db.query(model).all():
        if row.completed_at and row.status == TaskStatus.CURRENT.value:
            row.status = TaskStatus.COMPLETED.value
        elif not row.completed_at and row.status == TaskStatus.COMPLETED.value:
            row.status = TaskStatus.CURRENT.value


def _migrate_daily_tasks_to_plan_items(db: Session) -> None:
    rows = db.execute(
        text(
            "SELECT id, daily_plan_id, title, priority_order, target_date, date_kind, "
            "completed_at, source, master_task_id FROM daily_tasks ORDER BY id"
        )
    ).fetchall()

    db.execute(
        text(
            """
            CREATE TABLE daily_plan_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_plan_id INTEGER NOT NULL REFERENCES daily_plans(id),
                priority_order INTEGER DEFAULT 0,
                master_task_id INTEGER REFERENCES master_tasks(id),
                learning_task_id INTEGER REFERENCES learning_tasks(id),
                created_at DATETIME,
                UNIQUE (daily_plan_id, master_task_id),
                UNIQUE (daily_plan_id, learning_task_id),
                CHECK (
                    (master_task_id IS NOT NULL AND learning_task_id IS NULL) OR
                    (master_task_id IS NULL AND learning_task_id IS NOT NULL)
                )
            )
            """
        )
    )

    for row in rows:
        (
            old_id,
            daily_plan_id,
            title,
            priority_order,
            target_date,
            date_kind,
            completed_at,
            source,
            master_task_id,
        ) = row

        master_id = master_task_id
        completed_dt = _parse_datetime(completed_at)
        parsed_target = _parse_date_value(target_date)
        parsed_kind = date_kind or DateKind.GOAL.value
        if not master_id:
            status = TaskStatus.COMPLETED.value if completed_dt else TaskStatus.CURRENT.value
            master = MasterTask(
                task=title,
                target_completion_date=parsed_target,
                date_kind=parsed_kind if parsed_kind in {DateKind.GOAL.value, DateKind.REQUIREMENT.value} else DateKind.GOAL.value,
                status=status,
                completed_at=completed_dt,
            )
            db.add(master)
            db.flush()
            master_id = master.id

            daily_notes = (
                db.query(Note)
                .filter(
                    Note.noteable_type == "daily_task",
                    Note.noteable_id == old_id,
                )
                .order_by(Note.created_at)
                .all()
            )
            for note in daily_notes:
                note.noteable_type = NoteableType.MASTER_TASK.value
                note.noteable_id = master_id
        else:
            master = db.get(MasterTask, master_id)
            if master and completed_dt and master.status == TaskStatus.CURRENT.value:
                master.status = TaskStatus.COMPLETED.value
                master.completed_at = completed_dt

        db.execute(
            text(
                "INSERT INTO daily_plan_items "
                "(daily_plan_id, priority_order, master_task_id, learning_task_id, created_at) "
                "VALUES (:plan_id, :order, :master_id, NULL, :created)"
            ),
            {
                "plan_id": daily_plan_id,
                "order": priority_order,
                "master_id": master_id,
                "created": datetime.utcnow(),
            },
        )

    db.execute(text("DROP TABLE daily_tasks"))
    db.flush()


def _normalize_pipeline_stage(text_value: str | None) -> str | None:
    from app.models import PipelineStage

    if not text_value:
        return None
    normalized = text_value.strip().lower().replace(" ", "_").replace("-", "_")
    mapping = {
        "new": PipelineStage.NEW.value,
        "applied": PipelineStage.APPLIED.value,
        "interviewing": PipelineStage.INTERVIEWING.value,
        "follow_up": PipelineStage.FOLLOW_UP.value,
        "followup": PipelineStage.FOLLOW_UP.value,
        "offer": PipelineStage.OFFER.value,
        "passed": PipelineStage.PASSED.value,
        "declined": PipelineStage.PASSED.value,
        "closed": PipelineStage.CLOSED.value,
        "rejected": PipelineStage.CLOSED.value,
        "withdrawn": PipelineStage.CLOSED.value,
    }
    return mapping.get(normalized)


def _migrate_opportunities(db: Session) -> None:
    from app.models import Opportunity, OpportunityLifecycle, PipelineStage

    insp = inspect(engine)
    if not _table_exists(insp, "opportunities"):
        return

    with engine.begin() as conn:
        insp = inspect(engine)
        _add_column_if_missing(
            conn,
            insp,
            "opportunities",
            "pipeline_stage",
            "pipeline_stage VARCHAR(30) DEFAULT 'new'",
        )
        _add_column_if_missing(
            conn,
            insp,
            "opportunities",
            "lifecycle_status",
            "lifecycle_status VARCHAR(20) DEFAULT 'active'",
        )
        _add_column_if_missing(
            conn, insp, "opportunities", "highlight_rank", "highlight_rank INTEGER"
        )
        if _column_exists(insp, "opportunities", "stack_match") and not _column_exists(
            insp, "opportunities", "stack"
        ):
            conn.execute(text("ALTER TABLE opportunities RENAME COLUMN stack_match TO stack"))
        elif not _column_exists(insp, "opportunities", "stack"):
            _add_column_if_missing(conn, insp, "opportunities", "stack", "stack VARCHAR(200)")
        _add_column_if_missing(
            conn, insp, "opportunities", "updated_at", "updated_at DATETIME"
        )

    insp = inspect(engine)
    if _column_exists(insp, "opportunities", "updated_at"):
        db.execute(
            text(
                "UPDATE opportunities SET updated_at = created_at "
                "WHERE updated_at IS NULL AND created_at IS NOT NULL"
            )
        )
        db.execute(
            text("UPDATE opportunities SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
        )
        db.commit()

    for opp in db.query(Opportunity).all():
        if not opp.pipeline_stage:
            opp.pipeline_stage = PipelineStage.NEW.value
        if not opp.lifecycle_status:
            opp.lifecycle_status = OpportunityLifecycle.ACTIVE.value
        if (
            opp.lifecycle_status == OpportunityLifecycle.ACTIVE.value
            and opp.pipeline_stage in (PipelineStage.PASSED.value, PipelineStage.CLOSED.value)
        ):
            opp.lifecycle_status = OpportunityLifecycle.ARCHIVED.value
            opp.highlight_rank = None
    db.commit()

    if not _column_exists(inspect(engine), "opportunities", "status"):
        return

    rows = db.execute(
        text("SELECT id, status, stack FROM opportunities WHERE status IS NOT NULL AND status != ''")
    ).fetchall()
    for opp_id, old_status, stack in rows:
        stage = _normalize_pipeline_stage(old_status)
        opp = db.get(Opportunity, opp_id)
        if not opp:
            continue
        if stage:
            opp.pipeline_stage = stage
        else:
            existing = (
                db.query(Note)
                .filter(
                    Note.noteable_type == NoteableType.OPPORTUNITY.value,
                    Note.noteable_id == opp_id,
                )
                .order_by(Note.created_at)
                .first()
            )
            merged = old_status.strip()
            if existing and existing.body:
                merged = f"{merged}\n{existing.body}".strip()
            if existing:
                existing.body = merged
            else:
                db.add(
                    Note(
                        body=merged,
                        noteable_type=NoteableType.OPPORTUNITY.value,
                        noteable_id=opp_id,
                    )
                )
        if not opp.pipeline_stage:
            opp.pipeline_stage = PipelineStage.NEW.value
        if not opp.lifecycle_status:
            opp.lifecycle_status = OpportunityLifecycle.ACTIVE.value

    # Drop legacy status column by recreating table if SQLite supports it
    insp = inspect(engine)
    if _column_exists(insp, "opportunities", "status"):
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE opportunities DROP COLUMN status"))
        except Exception:
            pass

    db.commit()
