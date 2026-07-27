# Career Search Guide — Design Plan

> Source of truth for architecture and product decisions. Reference this file (`@docs/design_plan.md`) when starting new Agent chats.

## Goals

Organize a personal career/job search across:

- **Daily Plan** (home) — date-scoped actionable list with notes, priorities, goal vs requirement
- **Master Tasks** — longer-horizon work feeding the Daily Plan by target date
- **Learning Tasks** — skills and resources to study
- **Opportunities** — companies, postings, connections, application context

## Stack (chosen)

| Layer | Choice | Why |
|-------|--------|-----|
| Backend | FastAPI | Python learning goal; modern, readable, fast to build |
| UI | Jinja2 + HTMX | Rails-like server views; no React |
| DB | SQLite | Zero daemon, minimal RAM/disk locally |
| Deploy (later) | Render/Fly + Postgres | Full launch lifecycle practice |

## MVP (built)

- Date-scoped Daily Plan Mon–Sat; Sunday rest day
- Prev/next work-day arrows; calendar panel with month navigation
- Mission statement in header (editable in Settings)
- Active + completed task lists; friendly completed styling
- Goal vs requirement indicator; drag-and-drop reorder
- Polymorphic `notes` table (`noteable_type` + `noteable_id`)
- Master / Learning / Opportunities CRUD
- Excel (.xlsx) import from Google Sheet export

## Task sync refactor (built)

- **Separate source tables + join table** — not a single unified `tasks` table. Master and Learning have different fields (`date_kind` vs `resource`); daily plan stores placement only via `daily_plan_items`.
- **`status` lifecycle** on Master and Learning: `current` | `completed` | `archived`. `completed_at` kept as metadata timestamp.
- **Delete vs Archive** — Archive is the normal dismiss action; Delete is rare (duplicates). Archived tasks appear in a collapsed section on list views.
- **Event-driven assignment** — `assign_due_tasks` runs on new plan create, master/learning create/update with target date, and once-per-day catch-up when viewing today's plan (`last_assigned_at`).
- **Draggable Master/Learning lists** — SortableJS; hidden `priority` integer; `priority == 0` sorts last (migrated to end on upgrade).
- **Inline HTMX editing** — target date calendar popover and goal/requirement dropdown on Master list rows.
- Daily plan order seeded from source (`priority_order` on join table); independently draggable per day.

## Later (not MVP)

- Manual Master Task → Daily Plan date assignment (multi-day work)
- “Add More Tasks” when daily list is complete
- Locations map + hover → Opportunity
- Currency exchange API (GBP/USD)
- Adzuna job feed on Opportunities page (built); USAJobs API deferred
- Saved job postings library → Learning Task generation / pattern analysis
- Cloud deploy lifecycle
- **Opportunities view polish** (built) — see opportunities model above; map/kanban deferred

## Data model

### Architecture note

We chose **separate `master_tasks` and `learning_tasks` tables plus a thin `daily_plan_items` join table** rather than single-table inheritance. Master and Learning have genuinely different columns; the join table avoids duplicated titles/dates and sync drift.

### `settings`
- `mission_statement`

### `daily_plans`
- `plan_date` (unique)
- `last_assigned_at` — once-per-day catch-up for overdue assignment

### `daily_plan_items` (join table)
- `daily_plan_id`
- `priority_order` — daily-only order (independent of source `priority`)
- Exactly one of: `master_task_id`, `learning_task_id`
- Unique per plan per source task
- `completed_at` — per-day completion timestamp for recurring master tasks

### `master_tasks`
- `task`, `priority` (hidden sort key; 0 = sort last), `target_completion_date`
- `date_kind` (`goal`|`requirement`)
- `is_recurring` — when true, task auto-appears on each work day's plan from start date until completed/archived on Master Tasks
- `status` (`current`|`completed`|`archived`), `completed_at`

### `learning_tasks`
- `task`, `resource`, `priority`, `target_completion_date`
- `status`, `completed_at`

### `opportunities`
- Core: `company`, `posting_url`, `connections`, `referred_by`, `location_text`
- Enums (HTMX inline on list): `remote_status` (`remote`|`hybrid`|`on_site`), `source` (`direct`|`referral`|`recruiter`|`linkedin`|`robert_half`)
- `stack` (open text; renamed from `stack_match`), `mission_fit`, salary min/max/currency
- `pipeline_stage`: `new` | `applied` | `interviewing` | `follow_up` | `offer` | `passed` | `closed`
- `lifecycle_status`: `active` | `archived`
- `highlight_rank`: 1 (gold), 2 (silver), 3 (bronze), or null — exclusive slots with cascade-down on assign
- `applied_at`; notes via polymorphic `notes` table
- List: sortable columns (server-side), archived collapsed section, medal highlight buttons

### `notes` (polymorphic)
- `body`, `noteable_type`, `noteable_id`
- Attached to source tasks only (not daily plan items)

## Daily Plan rules

1. One plan per calendar date (`daily_plans.plan_date`)
2. Work days Mon–Sat; Sunday shows rest-day view
3. Prev/next navigation skips Sunday
4. Auto-feed: **`current`** Master/Learning tasks with `target_completion_date == plan_date`
5. On **today's** plan only: also include overdue incomplete tasks (`target_completion_date < today`)
6. **Recurring master tasks** (`is_recurring`): auto-add to every work day's plan from start date (`target_completion_date`, or `created_at` if unset) while `status == current`. Checking off on Daily Plan marks only that day's `daily_plan_items.completed_at`; the master task stays `current` and reappears on the next work day. Complete or archive on Master Tasks to stop recurrence.
7. New tasks created on Daily Plan → create `MasterTask` + join row (always in master list); optional recurring checkbox
8. Complete/uncomplete on daily plan: non-recurring updates source task `status`; recurring updates plan item `completed_at` only
9. Master tasks listed before learning tasks when auto-assigning; order within group by source `priority`

## Assignment triggers

1. `get_or_create_daily_plan` — when plan is newly created
2. Master/Learning create or update when `target_completion_date` set/changed
3. Once per calendar day when viewing today's plan (`last_assigned_at` check)

## Import mapping

| Sheet | Columns |
|-------|---------|
| Daily Plan | Goal/Task, Notes, Completed? → creates MasterTask + join row |
| Master Tasks | Task, Priority, Notes, Target Completion Date, Completed? |
| Learning Tasks | Task, Resource, Priority, Notes, Target Completion Date, Completed? |
| Opportunities | Company, Posting URL, Connections, Referred By, Remote Status, Source, Stack, Mission Fit, Pipeline/Status, Notes |

Import mode: append with duplicate warnings. Daily Plan rows assigned to user-selected import date.

## Opportunities list behavior

- **Page layout (top to bottom):** New opportunities table → Follow Up table → Adzuna panel → Archived section.
- **New table:** Active opportunities with `pipeline_stage = new` only. Columns exclude Pipeline and Applied (those apply once tracking begins). Highlight rank sorts first, then column sort. Paginated 7/page.
- **Follow Up table:** Active opportunities in `applied`, `interviewing`, `follow_up`, or `offer`. Columns: Company, Remote, Mission Fit, Salary, Status (same field as pipeline), Referred By, Location, Notes, Actions. Sorted by `updated_at` ascending (oldest first). All rows shown (no pagination).
- **Auto-archive:** Setting status to Passed or Closed moves the row to Archived automatically.
- **`updated_at`:** Bumped on any opportunity edit or inline patch; drives Follow Up sort order.
- **Compact table:** truncated notes (click row cell to expand); smaller action buttons.
- **Archive** clears highlight rank and moves row to collapsed archived section.
- **Sortable columns (New table):** server-side via `?sort=&dir=` query params.

### Deferred

- Yellow/red stale-row highlighting on Follow Up by days since last update.

### Adzuna job suggestions

- Register at [Adzuna Developer API](https://developer.adzuna.com/) for `app_id` + `app_key`.
- Set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env` (see `.env.example`).
- Search profile stored in **`adzuna_settings`** DB table (singleton); gear icon on panel opens settings modal. Defaults match `app/config.py` constants.
- Panel runs **4 merged searches** (remote US, Salt Lake City metro, Virginia excluding DC, Charlotte metro).
- Post-filter drops on-site listings outside allowed regions (SLC metro, Virginia non-DC, Charlotte metro); remote/hybrid always kept.
- Results cached **4 hours** in memory; cache busts on settings save or **Refresh Jobs**.
- **Add** opens a modal pre-filling opportunity fields; source set to `adzuna`; snippet + metadata in Notes.
- Remote/hybrid/on-site is **inferred** from title/description/location (Adzuna has no dedicated remote field).

| Opportunity field | From Adzuna |
|-------------------|-------------|
| company | company.display_name |
| posting_url | redirect_url |
| location_text | location.display_name |
| remote_status | inferred |
| source | adzuna |
| stack | configurable default (Ruby) |
| salary_min / salary_max | API values |
| pipeline_stage | new |
| notes | formatted snippet + metadata |

## Page CSS classes

Each page template sets `{% block page_class %}` on the shared `<main>` in `base.html`, e.g. `<main class="container opportunities">`. Slugs: `daily`, `master-tasks`, `learning-tasks`, `opportunities`, `import`, `settings`.

## Context management

- Keep this file updated when decisions change
- New Cursor chat per build phase
- Paste or `@docs/design_plan.md` at the start of implementation chats

## Local run

```bash
source venv/bin/activate
uvicorn app.main:app --reload
```

Schema upgrades for existing SQLite files run automatically on startup (`app.services.schema_migration`).

## Deploy notes (future)

- Swap SQLite for Postgres via `DATABASE_URL`
- Render/Fly.io free/hobby tiers suitable for personal use
- GitHub repo: push when ready for remote backup and deploy hook
