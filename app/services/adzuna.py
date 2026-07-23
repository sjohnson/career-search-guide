from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import ADZUNA_APP_ID, ADZUNA_APP_KEY, ADZUNA_CACHE_TTL_SECONDS
from app.models import AdzunaSettings, OpportunitySource, RemoteStatus
from app.services.opportunities import format_salary

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/us/search/1"

_cache: dict[str, Any] = {
    "fetched_at": None,
    "jobs": [],
    "error": None,
    "query_counts": {},
    "settings_fingerprint": None,
}


@dataclass
class AdzunaJob:
    adzuna_id: str
    title: str
    company: str
    location: str
    salary_min: int | None
    salary_max: int | None
    redirect_url: str
    description: str
    created: str
    inferred_remote_status: str | None
    bucket: str

    def salary_display(self) -> str:
        return format_salary(self.salary_min, self.salary_max, "USD")


@dataclass
class AdzunaFeed:
    jobs: list[AdzunaJob] = field(default_factory=list)
    fetched_at: datetime | None = None
    error: str | None = None
    query_counts: dict[str, int] = field(default_factory=dict)
    thin_results: bool = False


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


def _settings_fingerprint(settings: AdzunaSettings) -> str:
    if settings.updated_at:
        return str(settings.updated_at.timestamp())
    return f"{settings.id}:{settings.salary_min}:{settings.results_limit}"


def bust_adzuna_cache() -> None:
    _cache["fetched_at"] = None
    _cache["jobs"] = []
    _cache["error"] = None
    _cache["query_counts"] = {}
    _cache["settings_fingerprint"] = None


def _parse_job(raw: dict, bucket: str) -> AdzunaJob | None:
    adzuna_id = str(raw.get("id", ""))
    if not adzuna_id:
        return None
    company_obj = raw.get("company") or {}
    location_obj = raw.get("location") or {}
    title = raw.get("title") or "Untitled"
    location = location_obj.get("display_name") or ""
    description = raw.get("description") or ""
    if bucket == "virginia" and _is_dc_area(location):
        return None
    return AdzunaJob(
        adzuna_id=adzuna_id,
        title=title,
        company=company_obj.get("display_name") or "Unknown",
        location=location,
        salary_min=raw.get("salary_min"),
        salary_max=raw.get("salary_max"),
        redirect_url=raw.get("redirect_url") or "",
        description=description,
        created=raw.get("created") or "",
        inferred_remote_status=infer_remote_status(title, description, location),
        bucket=bucket,
    )


def _fetch_bucket(
    client: httpx.Client,
    settings: AdzunaSettings,
    bucket: str,
    extra: dict,
) -> list[AdzunaJob]:
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": 25,
        "what": settings.search_what,
        "what_and": settings.search_what_and,
        "salary_min": settings.salary_min,
        "salary_include_unknown": "1",
        "full_time": "1",
        "max_days_old": 30,
        **extra,
    }
    response = client.get(ADZUNA_BASE, params=params, timeout=20.0)
    response.raise_for_status()
    data = response.json()
    jobs = []
    for raw in data.get("results", []):
        parsed = _parse_job(raw, bucket)
        if parsed:
            jobs.append(parsed)
    return jobs


def _fetch_all_buckets(settings: AdzunaSettings) -> tuple[list[AdzunaJob], dict[str, int]]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        raise ValueError("Adzuna API credentials are not configured. Set ADZUNA_APP_ID and ADZUNA_APP_KEY in .env")

    buckets = {
        "remote": {"what_or": settings.search_what_or},
        "slc": {"where": settings.slc_where, "distance": settings.slc_distance},
        "virginia": {"where": settings.va_where, "distance": settings.va_distance},
        "charlotte": {"where": settings.charlotte_where, "distance": settings.charlotte_distance},
    }
    counts: dict[str, int] = {}
    merged: dict[str, AdzunaJob] = {}

    with httpx.Client() as client:
        for name, extra in buckets.items():
            jobs = _fetch_bucket(client, settings, name, extra)
            counts[name] = len(jobs)
            for job in jobs:
                merged[job.adzuna_id] = job

    filtered = [job for job in merged.values() if passes_relevance_filter(job)]
    ranked = sorted(
        filtered,
        key=lambda j: (
            -(j.salary_max or j.salary_min or 0),
            j.created or "",
        ),
    )
    return ranked[: settings.results_limit], counts


def _cache_valid(settings: AdzunaSettings) -> bool:
    fetched = _cache.get("fetched_at")
    if not fetched:
        return False
    if _cache.get("settings_fingerprint") != _settings_fingerprint(settings):
        return False
    age = (datetime.now(timezone.utc) - fetched).total_seconds()
    return age < ADZUNA_CACHE_TTL_SECONDS


def get_adzuna_jobs(settings: AdzunaSettings, refresh: bool = False) -> AdzunaFeed:
    if not refresh and _cache_valid(settings):
        return AdzunaFeed(
            jobs=_cache.get("jobs", []),
            fetched_at=_cache.get("fetched_at"),
            error=_cache.get("error"),
            query_counts=_cache.get("query_counts", {}),
            thin_results=len(_cache.get("jobs", [])) < 3,
        )

    try:
        jobs, counts = _fetch_all_buckets(settings)
        _cache["jobs"] = jobs
        _cache["fetched_at"] = datetime.now(timezone.utc)
        _cache["error"] = None
        _cache["query_counts"] = counts
        _cache["settings_fingerprint"] = _settings_fingerprint(settings)
    except Exception as exc:
        _cache["error"] = str(exc)
        if not _cache.get("jobs"):
            _cache["jobs"] = []

    return AdzunaFeed(
        jobs=_cache.get("jobs", []),
        fetched_at=_cache.get("fetched_at"),
        error=_cache.get("error"),
        query_counts=_cache.get("query_counts", {}),
        thin_results=len(_cache.get("jobs", [])) < 3,
    )


def get_cached_job(adzuna_id: str) -> AdzunaJob | None:
    for job in _cache.get("jobs", []):
        if job.adzuna_id == adzuna_id:
            return job
    return None


def build_notes_blob(job: AdzunaJob) -> str:
    lines = [
        f"Imported from Adzuna (job id: {job.adzuna_id})",
        f"Title: {job.title}",
        f"Company: {job.company}",
        f"Location: {job.location}",
        f"Posted: {job.created}",
        f"URL: {job.redirect_url}",
        f"Search bucket: {job.bucket}",
        "",
        "Description snippet:",
        job.description,
    ]
    return "\n".join(lines)


def map_to_opportunity_prefill(job: AdzunaJob, settings: AdzunaSettings) -> dict:
    return {
        "company": job.company,
        "posting_url": job.redirect_url,
        "location_text": job.location,
        "remote_status": job.inferred_remote_status or "",
        "source": OpportunitySource.ADZUNA.value,
        "stack": settings.stack_default,
        "salary_min": job.salary_min or "",
        "salary_max": job.salary_max or "",
        "salary_currency": "USD",
        "pipeline_stage": "new",
        "notes_text": build_notes_blob(job),
    }
