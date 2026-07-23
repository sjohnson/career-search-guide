from sqlalchemy.orm import Session

from app.config import (
    ADZUNA_CHARLOTTE_DISTANCE,
    ADZUNA_CHARLOTTE_WHERE,
    ADZUNA_RESULTS_LIMIT,
    ADZUNA_SALARY_MIN,
    ADZUNA_SEARCH_WHAT,
    ADZUNA_SEARCH_WHAT_AND,
    ADZUNA_SEARCH_WHAT_OR,
    ADZUNA_SLC_DISTANCE,
    ADZUNA_SLC_WHERE,
    ADZUNA_STACK_DEFAULT,
    ADZUNA_VA_DISTANCE,
    ADZUNA_VA_WHERE,
)
from app.models import AdzunaSettings


def default_adzuna_settings() -> AdzunaSettings:
    return AdzunaSettings(
        search_what=ADZUNA_SEARCH_WHAT,
        search_what_and=ADZUNA_SEARCH_WHAT_AND,
        search_what_or=ADZUNA_SEARCH_WHAT_OR,
        salary_min=ADZUNA_SALARY_MIN,
        slc_where=ADZUNA_SLC_WHERE,
        slc_distance=ADZUNA_SLC_DISTANCE,
        va_where=ADZUNA_VA_WHERE,
        va_distance=ADZUNA_VA_DISTANCE,
        charlotte_where=ADZUNA_CHARLOTTE_WHERE,
        charlotte_distance=ADZUNA_CHARLOTTE_DISTANCE,
        results_limit=ADZUNA_RESULTS_LIMIT,
        stack_default=ADZUNA_STACK_DEFAULT,
    )


def get_or_create_adzuna_settings(db: Session) -> AdzunaSettings:
    settings = db.query(AdzunaSettings).first()
    if not settings:
        settings = default_adzuna_settings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings
