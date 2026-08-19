"""Route and service tests for Network contacts."""

from datetime import date
import uuid

from app.database import SessionLocal
from app.models import Note, NoteableType, NetworkContact
from app.services.auth import create_user
from app.services.daily_plan import get_primary_note_body
from app.services.network import (
    clip_text,
    normalize_contact_method,
    opportunity_link_parts,
    parse_contact_date,
    sort_network_contacts,
)
from tests.conftest import csrf_from_html


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


class TestNetworkService:
    def test_normalize_contact_method(self):
        assert normalize_contact_method("Email") == "email"
        assert normalize_contact_method("in-person") == "in_person"
        assert normalize_contact_method("nope") is None
        assert normalize_contact_method("") is None

    def test_parse_contact_date(self):
        assert parse_contact_date("2026-08-19") == date(2026, 8, 19)
        assert parse_contact_date("not-a-date") is None
        assert parse_contact_date("") is None

    def test_clip_text(self):
        assert clip_text("  Ada  ", 60) == "Ada"
        assert clip_text("x" * 80, 60) == "x" * 60
        assert clip_text("   ", 60) is None

    def test_opportunity_link_parts(self):
        parts = opportunity_link_parts(
            "https://example.com/job, not-a-url https://jobs.example.com/x"
        )
        assert [part["is_url"] for part in parts] == [True, False, True]
        assert parts[0]["text"] == "https://example.com/job"

    def test_sort_followup_nulls_last(self):
        db = SessionLocal()
        try:
            later = NetworkContact(name="Zoe", followup_contact_at=date(2026, 9, 1))
            sooner = NetworkContact(name="Ada", followup_contact_at=date(2026, 8, 1))
            missing = NetworkContact(name="Mia")
            db.add_all([later, sooner, missing])
            db.commit()
            ordered = sort_network_contacts(db.query(NetworkContact)).all()
            assert [c.name for c in ordered] == ["Ada", "Zoe", "Mia"]
        finally:
            db.close()


class TestNetworkRoutes:
    def test_list_requires_login(self, client):
        client.cookies.clear()
        response = client.get("/network", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_nav_includes_network(self, client):
        _login(client)
        html = client.get("/network").text
        assert 'href="/network"' in html
        assert "Network" in html

    def test_create_contact_via_form(self, client):
        _login(client)
        token = csrf_from_html(client.get("/network/new").text)
        response = client.post(
            "/network",
            data={
                "name": "Ada Lovelace",
                "connection": "PyCon, https://linkedin.com/in/ada",
                "first_contact_at": "2026-01-15",
                "followup_contact_at": "2026-08-20",
                "method": "linkedin",
                "opportunities": "https://example.com/job other-text",
                "notes": "Ask about the compiler role",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        assert response.headers["location"] == "/network"

        db = SessionLocal()
        try:
            created = db.query(NetworkContact).filter(NetworkContact.name == "Ada Lovelace").one()
            assert created.connection.startswith("PyCon")
            assert created.first_contact_at == date(2026, 1, 15)
            assert created.followup_contact_at == date(2026, 8, 20)
            assert created.method == "linkedin"
            note = get_primary_note_body(db, NoteableType.NETWORK_CONTACT.value, created.id)
            assert note == "Ask about the compiler role"
        finally:
            db.close()

        html = client.get("/network").text
        assert "Ada Lovelace" in html
        assert "2026-01-15" in html
        assert "2026-08-20" in html
        assert "LinkedIn" in html
        assert 'href="https://example.com/job"' in html
        assert "other-text" in html
        assert "Ask about the compiler role" in html

    def test_edit_and_delete_clears_notes(self, client):
        _login(client)
        token = csrf_from_html(client.get("/network/new").text)
        client.post(
            "/network",
            data={
                "name": "Grace Hopper",
                "method": "email",
                "notes": "COBOL chat",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        db = SessionLocal()
        try:
            contact = db.query(NetworkContact).filter(NetworkContact.name == "Grace Hopper").one()
            contact_id = contact.id
        finally:
            db.close()

        token = csrf_from_html(client.get(f"/network/{contact_id}/edit").text)
        response = client.post(
            f"/network/{contact_id}",
            data={
                "name": "Grace Hopper",
                "method": "phone",
                "notes": "Call next week",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text

        db = SessionLocal()
        try:
            contact = db.get(NetworkContact, contact_id)
            assert contact.method == "phone"
            assert get_primary_note_body(db, NoteableType.NETWORK_CONTACT.value, contact_id) == "Call next week"
        finally:
            db.close()

        token = csrf_from_html(client.get("/network").text)
        response = client.post(
            f"/network/{contact_id}/delete",
            data={"csrf_token": token},
            follow_redirects=False,
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

    def test_create_rejects_missing_csrf(self, client):
        _login(client)
        response = client.post(
            "/network",
            data={"name": "No Token"},
            follow_redirects=False,
        )
        assert response.status_code == 403, response.text
