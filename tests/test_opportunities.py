from datetime import date

import pytest

from app.models import Opportunity, OpportunityLifecycle, PipelineStage
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
