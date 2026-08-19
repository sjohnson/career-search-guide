from datetime import date
import re
import uuid

import pytest

from app.database import SessionLocal
from app.models import Opportunity, OpportunityLifecycle, PipelineStage
from app.services.auth import create_user
from app.services.opportunities import (
    format_salary,
    normalize_pipeline_stage,
    normalize_remote_status,
    normalize_source,
    paginate_active,
    pipeline_stage_with_applied_date,
    section_for_stage,
    split_active_opportunities,
)
from tests.conftest import csrf_from_html


def _opp(*, stage: str, lifecycle: str = OpportunityLifecycle.ACTIVE.value) -> Opportunity:
    return Opportunity(
        company="Acme",
        pipeline_stage=stage,
        lifecycle_status=lifecycle,
    )


class TestNormalizePipelineStage:
    def test_maps_follow_up_variants(self):
        assert normalize_pipeline_stage("Follow Up") == PipelineStage.FOLLOW_UP.value
        assert normalize_pipeline_stage("follow-up") == PipelineStage.FOLLOW_UP.value

    def test_defaults_blank_to_new(self):
        assert normalize_pipeline_stage(None) == PipelineStage.NEW.value
        assert normalize_pipeline_stage("") == PipelineStage.NEW.value


class TestPipelineStageWithAppliedDate:
    def test_promotes_new_to_applied_when_date_present(self):
        applied = date(2026, 1, 15)
        assert pipeline_stage_with_applied_date(PipelineStage.NEW.value, applied) == (
            PipelineStage.APPLIED.value
        )

    def test_leaves_stage_when_no_applied_date(self):
        assert pipeline_stage_with_applied_date(PipelineStage.NEW.value, None) == (
            PipelineStage.NEW.value
        )

    def test_does_not_change_non_new_stages(self):
        assert pipeline_stage_with_applied_date(PipelineStage.INTERVIEWING.value, date.today()) == (
            PipelineStage.INTERVIEWING.value
        )


class TestNormalizeRemoteStatusAndSource:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Remote", "remote"),
            ("On-Site", "on_site"),
            ("  hybrid  ", "hybrid"),
            ("unknown", None),
            (None, None),
        ],
    )
    def test_normalize_remote_status(self, raw, expected):
        assert normalize_remote_status(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Hacker News", "hacker_news"),
            ("RubyOnRemote", "ruby_on_remote"),
            ("LinkedIn", "linkedin"),
            ("nope", None),
        ],
    )
    def test_normalize_source(self, raw, expected):
        assert normalize_source(raw) == expected


class TestSectionForStage:
    def test_new_stage(self):
        assert section_for_stage(PipelineStage.NEW.value) == "new"

    def test_follow_up_stages(self):
        for stage in (PipelineStage.APPLIED, PipelineStage.INTERVIEWING, PipelineStage.OFFER):
            assert section_for_stage(stage.value) == "follow_up"

    def test_archived_stages(self):
        assert section_for_stage(PipelineStage.PASSED.value) == "archived"
        assert section_for_stage(PipelineStage.CLOSED.value) == "archived"


class TestSplitActiveOpportunities:
    def test_splits_new_from_follow_up(self):
        active = [
            _opp(stage=PipelineStage.NEW.value),
            _opp(stage=PipelineStage.APPLIED.value),
            _opp(stage=PipelineStage.INTERVIEWING.value),
        ]
        new_opps, follow_up = split_active_opportunities(active)
        assert len(new_opps) == 1
        assert new_opps[0].pipeline_stage == PipelineStage.NEW.value
        assert len(follow_up) == 2


class TestFormatSalary:
    def test_range(self):
        assert format_salary(80_000, 120_000, "USD") == "$80k–$120k USD"

    def test_min_only(self):
        assert format_salary(95_000, None, "USD") == "$95k+ USD"

    def test_empty(self):
        assert format_salary(None, None, None) == "—"


class TestPaginateActive:
    def test_second_page(self):
        opps = [_opp(stage=PipelineStage.NEW.value) for _ in range(9)]
        page_items, total, total_pages, page = paginate_active(opps, page=2, per_page=7)
        assert total == 9
        assert total_pages == 2
        assert page == 2
        assert len(page_items) == 2

    def test_clamps_page_below_one(self):
        opps = [_opp(stage=PipelineStage.NEW.value)]
        _, _, _, page = paginate_active(opps, page=0)
        assert page == 1


def _login(client) -> None:
    email = f"opp-route-{uuid.uuid4().hex}@example.com"
    password = "password123"
    db = SessionLocal()
    try:
        create_user(db, email, password)
    finally:
        db.close()

    token = csrf_from_html(client.get("/login").text)
    resp = client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def _create_opp(company: str, stage: str) -> int:
    db = SessionLocal()
    try:
        opp = Opportunity(
            company=company,
            pipeline_stage=stage,
            lifecycle_status=OpportunityLifecycle.ACTIVE.value,
        )
        db.add(opp)
        db.commit()
        db.refresh(opp)
        return opp.id
    finally:
        db.close()


def _tbody_open_tags(html: str) -> list[str]:
    return re.findall(r"<tbody\b[^>]*>", html)


class TestPipelineStageSwapHtml:
    def test_list_pipeline_selects_use_swap_none(self, client):
        _login(client)
        _create_opp("Swap None Co", PipelineStage.APPLIED.value)
        html = client.get("/opportunities").text
        assert 'hx-swap="none"' in html
        assert 'id="follow-up-body"' in html

    def test_section_change_returns_only_oob_tbodies(self, client):
        _login(client)
        _create_opp("New Table Co", PipelineStage.NEW.value)
        follow_id = _create_opp("Follow Table Co", PipelineStage.APPLIED.value)
        token = csrf_from_html(client.get("/opportunities").text)

        response = client.patch(
            f"/opportunities/{follow_id}/pipeline-stage",
            data={"pipeline_stage": PipelineStage.NEW.value, "csrf_token": token},
        )
        assert response.status_code == 200, response.text
        html = response.text

        tbodies = _tbody_open_tags(html)
        assert tbodies
        assert all("hx-swap-oob" in tag for tag in tbodies)
        assert 'id="opportunities-active-body" hx-swap-oob="true"' in html
        assert 'id="follow-up-body" hx-swap-oob="true"' in html
        assert not re.search(r'<span id="pipeline-\d+"></span>', html)
        assert not re.search(r"^(\s|<span)[^<]*<tr\b", html.lstrip())

    def test_new_to_follow_up_returns_only_oob_tbodies(self, client):
        _login(client)
        new_id = _create_opp("Promote Co", PipelineStage.NEW.value)
        token = csrf_from_html(client.get("/opportunities").text)

        response = client.patch(
            f"/opportunities/{new_id}/pipeline-stage",
            data={"pipeline_stage": PipelineStage.APPLIED.value, "csrf_token": token},
        )
        assert response.status_code == 200, response.text
        html = response.text

        tbodies = _tbody_open_tags(html)
        assert tbodies
        assert all("hx-swap-oob" in tag for tag in tbodies)
        assert 'id="follow-up-body" hx-swap-oob="true"' in html

    def test_same_section_cell_is_oob(self, client):
        _login(client)
        opp_id = _create_opp("Stay Follow Up Co", PipelineStage.APPLIED.value)
        token = csrf_from_html(client.get("/opportunities").text)

        response = client.patch(
            f"/opportunities/{opp_id}/pipeline-stage",
            data={"pipeline_stage": PipelineStage.INTERVIEWING.value, "csrf_token": token},
        )
        assert response.status_code == 200, response.text
        html = response.text
        assert f'id="pipeline-{opp_id}"' in html
        assert 'hx-swap-oob="true"' in html
        assert "<tbody" not in html

    def test_section_change_wraps_oob_in_templates(self, client):
        _login(client)
        follow_id = _create_opp("Template Wrap Co", PipelineStage.APPLIED.value)
        token = csrf_from_html(client.get("/opportunities").text)

        response = client.patch(
            f"/opportunities/{follow_id}/pipeline-stage",
            data={"pipeline_stage": PipelineStage.NEW.value, "csrf_token": token},
        )
        assert response.status_code == 200, response.text
        html = response.text
        assert html.count("<template>") >= 4
        assert re.search(
            r'<div id="archived-section"[^>]*hx-swap-oob="true"',
            html,
        )
        assert not re.search(r"<details[^>]*id=\"archived-section\"", html)

    def test_archive_stage_oob_targets_wrapper(self, client):
        _login(client)
        follow_id = _create_opp("Archive From Follow Up", PipelineStage.APPLIED.value)
        token = csrf_from_html(client.get("/opportunities").text)

        response = client.patch(
            f"/opportunities/{follow_id}/pipeline-stage",
            data={"pipeline_stage": PipelineStage.PASSED.value, "csrf_token": token},
        )
        assert response.status_code == 200, response.text
        html = response.text
        assert re.search(
            r'<div id="archived-section"[^>]*hx-swap-oob="true"',
            html,
        )
        assert "Archived opportunities (1)" in html
        assert "<template>" in html

    def test_list_archived_wrapper_is_a_div(self, client):
        _login(client)
        html = client.get("/opportunities").text
        assert re.search(r'<div id="archived-section">', html)
        assert "<details class=\"archived-section card\">" in html
