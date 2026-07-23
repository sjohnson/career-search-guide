from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine, SessionLocal
from app.config import DEFAULT_MISSION
from app.models import AdzunaSettings, Settings
from app.routers import daily, import_data, learning_tasks, master_tasks, opportunities, settings
from app.services.adzuna_settings import default_adzuna_settings
from app.services.schema_migration import run_schema_migration

app = FastAPI(title="Career Search Guide")
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(daily.router)
app.include_router(master_tasks.router)
app.include_router(learning_tasks.router)
app.include_router(opportunities.router)
app.include_router(import_data.router)
app.include_router(settings.router)


@app.on_event("startup")
def startup() -> None:
    db = SessionLocal()
    try:
        run_schema_migration(db)
    finally:
        db.close()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if not db.query(Settings).first():
            db.add(Settings(mission_statement=DEFAULT_MISSION))
            db.commit()
        if not db.query(AdzunaSettings).first():
            db.add(default_adzuna_settings())
            db.commit()
    finally:
        db.close()
