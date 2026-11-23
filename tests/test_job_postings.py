import uuid
from datetime import timedelta

import httpx
import pytest

from app import config
from app.database import SessionLocal
from app.models import AdzunaFetch, JobPosting, Opportunity
from app.services import adzuna, job_postings
from app.services.adzuna_settings import get_or_create_adzuna_settings
from app.services.auth import create_user
from app.utils import utcnow
from tests.conftest import csrf_from_html


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def settings(db):
    return get_or_create_adzuna_settings(db)


@pytest.fixture
def adzuna_keys(monkeypatch):
    monkeypatch.setattr(config, "ADZUNA_APP_ID", "test-id")
    monkeypatch.setattr(config, "ADZUNA_APP_KEY", "test-key")


def _raw(job_id: str, title: str = "Senior Ruby Engineer", company: str = "Acme", **extra) -> dict:
    return {
        "id": job_id,
        "title": title,
        "company": {"display_name": company},
        "location": {"display_name": extra.pop("location", "US")},
        "description": extra.pop("description", "Remote Ruby role"),
        "salary_min": 150000.4,
        "salary_max": 170000,
        "salary_is_predicted": extra.pop("predicted", "0"),
        "contract_time": "full_time",
        "category": {"label": "IT Jobs"},
        "created": "2026-11-17T15:42:55Z",
        "redirect_url": f"https://www.adzuna.com/details/{job_id}?utm_medium=api",
        **extra,
    }


def _client(pages_by_bucket: dict, calls: list) -> httpx.Client:
    """Serve canned pages. Buckets are told apart by their params: `what_or`
    marks the remote bucket, `where` the metro buckets."""

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        calls.append(dict(params))
        bucket = "remote" if "what_or" in params else params.get("where")
        page = int(request.url.path.rsplit("/", 1)[1])
        pages = pages_by_bucket.get(bucket, [])
        results = pages[page - 1] if page <= len(pages) else []
        total = sum(len(p) for p in pages)
        return httpx.Response(200, json={"count": total, "results": results})

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestNormalizeUrl:
    def test_strips_tracking_fragment_and_trailing_slash(self):
        url = "HTTPS://Jobs.Example.com/roles/123/?utm_source=x&gh_jid=9&ref=abc#apply"
        assert job_postings.normalize_url(url) == "https://jobs.example.com/roles/123?gh_jid=9"

    def test_rejects_non_http(self):
        assert job_postings.normalize_url("javascript:alert(1)") == ""
        assert job_postings.normalize_url("") == ""


class TestMergeSearchHits:
    def test_same_search_bumps_last_seen(self):
        t1 = utcnow()
        t2 = t1 + timedelta(hours=5)
        hit = {"bucket": "remote", "what_and": "ruby"}
        first = job_postings.merge_search_hits([], [hit], t1)
        second = job_postings.merge_search_hits(first, [hit], t2)
        assert len(second) == 1
        assert second[0]["first_seen_at"] == t1.isoformat(timespec="seconds")
        assert second[0]["last_seen_at"] == t2.isoformat(timespec="seconds")

    def test_different_search_is_added(self):
        now = utcnow()
        hits = job_postings.merge_search_hits(
            [], [{"bucket": "remote", "what_and": "ruby"}, {"bucket": "slc", "what_and": "ruby"}], now
        )
        assert {h["bucket"] for h in hits} == {"remote", "slc"}


class TestRefreshAdzuna:
    def test_stores_results_and_logs_fetch(self, db, settings, adzuna_keys):
        calls: list = []
        client = _client({"remote": [[_raw("1"), _raw("2", predicted="1")]]}, calls)
        fetch = adzuna.refresh_adzuna(db, settings, client=client)

        assert fetch.error is None
        assert fetch.api_calls == 4  # one page per bucket
        assert fetch.new_count == 2
        posting = db.query(JobPosting).filter_by(source_id="2").one()
        assert posting.salary_min == 150000  # float from the API, rounded
        assert posting.salary_is_predicted is True
        assert posting.salary_display.startswith("~") and posting.salary_display.endswith("(est.)")
        assert posting.posted_at.isoformat() == "2026-11-17T15:42:55"
        assert posting.search_hits[0]["bucket"] == "remote"
        assert calls[0]["sort_by"] == "date"

    def test_resighting_does_not_duplicate_and_keeps_user_state(self, db, settings, adzuna_keys):
        adzuna.refresh_adzuna(db, settings, client=_client({"remote": [[_raw("1")]]}, []))
        posting = db.query(JobPosting).one()
        job_postings.dismiss_posting(db, posting)

        fetch = adzuna.refresh_adzuna(
            db, settings, client=_client({"remote": [[_raw("1", title="Renamed")]], "Salt Lake City": [[_raw("1", title="Renamed")]]}, [])
        )
        db.refresh(posting)
        assert fetch.new_count == 0
        assert db.query(JobPosting).count() == 1
        assert posting.title == "Renamed"
        assert posting.dismissed_at is not None
        assert {h["bucket"] for h in posting.search_hits} == {"remote", "slc"}

    def test_location_filter_applies_before_storing(self, db, settings, adzuna_keys):
        onsite_far = _raw("9", location="Boston, MA", description="On-site in our office")
        adzuna.refresh_adzuna(db, settings, client=_client({"remote": [[onsite_far, _raw("1")]]}, []))
        assert [p.source_id for p in db.query(JobPosting).all()] == ["1"]

    def test_paginates_until_count_reached(self, db, settings, adzuna_keys, monkeypatch):
        monkeypatch.setattr(config, "ADZUNA_RESULTS_PER_PAGE", 2)
        settings.max_pages = 3
        db.commit()
        calls: list = []
        pages = [[_raw("1"), _raw("2")], [_raw("3")]]  # 3 results: page 2 is short, so stop
        fetch = adzuna.refresh_adzuna(db, settings, client=_client({"remote": pages}, calls))
        remote_calls = [c for c in calls if "what_or" in c]
        assert len(remote_calls) == 2
        assert fetch.query_counts["remote"] == {"received": 3, "available": 3}
        assert db.query(JobPosting).count() == 3

    def test_blank_optional_terms_are_not_sent(self, db, settings, adzuna_keys):
        calls: list = []
        adzuna.refresh_adzuna(db, settings, client=_client({}, calls))
        assert "what_exclude" not in calls[0]
        assert "title_only" not in calls[0]

    def test_quota_guard_skips_refresh(self, db, settings, adzuna_keys):
        db.add(AdzunaFetch(fetched_at=utcnow() - timedelta(minutes=2), api_calls=148, query_counts={}, received_count=0, new_count=0))
        db.commit()
        calls: list = []
        fetch = adzuna.refresh_adzuna(db, settings, client=_client({}, calls))
        assert calls == []
        assert fetch.api_calls == 0
        assert "quota" in fetch.error.lower()

    def test_quota_runs_out_midway_keeps_partial_results(self, db, settings, adzuna_keys):
        db.add(AdzunaFetch(fetched_at=utcnow() - timedelta(minutes=2), api_calls=145, query_counts={}, received_count=0, new_count=0))
        db.commit()
        settings.max_pages = 3
        db.commit()
        # 5 calls left: enough to start, not enough for 4 buckets x 3 full pages.
        full_page = [_raw(str(i)) for i in range(config.ADZUNA_RESULTS_PER_PAGE)]
        calls: list = []
        fetch = adzuna.refresh_adzuna(
            db, settings, client=_client({"remote": [full_page, full_page, full_page]}, calls)
        )
        assert len(calls) == 5
        assert fetch.api_calls == 5
        assert "quota" in fetch.error.lower()
        assert db.query(JobPosting).count() > 0

    def test_missing_credentials_records_error_without_calls(self, db, settings, monkeypatch):
        monkeypatch.setattr(config, "ADZUNA_APP_ID", "")
        calls: list = []
        fetch = adzuna.refresh_adzuna(db, settings, client=_client({}, calls))
        assert calls == []
        assert "credentials" in fetch.error


class TestNeedsRefresh:
    def test_fresh_fetch_with_same_terms_does_not_refresh(self, db, settings, adzuna_keys):
        adzuna.refresh_adzuna(db, settings, client=_client({}, []))
        assert adzuna.needs_refresh(db, settings) is False

    def test_filter_only_change_does_not_refresh(self, db, settings, adzuna_keys):
        adzuna.refresh_adzuna(db, settings, client=_client({}, []))
        settings.title_exclude = "Principal"
        settings.company_blocklist = "Acme"
        settings.results_limit = 50
        db.commit()
        assert adzuna.needs_refresh(db, settings) is False

    def test_search_term_change_refreshes(self, db, settings, adzuna_keys):
        adzuna.refresh_adzuna(db, settings, client=_client({}, []))
        settings.search_what_exclude = "clearance"
        db.commit()
        assert adzuna.needs_refresh(db, settings) is True

    def test_stale_fetch_refreshes(self, db, settings, adzuna_keys):
        old = utcnow() - timedelta(seconds=config.ADZUNA_CACHE_TTL_SECONDS + 1)
        adzuna.refresh_adzuna(db, settings, client=_client({}, []), now=old)
        assert adzuna.needs_refresh(db, settings) is True


def _posting(db, source_id: str, title: str = "Senior Ruby Engineer", company: str = "Acme", **kwargs) -> JobPosting:
    now = utcnow()
    posting = JobPosting(
        source="adzuna",
        source_id=source_id,
        title=title,
        company=company,
        source_url=f"https://www.adzuna.com/details/{source_id}",
        dedupe_key=job_postings.make_dedupe_key(company, title),
        search_hits=[],
        first_seen_at=kwargs.pop("first_seen_at", now),
        last_seen_at=kwargs.pop("last_seen_at", now),
        **kwargs,
    )
    db.add(posting)
    db.commit()
    return posting


class TestVisiblePostings:
    def test_excludes_dismissed_linked_and_stale(self, db, settings):
        _posting(db, "keep")
        _posting(db, "dismissed", dismissed_at=utcnow())
        opp = Opportunity(company="Acme")
        db.add(opp)
        db.commit()
        _posting(db, "linked", opportunity_id=opp.id)
        _posting(db, "stale", last_seen_at=utcnow() - timedelta(days=config.POSTING_VISIBLE_DAYS + 1))
        result = job_postings.visible_postings(db, settings, limit=10)
        assert [p.source_id for p in result.postings] == ["keep"]

    def test_title_and_company_filters(self, db, settings):
        settings.title_exclude = "Principal\nManager"
        settings.company_blocklist = "Staffing Co"
        db.commit()
        _posting(db, "keep", title="Senior Ruby Engineer")
        _posting(db, "principal", title="Principal Engineer")
        _posting(db, "manager", title="Engineering Manager, Ruby")
        _posting(db, "blocked", company="staffing co")
        _posting(db, "word-boundary", title="Managerial-free Ruby Engineer")
        result = job_postings.visible_postings(db, settings, limit=10)
        assert {p.source_id for p in result.postings} == {"keep", "word-boundary"}
        assert result.hidden_by_filters == 3

    def test_limit_and_total(self, db, settings):
        for i in range(5):
            _posting(db, str(i))
        result = job_postings.visible_postings(db, settings, limit=2)
        assert len(result.postings) == 2
        assert result.total == 5

    def test_block_company_is_idempotent(self, db, settings):
        job_postings.block_company(db, settings, "Acme")
        job_postings.block_company(db, settings, "ACME")
        assert settings.company_blocklist == "Acme"


class TestOpportunityPrefill:
    def test_predicted_salary_not_copied(self, db, settings):
        posting = _posting(db, "1", salary_min=200000, salary_max=200000, salary_is_predicted=True)
        prefill = job_postings.map_to_opportunity_prefill(posting, settings)
        assert prefill["salary_min"] == ""
        assert "estimate" in prefill["notes_text"]

    def test_prefers_captured_employer_url(self, db, settings):
        posting = _posting(db, "1", posting_url="https://jobs.acme.com/1")
        assert job_postings.map_to_opportunity_prefill(posting, settings)["posting_url"] == "https://jobs.acme.com/1"


class TestCapture:
    def test_candidates_are_recently_opened_without_url(self, db):
        now = utcnow()
        _posting(db, "older", opened_at=now - timedelta(minutes=10))
        _posting(db, "latest", opened_at=now)
        _posting(db, "has-url", opened_at=now, posting_url="https://x.com/1")
        _posting(db, "never-opened")
        _posting(db, "long-ago", opened_at=now - timedelta(days=8))
        assert [p.source_id for p in job_postings.capture_candidates(db)] == ["latest", "older"]

    def test_create_captured_posting_dedupes_by_url(self, db):
        url = "https://rubyonremote.com/jobs/123-senior-rails?utm_source=feed"
        first, created = job_postings.create_captured_posting(db, url, "Senior Rails Dev", "Acme")
        again, created_again = job_postings.create_captured_posting(db, url.split("?")[0], "Other", "Other")
        assert created and not created_again
        assert first.id == again.id
        assert first.source == "ruby_on_remote"
        assert first.source_id == "https://rubyonremote.com/jobs/123-senior-rails"


def _login(client) -> None:
    email = f"postings-{uuid.uuid4().hex}@example.com"
    session = SessionLocal()
    try:
        create_user(session, email, "password123")
    finally:
        session.close()
    token = csrf_from_html(client.get("/login").text)
    resp = client.post(
        "/login",
        data={"email": email, "password": "password123", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303


class TestRoutes:
    def test_panel_lists_stored_postings(self, client, db):
        _posting(db, "1", title="Ruby Platform Engineer")
        _login(client)
        html = client.get("/opportunities").text
        assert "Ruby Platform Engineer" in html
        assert "/postings/" in html and "/open" in html
        assert "javascript:" in html  # bookmarklet

    def test_open_records_and_redirects(self, client, db):
        posting = _posting(db, "1")
        _login(client)
        resp = client.get(f"/postings/{posting.id}/open", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == posting.source_url
        db.refresh(posting)
        assert posting.opened_at is not None

    def test_dismiss_removes_from_panel(self, client, db):
        posting = _posting(db, "1", title="Dismiss Me Engineer")
        _login(client)
        token = csrf_from_html(client.get("/opportunities").text)
        html = client.post(f"/postings/{posting.id}/dismiss", data={"csrf_token": token}).text
        assert "Dismiss Me Engineer" not in html

    def test_block_company_hides_its_postings(self, client, db):
        posting = _posting(db, "1", company="Blocked Inc", title="Blocked Role")
        _login(client)
        token = csrf_from_html(client.get("/opportunities").text)
        html = client.post(f"/postings/{posting.id}/block-company", data={"csrf_token": token}).text
        assert "Blocked Role" not in html
        assert "1 hidden by your title/company filters" in html

    def test_capture_attaches_url_to_opened_posting(self, client, db):
        posting = _posting(db, "1", opened_at=utcnow())
        _login(client)
        page = client.get("/postings/capture", params={"url": "https://jobs.acme.com/42?utm_source=adzuna", "title": "Ruby Dev"})
        assert "Senior Ruby Engineer" in page.text
        resp = client.post(
            "/postings/capture",
            data={"csrf_token": csrf_from_html(page.text), "url": "https://jobs.acme.com/42?utm_source=adzuna", "target": str(posting.id)},
        )
        assert "Employer URL saved" in resp.text
        db.refresh(posting)
        assert posting.posting_url == "https://jobs.acme.com/42"

    def test_capture_new_posting_requires_title_and_company(self, client):
        _login(client)
        page = client.get("/postings/capture", params={"url": "https://rubyonremote.com/jobs/1"})
        token = csrf_from_html(page.text)
        bad = client.post("/postings/capture", data={"csrf_token": token, "url": "https://rubyonremote.com/jobs/1", "target": "new"})
        assert bad.status_code == 400
        good = client.post(
            "/postings/capture",
            data={"csrf_token": token, "url": "https://rubyonremote.com/jobs/1", "target": "new", "title": "Rails Dev", "company": "Acme"},
        )
        assert "Posting saved" in good.text

    def test_capture_rejects_non_http_url(self, client):
        _login(client)
        page = client.get("/postings/capture", params={"url": "https://x.com/1"})
        resp = client.post(
            "/postings/capture",
            data={"csrf_token": csrf_from_html(page.text), "url": "javascript:alert(1)", "target": "new", "title": "t", "company": "c"},
        )
        assert resp.status_code == 400

    def test_add_from_posting_links_opportunity(self, client, db):
        posting = _posting(db, "1", company="Linked Co")
        _login(client)
        modal = client.get(f"/opportunities/from-posting/{posting.id}").text
        assert f'name="job_posting_id" value="{posting.id}"' in modal
        resp = client.post(
            "/opportunities",
            data={"csrf_token": csrf_from_html(modal), "company": "Linked Co", "job_posting_id": str(posting.id)},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        db.refresh(posting)
        assert posting.opportunity_id is not None

    def test_settings_save_requires_a_positive_search_term(self, client, db):
        _login(client)
        form = client.get("/opportunities/adzuna/settings-form").text
        settings = get_or_create_adzuna_settings(db)
        data = {
            "csrf_token": csrf_from_html(form),
            "search_what": "",
            "search_what_and": "",
            "search_title_only": "",
            "salary_min": "135000",
            "slc_where": settings.slc_where,
            "slc_distance": str(settings.slc_distance),
            "va_where": settings.va_where,
            "va_distance": str(settings.va_distance),
            "charlotte_where": settings.charlotte_where,
            "charlotte_distance": str(settings.charlotte_distance),
            "results_limit": "10",
            "stack_default": "Ruby",
        }
        resp = client.post("/opportunities/adzuna/settings", data=data)
        assert "Settings not saved" in resp.text
