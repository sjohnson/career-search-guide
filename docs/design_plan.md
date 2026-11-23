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
- `applied_at`; `equity`, `collaboration_focused` (booleans; form-only, not shown as table columns)
- notes via polymorphic `notes` table
- List: sortable columns (server-side), sort toolbar above New table, archived collapsed section, medal highlight buttons

### `network_contacts`
- One row per **person**, not per contact event.
- Identity: `name`, `affiliation` ("How I know them" — e.g. Verisys, Family, Davis High), `linkedin_url`
- `opportunity_id` → `opportunities.id` (nullable, `ON DELETE SET NULL`). Most contacts are pure networking with no opportunity.
- Contact history (flat, not an events table): `first_contact_at` (thread start), `last_contact_at`, `last_contact_method`
- Cadence: `cadence_days` (default 14; presets 7/14/30/90), `next_touch_override`
- `status`: `active` | `closed`
- notes via polymorphic `notes` table
- Email and phone are deliberately **not** stored — method matters, the raw detail lives in Sam's mail/phone app.

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
- **Sort toolbar:** Above the New table; field + direction dropdowns share the same `?sort=&dir=` URL state as column header links. Toolbar is the primary “current sort” indicator; header arrows show when sorting by a visible column. Hidden sorts (`equity`, `collaboration`) are toolbar-only. Direction labels: text fields use A→Z / Z→A; booleans use Yes first / No first.
- **Follow Up table:** Active opportunities in `applied`, `interviewing`, `follow_up`, or `offer`. Columns: Company, Remote, Mission Fit, Salary, Status (same field as pipeline), Referred By, Location, Notes, Actions. Sorted by `updated_at` ascending (oldest first). All rows shown (no pagination).
- **Auto-archive:** Setting status to Passed or Closed moves the row to Archived automatically.
- **`updated_at`:** Bumped on any opportunity edit or inline patch; drives Follow Up sort order.
- **Compact table:** truncated notes (click row cell to expand); smaller action buttons.
- **Archive** clears highlight rank and moves row to collapsed archived section.
- **Sortable columns (New table):** server-side via `?sort=&dir=` query params.

### Deferred

- Yellow/red stale-row highlighting on Follow Up by days since last update.

## Network tab behavior

**The organising idea: the app computes who is due, rather than asking for a follow-up date to be typed.** The previous design stored a hand-entered `followup_contact_at`, which in practice was left blank on 15 of 16 rows — so nobody was ever surfaced as overdue.

### Derived next-touch date

`next_touch_at` is a model property, not a column:

1. `next_touch_override` if set, else
2. `last_contact_at + cadence_days`, else
3. `created_at` — so a never-contacted person is due immediately and sorts alongside overdue follow-ups with no special case in the ordering.

`days_overdue` is `today - next_touch_at` (positive = overdue). `is_due` additionally requires `status == active`.

Ordering is done in Python (`app/services/network.py`), not SQL, because `next_touch_at` is computed. The list is one row per person at personal scale — tens, not thousands.

### Page sections (stacked, top to bottom)

1. **Quick-add** — name + "How I know them" only. A new person has no contact logged, so they land straight in Reach out.
2. **Reach out** — `active AND is_due`, most overdue first. Rolodex-style cards. Shows `REACH_OUT_VISIBLE` (3) with the remainder behind a `<details>` disclosure, so a month of neglect reads as a short list rather than a backlog.
3. **Scheduled** — `active AND NOT is_due`, soonest first. Compact table; the quiet list.
4. **Closed threads** — `status == closed`, collapsed. Light: identify the person and re-open in one click.

### Actions

| Action | Effect |
|---|---|
| **Log contact** (method dropdown) | `last_contact_at = today`, sets method, backfills `first_contact_at` if unset, clears `next_touch_override` |
| **Snooze 1w** | `next_touch_override = today + 7`. Never touches `last_contact_at` — the escape valve exists so the panel can be cleared *honestly* |
| **No further contact** | `status = closed`. **One click, no confirm dialog** — safe because "Reach out again" is the undo |
| **Reach out again** | `status = active`, `next_touch_override = today` → straight back into the queue |
| **Cadence** | Inline preset dropdown (7/14/30/90); off-preset or junk input falls back to 14 |

**HTMX protocol:** every action returns `network/partials/sections_swap.html`, which repaints all three sections via `hx-swap-oob`. Any single action can move a person between any two sections, so repainting the lot avoids the stale/duplicate/vanishing-row bugs that per-row swaps keep producing. Buttons use `hx-swap="none"`; CSRF rides the `X-CSRF-Token` header from `base.html`.

### Daily Plan nudge

Today's plan renders a **read-only** "Reach out (N due)" block listing up to 3 names and linking to `/network`. It creates no `MasterTask` rows and nothing checkable — deliberately staying clear of `assign_due_tasks`, `daily_plan_dismissals`, and the recurring-completion fork. Shown only when `plan_date == today` and someone is due.

### Not in scope / deferred

- `Opportunity.connections` and `referred_by` remain free text, not linked to people (`referred_by` names several people absent from Network entirely).
- No contact-event history table. Flat `last_contact_at` + method is enough while every touch is logged by hand; the single `log_contact` write path leaves room to add history later.
- Recruiters spanning several openings use notes rather than a many-to-many link.
- **Auto-discovery of responses (Gmail API + Unipile)** — see `docs/PLANNING.md`. This is the feature expected to make the tab self-maintaining, and the point at which an events table starts to pay for itself.

### Adzuna job suggestions

- Register at [Adzuna Developer API](https://developer.adzuna.com/) for `app_id` + `app_key`.
- Set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env` (see `.env.example`).
- Search profile stored in **`adzuna_settings`** DB table (singleton); gear icon on panel opens settings modal. Defaults match `app/config.py` constants.
- Panel runs **4 merged searches** (remote US, Salt Lake City metro, Virginia excluding DC, Charlotte metro), newest first (`sort_by=date`), 50 results per page, `max_pages` pages per search (1–3; one API call per page).
- **Posting rules** (`app/services/posting_rules.py`) run before storing; see below.
- **Every result that passes the posting rules is stored** in `job_postings`, deduped on the Adzuna id. Re-sightings refresh Adzuna-owned fields and `last_seen_at`, and append to `search_hits` (which bucket and terms found it). User state (opened, dismissed, captured URL, linked opportunity) is never overwritten.
- Each refresh is logged in `adzuna_fetches` (API calls spent, per-bucket counts, new postings, error). Page loads refresh only when the latest fetch is older than 4 hours or the search terms changed.
- **Quota guard:** API calls are summed over rolling windows matching the trial plan (15/minute, 150/day, 750/week, 1500/month). A refresh is skipped if fewer than 4 calls remain, and pagination stops before exceeding a limit. Usage shows in the panel header.

**Search terms** (all sent to Adzuna, which matches them against the full posting with stemming, so "developer" also matches "development"). Terms in different fields are ANDed together:

| Setting | Adzuna param | Meaning |
|---|---|---|
| Keywords | `what` | all words must appear (title or description) |
| Required keywords | `what_and` | all words must appear |
| Remote search: any of | `what_or` | remote bucket only; at least one word must appear |
| Exclude | `what_exclude` | drop postings containing any of these words |
| Title must contain | `title_only` | all words must appear in the title |

At least one of keywords, required keywords, or title must be set. Measured 2026-11-21 (US-wide, ≥$135k, 30 days): `what=software developer` + `what_and=Ruby rails integration` → 34; + `what_and=ruby` → 224; `what_and=ruby` alone → 481; `title_only=software engineer` + `what_and=ruby` → 157.

**Posting rules** (one function, `PostingRules.rejection_reason`, run before storing and again when reading, so a tightened rule also hides postings saved earlier; editing them costs no API calls). Gathering keeps only likely-relevant postings with fixed, explainable rules; judging fit is ai-job-search's `/rank`. Rejected results aren't stored: each fetch logs per-rule counts plus up to 10 samples in `adzuna_fetches.rejections`, shown under "Last fetch" on the panel. Adzuna returns live postings on every refresh, so a loosened rule brings postings back on the next refresh. Hand-captured postings bypass the rules. Default term lists were drafted by ai-job-search (`job_scraper/adzuna-exclusion-terms.md`, 2026-11-21). Personal entries (non-compete employers and the like) live in the gitignored `posting_rules.local.toml`, `.env`-style: each list it defines replaces the code default (format in `posting_rules.example.toml`). New or blank settings lists are seeded from the result; after that the lists are edited in the settings window. Lists match whole words, case-insensitively (`+` and `#` count as word characters, so "Java" misses "JavaScript" and "C" misses "C++").

| Rule | Matched against | Effect |
|---|---|---|
| Blocked companies | company name | drop (non-competes, mission blocks, gambling operators; the panel's Block button adds here) |
| Excluded industries | title or company name | drop (gambling, extractive lending/collections) |
| Excluded title terms | title | drop (management, too junior, wrong discipline, relocation) |
| Excluded title stacks | title | drop unless the title also says Ruby, Rails, Python or JavaScript |
| Location | location + stated arrangement | see below |
| Signal terms | title + description snippet | never drop; shown as tags |

Never match employer names against the description: postings name non-compete companies as partners or clearinghouses.

**Location rule.** The stored location is Adzuna's display name plus the state from `location.area` ("Herndon, Fairfax County, Virginia"); display names alone omit it. Kept: anything in the allowed regions (SLC metro, Virginia outside the DC metro, Charlotte metro), anything stated as remote, and anything the remote search found that states no arrangement. A bare city isn't evidence of on-site work. Dropped: on-site or hybrid stated outside the regions, and metro-search results outside the regions that say nothing about remote. The metro searches use a radius and do reach outside: on 2026-11-23, 46 "Virginia" results were mostly Northern Virginia (Fairfax, Arlington, Loudoun) plus Maryland. The DC metro is DC plus Arlington, Fairfax, Alexandria, Falls Church, Loudoun, Prince William and Manassas.

**Panel** shows stored postings awaiting a decision: not dismissed, not linked to an opportunity, seen within 30 days, not filtered, newest discoveries first. Badges: **New** (first seen in the latest successful fetch, not yet opened), **Employer URL** (captured). Actions: **Add** (opportunity modal, links the posting), **Dismiss**, **Block** (adds the company to the blocklist). Predicted salaries display as `~$Xk (est.)`.

**Bookmarklet capture:** the title link goes through `/postings/{id}/open`, which records `opened_at` and redirects to Adzuna. On the employer page, the "Send to Career Search" bookmarklet opens `/postings/capture?url=…&title=…`. That page offers recently opened postings without an employer URL (newest first, last 7 days) or "a new posting" (title and company required; RubyOnRemote URLs get source `ruby_on_remote`, others `manual`). URLs are normalized (lowercased host, no fragment, tracking params like `utm_*` stripped, other query params kept) and deduped. The app never fetches third-party job pages itself.

| Opportunity field | From stored posting |
|-------------------|-------------|
| company | company |
| posting_url | captured employer URL, else Adzuna `redirect_url` |
| location_text | location |
| remote_status | inferred |
| source | adzuna / ruby_on_remote / direct (manual) |
| stack | configurable default (Ruby) |
| salary_min / salary_max | API values, **blank if predicted** |
| pipeline_stage | new |
| notes | formatted snippet + metadata (incl. estimate note, search buckets) |

## Page CSS classes

Each page template sets `{% block page_class %}` on the shared `<main>` in `base.html`, e.g. `<main class="container opportunities">`. Slugs: `daily`, `master-tasks`, `learning-tasks`, `opportunities`, `import`, `settings`.

## Auth and security

- **Authentication:** session cookies via Starlette `SessionMiddleware`; `user_id` in signed session after bcrypt password verify. `AuthMiddleware` gates all routes except login/register/logout and static assets.
- **Registration:** bootstrap UI when no users exist; `python -m app.cli create-user` for ops; optional `ALLOW_REGISTRATION=true` in dev.
- **Authorization:** deferred — login gates the app; task/opportunity rows are not yet scoped by `user_id`.
- **CSRF:** session-stored token on mutating requests (form field or `X-CSRF-Token` header for HTMX).
- **CORS:** intentionally omitted — same-origin server-rendered HTML app; add `CORSMiddleware` only if a separate SPA/API client is introduced.
- **SQL:** application routes use SQLAlchemy ORM; schema changes belong in Alembic migrations under `alembic/versions/`.

## Context management

- Keep this file updated when decisions change
- New Cursor chat per build phase
- Paste or `@docs/design_plan.md` at the start of implementation chats

## Local run

```bash
source venv/bin/activate
uvicorn app.main:app --reload
```

Schema upgrades run automatically on startup via Alembic (`alembic upgrade head` through `app.services.alembic_runner`). New schema changes belong in numbered files under `alembic/versions/`. Models in `app/models.py` define the intended shape; keep migrations in sync with `alembic check`.

## Deploy notes (future)

- Swap SQLite for Postgres via `DATABASE_URL`
- Render/Fly.io free/hobby tiers suitable for personal use
- GitHub repo: push when ready for remote backup and deploy hook
