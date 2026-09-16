# PLANNING.md

Working notes for prioritization and in-progress design discussions. Unlike `CLAUDE.md` (stable conventions) and `design_plan.md` (living spec of shipped behavior), this file tracks things we're actively deciding. Prune sections once they're resolved and folded into those two files.

## 2026-08-27: Pulled-update review

`docs/CLAUDE.md` arrived via commit `f414ce8` ("Add mise Python 3.13 pin and CLAUDE.md"), originally at repo root, moved into `docs/` by Sam. Reviewed it looking for a "next steps" list Sam remembered discussing — **it isn't in the file.** It's the standard architecture/commands doc (layering, HTMX OOB-swap protocol, CSRF wiring, domain rules). Nothing resembling a task list.

### Quick win found instead: deprecated `datetime.utcnow()`

Not documented anywhere, but real and relevant now that the same commit pinned the project to Python 3.13 (`mise.toml`) — `datetime.utcnow()` has been deprecated since 3.12 in favor of timezone-aware construction. It's used ~20 times across the codebase:

- `app/models.py` — every `created_at`/`updated_at` column default and `onupdate` (Opportunity, NetworkContact, Note, and others), lines 48, 57, 78, 88, 126, 152, 212, 233, 343, 345, 387, 389, 401, 403
- `app/services/import_service.py:159,212,258` — `completed_at` on import
- `app/services/opportunities.py:72` — `touch_opportunity`
- `app/services/daily_plan.py:136,296,360,367,443` — notes, plan assignment, completion timestamps

**Caveat before fixing:** all these columns are plain `DateTime` (not `DateTime(timezone=True)`), and SQLite stores naive values. Swapping in `datetime.now(timezone.utc)` directly would start writing timezone-aware datetimes into columns everything else treats as naive, which will raise or misbehave on comparison (e.g. `sort_network_contacts`, any `date.today()` comparisons elsewhere). Correct fix is to still produce a naive UTC value — e.g. a small `utcnow()` helper doing `datetime.now(timezone.utc).replace(tzinfo=None)` — not a bare find-and-replace.

**Status:** pending Sam's go-ahead — plausibly a "do this first, it's minutes" item, but not started.

### Priority decision

Sam confirmed: nothing in the pulled update outranks revisiting the Network tab. The utcnow fix is a candidate for "small thing to knock out first" but isn't blocking anything — decide at the start of the next work session whether to do it before or after Network planning lands on an implementation plan.

---

## Network functionality redesign (in discussion, started 2026-08-27)

### Why it's being revisited

Sam built the Network tab (`2417928`, plus follow-up fixes `70d1b04`, `d027c9b`) but isn't using it much in practice — the shape doesn't match how he actually works a job search. This is a "use it and find out" problem, not a build defect.

### Current shape (`app/models.py:377` `NetworkContact`, `app/services/network.py`, `app/routers/network.py`)

One table, one row per contact:

| Field | Type | Problem |
|---|---|---|
| `name` | string | — |
| `connection` | string(300), free text | Overloaded: mixes "how I know them" with a pasted LinkedIn URL in one field, e.g. `Verisys; https://www.linkedin.com/in/deborah-norton-a2695386/` |
| `first_contact_at` / `followup_contact_at` | date, date | Approximates a one-to-many contact history with two fixed columns; no real "last contact" concept, no history |
| `method` | string(30) | Single value — fine per Sam's feedback, just needs to survive restructuring |
| `opportunities` | string(300), free text, space/comma-split | Not linked to actual `Opportunity` rows; just tokens, some of which happen to be URLs (`opportunity_link_parts` in services/network.py) |
| notes | via polymorphic `Note` table (`noteable_type`/`noteable_id`) | Works, keep |

List view is a single sortable table (`sort_network_contacts`: unfollowed-up-first, then by date, then name) — Sam's complaint is that one big table doesn't answer "who do I need to reach out to" at a glance.

Separately, `Opportunity.connections` (`app/models.py:325`) and `Opportunity.referred_by` are free-text strings with no link to `NetworkContact` — explicitly flagged by Sam as a future improvement, **not in scope for this pass**, but the new People model should not make that future linkage harder.

### Sam's diagnosis

1. **Wrong primary entity.** The contact *event* was modeled as primary; the *person* should be. (One row per person, not one row that conflates "the person" with "one contact instance.")
2. **No appetite for granular event logging.** No API exists to auto-pull LinkedIn/text/Gmail history, and manually logging every touch ("received response with thumbs up emoji") isn't going to happen. So while a person-vs-events split is directionally right, the events side should stay minimal — likely just enough to know the *last* contact date and method, not a full timeline.
3. **Actual daily need:** answer "who do I still need to contact" — first-time or follow-up — at a glance. Supporting fields: method, last contact date (doesn't exist today — only first/followup), linked opportunities, notes.
4. **View should split by state**, not be one table:
   - **Needs attention** panel — richer per-row info: name, "how I know them" (needs a better name than `connection` — collides with `Opportunity.connections` meaning something different), target/follow-up contact date, method, opportunity, notes. Sam's sketched a rolodex-style layout (primary fields in a row, notes/opportunity underneath) as an alternative to a dense table.
   - **Closed threads** panel — people with no open follow-up and no current opportunity. Lighter — just enough to identify someone and re-open a thread (new contact instance) with one click.
5. **Contact-info field cleanup:**
   - Split the overloaded `connection` field into: how-I-know-them (name TBD) + LinkedIn URL (kept — clickable, jumps straight to profile) as separate fields.
   - Email and phone are explicitly **not** worth storing — Sam will pull those from his phone/email app directly; tracking *method* matters more than tracking the raw contact detail.

---

## Network redesign — settled design (2026-09-16)

Design session complete. All nine open questions resolved; what follows is the spec to implement. Fold into `design_plan.md` once shipped, and delete this section.

**Guiding goal (Sam's words):** make the Network tab easy enough that he's motivated to use it, and have it *suggest* next steps without being overwhelming.

### What the data actually showed

Read of the 16 live rows in `data/career_search.db` reframed the problem:

- **Nothing ever generates a follow-up.** 15 of 16 rows have `first_contact_at` set and `followup_contact_at` NULL. 13 people were contacted Aug 17–20; a month later the tab had never flagged one of them. Today's `sort_network_contacts` puts NULL-followup rows first, so all 16 tie for first place and the ordering conveys nothing. **Typing a future date is the step that never happens — so the app must compute it.** This is the core fix; everything else is support.
- **"How I know them" is past-employer/relationship, not an opportunity.** Verisys ×9, plus Maverik, iTransact, Robert Half, Davis High, Family. There is **no Verisys opportunity row** — those are former colleagues. Only 2 of 16 contacts touch an opportunity at all (Kole Frazier → `nextlinklabs` id 31 via `referred_by`; Joseph Johnson → `BigBear AI` id 33 via `connections`). This killed the "closed thread = no linked opportunity" idea outright: it would close 14 of 16 people.
- **Migration is trivial.** All 16 `connection` values split cleanly on `;`. `opportunities` holds only 2 values.
- **Out of scope but confirmed:** `Opportunity.referred_by` names people absent from Network entirely ("Amy Anderson" referred 4 opportunities). Reinforces People-as-source-of-truth later; not this pass.

### Resolutions

| # | Question | Decision |
|---|---|---|
| 1 | Person ↔ event split | **Flat fields on the person.** No events table. A single "Log contact" action is the only write path, so an append-only history can be added later without changing the UI. |
| 2 | Opportunity link | **One nullable FK now** (`opportunity_id`). Covers both real cases; a recruiter spanning several openings stays in notes until m2m is warranted. |
| 3 | What closes a thread | **Explicit `status`** (`active` \| `closed`). Derived-from-opportunity was rejected — see data above. |
| 4 | Naming | `connection` → **`affiliation`**, labeled **"How I know them."** No collision with `Opportunity.connections`. |
| 5 | Panel layout | **Stacked sections**, matching the Opportunities page convention (New → Follow Up → Archived). Avoids narrow columns in a table-heavy app. |
| 6 | Queue sorting | **One uniform sort by `next_touch_at` ascending.** Never-contacted needs no special case: with no `last_contact_at`, `next_touch_at` falls back to `created_at`, so first-contacts and follow-ups interleave correctly by age. |
| 7 | Re-opening a closed thread | Sets `status = active` and `next_touch_override = today`, dropping the person straight into the Reach out queue. |
| 8 | Add/edit flow | **Inline quick-add** (name + affiliation) at the top of the page; full form stays at `/network/new` for complete entry. Cadence and method are inline-editable on the row afterward. |
| 9 | Migration | Fully automatable — mapping below. Two `opportunity_id` links set by hand afterward (2 dropdown clicks). |

**Also decided:** the table stays `network_contacts` / `NetworkContact`. The overloading was in the columns, not the table name, and renaming would mean rewriting 15 `notes.noteable_type` rows plus every router/service/template/test identifier for a cosmetic gain.

### Cadence model (the centerpiece)

Per-person interval, **default 14 days**. Editable inline via preset dropdown (7 / 14 / 30 / 90) rather than a free-text number — fewer decisions, and it matches the existing inline-HTMX-dropdown pattern used for `pipeline_stage`.

Derived as model properties (no stored columns, nothing to keep in sync):

- `next_touch_at` = `next_touch_override` if set → else `last_contact_at + cadence_days` → else `created_at`
- `days_overdue` = `(today - next_touch_at).days` (negative = not yet due)
- `is_due` = `status == active and days_overdue >= 0`

Three actions, all HTMX partial swaps:

- **Log contact** (method dropdown) — sets `last_contact_at = today`, `last_contact_method`, `first_contact_at = coalesce(first_contact_at, today)`, and clears `next_touch_override`. The one write path that matters.
- **Snooze 1 week** — `next_touch_override = today + 7`. The escape valve; without it the only way to clear the panel is to falsely claim contact.
- **Close thread** — `status = closed`. **One click, no confirmation dialog** — this is the "they told me there's nothing open" action and it has to be frictionless or it won't get used. Safe to make destructive-free because the person lands in the Closed section with a **Reach out again** button, which *is* the undo. Present on both the Reach out cards and the Scheduled rows (a thread can end without being due).

### Schema

```
network_contacts
  id
  name                 String(60)    NOT NULL
  affiliation          String(120)   NULL      -- "How I know them"
  linkedin_url         String(500)   NULL
  opportunity_id       FK opportunities.id NULL  ON DELETE SET NULL
  first_contact_at     Date          NULL      -- kept: "how long this thread has run"
  last_contact_at      Date          NULL      -- NULL = never contacted
  last_contact_method  String(30)    NULL      -- ContactMethod
  cadence_days         Integer       NOT NULL  default 14
  next_touch_override  Date          NULL      -- explicit one-off; wins over computed
  status               String(20)    NOT NULL  default 'active'   -- active | closed
  created_at / updated_at
```

Dropped: `connection`, `followup_contact_at`, `method`, `opportunities`.
Notes stay on the polymorphic `notes` table (`noteable_type = 'network_contact'`) — unchanged.

### Page layout (stacked, top to bottom)

1. **Reach out** — `status = active AND is_due`. Rolodex-style cards: name + days overdue on the primary line; affiliation, LinkedIn link, linked opportunity and notes beneath; Log contact / Snooze / Close actions. **Shows the 3 most overdue, with a "N more due · show all" expander** so a 13-person backlog reads as a short to-do rather than a wall.
2. **Scheduled** — `status = active AND NOT is_due`. Compact table sorted by `next_touch_at` ascending (soonest first), showing the next-touch date. The quiet list.
3. **Closed** — `status = closed`, collapsed section. Minimal columns plus a **Reach out again** button (see #7).

### Daily Plan integration

A **read-only nudge block** on today's plan: "Reach out (N due)" listing up to 3 due names, linking to `/network`. Rendered from a `due_contacts(db, limit=3)` service call.

Deliberately creates no `MasterTask` rows and nothing checkable — it must not touch `assign_due_tasks`, `daily_plan_dismissals`, or the recurring-task fork, which is the most regression-prone machinery in the app.

### Migration (`alembic/versions/00N_network_person_shape.py`)

SQLite requires `batch_alter_table` for the drops. Add columns, backfill, then drop.

| New field | Backfill from existing 16 rows |
|---|---|
| `affiliation` / `linkedin_url` | Split `connection` on `;`, trim each part; a part starting `http` → `linkedin_url`, otherwise → `affiliation`. Handles both edge rows: id 16 (URL only) and id 2 "Robert Half" (text only). |
| `last_contact_at` | `= first_contact_at`. **Not** `max(first, followup)` — `followup_contact_at` meant the *planned* next date, and whether it happened is unknowable. |
| `next_touch_override` | `= followup_contact_at` where set. Only id 3 (Aaron Ozminski, 2026-09-01) → correctly shows as overdue. |
| `last_contact_method` | `= method` |
| `cadence_days` | `14` for all |
| `status` | `'active'` for all |
| `opportunity_id` | NULL for all. The 2 known links are set by hand post-migration rather than hardcoding opportunity ids in a migration: Kole Frazier → `nextlinklabs` (31), Joseph Johnson → `BigBear AI` (33). Old `opportunities` string is appended to those rows' notes first so nothing is lost. |

Migration filename/revision follows the `NNN_slug` convention. `network_contacts` is already in `TABLES_TO_TRUNCATE`; no test-fixture change needed.

### Sequencing

Do the `datetime.utcnow()` helper fix (section above) **first** — it's minutes, and this work adds `created_at`/`updated_at` defaults that would otherwise propagate the deprecated call.

Then: migration → model + derived properties → services (`due_contacts`, `log_contact`, `snooze`, `close_thread`, sort helpers, replacing `opportunity_link_parts`) → router actions → templates (three sections + quick-add) → daily-plan nudge partial → tests.

---

## Future: auto-discover responses via Gmail + LinkedIn (Sam, 2026-09-16)

**Not in the current pass.** Sam's view, and it's right: hand-logging every touch is the thing that will eventually kill consistent use of the tab, even with one-click actions. If responses are discovered automatically and he only *reviews* them, the tab maintains itself.

Shape Sam described: poll Gmail (Gmail API) and LinkedIn (via Unipile) for replies → present discovered messages in a review/approve screen → approving logs the contact, with an option to close the thread in the same step.

### The one decision this forces on the current pass

**Matching a Gmail reply to a person requires storing their email address** — and this pass deliberately drops email/phone on the grounds that Sam reads those in his mail app anyway. Those two decisions collide.

**Resolution: still don't add an `email` column now.** Adding a nullable column later is a trivial Alembic step, and typing 16 email addresses by hand is exactly the friction this redesign exists to remove. When the integration lands, the *approve* step should **learn** the address from the matched thread and store it — the same principle as the cadence model: the app derives what it can, Sam confirms. First-time matching can fall back on name matching against the sender's display name, which is why it needs a human approve step regardless.

`linkedin_url` already covers the LinkedIn side of identity, so the schema we're building is fine as-is.

### Notes for when this is built

- **Check whether Unipile alone covers both.** It offers email/Gmail alongside LinkedIn messaging; if so this is one vendor and one OAuth flow rather than two. Verify against their current docs before committing to the Gmail API separately — it would remove the heaviest piece of work below.
- **Gmail OAuth is much heavier than Adzuna's API key** — consent flow, refresh-token storage, token rotation. Adzuna needed two `.env` values; this needs a stored credential per account and a re-auth path when it expires. Budget for it. Use read-only scope (`gmail.readonly`); nothing in this app should ever send mail.
- **There is no background worker** (FastAPI + SQLite, no Celery/cron). Don't invent one. Reuse the **Adzuna pattern**: fetch on demand, cache in a module-level dict keyed by a settings fingerprint, plus a manual **Check for responses** button that busts the cache. "Polling" here means "on page view, at most every N hours."
- **Staging table**, e.g. `discovered_messages`: matched `network_contact_id` (nullable — unmatched needs a person picker), channel, message date, sender, snippet, external message id (unique, so re-polling doesn't duplicate), and a `state` of `pending` | `approved` | `dismissed`. Approving calls the existing `log_contact` service rather than writing dates directly — keeps one write path.
- **This is where a real contact-event history starts paying for itself.** v1 deliberately keeps flat fields (`last_contact_at` + method). Auto-discovery produces a genuine stream of dated events, at which point the append-only events table deferred in question #1 becomes worth building. Expect to revisit that decision here, not before.
- Secrets in `.env` + `.env.example`, matching Adzuna. Credentials never in the DB in plaintext.
