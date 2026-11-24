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
    "job_postings",
    "adzuna_fetches",
    "daily_plan_items",
    "daily_plan_dismissals",
    "notes",
    "opportunities",
    "network_contacts",
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
    # Blank (not unset) so load_dotenv, which never overrides existing
    # variables, can't pull the real keys from .env: tests that load the
    # Opportunities page would otherwise spend live Adzuna API calls.
    os.environ["ADZUNA_APP_ID"] = ""
    os.environ["ADZUNA_APP_KEY"] = ""
    # Tests see the code defaults, never the developer's personal lists.
    os.environ["POSTING_RULES_FILE"] = str(ROOT / "tests" / "no-such-posting-rules.toml")

    alembic_config = Config(str(ROOT / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(alembic_config, "head")


def csrf_from_html(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "CSRF token input not found in HTML"
    return match.group(1)


@pytest.fixture(autouse=True)
def clean_database():
    from app.database import engine

    yield
    # Truncation ignores foreign keys so tables can be cleared in any order.
    # The pragma MUST be restored afterwards, on the SAME connection: it is
    # connection scoped, the connection goes back into the pool, and the
    # "connect"-time listener in app.database only fires for brand new
    # connections, so leaving it off silently disables every ondelete rule for
    # the rest of the run. Hence one explicit Connection, not a Session: a
    # Session returns its connection to the pool on commit, and the next
    # statement may check out a different one once the pool holds more than
    # one idle connection.
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            for table in TABLES_TO_TRUNCATE:
                conn.execute(text(f"DELETE FROM {table}"))
            conn.commit()
        finally:
            # Outside any transaction: SQLite treats this pragma as a no-op
            # while one is open.
            conn.rollback()
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.commit()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
