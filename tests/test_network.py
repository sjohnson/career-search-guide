"""Route and service tests for Network contacts.

The behaviour worth pinning here is the derived follow-up queue: who counts as
due, how the three sections partition, and that each action moves people
between them correctly. See `docs/PLANNING.md` for the design.
"""

from datetime import date, timedelta
import uuid

from sqlalchemy import text

from app.database import SessionLocal
from app.models import ContactStatus, Note, NoteableType, NetworkContact, Opportunity
from app.services.auth import create_user
from app.services.daily_plan import get_primary_note_body
from app.services.network import (
    active_contacts,
    clip_text,
    close_thread,
    closed_contacts,
    due_contacts,
    log_contact,
    normalize_cadence_days,
    normalize_contact_method,
    parse_contact_date,
    reopen_thread,
    snooze_contact,
    split_by_due,
)
from tests.conftest import csrf_from_html

TODAY = date.today()


def _login(client) -> None:
    email = f"network-route-{uuid.uuid4().hex}@example.com"
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
    return token


def _add(**kwargs) -> int:
    db = SessionLocal()
    try:
        contact = NetworkContact(**kwargs)
        db.add(contact)
        db.commit()
        return contact.id
    finally:
        db.close()


def _get(contact_id: int) -> NetworkContact:
    db = SessionLocal()
    try:
        contact = db.get(NetworkContact, contact_id)
        db.refresh(contact)
        return contact
    finally:
        db.close()


class TestNetworkService:
    def test_normalize_contact_method(self):
        assert normalize_contact_method("Email") == "email"
        assert normalize_contact_method("in-person") == "in_person"
        assert normalize_contact_method("nope") is None
        assert normalize_contact_method("") is None

    def test_normalize_cadence_days_falls_back_to_default(self):
        assert normalize_cadence_days("30") == 30
        assert normalize_cadence_days(90) == 90
        # Off-preset and junk values must not persist a nonsense cadence.
        assert normalize_cadence_days("13") == 14
        assert normalize_cadence_days("banana") == 14
        assert normalize_cadence_days(None) == 14

    def test_parse_contact_date(self):
        assert parse_contact_date("2026-08-19") == date(2026, 8, 19)
        assert parse_contact_date("not-a-date") is None
        assert parse_contact_date("") is None

    def test_clip_text(self):
        assert clip_text("  Ada  ", 60) == "Ada"
        assert clip_text("x" * 80, 60) == "x" * 60
        assert clip_text("   ", 60) is None


class TestNextTouchDerivation:
    """The core of the redesign: due-ness is computed, never typed."""

    def test_cadence_drives_next_touch(self):
        contact = NetworkContact(name="Ada", last_contact_at=TODAY - timedelta(days=20), cadence_days=14)
        assert contact.next_touch_at == TODAY - timedelta(days=6)
        assert contact.days_overdue == 6
        assert contact.is_due

    def test_longer_cadence_keeps_someone_quiet(self):
        contact = NetworkContact(name="Ada", last_contact_at=TODAY - timedelta(days=20), cadence_days=90)
        assert not contact.is_due
        assert contact.days_overdue == -70

    def test_override_wins_over_cadence(self):
        contact = NetworkContact(
            name="Ada",
            last_contact_at=TODAY - timedelta(days=100),
            cadence_days=14,
            next_touch_override=TODAY + timedelta(days=3),
        )
        assert contact.next_touch_at == TODAY + timedelta(days=3)
        assert not contact.is_due

    def test_never_contacted_is_due_immediately(self):
        """No last_contact_at falls back to created_at, so a quick-added person
        lands in the queue without needing a special case in the sort."""
        contact_id = _add(name="Amy Anderson")
        contact = _get(contact_id)
        assert contact.is_never_contacted
        assert contact.next_touch_at == TODAY
        assert contact.is_due
        assert contact.overdue_label == "not yet contacted"

    def test_closed_thread_is_never_due(self):
        contact = NetworkContact(
            name="Ada",
            last_contact_at=TODAY - timedelta(days=99),
            status=ContactStatus.CLOSED.value,
        )
        assert contact.days_overdue > 0
        assert not contact.is_due

    def test_overdue_label_wording(self):
        base = dict(name="Ada", cadence_days=14)
        assert NetworkContact(**base, last_contact_at=TODAY - timedelta(days=16)).overdue_label == "2d overdue"
        assert NetworkContact(**base, last_contact_at=TODAY - timedelta(days=14)).overdue_label == "due today"
        assert NetworkContact(**base, last_contact_at=TODAY - timedelta(days=10)).overdue_label == "in 4d"


class TestSectionPartitioning:
    def test_due_sorts_most_overdue_first_and_splits(self):
        _add(name="Stale", last_contact_at=TODAY - timedelta(days=60), cadence_days=14)
        _add(name="Middling", last_contact_at=TODAY - timedelta(days=20), cadence_days=14)
        _add(name="Quiet", last_contact_at=TODAY - timedelta(days=2), cadence_days=14)
        _add(name="Finished", last_contact_at=TODAY - timedelta(days=90), status=ContactStatus.CLOSED.value)

        db = SessionLocal()
        try:
            due, scheduled = split_by_due(active_contacts(db))
            closed = closed_contacts(db)
        finally:
            db.close()

        assert [c.name for c in due] == ["Stale", "Middling"]
        assert [c.name for c in scheduled] == ["Quiet"]
        assert [c.name for c in closed] == ["Finished"]

    def test_due_contacts_respects_limit(self):
        for i in range(5):
            _add(name=f"Person {i}", last_contact_at=TODAY - timedelta(days=30 + i), cadence_days=14)
        db = SessionLocal()
        try:
            assert len(due_contacts(db)) == 5
            assert len(due_contacts(db, limit=3)) == 3
        finally:
            db.close()


class TestContactActions:
    def test_log_contact_sets_dates_and_clears_override(self):
        contact = NetworkContact(
            name="Ada",
            last_contact_at=TODAY - timedelta(days=30),
            first_contact_at=date(2026, 1, 1),
            next_touch_override=TODAY - timedelta(days=5),
        )
        log_contact(contact, "linkedin")

        assert contact.last_contact_at == TODAY
        assert contact.last_contact_method == "linkedin"
        assert contact.next_touch_override is None
        # The thread's start date must survive later contacts.
        assert contact.first_contact_at == date(2026, 1, 1)
        assert not contact.is_due

    def test_log_contact_backfills_first_contact(self):
        contact = NetworkContact(name="Ada")
        log_contact(contact, "email")
        assert contact.first_contact_at == TODAY

    def test_log_contact_keeps_existing_method_when_blank(self):
        contact = NetworkContact(name="Ada", last_contact_method="phone")
        log_contact(contact, "")
        assert contact.last_contact_method == "phone"

    def test_snooze_does_not_claim_contact(self):
        """Snooze exists so the panel can be cleared honestly — it must never
        move last_contact_at, or the cadence starts lying."""
        original = TODAY - timedelta(days=30)
        contact = NetworkContact(name="Ada", last_contact_at=original)
        snooze_contact(contact)

        assert contact.last_contact_at == original
        assert contact.next_touch_override == TODAY + timedelta(days=7)
        assert not contact.is_due

    def test_close_then_reopen_round_trip(self):
        contact = NetworkContact(name="Ada", last_contact_at=TODAY - timedelta(days=30))
        close_thread(contact)
        assert contact.status == ContactStatus.CLOSED.value
        assert not contact.is_due

        reopen_thread(contact)
        assert contact.status == ContactStatus.ACTIVE.value
        assert contact.next_touch_override == TODAY
        assert contact.is_due


class TestNetworkRoutes:
    def test_list_requires_login(self, client):
        client.cookies.clear()
        response = client.get("/network", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_list_renders_three_sections(self, client):
        _login(client)
        _add(name="Due Person", last_contact_at=TODAY - timedelta(days=30))
        _add(name="Quiet Person", last_contact_at=TODAY - timedelta(days=1))
        _add(name="Closed Person", status=ContactStatus.CLOSED.value)

        html = client.get("/network").text
        assert 'id="network-reach-out"' in html
        assert 'id="network-scheduled"' in html
        assert 'id="network-closed"' in html
        for name in ["Due Person", "Quiet Person", "Closed Person"]:
            assert name in html

    def test_reach_out_panel_collapses_the_overflow(self, client):
        _login(client)
        for i in range(6):
            _add(name=f"Overdue {i}", last_contact_at=TODAY - timedelta(days=30 + i))

        html = client.get("/network").text
        # 3 shown, 3 behind the disclosure.
        assert "3 more due" in html
        assert "<details" in html

    def test_quick_add_creates_a_due_contact(self, client):
        token = _login(client)
        response = client.post(
            "/network/quick-add",
            data={"name": "Amy Anderson", "affiliation": "Referrer", "csrf_token": token},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text

        db = SessionLocal()
        try:
            created = db.query(NetworkContact).filter(NetworkContact.name == "Amy Anderson").one()
            assert created.affiliation == "Referrer"
            assert created.is_due
        finally:
            db.close()

    def test_quick_add_ignores_a_blank_name(self, client):
        token = _login(client)
        client.post("/network/quick-add", data={"name": "   ", "csrf_token": token}, follow_redirects=False)
        db = SessionLocal()
        try:
            assert db.query(NetworkContact).count() == 0
        finally:
            db.close()

    def test_htmx_actions_repaint_all_three_sections(self, client):
        """Every action can move someone between sections, so each response
        must carry all three out-of-band swaps — a missing target id is how
        rows go stale or vanish in this app."""
        token = _login(client)
        contact_id = _add(name="Ada", last_contact_at=TODAY - timedelta(days=30))
        headers = {"HX-Request": "true", "X-CSRF-Token": token}

        for path, data in [
            (f"/network/{contact_id}/log-contact", {"method": "email"}),
            (f"/network/{contact_id}/snooze", {}),
            (f"/network/{contact_id}/close", {}),
            (f"/network/{contact_id}/reopen", {}),
            (f"/network/{contact_id}/cadence", {"cadence_days": "30"}),
            ("/network/quick-add", {"name": "Quick Person"}),
        ]:
            response = client.post(path, data=data, headers=headers)
            assert response.status_code == 200, f"{path}: {response.text[:200]}"
            for section in ["reach-out", "scheduled", "closed"]:
                assert f'id="network-{section}" hx-swap-oob="true"' in response.text, (
                    f"{path} did not repaint {section}"
                )

    def test_log_contact_moves_person_out_of_reach_out(self, client):
        token = _login(client)
        contact_id = _add(name="Chad Oliver", last_contact_at=TODAY - timedelta(days=30))
        headers = {"HX-Request": "true", "X-CSRF-Token": token}

        client.post(f"/network/{contact_id}/log-contact", data={"method": "linkedin"}, headers=headers)

        contact = _get(contact_id)
        assert contact.last_contact_at == TODAY
        assert contact.last_contact_method == "linkedin"
        assert not contact.is_due

    def test_close_and_reopen_via_routes(self, client):
        token = _login(client)
        contact_id = _add(name="Kevin Chin", last_contact_at=TODAY - timedelta(days=30))
        headers = {"HX-Request": "true", "X-CSRF-Token": token}

        client.post(f"/network/{contact_id}/close", headers=headers)
        assert _get(contact_id).status == ContactStatus.CLOSED.value

        client.post(f"/network/{contact_id}/reopen", headers=headers)
        contact = _get(contact_id)
        assert contact.status == ContactStatus.ACTIVE.value
        assert contact.is_due

    def test_create_contact_via_full_form(self, client):
        _login(client)
        db = SessionLocal()
        try:
            opp = Opportunity(company="NextLink Labs")
            db.add(opp)
            db.commit()
            opp_id = opp.id
        finally:
            db.close()

        token = csrf_from_html(client.get("/network/new").text)
        response = client.post(
            "/network",
            data={
                "name": "Ada Lovelace",
                "affiliation": "PyCon",
                "linkedin_url": "https://linkedin.com/in/ada",
                "opportunity_id": str(opp_id),
                "first_contact_at": "2026-01-15",
                "last_contact_at": "2026-08-20",
                "last_contact_method": "linkedin",
                "cadence_days": "30",
                "notes": "Ask about the compiler role",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text

        db = SessionLocal()
        try:
            created = db.query(NetworkContact).filter(NetworkContact.name == "Ada Lovelace").one()
            assert created.affiliation == "PyCon"
            assert created.linkedin_url == "https://linkedin.com/in/ada"
            assert created.opportunity_id == opp_id
            assert created.first_contact_at == date(2026, 1, 15)
            assert created.last_contact_at == date(2026, 8, 20)
            assert created.last_contact_method == "linkedin"
            assert created.cadence_days == 30
            note = get_primary_note_body(db, NoteableType.NETWORK_CONTACT.value, created.id)
            assert note == "Ask about the compiler role"
        finally:
            db.close()

        html = client.get("/network").text
        assert "Ada Lovelace" in html
        assert "PyCon" in html
        assert 'href="https://linkedin.com/in/ada"' in html
        assert "NextLink Labs" in html

    def test_edit_and_delete_clears_notes(self, client):
        _login(client)
        token = csrf_from_html(client.get("/network/new").text)
        client.post(
            "/network",
            data={"name": "Grace Hopper", "last_contact_method": "email", "notes": "COBOL chat", "csrf_token": token},
            follow_redirects=False,
        )
        db = SessionLocal()
        try:
            contact_id = db.query(NetworkContact).filter(NetworkContact.name == "Grace Hopper").one().id
        finally:
            db.close()

        token = csrf_from_html(client.get(f"/network/{contact_id}/edit").text)
        response = client.post(
            f"/network/{contact_id}",
            data={"name": "Grace Hopper", "last_contact_method": "phone", "notes": "Call next week", "csrf_token": token},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text

        db = SessionLocal()
        try:
            contact = db.get(NetworkContact, contact_id)
            assert contact.last_contact_method == "phone"
            assert get_primary_note_body(db, NoteableType.NETWORK_CONTACT.value, contact_id) == "Call next week"
        finally:
            db.close()

        token = csrf_from_html(client.get("/network").text)
        response = client.post(
            f"/network/{contact_id}/delete", data={"csrf_token": token}, follow_redirects=False
        )
        assert response.status_code == 303, response.text

        db = SessionLocal()
        try:
            assert db.get(NetworkContact, contact_id) is None
            leftover = (
                db.query(Note)
                .filter(
                    Note.noteable_type == NoteableType.NETWORK_CONTACT.value,
                    Note.noteable_id == contact_id,
                )
                .all()
            )
            assert leftover == []
        finally:
            db.close()

    def test_foreign_keys_are_enforced_after_earlier_tests(self):
        """Guards the pragma restore in tests/conftest.py.

        Cleanup disables foreign keys to truncate in any order, on a pooled
        connection. If it is not turned back on, every ondelete rule in the
        schema silently stops being enforced for the rest of the run — and
        only the first test in a session would notice.
        """
        db = SessionLocal()
        try:
            assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
        finally:
            db.close()

    def test_deleting_an_opportunity_clears_the_link(self, client):
        """The FK is ON DELETE SET NULL so a removed opportunity must not take
        the person with it."""
        _login(client)
        db = SessionLocal()
        try:
            opp = Opportunity(company="Doomed Corp")
            db.add(opp)
            db.commit()
            contact = NetworkContact(name="Linked Person", opportunity_id=opp.id)
            db.add(contact)
            db.commit()
            contact_id, opp_id = contact.id, opp.id
        finally:
            db.close()

        db = SessionLocal()
        try:
            db.execute(Opportunity.__table__.delete().where(Opportunity.id == opp_id))
            db.commit()
        finally:
            db.close()

        contact = _get(contact_id)
        assert contact is not None
        assert contact.opportunity_id is None

    def test_create_rejects_missing_csrf(self, client):
        _login(client)
        response = client.post("/network", data={"name": "No Token"}, follow_redirects=False)
        assert response.status_code == 403, response.text

    def test_quick_add_rejects_missing_csrf(self, client):
        _login(client)
        response = client.post("/network/quick-add", data={"name": "No Token"}, follow_redirects=False)
        assert response.status_code == 403, response.text


class TestDailyPlanNudge:
    def test_nudge_lists_due_contacts_on_todays_plan(self, client):
        _login(client)
        for i in range(5):
            _add(name=f"Due {i}", last_contact_at=TODAY - timedelta(days=30 + i))

        html = client.get(f"/daily/{TODAY.isoformat()}").text
        assert "reach-out-nudge" in html
        assert "5 due" in html
        # Capped at 3 names plus an overflow count, not the whole backlog.
        assert "+2 more" in html
        assert 'href="/network"' in html

    def test_nudge_absent_when_nobody_is_due(self, client):
        _login(client)
        _add(name="Quiet Person", last_contact_at=TODAY - timedelta(days=1))
        html = client.get(f"/daily/{TODAY.isoformat()}").text
        assert "reach-out-nudge" not in html

    def test_nudge_absent_on_a_non_today_plan(self, client):
        _login(client)
        _add(name="Due Person", last_contact_at=TODAY - timedelta(days=30))
        past = TODAY - timedelta(days=6)
        html = client.get(f"/daily/{past.isoformat()}").text
        assert "reach-out-nudge" not in html
