# Career Search Guide

A local-first app that pulls your job search into one place — daily tasks, longer-horizon work, learning, and opportunities — so you spend less time switching between spreadsheets, notes, and job boards and more time acting on the roles that matter most.

Built to replace (or complement) a Google Sheet workflow with a single, fast UI for tracking what to do today and which companies deserve follow-up.

## What it does

| Area | Purpose |
|------|---------|
| **Daily Plan** | Date-scoped to-do list (Mon–Sat). Master and learning tasks auto-appear when due; drag to reorder; goal vs requirement markers. |
| **Master Tasks** | Bigger career-search work with target dates — feeds the daily plan automatically. |
| **Learning Tasks** | Skills and resources to study, with the same due-date → daily plan flow. |
| **Opportunities** | Companies, postings, pipeline stage, salary, highlights, and notes — your active search pipeline in one table. |
| **Import** | One-shot migration from an existing Google Sheet export (.xlsx). |

### Opportunities highlights

- **New vs Follow Up** — New leads stay in the main table; once you apply or move forward, rows shift to a Follow Up section sorted by last activity (oldest first).
- **Gold / silver / bronze pins** — Mark your top three prospects; they sort to the top of the New list.
- **Inline editing** — Pipeline stage, remote status, source, stack, and more update in place via HTMX (no full-page reloads).
- **Adzuna job feed** (optional) — Merged searches for remote US plus Salt Lake City, Virginia, and Charlotte metros. Add a listing to your pipeline in one click. Configure search terms and result limits via the gear icon; API keys live in `.env`.
- **Archive** — Passed and closed roles archive automatically; everything else can be archived manually.

## Stack

- Python 3.11+ / FastAPI
- Jinja2 + HTMX (server-rendered UI, no React)
- SQLite (single file in `data/`)
- SortableJS for drag-and-drop task ordering

## Setup

```bash
git clone https://github.com/sjohnson/career-search-guide.git
cd career-search-guide
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `SECRET_KEY` in `.env` (required for session cookies). Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

For Adzuna job suggestions, register at [developer.adzuna.com](https://developer.adzuna.com/) and set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env`.

## Run

```bash
source venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000)

On first launch, the app creates `data/career_search.db` and applies the schema via Alembic on startup (`alembic upgrade head`). Schema changes belong in `alembic/versions/`; run `alembic upgrade head` manually if you use CLI-only workflows without starting the web app. Use `alembic check` during development to catch model/migration drift.

**First account:** if no users exist yet, visit `/register` to create one. Otherwise log in at `/login`, or create an account from the CLI:

```bash
python -m app.cli create-user --email you@example.com --allow-existing
```

The app uses signed session cookies (not JWT) and bcrypt password hashing. CORS is intentionally omitted — this is a same-origin server-rendered app.

## Tests

```bash
source venv/bin/activate
pip install -r requirements-dev.txt   # first time only
pytest                                # run all tests
pytest tests/test_opportunities.py    # one file
pytest -k "pipeline"                  # name filter (like RSpec -e)
```

Tests live in `tests/` and cover core service logic plus auth/security behavior. Pytest uses an isolated SQLite file at `data/test.db` (gitignored with `data/`); your dev database at `data/career_search.db` is never touched. Schema is applied via Alembic once per test session; table data is cleared after each test.

Optional: override the database file for CLI workflows with `DATABASE_URL` in `.env` (see `.env.example`).

## Import your Google Sheet

1. Export as `.xlsx` from Google Sheets
2. Go to **Import** in the app
3. Choose a date for Daily Plan rows (defaults to today)
4. Upload the file

Expected sheet tab names: `Daily Plan`, `Master Tasks`, `Learning Tasks`, `Opportunities`.

Import mode is append-only with duplicate warnings.

## Data

SQLite database: `data/career_search.db`

## Docs

See [`docs/design_plan.md`](docs/design_plan.md) for architecture, data model, and feature notes.
