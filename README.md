# Career Search Guide

A local-first career search tracker: Daily Plan hub, Master Tasks, Learning Tasks, Opportunities, and spreadsheet import.

## Stack

- Python 3.11+ / FastAPI
- Jinja2 + HTMX (server-rendered UI, no React)
- SQLite (single file in `data/`)
- SortableJS for drag-and-drop task ordering

## Setup

```bash
cd "/Volumes/Studio Storage/documents/tech/projects/career-search-guide"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000)

## Import your Google Sheet

1. Export as `.xlsx` from Google Sheets
2. Go to **Import** in the app
3. Choose a date for Daily Plan rows (defaults to today)
4. Upload the file

Expected sheet tab names: `Daily Plan`, `Master Tasks`, `Learning Tasks`, `Opportunities`.

## Data

SQLite database: `data/career_search.db`

## Docs

See [`docs/design_plan.md`](docs/design_plan.md) for architecture, data model, and MVP/later feature split.
