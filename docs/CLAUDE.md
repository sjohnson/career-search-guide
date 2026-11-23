# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
source venv/bin/activate                                    # all commands assume this

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000  # run (http://127.0.0.1:8000)

pip install -r requirements-dev.txt                         # test deps (first time)
pytest                                                      # all tests
pytest tests/test_opportunities.py                          # one file
pytest tests/test_opportunities.py::TestNormalizePipelineStage::test_defaults_blank_to_new
pytest -k "pipeline"                                        # name filter

alembic upgrade head                                        # apply migrations (also runs on app startup)
alembic check                                               # detect model/migration drift
alembic revision -m "add x"                                 # new migration (then rename per convention below)

python -m app.cli create-user --email you@example.com --allow-existing
```

There is no linter or formatter configured.

## Architecture

FastAPI + Jinja2 + HTMX, server-rendered, SQLite. No SPA, no JSON API, no CORS — every route returns HTML.

**Layering:** `app/routers/*` parse `Form(...)` params and render templates; `app/services/*` hold all domain logic and own DB writes; `app/models.py` is a single SQLAlchemy module with computed display properties (`salary_display`, `DailyPlanItem.is_completed`, `highlight_class`) that templates read directly. Keep logic in services — routers should stay thin and testable through both service calls and `TestClient` route tests.

**Templates:** always render via `app.templating.templates` (not `Jinja2Templates` directly) — the wrapper injects `csrf_token` into every context. Full pages live in `app/templates/<area>/`, HTMX fragments in `app/templates/<area>/partials/` and `app/templates/shared/partials/`.

**HTMX partial protocol:** inline edits return only the changed fragment. When a mutation moves a row between sections (e.g. a pipeline-stage change relocating an opportunity from New to Follow Up), the response is a `*_swap.html` template made of `hx-swap-oob="true"` blocks that repaint several regions at once — the New tbody, Follow Up tbody, pagination, and archived section. See `_pipeline_stage_response` in `app/routers/opportunities.py:123`. Regressions in this area (rows disappearing, duplicating, or becoming unclickable) recur; check that every OOB target id in the swap template exists in the full-page template.

**Security plumbing** (three separate pieces, easy to miss one):
- `app/middleware/auth.py` — gates every path except `/login`, `/register`, `/logout`, `/static`; returns `HX-Redirect` for HTMX requests instead of a 303.
- `app/deps/csrf.py` — `verify_csrf` is attached per-router in `app/main.py`, not globally. **A new router must be included with `dependencies=[Depends(verify_csrf)]`.** It reads the token as a `Form` field so it participates in the endpoint's single body parse; a middleware calling `request.form()` would consume the body first.
- Browser side: `base.html` adds `X-CSRF-Token` to every HTMX request via `htmx:configRequest`; hand-written `fetch()` calls must use the `csrfHeaders()` helper (see `static/js/task_lists.js`).

Auth is login-only — rows are **not** scoped by `user_id`, and there is no per-user authorization layer.

**Schema:** Alembic is authoritative; there is no `create_all`. `app.services.alembic_runner` runs `alembic upgrade head` on startup (skipped when `TESTING` is set) after `engine.dispose()`, since SQLite's pooled connections block the migration write lock. Migration files and revision ids use the `NNN_slug` convention (`006_add_network_contacts`), not generated hashes.

## Domain rules that aren't obvious from the code

- **Daily Plan week is Mon–Sat.** Sunday renders a rest-day view and prev/next navigation skips it. `resolve_today()` returns the next work day on Sundays — prefer it over `date.today()` for plan lookups.
- **Task auto-assignment** happens in three places: on plan creation, when a Master/Learning task's `target_completion_date` is set or changed, and once per day when viewing today's plan (guarded by `daily_plans.last_assigned_at`). Overdue tasks are pulled in on *today's* plan only.
- **Recurring master tasks** complete differently: checking one off on the Daily Plan sets `daily_plan_items.completed_at` and leaves the source task `current`, so it reappears the next work day. Non-recurring tasks update the source task's `status` instead. `DailyPlanItem.is_completed` encodes this fork.
- **Dismissals** (`daily_plan_dismissals`) exist so a task removed from a day isn't re-added by the next auto-assign pass.
- **Opportunities split into three sections by `pipeline_stage`** — `new` (paginated 7/page, highlight ranks 1–3 sort first), the follow-up stages (`applied`/`interviewing`/`follow_up`/`offer`, sorted by `updated_at` ascending, unpaginated), and archived. Setting `passed` or `closed` auto-archives. Any edit must call `touch_opportunity` since `updated_at` drives the follow-up sort.
- **Adzuna** is optional; without keys the panel renders an error state. It merges 4 searches, applies the posting rules (`app/services/posting_rules.py`: company, industry, title, title-stack and location rules, run before storing and again on read; per-rule rejection counts logged on `adzuna_fetches.rejections`; personal term lists come from the gitignored `posting_rules.local.toml`, never committed: the repo is public), and **stores every remaining result** in `job_postings` (upserted on `(source, source_id)`, the Adzuna id). Each refresh is logged in `adzuna_fetches`; there is no in-memory cache. A page load refreshes only when the latest fetch is >4h old or the search-term fingerprint changed. Posting rules and results shown are not in the fingerprint, so editing them costs no API calls. Summed `adzuna_fetches.api_calls` drive a quota guard over rolling windows (`ADZUNA_QUOTA_WINDOWS`, the trial plan's 15/min, 150/day, 750/week, 1500/month). It refuses a refresh, or stops mid-refresh keeping partial results, rather than exceed a limit. Search parameters live in the singleton `adzuna_settings` table (seeded from `app/config.py` constants), not in `.env`; only the API credentials come from the environment.
- **Never fetch third-party job pages to enrich postings.** Adzuna's details and apply pages return 403 to honest non-browser clients, and spoofing a browser to get around that is off the table. Full postings reach the app only when the user's own browser visits them: the panel's title link goes through `/postings/{id}/open` (records `opened_at`), and the "Send to Career Search" bookmarklet sends the employer page URL to `/postings/capture`, which attaches it to the most recently opened posting or saves a new one (RubyOnRemote and other manual finds).
- **`salary_is_predicted`**: Adzuna estimates salaries for postings that state none. Show those as estimates and never copy them into an opportunity's salary fields.

## Tests

`tests/conftest.py` forces `DATABASE_URL=sqlite:///./data/test.db`, sets `TESTING=1`, blanks the Adzuna credentials (so tests never spend live API calls; mock with `httpx.MockTransport` and monkeypatch `app.config.ADZUNA_APP_ID`/`KEY`, see `tests/test_job_postings.py`), and applies Alembic once per session; an autouse fixture deletes rows from every table after each test. The dev database is never touched. New tables must be added to `TABLES_TO_TRUNCATE`.

Route tests use the `client` fixture, create a user directly via `create_user`, log in through `/login`, and scrape the CSRF token from rendered HTML with `csrf_from_html` (see `_login` in `tests/test_opportunities.py:138`) — every mutating request needs a fresh token in the form body.

## Docs

`docs/design_plan.md` is the living spec (data model, daily-plan rules, opportunities behavior, import column mapping, Adzuna field mapping). Update it when behavior decisions change.
