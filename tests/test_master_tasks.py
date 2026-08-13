"""Route tests for master task creation.

Regression coverage for the CSRF body-consumption bug: the old CSRF middleware
called request.form() and consumed the body, so Form(...) fields (like `task`)
arrived empty at the endpoint. These tests exercise the real form POST flow.
"""

import uuid

from app.database import SessionLocal
from app.models import MasterTask
from app.services.auth import create_user
from tests.conftest import csrf_from_html


def _login(client) -> None:
    email = f"mt-route-{uuid.uuid4().hex}@example.com"
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


class TestMasterTaskRoutes:
    def test_create_master_task_via_form(self, client):
        _login(client)

        # The form page carries the current session's CSRF token.
        token = csrf_from_html(client.get("/master-tasks/new").text)

        response = client.post(
            "/master-tasks",
            data={
                "task": "Apply for this Headway position",
                "date_kind": "goal",
                "target_completion_date": "2030-01-01",
                "notes": "",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text

        db = SessionLocal()
        try:
            created = (
                db.query(MasterTask)
                .filter(MasterTask.task == "Apply for this Headway position")
                .one_or_none()
            )
            assert created is not None
            assert created.date_kind == "goal"
        finally:
            db.close()

    def test_create_master_task_rejects_missing_csrf(self, client):
        _login(client)

        response = client.post(
            "/master-tasks",
            data={"task": "No token task", "date_kind": "goal"},
            follow_redirects=False,
        )
        assert response.status_code == 403, response.text
