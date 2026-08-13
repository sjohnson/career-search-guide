import logging
import os
import warnings

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import ALLOW_REGISTRATION, SECRET_KEY, SESSION_HTTPS_ONLY
from app.database import SessionLocal
from app.config import DEFAULT_MISSION
from app.middleware.auth import auth_middleware
from app.middleware.csrf import csrf_middleware
from app.models import AdzunaSettings, Settings
from app.routers import auth, daily, import_data, learning_tasks, master_tasks, opportunities, settings
from app.services.adzuna_settings import default_adzuna_settings
from app.services.alembic_runner import run_alembic_upgrade
from app.services.auth import user_count

logger = logging.getLogger(__name__)

_effective_secret_key = SECRET_KEY
if not _effective_secret_key:
    _effective_secret_key = "dev-insecure-secret-key"
    warnings.warn(
        "SECRET_KEY is not set; using an insecure development default. "
        "Set SECRET_KEY in .env before deploying.",
        stacklevel=1,
    )

app = FastAPI(title="Career Search Guide")
app.middleware("http")(csrf_middleware)
app.middleware("http")(auth_middleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=_effective_secret_key,
    https_only=SESSION_HTTPS_ONLY,
    same_site="lax",
)

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(auth.router)
app.include_router(daily.router)
app.include_router(master_tasks.router)
app.include_router(learning_tasks.router)
app.include_router(opportunities.router)
app.include_router(import_data.router)
app.include_router(settings.router)


@app.on_event("startup")
def startup() -> None:
    if not os.getenv("TESTING"):
        run_alembic_upgrade()
    db = SessionLocal()
    try:
        if not db.query(Settings).first():
            db.add(Settings(mission_statement=DEFAULT_MISSION))
            db.commit()
        if not db.query(AdzunaSettings).first():
            db.add(default_adzuna_settings())
            db.commit()
        if user_count(db) == 0:
            logger.info(
                "No users found. Open /register to create the first account "
                "or run: python -m app.cli create-user"
            )
        elif not ALLOW_REGISTRATION:
            logger.debug("Registration UI disabled; existing user count=%s", user_count(db))
    finally:
        db.close()
