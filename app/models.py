from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DateKind(str, Enum):
    GOAL = "goal"
    REQUIREMENT = "requirement"


class TaskStatus(str, Enum):
    CURRENT = "current"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class NoteableType(str, Enum):
    MASTER_TASK = "master_task"
    LEARNING_TASK = "learning_task"
    OPPORTUNITY = "opportunity"


NOTEABLE_TYPES = {item.value for item in NoteableType}


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_statement: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class AdzunaSettings(Base):
    __tablename__ = "adzuna_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_what: Mapped[str] = mapped_column(String(255), nullable=False)
    search_what_and: Mapped[str] = mapped_column(String(255), nullable=False)
    search_what_or: Mapped[str] = mapped_column(String(255), nullable=False)
    salary_min: Mapped[int] = mapped_column(Integer, nullable=False)
    slc_where: Mapped[str] = mapped_column(String(255), nullable=False)
    slc_distance: Mapped[int] = mapped_column(Integer, nullable=False)
    va_where: Mapped[str] = mapped_column(String(255), nullable=False)
    va_distance: Mapped[int] = mapped_column(Integer, nullable=False)
    charlotte_where: Mapped[str] = mapped_column(String(255), nullable=False)
    charlotte_distance: Mapped[int] = mapped_column(Integer, nullable=False)
    results_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    stack_default: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class DailyPlan(Base):
    __tablename__ = "daily_plans"
    __table_args__ = (UniqueConstraint("plan_date", name="uq_daily_plans_plan_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    items: Mapped[list["DailyPlanItem"]] = relationship(
        back_populates="daily_plan",
        cascade="all, delete-orphan",
        order_by="DailyPlanItem.priority_order",
    )


class DailyPlanItem(Base):
    __tablename__ = "daily_plan_items"
    __table_args__ = (
        UniqueConstraint("daily_plan_id", "master_task_id", name="uq_plan_master"),
        UniqueConstraint("daily_plan_id", "learning_task_id", name="uq_plan_learning"),
        CheckConstraint(
            "(master_task_id IS NOT NULL AND learning_task_id IS NULL) OR "
            "(master_task_id IS NULL AND learning_task_id IS NOT NULL)",
            name="ck_plan_item_single_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    daily_plan_id: Mapped[int] = mapped_column(ForeignKey("daily_plans.id"), nullable=False)
    priority_order: Mapped[int] = mapped_column(Integer, default=0)
    master_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("master_tasks.id", ondelete="CASCADE"), nullable=True
    )
    learning_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_tasks.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    daily_plan: Mapped["DailyPlan"] = relationship(back_populates="items")
    master_task: Mapped["MasterTask | None"] = relationship(back_populates="plan_items")
    learning_task: Mapped["LearningTask | None"] = relationship(back_populates="plan_items")

    @property
    def source_task(self) -> "MasterTask | LearningTask | None":
        return self.master_task or self.learning_task

    @property
    def title(self) -> str:
        source = self.source_task
        return source.task if source else ""

    @property
    def is_master(self) -> bool:
        return self.master_task_id is not None

    @property
    def is_learning(self) -> bool:
        return self.learning_task_id is not None

    @property
    def is_completed(self) -> bool:
        source = self.source_task
        return bool(source and source.status == TaskStatus.COMPLETED.value)

    @property
    def date_kind(self) -> str:
        if self.master_task:
            return self.master_task.date_kind
        return DateKind.GOAL.value

    @property
    def target_date(self) -> date | None:
        source = self.source_task
        if not source:
            return None
        return getattr(source, "target_completion_date", None)


class MasterTask(Base):
    __tablename__ = "master_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task: Mapped[str] = mapped_column(String(500), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    target_completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_kind: Mapped[str] = mapped_column(String(20), default=DateKind.GOAL.value)
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.CURRENT.value)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    plan_items: Mapped[list["DailyPlanItem"]] = relationship(back_populates="master_task")


class LearningTask(Base):
    __tablename__ = "learning_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task: Mapped[str] = mapped_column(String(500), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(500), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    target_completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.CURRENT.value)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    plan_items: Mapped[list["DailyPlanItem"]] = relationship(back_populates="learning_task")


class OpportunityLifecycle(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class RemoteStatus(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on_site"


class OpportunitySource(str, Enum):
    DIRECT = "direct"
    REFERRAL = "referral"
    RECRUITER = "recruiter"
    LINKEDIN = "linkedin"
    ROBERT_HALF = "robert_half"
    ADZUNA = "adzuna"


class PipelineStage(str, Enum):
    NEW = "new"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    FOLLOW_UP = "follow_up"
    OFFER = "offer"
    PASSED = "passed"
    CLOSED = "closed"


REMOTE_STATUS_LABELS = {
    RemoteStatus.REMOTE.value: "Remote",
    RemoteStatus.HYBRID.value: "Hybrid",
    RemoteStatus.ON_SITE.value: "On-site",
}

SOURCE_LABELS = {
    OpportunitySource.DIRECT.value: "Direct",
    OpportunitySource.REFERRAL.value: "Referral",
    OpportunitySource.RECRUITER.value: "Recruiter (external)",
    OpportunitySource.LINKEDIN.value: "LinkedIn",
    OpportunitySource.ROBERT_HALF.value: "Robert Half",
    OpportunitySource.ADZUNA.value: "Adzuna",
}

PIPELINE_STAGE_LABELS = {
    PipelineStage.NEW.value: "New",
    PipelineStage.APPLIED.value: "Applied",
    PipelineStage.INTERVIEWING.value: "Interviewing",
    PipelineStage.FOLLOW_UP.value: "Follow Up",
    PipelineStage.OFFER.value: "Offer",
    PipelineStage.PASSED.value: "Passed",
    PipelineStage.CLOSED.value: "Closed",
}


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    posting_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    connections: Mapped[str | None] = mapped_column(String(500), nullable=True)
    referred_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stack: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mission_fit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pipeline_stage: Mapped[str] = mapped_column(String(30), default=PipelineStage.NEW.value)
    lifecycle_status: Mapped[str] = mapped_column(
        String(20), default=OpportunityLifecycle.ACTIVE.value
    )
    highlight_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    @property
    def salary_display(self) -> str:
        if self.salary_min is None and self.salary_max is None:
            return "—"
        currency = self.salary_currency or "USD"

        def fmt(amount: int) -> str:
            if amount >= 1000:
                k = amount / 1000
                return f"${k:g}k" if k == int(k) else f"${k:.0f}k"
            return f"${amount:,}"

        if self.salary_min is not None and self.salary_max is not None:
            return f"{fmt(self.salary_min)}–{fmt(self.salary_max)} {currency}"
        if self.salary_min is not None:
            return f"{fmt(self.salary_min)}+ {currency}"
        return f"Up to {fmt(self.salary_max)} {currency}"  # type: ignore[arg-type]

    @property
    def highlight_class(self) -> str:
        if self.highlight_rank == 1:
            return "highlight-gold"
        if self.highlight_rank == 2:
            return "highlight-silver"
        if self.highlight_rank == 3:
            return "highlight-bronze"
        return ""


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (Index("ix_notes_noteable", "noteable_type", "noteable_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    noteable_type: Mapped[str] = mapped_column(String(50), nullable=False)
    noteable_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
