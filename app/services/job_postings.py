"""Stored job postings: dedupe on ingest, triage filters, and URL capture.

Postings arrive two ways: Adzuna refreshes (`record_adzuna_results`) and the
"Send to Career Search" bookmarklet (`capture_url`), which the user clicks on a
page their own browser has opened. Nothing here fetches third-party pages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.config import POSTING_VISIBLE_DAYS
from app.models import AdzunaSettings, JobPosting, JobPostingSource, Opportunity, OpportunitySource
from app.services.posting_rules import PostingRules, parse_lines  # noqa: F401 - parse_lines re-exported
from app.utils import utcnow

# Query parameters that identify a click, not a posting. Anything else is kept:
# some job boards put the job id in the query string (e.g. `?gh_jid=123`).
_TRACKING_PARAMS = {
    "ref",
    "referrer",
    "source",
    "src",
    "gh_src",
    "lever-source",
    "lever-origin",
    "trk",
    "trackingid",
    "refid",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}

_CAPTURE_CANDIDATE_WINDOW = timedelta(days=7)


def normalize_url(url: str) -> str:
    """Canonical form for dedupe: lowercase scheme/host, no fragment, no
    tracking params, no trailing slash. Returns "" for non-http(s) input."""
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return ""
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def _normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split())


def make_dedupe_key(company: str, title: str) -> str:
    return f"{_normalize_text(company)}|{_normalize_text(title)}"[:800]


# --- Ingest ------------------------------------------------------------------


def _hit_identity(hit: dict) -> dict:
    return {k: v for k, v in hit.items() if k not in ("first_seen_at", "last_seen_at")}


def merge_search_hits(existing: Iterable[dict], new_hits: Iterable[dict], now: datetime) -> list[dict]:
    """Add each new search hit, or bump `last_seen_at` on a matching one.
    Returns a new list: JSON columns don't track in-place mutation."""
    merged = [dict(h) for h in existing]
    stamp = now.isoformat(timespec="seconds")
    for hit in new_hits:
        identity = _hit_identity(hit)
        for current in merged:
            if _hit_identity(current) == identity:
                current["last_seen_at"] = stamp
                break
        else:
            merged.append({**identity, "first_seen_at": stamp, "last_seen_at": stamp})
    return merged


def record_adzuna_results(
    db: Session,
    jobs: Iterable,  # app.services.adzuna.AdzunaJob
    hits_by_id: dict[str, list[dict]],
    now: datetime | None = None,
) -> int:
    """Upsert Adzuna jobs by Adzuna id. Returns how many were new. Caller commits."""
    now = now or utcnow()
    jobs = list(jobs)
    ids = [job.adzuna_id for job in jobs]
    existing: dict[str, JobPosting] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        for posting in (
            db.query(JobPosting)
            .filter(JobPosting.source == JobPostingSource.ADZUNA.value, JobPosting.source_id.in_(chunk))
            .all()
        ):
            existing[posting.source_id] = posting

    new_count = 0
    for job in jobs:
        posting = existing.get(job.adzuna_id)
        if posting is None:
            posting = JobPosting(
                source=JobPostingSource.ADZUNA.value,
                source_id=job.adzuna_id,
                first_seen_at=now,
                search_hits=[],
            )
            db.add(posting)
            existing[job.adzuna_id] = posting
            new_count += 1
        # Fields Adzuna owns are refreshed on every sighting; user-owned
        # state (opened, dismissed, captured URL, opportunity) is never touched.
        posting.title = job.title[:500]
        posting.company = job.company[:255]
        posting.location = job.location[:255] or None
        posting.remote_status = job.inferred_remote_status
        posting.salary_min = job.salary_min
        posting.salary_max = job.salary_max
        posting.salary_currency = "USD"
        posting.salary_is_predicted = job.salary_is_predicted
        posting.contract_time = job.contract_time
        posting.category = job.category
        posting.description = job.description
        posting.source_url = job.redirect_url[:1000] or None
        posting.posted_at = job.posted_at
        posting.dedupe_key = make_dedupe_key(job.company, job.title)
        posting.last_seen_at = now
        posting.search_hits = merge_search_hits(posting.search_hits or [], hits_by_id.get(job.adzuna_id, []), now)
    return new_count


# --- Reading -----------------------------------------------------------------


def _triage_query(db: Session, now: datetime):
    cutoff = now - timedelta(days=POSTING_VISIBLE_DAYS)
    return db.query(JobPosting).filter(
        JobPosting.dismissed_at.is_(None),
        JobPosting.opportunity_id.is_(None),
        JobPosting.last_seen_at >= cutoff,
    )


@dataclass
class VisiblePostings:
    postings: list[JobPosting]
    total: int
    hidden_by_filters: int
    signals: dict[int, list[str]] = field(default_factory=dict)


def _buckets(posting: JobPosting) -> list[str]:
    return [hit.get("bucket", "") for hit in posting.search_hits or []]


def passes_rules(rules: PostingRules, posting: JobPosting) -> bool:
    """Gathered postings must pass the current rules. Postings the user
    captured by hand were chosen deliberately, so they always pass."""
    if posting.source != JobPostingSource.ADZUNA.value:
        return True
    return (
        rules.rejection_reason(
            title=posting.title,
            company=posting.company,
            location=posting.location,
            remote_status=posting.remote_status,
            buckets=_buckets(posting),
        )
        is None
    )


def visible_postings(
    db: Session, settings: AdzunaSettings, limit: int, now: datetime | None = None
) -> VisiblePostings:
    """Postings still awaiting a decision, newest discoveries first. The
    posting rules run again here, so a tightened rule hides postings that
    were stored before it changed."""
    now = now or utcnow()
    rules = PostingRules.from_settings(settings)
    candidates = (
        _triage_query(db, now)
        .order_by(JobPosting.first_seen_at.desc(), JobPosting.posted_at.desc(), JobPosting.id.desc())
        .all()
    )
    kept = [p for p in candidates if passes_rules(rules, p)]
    shown = kept[:limit]
    return VisiblePostings(
        postings=shown,
        total=len(kept),
        hidden_by_filters=len(candidates) - len(kept),
        signals={p.id: rules.signals(p.title, p.description) for p in shown},
    )


# --- Triage actions ----------------------------------------------------------


def dismiss_posting(db: Session, posting: JobPosting) -> None:
    posting.dismissed_at = utcnow()
    db.commit()


def block_company(db: Session, settings: AdzunaSettings, company: str) -> None:
    company = company.strip()
    current = parse_lines(settings.company_blocklist)
    if _normalize_text(company) not in {_normalize_text(c) for c in current}:
        current.append(company)
        settings.company_blocklist = "\n".join(current)
        db.commit()


def mark_opened(db: Session, posting: JobPosting) -> None:
    posting.opened_at = utcnow()
    db.commit()


def link_opportunity(db: Session, posting_id: int, opp: Opportunity) -> None:
    posting = db.get(JobPosting, posting_id)
    if posting is not None:
        posting.opportunity_id = opp.id


# --- Bookmarklet capture -----------------------------------------------------


def capture_candidates(db: Session, now: datetime | None = None, limit: int = 15) -> list[JobPosting]:
    """Postings recently opened from the panel that still lack an employer URL,
    most recently opened first: the bookmarklet's likely targets."""
    now = now or utcnow()
    return (
        db.query(JobPosting)
        .filter(
            JobPosting.opened_at.is_not(None),
            JobPosting.opened_at >= now - _CAPTURE_CANDIDATE_WINDOW,
            JobPosting.posting_url.is_(None),
            JobPosting.dismissed_at.is_(None),
        )
        .order_by(JobPosting.opened_at.desc())
        .limit(limit)
        .all()
    )


def source_for_url(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    if host == "rubyonremote.com" or host.endswith(".rubyonremote.com"):
        return JobPostingSource.RUBY_ON_REMOTE.value
    return JobPostingSource.MANUAL.value


def attach_posting_url(db: Session, posting: JobPosting, url: str) -> None:
    posting.posting_url = normalize_url(url)[:1000]
    posting.posting_url_captured_at = utcnow()
    db.commit()


def create_captured_posting(
    db: Session, url: str, title: str, company: str, location: str = ""
) -> tuple[JobPosting, bool]:
    """Store a hand-captured posting keyed by its normalized URL.
    Returns (posting, created); an existing posting for the URL is returned as-is."""
    normalized = normalize_url(url)[:1000]
    source = source_for_url(normalized)
    existing = (
        db.query(JobPosting)
        .filter(JobPosting.source == source, JobPosting.source_id == normalized)
        .first()
    )
    if existing is not None:
        return existing, False
    now = utcnow()
    posting = JobPosting(
        source=source,
        source_id=normalized,
        title=title.strip()[:500] or "Untitled",
        company=company.strip()[:255] or "Unknown",
        location=location.strip()[:255] or None,
        source_url=normalized,
        posting_url=normalized,
        posting_url_captured_at=now,
        dedupe_key=make_dedupe_key(company, title),
        search_hits=[],
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(posting)
    db.commit()
    db.refresh(posting)
    return posting, True


# --- Opportunity prefill -----------------------------------------------------

_SOURCE_TO_OPPORTUNITY_SOURCE = {
    JobPostingSource.ADZUNA.value: OpportunitySource.ADZUNA.value,
    JobPostingSource.RUBY_ON_REMOTE.value: OpportunitySource.RUBY_ON_REMOTE.value,
    JobPostingSource.MANUAL.value: OpportunitySource.DIRECT.value,
}


def build_notes_blob(posting: JobPosting) -> str:
    lines = [
        f"Imported from {posting.source} (id: {posting.source_id})",
        f"Title: {posting.title}",
        f"Company: {posting.company}",
        f"Location: {posting.location or ''}",
        f"Posted: {posting.posted_at.date().isoformat() if posting.posted_at else ''}",
        f"Source URL: {posting.source_url or ''}",
    ]
    if posting.posting_url:
        lines.append(f"Employer URL: {posting.posting_url}")
    if posting.salary_is_predicted:
        lines.append(f"Salary: {posting.salary_display} (Adzuna estimate, not stated in the posting)")
    buckets = sorted({hit.get("bucket", "") for hit in posting.search_hits or []} - {""})
    if buckets:
        lines.append(f"Search buckets: {', '.join(buckets)}")
    if posting.description:
        lines += ["", "Description snippet:", posting.description]
    return "\n".join(lines)


def map_to_opportunity_prefill(posting: JobPosting, settings: AdzunaSettings) -> dict:
    # A predicted salary isn't the employer's number, so it isn't copied into
    # the opportunity's salary fields; it stays visible in the notes.
    stated = not posting.salary_is_predicted
    return {
        "company": posting.company,
        "posting_url": posting.posting_url or posting.source_url or "",
        "location_text": posting.location or "",
        "remote_status": posting.remote_status or "",
        "source": _SOURCE_TO_OPPORTUNITY_SOURCE.get(posting.source, OpportunitySource.DIRECT.value),
        "stack": settings.stack_default,
        "salary_min": (posting.salary_min or "") if stated else "",
        "salary_max": (posting.salary_max or "") if stated else "",
        "salary_currency": "USD",
        "pipeline_stage": "new",
        "notes_text": build_notes_blob(posting),
    }
