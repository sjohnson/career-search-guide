"""Unemployment tab: Sunday-Saturday claim weeks and saving a week's rows."""

import uuid
from datetime import date, timedelta

import pytest

from app.database import SessionLocal
from app.models import UnemploymentContact
from app.services import unemployment
from app.services.auth import create_user
from tests.conftest import csrf_from_html

WEEK = date(2026, 11, 28)  # a Saturday


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _row(**fields) -> unemployment.ContactRow:
    return unemployment.ContactRow(**fields)


def _full(**overrides) -> unemployment.ContactRow:
    values = dict(
        contact_date="2026-11-24",
        company="Globex",
        contact_details="https://jobs.globex.example/42",
        position_title="Senior Ruby Engineer",
        method="Online application",
        result="Applied; awaiting response",
    )
    return _row(**{**values, **overrides})


class TestWeeks:
    @pytest.mark.parametrize(
        "day,expected",
        [
            (date(2026, 11, 22), WEEK),  # Sunday starts the week
            (date(2026, 11, 24), WEEK),  # Tuesday
            (WEEK, WEEK),  # Saturday ends it
            (date(2026, 11, 29), date(2026, 12, 5)),  # next Sunday is a new week
        ],
    )
    def test_week_ending_is_the_saturday(self, day, expected):
        assert unemployment.week_ending_for(day) == expected

    def test_empty_week_shows_four_blank_rows(self, db):
        week = unemployment.build_week(db, WEEK)
        assert len(week.rows) == unemployment.REQUIRED_CONTACTS
        assert all(r.is_blank for r in week.rows)
        assert week.start == date(2026, 11, 22)

    def test_weeks_to_show_this_week_plus_saved_and_requested(self, db):
        old = date(2026, 10, 31)
        unemployment.save_week(db, old, [_full(contact_date="2026-10-27")])
        weeks = unemployment.weeks_to_show(db, today=date(2026, 11, 24), extra=date(2026, 11, 10))
        assert [w.week_ending for w in weeks] == [WEEK, date(2026, 11, 14), old]


class TestSaveWeek:
    def test_saves_filled_rows_and_drops_blank_ones(self, db):
        week = unemployment.save_week(db, WEEK, [_full(), _row(), _full(company="Initech", result=""), _row()])
        assert week.saved_count == 2
        assert week.complete_count == 1
        assert len(week.rows) == 4  # padded back to four
        assert [c.company for c in unemployment.contacts_for_week(db, WEEK)] == ["Globex", "Initech"]

    def test_more_than_four_rows(self, db):
        week = unemployment.save_week(db, WEEK, [_full(company=f"Co {i}") for i in range(6)])
        assert week.saved_count == 6 and len(week.rows) == 6

    def test_edit_and_clear_rows(self, db):
        unemployment.save_week(db, WEEK, [_full(), _full(company="Initech")])
        first, second = unemployment.contacts_for_week(db, WEEK)
        unemployment.save_week(db, WEEK, [_full(id=first.id, result="Interview scheduled"), _row(id=second.id)])
        db.expire_all()
        remaining = unemployment.contacts_for_week(db, WEEK)
        assert [(c.id, c.result) for c in remaining] == [(first.id, "Interview scheduled")]

    def test_date_outside_week_is_rejected_without_saving(self, db):
        week = unemployment.save_week(db, WEEK, [_full(contact_date="2026-11-21")])
        assert week.errors == ["Row 1: Nov 21 is outside this week (Nov 22–Nov 28)."]
        assert week.rows[0].company == "Globex"  # typing kept
        assert db.query(UnemploymentContact).count() == 0

    def test_rows_without_a_date_are_kept(self, db):
        week = unemployment.save_week(db, WEEK, [_full(contact_date="")])
        assert week.saved_count == 1 and week.complete_count == 0


def _login(client) -> None:
    email = f"unemployment-{uuid.uuid4().hex}@example.com"
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
    def test_page_shows_this_week_with_four_rows(self, client):
        _login(client)
        html = client.get("/unemployment").text
        this_week = unemployment.week_ending_for(date.today())
        assert f'id="week-{this_week.isoformat()}"' in html
        assert "This week" in html
        assert html.count('name="company"') == unemployment.REQUIRED_CONTACTS + 1  # + blank-row template
        assert "Contact details<sup>*</sup>" in html
        assert 'href="/unemployment"' in html  # nav link

    def test_save_week_round_trip(self, client, db):
        _login(client)
        page = client.get("/unemployment").text
        data = {
            "csrf_token": csrf_from_html(page),
            "row_id": ["", "", "", ""],
            "contact_date": ["2026-11-24", "", "", ""],
            "company": ["Globex", "", "", ""],
            "contact_details": ["Jane Doe, recruiter", "", "", ""],
            "position_title": ["Senior Ruby Engineer", "", "", ""],
            "method": ["Email", "", "", ""],
            "result": ["Applied; awaiting response", "", "", ""],
        }
        html = client.post(f"/unemployment/weeks/{WEEK.isoformat()}", data=data).text
        assert "Saved" in html and "1 of 4 complete" in html
        contact = db.query(UnemploymentContact).one()
        assert (contact.week_ending, contact.contact_details) == (WEEK, "Jane Doe, recruiter")

        page = client.get(f"/unemployment?week={WEEK.isoformat()}").text
        assert 'value="Jane Doe, recruiter"' in page

    def test_rejects_a_non_saturday_week(self, client):
        _login(client)
        token = csrf_from_html(client.get("/unemployment").text)
        resp = client.post("/unemployment/weeks/2026-11-24", data={"csrf_token": token})
        assert resp.status_code == 404

    def test_requires_csrf(self, client):
        _login(client)
        resp = client.post(f"/unemployment/weeks/{WEEK.isoformat()}", data={"company": ["x"]})
        assert resp.status_code in (400, 403)
