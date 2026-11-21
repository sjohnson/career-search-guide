"""Stored job postings: triage actions on the Suggested jobs panel and the
"Send to Career Search" bookmarklet capture flow."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import JobPosting, REMOTE_STATUS_LABELS
from app.services import job_postings
from app.services.adzuna import get_adzuna_feed
from app.services.adzuna_settings import get_or_create_adzuna_settings
from app.templating import templates

router = APIRouter(prefix="/postings", tags=["postings"])


def bookmarklet_href(request: Request) -> str:
    capture = f"{str(request.base_url).rstrip('/')}/postings/capture"
    return (
        "javascript:(()=>{window.open('" + capture + "?url='+encodeURIComponent(location.href)"
        "+'&title='+encodeURIComponent(document.title),'_blank');})();"
    )


def panel_context(request: Request, db: Session, refresh: bool = False) -> dict:
    settings = get_or_create_adzuna_settings(db)
    return {
        "adzuna": get_adzuna_feed(db, settings, refresh=refresh),
        "adzuna_remote_labels": REMOTE_STATUS_LABELS,
        "bookmarklet_href": bookmarklet_href(request),
    }


def _panel_response(request: Request, db: Session):
    return templates.TemplateResponse(
        request, "opportunities/partials/adzuna_panel.html", panel_context(request, db)
    )


def _not_found():
    return HTMLResponse("<p class='error'>Posting not found.</p>", status_code=404)


@router.get("/capture", response_class=HTMLResponse)
def capture_form(request: Request, url: str = "", title: str = "", db: Session = Depends(get_db)):
    candidates = job_postings.capture_candidates(db)
    return templates.TemplateResponse(
        request,
        "postings/capture.html",
        {
            "url": url,
            "page_title": title,
            "valid_url": bool(job_postings.normalize_url(url)),
            "candidates": candidates,
            "source_for_url": job_postings.source_for_url(url) if url else "",
        },
    )


@router.post("/capture", response_class=HTMLResponse)
def capture_submit(
    request: Request,
    url: str = Form(...),
    target: str = Form(""),
    title: str = Form(""),
    company: str = Form(""),
    location: str = Form(""),
    db: Session = Depends(get_db),
):
    if not job_postings.normalize_url(url):
        return HTMLResponse("<p class='error'>That doesn't look like a web page URL.</p>", status_code=400)

    if target and target != "new":
        posting = db.get(JobPosting, int(target)) if target.isdigit() else None
        if posting is None:
            return _not_found()
        job_postings.attach_posting_url(db, posting, url)
        outcome = "attached"
    else:
        if not title.strip() or not company.strip():
            return HTMLResponse("<p class='error'>Title and company are required.</p>", status_code=400)
        posting, created = job_postings.create_captured_posting(db, url, title, company, location)
        outcome = "created" if created else "duplicate"

    return templates.TemplateResponse(
        request, "postings/captured.html", {"posting": posting, "outcome": outcome}
    )


@router.get("/{posting_id}/open")
def open_posting(posting_id: int, db: Session = Depends(get_db)):
    """Record that the user opened a posting, then send them to it. The
    bookmarklet uses `opened_at` to guess which posting a captured URL is for."""
    posting = db.get(JobPosting, posting_id)
    if posting is None or not posting.source_url:
        return RedirectResponse(url="/opportunities", status_code=303)
    job_postings.mark_opened(db, posting)
    return RedirectResponse(url=posting.source_url, status_code=303)


@router.post("/{posting_id}/dismiss", response_class=HTMLResponse)
def dismiss(request: Request, posting_id: int, db: Session = Depends(get_db)):
    posting = db.get(JobPosting, posting_id)
    if posting is None:
        return _not_found()
    job_postings.dismiss_posting(db, posting)
    return _panel_response(request, db)


@router.post("/{posting_id}/block-company", response_class=HTMLResponse)
def block_company(request: Request, posting_id: int, db: Session = Depends(get_db)):
    posting = db.get(JobPosting, posting_id)
    if posting is None:
        return _not_found()
    job_postings.block_company(db, get_or_create_adzuna_settings(db), posting.company)
    return _panel_response(request, db)
