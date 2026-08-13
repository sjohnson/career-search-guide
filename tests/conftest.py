import os
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent

TABLES_TO_TRUNCATE = [
    "daily_plan_items",
    "daily_plan_dismissals",
    "notes",
    "opportunities",
    "master_tasks",
    "learning_tasks",
    "daily_plans",
    "users",
    "settings",
    "adzuna_settings",
]


def pytest_configure(config) -> None:
    test_db = ROOT / "data" / "test.db"
    test_db.unlink(missing_ok=True)
    os.environ["DATABASE_URL"] = "sqlite:///./data/test.db"
    os.environ["TESTING"] = "1"
    os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")

    alembic_config = Config(str(ROOT / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(alembic_config, "head")


def csrf_from_html(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "CSRF token input not found in HTML"
    return match.group(1)


@pytest.fixture(autouse=True)
def clean_database():
    from app.database import SessionLocal

    yield
    db = SessionLocal()
    try:
        db.execute(text("PRAGMA foreign_keys=OFF"))
        for table in TABLES_TO_TRUNCATE:
            db.execute(text(f"DELETE FROM {table}"))
        db.commit()
    finally:
        db.close()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
