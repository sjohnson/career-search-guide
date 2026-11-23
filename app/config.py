import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Personal posting-rule term lists (gitignored); see posting_rules.example.toml.
POSTING_RULES_FILE = os.getenv("POSTING_RULES_FILE", str(BASE_DIR / "posting_rules.local.toml"))

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'career_search.db'}")
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

DEFAULT_MISSION = (
    "Land a meaningful role where my skills create real impact — "
    "one focused step at a time."
)

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")

SECRET_KEY = os.getenv("SECRET_KEY", "")
ALLOW_REGISTRATION = os.getenv("ALLOW_REGISTRATION", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

IMPORT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# How old the latest Adzuna fetch may get before a page load triggers a new one.
ADZUNA_CACHE_TTL_SECONDS = 4 * 60 * 60
ADZUNA_RESULTS_PER_PAGE = 50  # Adzuna's maximum page size
ADZUNA_MAX_PAGES_LIMIT = 3  # 4 buckets x 3 pages = 12 calls, under the 15/minute cap
# Adzuna trial-plan limits, as (window in seconds, max calls). Enforced over
# rolling windows, which is at least as strict as calendar ones.
ADZUNA_QUOTA_WINDOWS = (
    ("minute", 60, 15),
    ("day", 24 * 60 * 60, 150),
    ("week", 7 * 24 * 60 * 60, 750),
    ("month", 30 * 24 * 60 * 60, 1500),
)
# Stored postings not seen by a refresh in this many days drop out of the panel.
POSTING_VISIBLE_DAYS = 30
ADZUNA_SALARY_MIN = 140_000
ADZUNA_RESULTS_LIMIT = 10
ADZUNA_SEARCH_WHAT = ""
ADZUNA_SEARCH_WHAT_AND = "ruby"
ADZUNA_SEARCH_WHAT_OR = "remote"
ADZUNA_SLC_WHERE = "Salt Lake City"
ADZUNA_SLC_DISTANCE = 30
ADZUNA_VA_WHERE = "Virginia"
ADZUNA_VA_DISTANCE = 50
ADZUNA_CHARLOTTE_WHERE = "Charlotte"
ADZUNA_CHARLOTTE_DISTANCE = 30
ADZUNA_STACK_DEFAULT = "Ruby"
