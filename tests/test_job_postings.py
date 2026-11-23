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
        "location": {"display_name": extra.pop("location", "US"), "area": extra.pop("area", ["US"])},
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
            db, settings, client=_client({"remote": [[_raw("1", title="Renamed Engineer")]], "Salt Lake City": [[_raw("1", title="Renamed Engineer")]]}, [])
        )
        db.refresh(posting)
        assert fetch.new_count == 0
        assert db.query(JobPosting).count() == 1
        assert posting.title == "Renamed Engineer"
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
        entries = job_postings.parse_lines(settings.company_blocklist)
        assert entries.count("Acme") == 1 and "ACME" not in entries


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
        assert "1 saved earlier are hidden by your current posting rules" in html

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


# --- Posting rules -----------------------------------------------------------

from app.services import posting_rules  # noqa: E402
from app.services.posting_rules import PostingRules  # noqa: E402


def _rules(**overrides) -> PostingRules:
    base = dict(blocked_companies=[], industry_terms=[], title_terms=[], stack_terms=[], signal_terms=[])
    return PostingRules(**{**base, **overrides})


def _reason(rules: PostingRules, title="Senior Ruby Engineer", company="Acme", location="US", remote_status=None, buckets=("remote",)):
    return rules.rejection_reason(
        title=title, company=company, location=location, remote_status=remote_status, buckets=buckets
    )


class TestTermMatching:
    @pytest.mark.parametrize(
        "term,text,expected",
        [
            ("Java", "Senior Java Engineer", True),
            ("Java", "Senior JavaScript Engineer", False),
            ("intern", "Internal Tools Engineer", False),
            ("C#", "C# Developer", True),
            ("C#", "Senior C#/.NET Engineer", True),
            (".NET", "Senior .NET Engineer", True),
            ("C++", "Software Engineer (C++)", True),
            ("C", "Software Engineer (C++)", False),
            ("head of", "Head  of Engineering", True),
            ("10+ years", "requires 10+ years of Ruby", True),
            ("VP", "VPN Engineer", False),
        ],
    )
    def test_whole_word_case_insensitive(self, term, text, expected):
        assert (posting_rules.find_term([term], text) == term) is expected


class TestRejectionReason:
    def test_company_matches_whole_words_in_name(self):
        rules = _rules(blocked_companies=["Globex"])
        assert _reason(rules, company="Globex Health").rule == "company"
        assert _reason(rules, company="Globexia Labs") is None

    def test_industry_matches_title_or_company(self):
        rules = _rules(industry_terms=["sportsbook"])
        assert _reason(rules, title="Ruby Engineer, Sportsbook").rule == "industry"
        assert _reason(rules, company="Acme Sportsbook").rule == "industry"

    def test_title_terms(self):
        rules = _rules(title_terms=["manager"])
        assert _reason(rules, title="Engineering Manager, Ruby").rule == "title"
        assert _reason(rules, title="Senior Ruby Engineer") is None

    def test_stack_term_rescued_by_ruby_in_title(self):
        rules = _rules(stack_terms=["C#"])
        assert _reason(rules, title="Senior C# Engineer") == posting_rules.Rejection("stack", "C#")
        assert _reason(rules, title="Ruby or C# Engineer") is None

    def test_remote_search_drops_only_stated_on_site_outside_regions(self):
        rules = _rules()
        assert _reason(rules, location="Boston, MA", remote_status="on_site").rule == "location"
        assert _reason(rules, location="Boston, MA", remote_status="hybrid").rule == "location"
        # Unknown arrangement: Adzuna matched "remote" somewhere; kept for /rank.
        assert _reason(rules, location="Boston, MA", remote_status=None) is None
        assert _reason(rules, location="Lehi, Utah County, Utah", remote_status="on_site") is None

    def test_metro_search_results_must_be_in_region_unless_remote(self):
        rules = _rules()
        va = ("virginia",)
        assert _reason(rules, location="South Norfolk, Chesapeake City, Virginia", buckets=va) is None
        assert _reason(rules, location="Herndon, Fairfax County, Virginia", buckets=va).rule == "location"
        assert _reason(rules, location="Laurel, Prince George's County, Maryland", buckets=va).rule == "location"
        assert _reason(rules, location="Herndon, Fairfax County, Virginia", remote_status="remote", buckets=va) is None
        assert _reason(rules, location="Herndon, Fairfax County, Virginia", buckets=("virginia", "remote")) is None

    def test_default_lists(self):
        rules = PostingRules(
            blocked_companies=posting_rules.DEFAULT_COMPANY_BLOCKLIST,
            industry_terms=posting_rules.DEFAULT_INDUSTRY_EXCLUDE,
            title_terms=posting_rules.DEFAULT_TITLE_EXCLUDE,
            stack_terms=posting_rules.DEFAULT_TITLE_STACK_EXCLUDE,
            signal_terms=posting_rules.DEFAULT_SIGNAL_TERMS,
        )
        for title in ("Senior Software Engineer", "Lead Software Developer", "Staff Engineer, Rails", "Principal Ruby Engineer", "Full Stack Engineer (Ruby/React)"):
            assert _reason(rules, title=title) is None, title
        for title in ("Engineering Manager", "Junior Ruby Developer", "Senior .NET Developer", "Frontend Engineer", "DevOps Engineer"):
            assert _reason(rules, title=title) is not None, title
        assert rules.signals("Senior Engineer", "Ruby and Java, some JavaScript; on-call rotation") == ["Java", "on-call", "rotation"]


class TestInferRemoteStatus:
    def test_bare_city_is_unknown(self):
        assert posting_rules.infer_remote_status("Ruby Engineer", "Build things", "Boston, MA") is None

    def test_stated_arrangements(self):
        assert posting_rules.infer_remote_status("Ruby Engineer", "Work remotely from anywhere", "Boston, MA") == "remote"
        assert posting_rules.infer_remote_status("Ruby Engineer", "Hybrid, 3 days in office", "Boston, MA") == "hybrid"
        assert posting_rules.infer_remote_status("Ruby Engineer", "This role is onsite", "Boston, MA") == "on_site"


class TestIngestRules:
    def test_rejections_are_counted_with_samples_not_stored(self, db, settings, adzuna_keys):
        jobs = [
            _raw("keep"),
            _raw("city-only", location="Boston, MA", description="Ruby role"),
            _raw("mgr", title="Engineering Manager"),
            _raw("mgr2", title="Director of Engineering"),
            _raw("onsite", location="Boston, MA", description="On-site in our office"),
            _raw("blocked", company="Underdog Sports"),
        ]
        fetch = adzuna.refresh_adzuna(db, settings, client=_client({"remote": [jobs]}, []))
        assert {p.source_id for p in db.query(JobPosting).all()} == {"keep", "city-only"}
        assert fetch.received_count == 6
        assert fetch.kept_count == 2
        assert fetch.rejections["title"]["count"] == 2
        assert fetch.rejections["location"]["samples"][0]["title"] == "Senior Ruby Engineer"
        assert fetch.rejections["company"]["samples"][0]["term"] == "Underdog"

    def test_state_from_area_is_added_to_location(self, db, settings, adzuna_keys):
        nova = _raw("nova", location="Herndon, Fairfax County", area=["US", "Virginia", "Fairfax County", "Herndon"], description="Ruby role")
        tidewater = _raw("tide", location="South Norfolk, Chesapeake City", area=["US", "Virginia", "Chesapeake City"], description="Ruby role")
        fetch = adzuna.refresh_adzuna(db, settings, client=_client({"Virginia": [[nova, tidewater]]}, []))
        stored = db.query(JobPosting).one()
        assert stored.location == "South Norfolk, Chesapeake City, Virginia"
        assert fetch.rejections["location"]["samples"][0]["location"] == "Herndon, Fairfax County, Virginia"

    def test_tightened_rule_hides_stored_but_not_captured(self, db, settings):
        _posting(db, "kept", title="Senior Ruby Engineer")
        _posting(db, "later-blocked", title="Senior Rust Engineer")
        captured, _ = job_postings.create_captured_posting(db, "https://jobs.example.com/rust", "Senior Rust Engineer", "Example")
        result = job_postings.visible_postings(db, settings, limit=10)
        assert {p.source_id for p in result.postings} == {"kept", captured.source_id}
        assert result.hidden_by_filters == 1

    def test_panel_shows_fetch_summary_and_signals(self, client, db, settings, adzuna_keys):
        jobs = [_raw("keep", description="Ruby and Java, on-call"), _raw("mgr", title="Engineering Manager")]
        adzuna.refresh_adzuna(db, settings, client=_client({"remote": [jobs]}, []))
        _login(client)
        html = client.get("/opportunities").text
        assert "2 received · 1 kept (1 new)" in html
        assert "1 title" in html
        assert 'badge-signal' in html and ">Java<" in html

    def test_settings_save_stores_rule_lists(self, client, db):
        _login(client)
        form = client.get("/opportunities/adzuna/settings-form").text
        assert "Excluded title stacks" in form and "ruby, rails" in form
        settings = get_or_create_adzuna_settings(db)
        data = {
            "csrf_token": csrf_from_html(form),
            "search_what_and": "ruby",
            "salary_min": "135000",
            "slc_where": settings.slc_where,
            "slc_distance": str(settings.slc_distance),
            "va_where": settings.va_where,
            "va_distance": str(settings.va_distance),
            "charlotte_where": settings.charlotte_where,
            "charlotte_distance": str(settings.charlotte_distance),
            "results_limit": "10",
            "stack_default": "Ruby",
            "industry_exclude": "casino\n\n lottery ",
            "title_stack_exclude": "C#, Rust",
            "signal_terms": "on-call",
        }
        client.post("/opportunities/adzuna/settings", data=data)
        db.expire_all()
        settings = get_or_create_adzuna_settings(db)
        assert settings.industry_exclude == "casino\nlottery"
        assert settings.title_stack_exclude == "C#\nRust"
        assert settings.signal_terms == "on-call"


class TestRequiredTitleWords:
    def test_title_needs_one_required_word(self):
        rules = _rules(required_title_terms=["engineer", "developer"])
        assert _reason(rules, title="Senior Ruby Engineer") is None
        assert _reason(rules, title="Penetration Tester").rule == "require"
        # Blank list turns the rule off.
        assert _reason(_rules(), title="Penetration Tester") is None

    def test_defaults_drop_non_software_titles(self, db, settings):
        rules = PostingRules.from_settings(settings)
        for title in ("Field Service Technician", "CSA1- Cloud System Administrator", "Delivery Consultant", "Business Development Representative"):
            assert _reason(rules, title=title).rule == "require", title
        for title in ("Lead Software Developer", "Application Architect", "SDE II", "Senior Software Engineer (Ruby)"):
            assert _reason(rules, title=title) is None, title


class TestBackfillPages:
    def test_override_fetches_more_pages_without_changing_fingerprint(self, db, settings, adzuna_keys, monkeypatch):
        monkeypatch.setattr(config, "ADZUNA_RESULTS_PER_PAGE", 2)
        pages = [[_raw("1"), _raw("2")], [_raw("3"), _raw("4")], [_raw("5")]]
        calls: list = []
        fetch = adzuna.refresh_adzuna(db, settings, client=_client({"remote": pages}, calls), max_pages=3)
        assert len([c for c in calls if "what_or" in c]) == 3
        assert fetch.settings_fingerprint == adzuna.settings_fingerprint(settings)
        assert adzuna.needs_refresh(db, settings) is False


class TestLocalRuleFile:
    def test_missing_file_gives_code_defaults(self, tmp_path):
        lists = posting_rules.default_rule_lists(tmp_path / "absent.toml")
        assert lists["title_exclude"] == posting_rules.DEFAULT_TITLE_EXCLUDE

    def test_defined_lists_replace_defaults_others_kept(self, tmp_path):
        path = tmp_path / "rules.toml"
        path.write_text('company_blocklist = ["Globex", " Initech ", ""]\nsignal_terms = []\n')
        lists = posting_rules.default_rule_lists(path)
        assert lists["company_blocklist"] == ["Globex", "Initech"]
        assert lists["signal_terms"] == []
        assert lists["title_exclude"] == posting_rules.DEFAULT_TITLE_EXCLUDE

    @pytest.mark.parametrize("content", ['title_exlude = ["x"]', 'title_exclude = "x"', "not toml ["])
    def test_malformed_file_raises(self, tmp_path, content):
        path = tmp_path / "rules.toml"
        path.write_text(content)
        with pytest.raises(ValueError):
            posting_rules.default_rule_lists(path)

    def test_new_settings_are_seeded_from_local_file(self, db, tmp_path, monkeypatch):
        from app import config
        from app.services.adzuna_settings import default_adzuna_settings

        path = tmp_path / "rules.toml"
        path.write_text('company_blocklist = ["Globex"]\n')
        monkeypatch.setattr(config, "POSTING_RULES_FILE", str(path))
        assert default_adzuna_settings().company_blocklist == "Globex"
