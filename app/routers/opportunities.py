from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    NoteableType,
    Opportunity,
    OpportunityLifecycle,
    OpportunitySource,
    PIPELINE_STAGE_LABELS,
    PipelineStage,
    REMOTE_STATUS_LABELS,
    RemoteStatus,
    SOURCE_LABELS,
)
from app.services.adzuna import bust_adzuna_cache, get_adzuna_jobs, get_cached_job, map_to_opportunity_prefill
from app.services.adzuna_settings import get_or_create_adzuna_settings
from app.services.daily_plan import get_or_create_settings, get_primary_note_body, set_primary_note
from app.services.opportunities import (
    OPPORTUNITIES_PER_PAGE,
    applied_days_ago,
    archive_opportunity,
    assign_highlight_rank,
    clear_highlight_rank,
    normalize_pipeline_stage,
    normalize_remote_status,
    normalize_source,
    paginate_active,
    sort_opportunities,
    split_opportunities,
)

router = APIRouter(prefix="/opportunities", tags=["opportunities"])
templates = Jinja2Templates(directory="app/templates")

SORTABLE = [
    "company",
    "remote",
    "source",
    "stack",
    "salary",
    "pipeline",
    "connections",
    "referred_by",
    "location",
]


def _pagination_context(page: int, total: int, total_pages: int) -> dict:
    return {
        "page": page,
        "total": total,
        "total_pages": total_pages,
        "per_page": OPPORTUNITIES_PER_PAGE,
    }


def _rows_context(db: Session, sort_by: str, sort_dir: str, page: int = 1) -> dict:
    query = db.query(Opportunity)
    query = sort_opportunities(query, sort_by, sort_dir)
    all_opps = query.all()
    active_all, archived = split_opportunities(all_opps)
    active_page, total, total_pages, page = paginate_active(active_all, page)
    notes = {o.id: get_primary_note_body(db, NoteableType.OPPORTUNITY.value, o.id) for o in all_opps}
    applied_ages = {o.id: applied_days_ago(o.applied_at) for o in all_opps}
    return {
        "active_opportunities": active_page,
        "active_total": total,
        "archived_opportunities": archived,
        "notes": notes,
        "applied_ages": applied_ages,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "remote_statuses": RemoteStatus,
        "sources": OpportunitySource,
        "pipeline_stages": PipelineStage,
        "remote_labels": REMOTE_STATUS_LABELS,
        "source_labels": SOURCE_LABELS,
        "pipeline_labels": PIPELINE_STAGE_LABELS,
        "archived": False,
        **_pagination_context(page, total, total_pages),
    }


def _list_context(request: Request, db: Session, sort_by: str, sort_dir: str, page: int = 1) -> dict:
    settings = get_or_create_settings(db)
    adzuna_settings = get_or_create_adzuna_settings(db)
    ctx = _rows_context(db, sort_by, sort_dir, page)
    ctx["mission"] = settings.mission_statement
    ctx["sortable_columns"] = SORTABLE
    adzuna = get_adzuna_jobs(adzuna_settings, refresh=False)
    ctx["adzuna"] = adzuna
    ctx["adzuna_remote_labels"] = REMOTE_STATUS_LABELS
    return ctx


def _active_rows_response(request: Request, db: Session, sort_by: str, sort_dir: str, page: int = 1):
    sort_by = sort_by if sort_by in SORTABLE else "company"
    sort_dir = sort_dir if sort_dir in ("asc", "desc") else "asc"
    return templates.TemplateResponse(
        request,
        "opportunities/partials/active_body_swap.html",
        _rows_context(db, sort_by, sort_dir, page),
    )


@router.get("", response_class=HTMLResponse)
def list_opportunities(
    request: Request,
    sort: str = "company",
    dir: str = "asc",
    page: int = 1,
    db: Session = Depends(get_db),
):
    sort_by = sort if sort in SORTABLE else "company"
    sort_dir = dir if dir in ("asc", "desc") else "asc"
    page = max(1, page)
    return templates.TemplateResponse(
        request,
        "opportunities/list.html",
        _list_context(request, db, sort_by, sort_dir, page),
    )


@router.get("/new", response_class=HTMLResponse)
def new_opportunity(request: Request, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    return templates.TemplateResponse(
        request,
        "opportunities/form.html",
        {
            "opportunity": None,
            "notes_text": "",
            "mission": settings.mission_statement,
            "remote_statuses": RemoteStatus,
            "sources": OpportunitySource,
            "pipeline_stages": PipelineStage,
            "remote_labels": REMOTE_STATUS_LABELS,
            "source_labels": SOURCE_LABELS,
            "pipeline_labels": PIPELINE_STAGE_LABELS,
        },
    )


@router.post("")
def create_opportunity(
    company: str = Form(...),
    posting_url: str = Form(""),
    connections: str = Form(""),
    referred_by: str = Form(""),
    location_text: str = Form(""),
    remote_status: str = Form(""),
    source: str = Form(""),
    stack: str = Form(""),
    mission_fit: str = Form(""),
    salary_min: str = Form(""),
    salary_max: str = Form(""),
    salary_currency: str = Form(""),
    pipeline_stage: str = Form(PipelineStage.NEW.value),
    applied_at: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    opp = Opportunity(
        company=company.strip(),
        posting_url=posting_url.strip() or None,
        connections=connections.strip() or None,
        referred_by=referred_by.strip() or None,
        location_text=location_text.strip() or None,
        remote_status=normalize_remote_status(remote_status),
        source=normalize_source(source),
        stack=stack.strip() or None,
        mission_fit=mission_fit.strip() or None,
        salary_min=int(salary_min) if salary_min.isdigit() else None,
        salary_max=int(salary_max) if salary_max.isdigit() else None,
        salary_currency=salary_currency.strip() or None,
        pipeline_stage=normalize_pipeline_stage(pipeline_stage),
        lifecycle_status=OpportunityLifecycle.ACTIVE.value,
    )
    if applied_at:
        try:
            opp.applied_at = date.fromisoformat(applied_at)
        except ValueError:
            pass
    db.add(opp)
    db.flush()
    set_primary_note(db, NoteableType.OPPORTUNITY.value, opp.id, notes)
    db.commit()
    return RedirectResponse(url="/opportunities", status_code=303)


@router.post("/adzuna/refresh", response_class=HTMLResponse)
def refresh_adzuna_jobs(request: Request, db: Session = Depends(get_db)):
    adzuna_settings = get_or_create_adzuna_settings(db)
    adzuna = get_adzuna_jobs(adzuna_settings, refresh=True)
    return templates.TemplateResponse(
        request,
        "opportunities/partials/adzuna_panel.html",
        {
            "adzuna": adzuna,
            "adzuna_remote_labels": REMOTE_STATUS_LABELS,
        },
    )


@router.get("/adzuna/settings-form", response_class=HTMLResponse)
def adzuna_settings_form(request: Request, db: Session = Depends(get_db)):
    adzuna_settings = get_or_create_adzuna_settings(db)
    return templates.TemplateResponse(
        request,
        "opportunities/partials/adzuna_settings_modal.html",
        {"adzuna_settings": adzuna_settings},
    )


@router.post("/adzuna/settings", response_class=HTMLResponse)
def update_adzuna_settings(
    request: Request,
    search_what: str = Form(...),
    search_what_and: str = Form(...),
    search_what_or: str = Form(...),
    salary_min: str = Form(...),
    slc_where: str = Form(...),
    slc_distance: str = Form(...),
    va_where: str = Form(...),
    va_distance: str = Form(...),
    charlotte_where: str = Form(...),
    charlotte_distance: str = Form(...),
    results_limit: str = Form(...),
    stack_default: str = Form(...),
    db: Session = Depends(get_db),
):
    adzuna_settings = get_or_create_adzuna_settings(db)
    adzuna_settings.search_what = search_what.strip()
    adzuna_settings.search_what_and = search_what_and.strip()
    adzuna_settings.search_what_or = search_what_or.strip()
    adzuna_settings.salary_min = int(salary_min) if salary_min.isdigit() else adzuna_settings.salary_min
    adzuna_settings.slc_where = slc_where.strip()
    adzuna_settings.slc_distance = int(slc_distance) if slc_distance.isdigit() else adzuna_settings.slc_distance
    adzuna_settings.va_where = va_where.strip()
    adzuna_settings.va_distance = int(va_distance) if va_distance.isdigit() else adzuna_settings.va_distance
    adzuna_settings.charlotte_where = charlotte_where.strip()
    adzuna_settings.charlotte_distance = (
        int(charlotte_distance) if charlotte_distance.isdigit() else adzuna_settings.charlotte_distance
    )
    adzuna_settings.results_limit = int(results_limit) if results_limit.isdigit() else adzuna_settings.results_limit
    adzuna_settings.stack_default = stack_default.strip()
    db.commit()
    db.refresh(adzuna_settings)
    bust_adzuna_cache()
    adzuna = get_adzuna_jobs(adzuna_settings, refresh=True)
    return templates.TemplateResponse(
        request,
        "opportunities/partials/adzuna_settings_saved.html",
        {
            "adzuna": adzuna,
            "adzuna_remote_labels": REMOTE_STATUS_LABELS,
        },
    )


@router.get("/adzuna/{adzuna_id}/add-form", response_class=HTMLResponse)
def adzuna_add_form(request: Request, adzuna_id: str, db: Session = Depends(get_db)):
    adzuna_settings = get_or_create_adzuna_settings(db)
    job = get_cached_job(adzuna_id)
    if not job:
        get_adzuna_jobs(adzuna_settings, refresh=False)
        job = get_cached_job(adzuna_id)
    if not job:
        return HTMLResponse("<p class='error'>Job not found in cache. Try refreshing jobs.</p>", status_code=404)
    prefill = map_to_opportunity_prefill(job, adzuna_settings)
    settings = get_or_create_settings(db)
    return templates.TemplateResponse(
        request,
        "opportunities/partials/opportunity_modal.html",
        {
            "prefill": prefill,
            "job": job,
            "mission": settings.mission_statement,
            "remote_statuses": RemoteStatus,
            "sources": OpportunitySource,
            "pipeline_stages": PipelineStage,
            "remote_labels": REMOTE_STATUS_LABELS,
            "source_labels": SOURCE_LABELS,
            "pipeline_labels": PIPELINE_STAGE_LABELS,
        },
    )


@router.get("/{opp_id}/edit", response_class=HTMLResponse)
def edit_opportunity(request: Request, opp_id: int, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    opp = db.get(Opportunity, opp_id)
    if not opp:
        return RedirectResponse(url="/opportunities", status_code=303)
    notes_text = get_primary_note_body(db, NoteableType.OPPORTUNITY.value, opp.id)
    return templates.TemplateResponse(
        request,
        "opportunities/form.html",
        {
            "opportunity": opp,
            "notes_text": notes_text,
            "mission": settings.mission_statement,
            "remote_statuses": RemoteStatus,
            "sources": OpportunitySource,
            "pipeline_stages": PipelineStage,
            "remote_labels": REMOTE_STATUS_LABELS,
            "source_labels": SOURCE_LABELS,
            "pipeline_labels": PIPELINE_STAGE_LABELS,
        },
    )


@router.post("/{opp_id}")
def update_opportunity(
    opp_id: int,
    company: str = Form(...),
    posting_url: str = Form(""),
    connections: str = Form(""),
    referred_by: str = Form(""),
    location_text: str = Form(""),
    remote_status: str = Form(""),
    source: str = Form(""),
    stack: str = Form(""),
    mission_fit: str = Form(""),
    salary_min: str = Form(""),
    salary_max: str = Form(""),
    salary_currency: str = Form(""),
    pipeline_stage: str = Form(PipelineStage.NEW.value),
    applied_at: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        return RedirectResponse(url="/opportunities", status_code=303)
    opp.company = company.strip()
    opp.posting_url = posting_url.strip() or None
    opp.connections = connections.strip() or None
    opp.referred_by = referred_by.strip() or None
    opp.location_text = location_text.strip() or None
    opp.remote_status = normalize_remote_status(remote_status)
    opp.source = normalize_source(source)
    opp.stack = stack.strip() or None
    opp.mission_fit = mission_fit.strip() or None
    opp.salary_min = int(salary_min) if salary_min.isdigit() else None
    opp.salary_max = int(salary_max) if salary_max.isdigit() else None
    opp.salary_currency = salary_currency.strip() or None
    opp.pipeline_stage = normalize_pipeline_stage(pipeline_stage)
    if applied_at:
        try:
            opp.applied_at = date.fromisoformat(applied_at)
        except ValueError:
            opp.applied_at = None
    else:
        opp.applied_at = None
    set_primary_note(db, NoteableType.OPPORTUNITY.value, opp.id, notes)
    db.commit()
    return RedirectResponse(url="/opportunities", status_code=303)


@router.post("/{opp_id}/archive")
def archive_opp(opp_id: int, db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if opp:
        archive_opportunity(db, opp)
    return RedirectResponse(url="/opportunities", status_code=303)


@router.post("/{opp_id}/delete")
def delete_opportunity(opp_id: int, db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if opp:
        db.delete(opp)
        db.commit()
    return RedirectResponse(url="/opportunities", status_code=303)


@router.post("/{opp_id}/highlight/{rank}", response_class=HTMLResponse)
def set_highlight(
    request: Request,
    opp_id: int,
    rank: int,
    sort: str = "company",
    dir: str = "asc",
    page: int = 1,
    db: Session = Depends(get_db),
):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        return HTMLResponse("", status_code=404)
    assign_highlight_rank(db, opp, rank)
    return _active_rows_response(request, db, sort, dir, page)


@router.post("/{opp_id}/highlight/clear", response_class=HTMLResponse)
def clear_highlight(
    request: Request,
    opp_id: int,
    sort: str = "company",
    dir: str = "asc",
    page: int = 1,
    db: Session = Depends(get_db),
):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        return HTMLResponse("", status_code=404)
    clear_highlight_rank(db, opp)
    return _active_rows_response(request, db, sort, dir, page)


@router.patch("/{opp_id}/remote-status", response_class=HTMLResponse)
def patch_remote_status(
    request: Request,
    opp_id: int,
    remote_status: str = Form(""),
    db: Session = Depends(get_db),
):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        return HTMLResponse("", status_code=404)
    opp.remote_status = normalize_remote_status(remote_status)
    db.commit()
    return templates.TemplateResponse(
        request,
        "opportunities/partials/remote_status_cell.html",
        {"opp": opp, "remote_labels": REMOTE_STATUS_LABELS, "remote_statuses": RemoteStatus},
    )


@router.patch("/{opp_id}/source", response_class=HTMLResponse)
def patch_source(
    request: Request,
    opp_id: int,
    source: str = Form(""),
    db: Session = Depends(get_db),
):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        return HTMLResponse("", status_code=404)
    opp.source = normalize_source(source)
    db.commit()
    return templates.TemplateResponse(
        request,
        "opportunities/partials/source_cell.html",
        {"opp": opp, "source_labels": SOURCE_LABELS, "sources": OpportunitySource},
    )


@router.patch("/{opp_id}/pipeline-stage", response_class=HTMLResponse)
def patch_pipeline_stage(
    request: Request,
    opp_id: int,
    pipeline_stage: str = Form(PipelineStage.NEW.value),
    db: Session = Depends(get_db),
):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        return HTMLResponse("", status_code=404)
    opp.pipeline_stage = normalize_pipeline_stage(pipeline_stage)
    db.commit()
    return templates.TemplateResponse(
        request,
        "opportunities/partials/pipeline_cell.html",
        {"opp": opp, "pipeline_labels": PIPELINE_STAGE_LABELS, "pipeline_stages": PipelineStage},
    )


@router.patch("/{opp_id}/stack", response_class=HTMLResponse)
def patch_stack(
    request: Request,
    opp_id: int,
    stack: str = Form(""),
    db: Session = Depends(get_db),
):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        return HTMLResponse("", status_code=404)
    opp.stack = stack.strip() or None
    db.commit()
    return templates.TemplateResponse(
        request,
        "opportunities/partials/stack_cell.html",
        {"opp": opp},
    )


@router.patch("/{opp_id}/mission-fit", response_class=HTMLResponse)
def patch_mission_fit(
    request: Request,
    opp_id: int,
    mission_fit: str = Form(""),
    db: Session = Depends(get_db),
):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        return HTMLResponse("", status_code=404)
    opp.mission_fit = mission_fit.strip() or None
    db.commit()
    return templates.TemplateResponse(
        request,
        "opportunities/partials/mission_fit_cell.html",
        {"opp": opp},
    )
