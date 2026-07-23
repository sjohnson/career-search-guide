import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR / 'career_search.db'}"
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

DEFAULT_MISSION = (
    "Land a meaningful role where my skills create real impact — "
    "one focused step at a time."
)

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
ADZUNA_CACHE_TTL_SECONDS = 4 * 60 * 60
ADZUNA_SALARY_MIN = 140_000
ADZUNA_RESULTS_LIMIT = 10
ADZUNA_SEARCH_WHAT = "senior software engineer"
ADZUNA_SEARCH_WHAT_AND = "ruby"
ADZUNA_SEARCH_WHAT_OR = "remote"
ADZUNA_SLC_WHERE = "Salt Lake City"
ADZUNA_SLC_DISTANCE = 30
ADZUNA_VA_WHERE = "Virginia"
ADZUNA_VA_DISTANCE = 50
ADZUNA_CHARLOTTE_WHERE = "Charlotte"
ADZUNA_CHARLOTTE_DISTANCE = 30
ADZUNA_STACK_DEFAULT = "Ruby"
