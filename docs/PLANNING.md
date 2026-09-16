# PLANNING.md

Working notes for prioritization and in-progress design discussions. Unlike `CLAUDE.md` (stable conventions) and `design_plan.md` (living spec of shipped behavior), this file tracks things we're actively deciding. Prune sections once they're resolved and folded into those two files.

## Network redesign — SHIPPED (2026-09-16)

Designed and implemented in one session. **Behaviour now lives in `docs/design_plan.md`** ("Network tab behavior" + the `network_contacts` data model); this section keeps only the reasoning and the loose ends.

### Why it was rebuilt

Reading the 16 live rows reframed the problem: **nothing ever generated a follow-up.** 15 of 16 had a first-contact date and a blank `followup_contact_at`; 13 people were contacted Aug 17-20 and a month later the tab had never flagged one of them. The old sort put NULL-followup rows first, so all 16 tied for first place and the ordering conveyed nothing. Typing a future date was the step that never happened — hence the computed cadence.

Two other findings shaped the model:

- **"How I know them" is past-employer/relationship, not an opportunity.** Verisys x9, plus Maverik, iTransact, Robert Half, Davis High, Family — and there is *no* Verisys opportunity row. Only 2 of 16 contacts touch an opportunity at all. This killed the "closed thread = no linked opportunity" idea, which would have closed 14 of 16 people; hence the explicit `status`.
- **`Opportunity.referred_by` names people absent from Network entirely** ("Amy Anderson" referred 4 opportunities). Reinforces People-as-source-of-truth eventually; still out of scope.

### Decisions worth not relitigating

- The table stays `network_contacts` / `NetworkContact`. The overloading was in the columns, not the name; renaming would mean rewriting 15 `notes.noteable_type` rows plus every router/service/template/test identifier for a cosmetic gain.
- No contact-events table in v1 (no appetite for hand-logging every touch). The single `log_contact` write path means history can be added later without changing the UI.
- One nullable `opportunity_id` FK rather than many-to-many — covers both real cases; recruiters use notes.
- Snooze is not optional. Without it the only way to clear the Reach out panel is to log a contact that never happened, which corrupts the cadence.
- Email/phone deliberately not stored. **Note the tension with auto-discovery below.**

### Migration notes (`007_network_person_shape`)

Tested against a copy of the live database; all 16 rows and both edge cases (`Robert Half` with no URL, a bare URL with no affiliation) split correctly, and the downgrade reconstructs `connection` exactly.

- `last_contact_at` took `first_contact_at`, **not** `max(first, followup)` — `followup_contact_at` recorded a *planned* date and whether it happened is unknowable. It became `next_touch_override`, so Aaron Ozminski correctly shows as overdue.
- The free-text `opportunities` string was appended to each contact's note rather than guessed into `opportunity_id`.

### Remaining loose ends

- **Two opportunity links to set by hand** (deliberately not hardcoded into a migration): Kole Frazier → `nextlinklabs`, Joseph Johnson → `BigBear AI`. Both have the old string preserved in their notes.
- Sam has not yet used this in anger. Cadence default (14d), the 3-card cap, and the preset cadence choices are all first guesses that should be revisited after a week of real use.
- `@app.on_event("startup")` in `app/main.py:58` is still deprecated — unrelated to this work, intentionally deferred so app-boot changes and a boot-time migration did not land together.

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
