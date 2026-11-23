"""Adzuna search: fetch, filter, store, and enforce the API quota.

Results are stored in `job_postings` (see app.services.job_postings) and every
refresh is logged in `adzuna_fetches`. The log replaces the old in-memory
cache: a page load refreshes only when the latest fetch is older than
ADZUNA_CACHE_TTL_SECONDS or the settings changed, and the summed `api_calls`
drive the quota guard.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import config
from app.models import AdzunaFetch, AdzunaSettings, JobPosting, RemoteStatus
from app.services import job_postings
from app.utils import utcnow

ADZUNA_SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"


@dataclass
class AdzunaJob:
    adzuna_id: str
    title: str
    company: str
    location: str
    salary_min: int | None
    salary_max: int | None
    salary_is_predicted: bool
    contract_time: str | None
    category: str | None
    redirect_url: str
    description: str
    posted_at: datetime | None
    inferred_remote_status: str | None


@dataclass
class QuotaWindow:
    name: str
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


@dataclass
class AdzunaFeed:
    postings: list[JobPosting] = field(default_factory=list)
    total: int = 0
    hidden_by_filters: int = 0
    fetched_at: datetime | None = None
    error: str | None = None
    query_counts: dict = field(default_factory=dict)
    new_since: datetime | None = None
    quota: list[QuotaWindow] = field(default_factory=list)

    @property
    def thin_results(self) -> bool:
        return self.total < 3


def infer_remote_status(title: str, description: str, location: str) -> str | None:
    text = f"{title} {description} {location}".lower()
    if "hybrid" in text:
        return RemoteStatus.HYBRID.value
    if any(k in text for k in ("remote", "work from home", "wfh", "telecommute")):
        return RemoteStatus.REMOTE.value
    if any(k in text for k in ("on-site", "onsite", "on site", "in office", "in-office")):
        return RemoteStatus.ON_SITE.value
    if location and location.lower() not in ("", "us", "usa", "united states"):
        return RemoteStatus.ON_SITE.value
    return None


def _is_dc_area(location: str) -> bool:
    loc = location.lower()
    return "washington" in loc or "district of columbia" in loc or ", dc" in loc


def _is_vague_location(location: str) -> bool:
    loc = location.strip().lower()
    return loc in ("", "us", "usa", "united states")


def _is_slc_metro(location: str) -> bool:
    loc = location.lower()
    markers = (
        "salt lake",
        "slc",
        "provo",
        "lehi",
        "draper",
        "sandy",
        "murray",
        "orem",
        "west valley",
        "south jordan",
        "herriman",
        "american fork",
        "pleasant grove",
        "layton",
        "bountiful",
        "utah",
    )
    return any(m in loc for m in markers)


def _is_virginia_allowed(location: str) -> bool:
    if _is_dc_area(location):
        return False
    loc = location.lower()
    return "virginia" in loc or ", va" in loc or loc.endswith(" va") or " va," in loc


def _is_charlotte_metro(location: str) -> bool:
    loc = location.lower()
    markers = (
        "charlotte",
        "fort mill",
        "rock hill",
        "concord",
        "gastonia",
        "huntersville",
        "matthews",
        "pineville",
        "indian trail",
        "mooresville",
    )
    return any(m in loc for m in markers)


def _location_in_allowed_region(location: str) -> bool:
    return _is_slc_metro(location) or _is_virginia_allowed(location) or _is_charlotte_metro(location)


def passes_relevance_filter(job: AdzunaJob) -> bool:
    status = job.inferred_remote_status
    if status in (RemoteStatus.REMOTE.value, RemoteStatus.HYBRID.value):
        return True
    if _is_vague_location(job.location):
        return True
    if status == RemoteStatus.ON_SITE.value:
        return _location_in_allowed_region(job.location)
    return True



# --- Quota -------------------------------------------------------------------


class QuotaExhausted(Exception):
    pass


def quota_usage(db: Session, now: datetime | None = None) -> list[QuotaWindow]:
    now = now or utcnow()
    windows = []
    for name, seconds, limit in config.ADZUNA_QUOTA_WINDOWS:
        used = (
            db.query(func.coalesce(func.sum(AdzunaFetch.api_calls), 0))
            .filter(AdzunaFetch.fetched_at >= now - timedelta(seconds=seconds))
            .scalar()
        )
        windows.append(QuotaWindow(name=name, used=int(used), limit=limit))
    return windows


class _CallBudget:
    """Counts API calls and refuses one that would exceed any quota window."""

    def __init__(self, remaining: int):
        self.remaining = remaining
        self.calls = 0

    def spend(self) -> None:
        if self.calls >= self.remaining:
            raise QuotaExhausted("Adzuna API quota reached; stopped before exceeding it.")
        self.calls += 1


# --- Fetching ----------------------------------------------------------------


def settings_fingerprint(settings: AdzunaSettings) -> str:
    """Hash of everything sent to Adzuna. In-app filters (title exclude,
    company blocklist, results shown) are left out on purpose: editing them
    re-reads stored postings without spending API calls."""
    searched = {name: _search_params(settings, extra) for name, extra in _buckets(settings).items()}
    searched["max_pages"] = settings.max_pages
    return hashlib.sha256(json.dumps(searched, sort_keys=True).encode()).hexdigest()[:32]


def _parse_created(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _to_int(value) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _parse_job(raw: dict, bucket: str) -> AdzunaJob | None:
    adzuna_id = str(raw.get("id", ""))
    if not adzuna_id:
        return None
    location = (raw.get("location") or {}).get("display_name") or ""
    if bucket == "virginia" and _is_dc_area(location):
        return None
    title = raw.get("title") or "Untitled"
    description = raw.get("description") or ""
    return AdzunaJob(
        adzuna_id=adzuna_id,
        title=title,
        company=(raw.get("company") or {}).get("display_name") or "Unknown",
        location=location,
        salary_min=_to_int(raw.get("salary_min")),
        salary_max=_to_int(raw.get("salary_max")),
        salary_is_predicted=str(raw.get("salary_is_predicted", "0")) == "1",
        contract_time=raw.get("contract_time"),
        category=(raw.get("category") or {}).get("label"),
        redirect_url=raw.get("redirect_url") or "",
        description=description,
        posted_at=_parse_created(raw.get("created")),
        inferred_remote_status=infer_remote_status(title, description, location),
    )


def _buckets(settings: AdzunaSettings) -> dict[str, dict]:
    return {
        "remote": {"what_or": settings.search_what_or},
        "slc": {"where": settings.slc_where, "distance": settings.slc_distance},
        "virginia": {"where": settings.va_where, "distance": settings.va_distance},
        "charlotte": {"where": settings.charlotte_where, "distance": settings.charlotte_distance},
    }


def _search_params(settings: AdzunaSettings, extra: dict) -> dict:
    """Search terms shared by every bucket plus the bucket's own. Blank
    optional terms are omitted rather than sent empty."""
    params = {
        "what": settings.search_what,
        "what_and": settings.search_what_and,
        "what_exclude": settings.search_what_exclude,
        "title_only": settings.search_title_only,
        "salary_min": settings.salary_min,
        **extra,
    }
    return {k: v for k, v in params.items() if v not in ("", None)}


@dataclass
class _FetchResult:
    jobs: dict[str, AdzunaJob] = field(default_factory=dict)
    hits: dict[str, list[dict]] = field(default_factory=dict)
    counts: dict[str, dict] = field(default_factory=dict)


def _fetch_bucket(
    client: httpx.Client,
    settings: AdzunaSettings,
    bucket: str,
    extra: dict,
    budget: _CallBudget,
    result: _FetchResult,
) -> None:
    search = _search_params(settings, extra)
    hit = {"bucket": bucket, **search}
    pages = max(1, min(settings.max_pages or 1, config.ADZUNA_MAX_PAGES_LIMIT))
    received = 0
    total = 0
    for page in range(1, pages + 1):
        budget.spend()
        response = client.get(
            ADZUNA_SEARCH_URL.format(page=page),
            params={
                "app_id": config.ADZUNA_APP_ID,
                "app_key": config.ADZUNA_APP_KEY,
                "results_per_page": config.ADZUNA_RESULTS_PER_PAGE,
                "salary_include_unknown": "1",
                "full_time": "1",
                "max_days_old": config.POSTING_VISIBLE_DAYS,
                # Newest first, so a regular refresh picks up everything new
                # within the first page or two.
                "sort_by": "date",
                **search,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        total = int(data.get("count") or 0)
        received += len(results)
        for raw in results:
            job = _parse_job(raw, bucket)
            if job is None or not passes_relevance_filter(job):
                continue
            result.jobs[job.adzuna_id] = job
            result.hits.setdefault(job.adzuna_id, []).append(hit)
        result.counts[bucket] = {"received": received, "available": total}
        if received >= total or len(results) < config.ADZUNA_RESULTS_PER_PAGE:
            break


def refresh_adzuna(
    db: Session,
    settings: AdzunaSettings,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> AdzunaFetch:
    """Run every bucket, store what passes the location filter, and log the
    fetch. Partial results are kept if a bucket fails or the quota runs out."""
    now = now or utcnow()
    fetch = AdzunaFetch(fetched_at=now, settings_fingerprint=settings_fingerprint(settings))
    result = _FetchResult()
    budget = _CallBudget(min(w.remaining for w in quota_usage(db, now)))
    buckets = _buckets(settings)

    if not config.ADZUNA_APP_ID or not config.ADZUNA_APP_KEY:
        fetch.error = "Adzuna API credentials are not configured. Set ADZUNA_APP_ID and ADZUNA_APP_KEY in .env"
    elif budget.remaining < len(buckets):
        fetch.error = "Adzuna API quota nearly used up; refresh skipped. See the usage line for details."
    else:
        owns_client = client is None
        client = client or httpx.Client()
        try:
            for name, extra in buckets.items():
                _fetch_bucket(client, settings, name, extra, budget, result)
        except Exception as exc:  # noqa: BLE001 - surfaced in the panel, partial results kept
            fetch.error = str(exc)
        finally:
            if owns_client:
                client.close()

    fetch.api_calls = budget.calls
    fetch.query_counts = result.counts
    fetch.received_count = len(result.jobs)
    fetch.new_count = job_postings.record_adzuna_results(db, result.jobs.values(), result.hits, now)
    db.add(fetch)
    db.commit()
    return fetch


def latest_fetch(db: Session, successful: bool = False) -> AdzunaFetch | None:
    query = db.query(AdzunaFetch)
    if successful:
        query = query.filter(AdzunaFetch.error.is_(None))
    return query.order_by(AdzunaFetch.fetched_at.desc(), AdzunaFetch.id.desc()).first()


def needs_refresh(db: Session, settings: AdzunaSettings, now: datetime | None = None) -> bool:
    """Any fetch attempt (failed ones included) resets the clock, so a broken
    setup doesn't spend API calls on every page load."""
    now = now or utcnow()
    latest = latest_fetch(db)
    if latest is None or latest.settings_fingerprint != settings_fingerprint(settings):
        return True
    return (now - latest.fetched_at).total_seconds() >= config.ADZUNA_CACHE_TTL_SECONDS


def get_adzuna_feed(db: Session, settings: AdzunaSettings, refresh: bool = False) -> AdzunaFeed:
    if refresh or needs_refresh(db, settings):
        refresh_adzuna(db, settings)
    latest = latest_fetch(db)
    last_good = latest_fetch(db, successful=True)
    visible = job_postings.visible_postings(db, settings, limit=settings.results_limit)
    return AdzunaFeed(
        postings=visible.postings,
        total=visible.total,
        hidden_by_filters=visible.hidden_by_filters,
        fetched_at=latest.fetched_at if latest else None,
        error=latest.error if latest else None,
        query_counts=latest.query_counts if latest else {},
        new_since=last_good.fetched_at if last_good else None,
        quota=quota_usage(db),
    )
