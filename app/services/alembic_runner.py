"""Run Alembic migrations programmatically on app startup."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.database import engine


def run_alembic_upgrade() -> None:
    # Release pooled SQLite connections so Alembic can acquire the write lock.
    engine.dispose()
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    command.upgrade(config, "head")
