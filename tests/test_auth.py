import uuid

from app.database import SessionLocal
from app.services.auth import (
    authenticate_user,
    create_user,
    registration_allowed,
    validate_password,
)


class TestAuthService:
    def test_validate_password_requires_minimum_length(self):
        assert validate_password("short") is not None
        assert validate_password("longenough") is None

    def test_create_and_authenticate_user(self):
        db = SessionLocal()
        email = "unit-auth-service@example.com"
        try:
            user = create_user(db, email, "password123")
            assert user.id is not None

            authed = authenticate_user(db, email, "password123")
            assert authed is not None
            assert authed.email == email

            assert authenticate_user(db, email, "wrong-password") is None
        finally:
            db.close()

    def test_registration_allowed_when_empty_or_flag_set(self):
        db = SessionLocal()
        try:
            assert registration_allowed(db, allow_registration=False)
            assert registration_allowed(db, allow_registration=True)
        finally:
            db.close()


class TestAuthRoutes:
    def test_login_page_loads(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        assert "Log in" in response.text

    def test_protected_route_redirects_to_login(self, client):
        client.cookies.clear()
        response = client.get("/master-tasks", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_login_success_grants_access(self, client):
        db = SessionLocal()
        email = f"route-auth-{uuid.uuid4().hex}@example.com"
        password = "password123"
        try:
            create_user(db, email, password)
        finally:
            db.close()

        from tests.conftest import csrf_from_html

        login_page = client.get("/login")
        token = csrf_from_html(login_page.text)
        response = client.post(
            "/login",
            data={"email": email, "password": password, "csrf_token": token},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text

        home = client.get("/")
        assert home.status_code == 200
        assert "Daily Plan" in home.text

    def test_register_blocked_when_users_exist_and_flag_off(self, client):
        db = SessionLocal()
        try:
            create_user(db, "bootstrap-user@example.com", "password123")
        finally:
            db.close()

        response = client.get("/register", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
