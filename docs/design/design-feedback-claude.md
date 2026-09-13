# Design Feedback: Survivor Fantasy Application

Reviewer role: Systems engineer
Subject document: `docs/design/survivor-fantasy.md`

I reviewed the design doc end-to-end (assumptions, data model, decisions, operational sections). It's a strong, unusually rigorous design doc — most edge cases are explicitly resolved. Below are the gaps I'd want closed (or explicitly deferred) before/while coding, organized by how much they'd bite during implementation.

## Critical (will cause bugs or rework if not resolved before coding)

**1. "Eligible player" for wagering is never formally defined.**
The doc uses "eligible" constantly (initial wager-set creation, resets, cap validation, late-entry) but never states the exact predicate. Scenario text implies pending-roster members can't see scores/standings, but doesn't say whether they can *wager*. If "eligible" silently means `participation_state = active` (roster complete) in some code paths and "any active membership" in others, you'll get inconsistent participation rows across the codebase.

**Recommendation:** add one explicit assumption: "A membership is wager-eligible if and only if its `participation_state` is active," and make it a single reusable predicate/service method, not a copy-pasted query condition.

**2. The wager-cap "lockable league-castaway row" has no home in the data model.**
The Transactional Wager Caps research finding says to lock "a lockable league-castaway capacity row" per castaway, but the ERD has no such row — `castaway_cap` is a single global integer on `BETTING_CONFIG`, and `CASTAWAY` has no per-wager-set capacity/used counter. It's workable to lock the `CASTAWAY` row itself and aggregate `SUM(wager.amount)` under that lock, but the doc doesn't say so, and two developers could implement this differently (row-level lock on `CASTAWAY` vs. an aggregate-only check with no lock at all, reintroducing the race the whole decision exists to prevent).

**Recommendation:** state explicitly what row is locked and confirm the cap is scoped to the *current* wager set only (not lifetime), since resets create a fresh set.

**3. `Reset wagers` has no concurrency guard against double execution.**
"Reset wagers" checks "current set is locked" then finalizes + creates a new set — described as atomic, but nothing prevents two concurrent commissioner requests from both passing the "is locked" check and each creating a new current wager set (violating "exactly one non-finalized current wager set" invariant). Same class of risk as the wager-cap race the doc already solved elsewhere.

**Recommendation:** require the reset transaction to take a row lock on the league's active `WAGER_SET` (or a `BETTING_CONFIG` row) before validating and mutating.

## Important (ambiguous enough to cause divergent implementation or missing functionality)

**4. `AUDIT_EVENT` has no entity reference columns.**
It has `league_id`, `event_type`, and JSON `before_state`/`after_state`, but no `entity_type`/`entity_id`. "Players may view the scoring ledger but not commissioner audit attribution" and commissioner-facing "audit history" screens both need to query "all audit events for castaway X" or "for scoring action Y" — without indexed entity columns that means scanning/parsing JSON blobs.

**Recommendation:** add `entity_type` + `entity_id` (and possibly `deletion_batch_id` correlation) as first-class columns.

**5. No entity tracks Resend notification status.**
Operational Considerations says "Store notification status and expose retry to commissioners," and the Failure Modes table relies on "persisted failed notification status," but the data model has nothing for it (no `NOTIFICATION` table, no field on `LEAGUE_MEMBERSHIP`/`ACCOUNT`).

**Recommendation:** add an explicit table/column with status + provider message id + retry count before the notification adapter can be built to spec.

**6. `ACCOUNT.email` is denormalized from Supabase Auth with no sync story.**
Since Supabase Auth owns identity/email and the app stores its own `email` column, nothing describes what happens if a user's email changes in Supabase (e.g., via password-reset/email-change flow) or how invitation-email matching is re-verified afterward.

**Recommendation:** either state email changes aren't supported in v1, or define a sync mechanism (webhook, or always read email from the verified JWT rather than a stored column).

**7. `budget_source` enum on `BETTING_PARTICIPATION` is unspecified.**
Never enumerated (e.g., `initial`, `late_entry`, `carryover`). Trivial to fix now, easy to bikeshed later mid-implementation.

**8. Missing primary keys on `ROSTER_PICK` and `WAGER`.**
Both entities show only FK/value columns with no `id PK`, unlike every other entity. If the composite key is intentional (`membership_id + bucket_id` for `ROSTER_PICK`, `participation_id + castaway_id` for `WAGER`), say so explicitly — audit references, soft-delete/restore operations, and ORM mapping all need a stable identity, and composite soft-deletable keys are awkward with partial unique indexes (mentioned elsewhere as a technique).

**Recommendation:** add a synthetic `id` to both — simpler and consistent with the rest of the schema.

**9. Tie-break algorithm is under-specified.**
"Main-score ties use bucket-by-bucket castaway placement; an equal bucket-win count remains tied" is the entire spec for a comparison algorithm.

**Recommendation:** spell out the algorithm step-by-step (what does "bucket win" mean when a player's roster is incomplete in that bucket? does missing-bucket-as-zero apply to tie-breaking too, or is that a separate rule from the standings-score zero rule?) before someone can implement it correctly.

**10. Only one global `castaway_cap` per league — no per-castaway variance.**
"Each castaway's league-wide cap" is actually one constant applied uniformly to every castaway. That may be intentional simplicity, but worth confirming with the product owner since favorite castaways will predictably fill first; if that's not the intended UX, this is the wrong place to discover it (mid-build).

## Minor (worth a note, low implementation risk)

- **Rate limiting** is required in Security/Operational sections but the architecture has no shared state store (Supabase is DB-only, no Redis/cache is explicitly excluded). In-memory rate limiting only works as long as the service stays a single instance — fine today, but should be called out as an assumption tied to "one web service" so it isn't silently broken by a future scale-out.
- **API versioning** is mentioned ("versioned JSON-over-HTTPS API") but no scheme is specified (URL prefix, header, etc.).
- **Timezone handling** for all the `datetime` columns is unspecified (assume UTC storage + client-local display, but say so).
- `SCORING_ACTION.deletion_batch_id` vs `SCORING_EVENT.action_deletion_batch_id` — naming is inconsistent for what's conceptually the same kind of tag; a reader has to infer they're related batch markers rather than unrelated fields.
- `tribes` on `CASTAWAY` is a plain string with no history — fine as flavor text, but flag if tribe-swap history is ever wanted, since it isn't a non-goal explicitly.

## Overall

No structural or architectural red flags — the modular monolith, Supabase/FastAPI boundary, event-sourced scoring, and transactional wager-cap approach are all sound and well-justified for the stated scale/budget. The issues above are concentrated in **underspecified data-model support entities** (audit entity refs, notification status, missing PKs) and a couple of **concurrency edges the doc's own stated pattern (row-lock + validate + commit) wasn't applied to consistently** (reset-wagers race). I'd treat items 1–3 as blocking clarifications and 4–10 as pre-implementation backlog items rather than "Open Issues: None."
