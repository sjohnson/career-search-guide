from datetime import date, datetime

from sqlalchemy.orm import Query, Session

from app.models import Opportunity, OpportunityLifecycle, PipelineStage

SORTABLE_COLUMNS = {
    "company": Opportunity.company,
    "remote": Opportunity.remote_status,
    "source": Opportunity.source,
    "stack": Opportunity.stack,
    "salary": Opportunity.salary_max,
    "pipeline": Opportunity.pipeline_stage,
    "connections": Opportunity.connections,
    "referred_by": Opportunity.referred_by,
    "location": Opportunity.location_text,
    "applied": Opportunity.applied_at,
}


def format_salary(min_val: int | None, max_val: int | None, currency: str | None) -> str:
    opp = Opportunity(
        salary_min=min_val,
        salary_max=max_val,
        salary_currency=currency,
        company="",
    )
    return opp.salary_display


def applied_days_ago(applied_at: date | None) -> int | None:
    if not applied_at:
        return None
    return (date.today() - applied_at).days


OPPORTUNITIES_PER_PAGE = 7

FOLLOW_UP_STAGES = frozenset(
    {
        PipelineStage.APPLIED.value,
        PipelineStage.INTERVIEWING.value,
        PipelineStage.FOLLOW_UP.value,
        PipelineStage.OFFER.value,
    }
)

ARCHIVE_ON_STAGES = frozenset(
    {
        PipelineStage.PASSED.value,
        PipelineStage.CLOSED.value,
    }
)


def touch_opportunity(opp: Opportunity) -> None:
    opp.updated_at = datetime.utcnow()


def section_for_stage(stage: str) -> str:
    if stage == PipelineStage.NEW.value:
        return "new"
    if stage in FOLLOW_UP_STAGES:
        return "follow_up"
    return "archived"


def sort_opportunities(
    query: Query,
    sort_by: str = "company",
    sort_dir: str = "asc",
) -> Query:
    column = SORTABLE_COLUMNS.get(sort_by, Opportunity.company)
    descending = sort_dir == "desc"
    rank_order = Opportunity.highlight_rank.asc().nulls_last()
    if descending:
        return query.order_by(rank_order, column.desc().nulls_last(), Opportunity.id.desc())
    return query.order_by(rank_order, column.asc().nulls_last(), Opportunity.id.asc())


def paginate_active(
    active: list[Opportunity],
    page: int,
    per_page: int = OPPORTUNITIES_PER_PAGE,
) -> tuple[list[Opportunity], int, int, int]:
    total = len(active)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return active[start : start + per_page], total, total_pages, page


def assign_highlight_rank(db: Session, opp: Opportunity, rank: int) -> None:
    if rank not in (1, 2, 3):
        return
    if opp.lifecycle_status != OpportunityLifecycle.ACTIVE.value:
        return
    if opp.highlight_rank == rank:
        return

    opp.highlight_rank = None
    db.flush()

    def holder(r: int) -> Opportunity | None:
        return (
            db.query(Opportunity)
            .filter(
                Opportunity.lifecycle_status == OpportunityLifecycle.ACTIVE.value,
                Opportunity.highlight_rank == r,
            )
            .first()
        )

    if rank == 1:
        gold, silver, bronze = holder(1), holder(2), holder(3)
        if bronze:
            bronze.highlight_rank = None
        if silver:
            silver.highlight_rank = 3
        if gold:
            gold.highlight_rank = 2
        opp.highlight_rank = 1
    elif rank == 2:
        silver, bronze = holder(2), holder(3)
        if bronze:
            bronze.highlight_rank = None
        if silver:
            silver.highlight_rank = 3
        opp.highlight_rank = 2
    else:
        bronze = holder(3)
        if bronze:
            bronze.highlight_rank = None
        opp.highlight_rank = 3

    db.commit()


def clear_highlight_rank(db: Session, opp: Opportunity) -> None:
    opp.highlight_rank = None
    db.commit()


def archive_opportunity(db: Session, opp: Opportunity) -> None:
    opp.lifecycle_status = OpportunityLifecycle.ARCHIVED.value
    opp.highlight_rank = None
    db.commit()


def split_opportunities(
    opps: list[Opportunity],
) -> tuple[list[Opportunity], list[Opportunity]]:
    active = [o for o in opps if o.lifecycle_status == OpportunityLifecycle.ACTIVE.value]
    archived = [o for o in opps if o.lifecycle_status == OpportunityLifecycle.ARCHIVED.value]
    return active, archived


def split_active_opportunities(
    active: list[Opportunity],
) -> tuple[list[Opportunity], list[Opportunity]]:
    new_opps = [o for o in active if o.pipeline_stage == PipelineStage.NEW.value]
    follow_up = [o for o in active if o.pipeline_stage in FOLLOW_UP_STAGES]
    return new_opps, follow_up


def sort_follow_up(opps: list[Opportunity]) -> list[Opportunity]:
    return sorted(opps, key=lambda o: (o.updated_at or o.created_at, o.id))


def apply_pipeline_stage_change(db: Session, opp: Opportunity, new_stage: str) -> str:
    """Update pipeline stage; auto-archive passed/closed. Returns new section name."""
    old_section = section_for_stage(opp.pipeline_stage)
    if new_stage in ARCHIVE_ON_STAGES:
        opp.pipeline_stage = new_stage
        touch_opportunity(opp)
        archive_opportunity(db, opp)
        return "archived"
    opp.pipeline_stage = new_stage
    if old_section == "new" and new_stage != PipelineStage.NEW.value:
        opp.highlight_rank = None
    touch_opportunity(opp)
    db.commit()
    return section_for_stage(new_stage)


def normalize_remote_status(value: str | None) -> str | None:
    from app.models import RemoteStatus

    if not value:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "remote": RemoteStatus.REMOTE.value,
        "hybrid": RemoteStatus.HYBRID.value,
        "on_site": RemoteStatus.ON_SITE.value,
        "onsite": RemoteStatus.ON_SITE.value,
        "on-site": RemoteStatus.ON_SITE.value,
    }
    return mapping.get(normalized)


def normalize_source(value: str | None) -> str | None:
    from app.models import OpportunitySource

    if not value:
        return None
    normalized = value.strip().lower()
    mapping = {
        "direct": OpportunitySource.DIRECT.value,
        "referral": OpportunitySource.REFERRAL.value,
        "recruiter": OpportunitySource.RECRUITER.value,
        "recruiter (external)": OpportunitySource.RECRUITER.value,
        "external": OpportunitySource.RECRUITER.value,
        "linkedin": OpportunitySource.LINKEDIN.value,
        "robert half": OpportunitySource.ROBERT_HALF.value,
        "robert_half": OpportunitySource.ROBERT_HALF.value,
        "adzuna": OpportunitySource.ADZUNA.value,
    }
    return mapping.get(normalized)


def normalize_pipeline_stage(value: str | None) -> str:
    from app.models import PipelineStage

    stage = _normalize_pipeline_stage_value(value)
    return stage or PipelineStage.NEW.value


def _normalize_pipeline_stage_value(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    mapping = {
        "new": PipelineStage.NEW.value,
        "applied": PipelineStage.APPLIED.value,
        "interviewing": PipelineStage.INTERVIEWING.value,
        "follow_up": PipelineStage.FOLLOW_UP.value,
        "followup": PipelineStage.FOLLOW_UP.value,
        "offer": PipelineStage.OFFER.value,
        "passed": PipelineStage.PASSED.value,
        "closed": PipelineStage.CLOSED.value,
    }
    return mapping.get(normalized)
