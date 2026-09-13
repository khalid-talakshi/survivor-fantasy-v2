# Design Feedback: Survivor Fantasy Application (v2)

**Reviewer:** Gemini (Systems & Application Architecture Review)  
**Subject Document:** `docs/design/survivor-fantasy.md`  
**Output Target:** `docs/design/design-feedback-gemini.md`

---

## Executive Assessment

The design document in `docs/design/survivor-fantasy.md` is exceptionally well-structured, rigorous, and practical. It clearly defines domain boundaries, avoids over-engineering (such as unnecessary microservices, WebSockets, or distributed caches), and establishes sound principles like single-origin hosting, on-demand standings computation, and immutable event sourcing.

The core architecture—a FastAPI/React modular monolith hosted on Railway backed by Supabase PostgreSQL and Auth—is well-suited to the single-maintainer constraint and the ~$10/month budget.

This review focuses on deep system invariants, concurrency edge cases, mathematical/tie-breaking edge cases, schema completeness, and operational integration details that should be resolved or clarified prior to implementation.

---

## 1. Critical Concurrency & Domain Invariants

### 1.1 Concurrency Guard for `Reset wagers` and `Lock wagering`

* **The Issue:** The design explicitly details row-level locking for individual player wager placement under aggregate caps, but does not specify a concurrency guard for commissioner-level lifecycle commands:
  * If two commissioners (or one commissioner double-clicking) invoke **Reset wagers** concurrently, both requests could verify that `WAGER_SET.locked == true`, finalize the current set, calculate carry-forward budgets, and create multiple "current" non-finalized `WAGER_SET` records.
  * This violates the core invariant: *"exactly one non-finalized current wager set exists when betting is enabled."*
* **Recommendation:**
  1. Add a database constraint or lock pattern: Lock the league's `BETTING_CONFIG` or current `WAGER_SET` row (`SELECT ... FOR UPDATE`) at the start of `reset_wagers` and `lock_wagers` operations.
  2. Add a partial unique index in PostgreSQL ensuring only one unfinalized wager set exists per league:

     ```sql
     CREATE UNIQUE INDEX uq_single_active_wager_set 
     ON wager_set (league_id) 
     WHERE finalized_at IS NULL;
     ```

### 1.2 Mechanics of the Transactional Wager-Cap Lock

* **The Issue:** The design states: *"Represent each castaway's betting capacity in a lockable league-castaway row. A wager write locks the relevant capacity rows in stable identifier order, validates aggregate allocation, writes the player's allocation, and commits atomically."*
  However, when a player *modifies* an existing allocation (e.g., shifting 40 points from Castaway A to Castaway B), capacity is released on A and consumed on B.
* **Recommendation:** Explicitly document the transaction locking scope:
  * The transaction must lock all castaways in `(previous_wagered_castaway_ids ∪ new_wagered_castaway_ids)` ordered by `id ASC` (`SELECT id FROM castaway WHERE id = ANY(:ids) ORDER BY id FOR UPDATE`).
  * The aggregate usage check for each castaway $C$ must compute:
    $$\text{ExistingLeagueUsageExceptUser}(C) + \text{ProposedUserWager}(C) \le \text{castaway\_cap}$$
  * Confirm that the cap is scoped strictly to the *current* `wager_set_id` (wagers in finalized historical sets do not count toward active capacity).

### 1.3 Formal Definition of "Wager-Eligible Member"

* **The Issue:** The term "eligible player" is used throughout for initial budget assignment, resets, and locking validation, but its exact lifecycle condition is not formally pinned down:
  * Does a member in `participation_state = pending_roster` receive a wager participation and budget?
  * If a player joins late and has an incomplete roster, are they allowed to submit wagers, or must their roster be complete (`active`) before wager eligibility opens?
* **Recommendation:** Add an explicit assumption/rule:
  > *"A league member is eligible for betting participation in the current wager set if and only if their membership is active (`deleted_at IS NULL`), their role includes player participation (`participation_state = active`), and their membership was activated prior to the current wager set's `eligibility_closed_at`."*

---

## 2. Scoring, Standings & Algorithmic Edge Cases

### 2.1 Multi-Set Betting Payout Model

* **The Issue:** The doc defines that:
  1. Resetting wagers carries forward *only* stakes placed on active castaways into a new budget.
  2. Historical wager sets are archived as immutable snapshots.
  3. Leaderboard betting score = $2 \times \text{stake on winner}$ (or max potential surviving payout).
* **Clarification Needed:** Does the final season betting score derive **solely** from the *final/current* wager set?
  * *Example:* Player wagers 100 on Castaway X in Set 1. Reset occurs at merge; X is active, so player carries over 100. In Set 2, player puts 50 on X and 50 on Y. Castaway X wins the season.
  * Final betting score is $2 \times 50 = 100$ points (not $2 \times (100 + 50) = 300$).
* **Recommendation:** Explicitly state that because carry-forward budgets already roll over value from prior sets, only the **current/final active wager set** generates points for the leaderboard. Historical sets are audit records and context, not additive score sources.

### 2.2 Tie-Breaking Algorithm Specification

* **The Issue:** The doc states: *"Main-score ties use bucket-by-bucket castaway placement; an equal bucket-win count remains tied."*
  This description leaves several algorithmic ambiguities for the developer:
  1. **Incomplete Rosters:** If Player A has a missing pick in Bucket 2, does Player B automatically win Bucket 2 if Player B's castaway has any placement?
  2. **Shared Castaways:** What if Player A and Player B picked the *same* castaway in Bucket 1? (Neither wins the bucket / tie in bucket).
  3. **Multi-Way Ties (3+ players):** Bucket-win head-to-head comparisons are pairwise and can produce Condorcet cycles ($A > B$, $B > C$, $C > A$).
* **Recommendation:** Define the tie-breaker deterministically:
  * Compare tied players by:
    1. Highest number of buckets where the player's castaway finished with a strictly better placement than the opposing player's castaway.
    2. Sum of finishing placements across all selected castaways (lower sum wins; unpicked buckets or unplaced castaways assigned penalty placement $N + 1$).
    3. If still equal, assign identical rank (e.g., Tied for 2nd).

### 2.3 Numeric Representation and Increment Checks

* **The Issue:** Scoring actions allow half-point values (multiples of `0.5`, positive or negative).
* **Recommendation:**
  * In PostgreSQL, specify `NUMERIC(6, 1)` or `DECIMAL(6, 1)` rather than generic floating-point types (`float` / `double precision`).
  * Add a database check constraint to enforce half-point increments:

    ```sql
    CHECK (points * 2 = ROUND(points * 2))
    ```

  * In Pydantic/FastAPI, validate with `validator` or `Field(multiple_of=Decimal("0.5"))`.

---

## 3. Data Model & Schema Refinements

### 3.1 Explicit Primary Keys on Join/Allocation Entities

* **The Issue:** In the ERD, `ROSTER_PICK` and `WAGER` show only foreign keys and attributes without an explicit `id PK`.
* **Recommendation:** Give every entity a synthetic UUID `id PK`.
  * While composite keys (`membership_id, bucket_id` and `participation_id, castaway_id`) represent natural uniqueness, synthetic primary keys simplify ORM mappings (SQLAlchemy), audit tracking (`AUDIT_EVENT.entity_id`), and soft-deletion operations without composite FK gymnastics.

### 3.2 Partial Unique Indexes for Soft-Deletable Entities

* **The Issue:** Soft deletes (`deleted_at TIMESTAMP WITH TIME ZONE`) break standard SQL `UNIQUE` constraints when a deleted entity is re-created.
* **Recommendation:** Document that the following partial unique indexes are required in PostgreSQL migrations:
  * `LEAGUE_MEMBERSHIP (league_id, account_id) WHERE deleted_at IS NULL`
  * `ROSTER_PICK (membership_id, bucket_id) WHERE deleted_at IS NULL`
  * `CASTAWAY (league_id, placement) WHERE deleted_at IS NULL AND placement IS NOT NULL`
  * `CASTAWAY (league_id, name) WHERE deleted_at IS NULL`
  * `WAGER (participation_id, castaway_id) WHERE deleted_at IS NULL`
  * `BETTING_PARTICIPATION (membership_id, wager_set_id) WHERE deleted_at IS NULL`
  * `SCORING_ACTION (league_id, name) WHERE deleted_at IS NULL`

### 3.3 Notification Delivery Tracking Entity

* **The Issue:** Section *Operational Considerations* references storing failed Resend notifications so commissioners can retry, and the *Failure Modes* table lists "persisted failed notification status," but no table or column exists in the schema to store this state.
* **Recommendation:** Add a `LEAGUE_INVITATION_NOTIFICATION` or `NOTIFICATION_DISPATCH` table:

  ```sql
  CREATE TABLE notification_dispatch (
      id UUID PRIMARY KEY,
      league_id UUID NOT NULL REFERENCES league(id),
      account_id UUID NOT NULL REFERENCES account(id),
      notification_type VARCHAR(32) NOT NULL, -- e.g. 'existing_user_added'
      status VARCHAR(16) NOT NULL,            -- 'pending', 'sent', 'failed'
      provider_message_id VARCHAR(128),
      error_message TEXT,
      retry_count INT NOT NULL DEFAULT 0,
      created_at TIMESTAMPTZ NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL
  );
  ```

### 3.4 Audit Trail Queryability (`entity_type` and `entity_id`)

* **The Issue:** `AUDIT_EVENT` contains `actor_account_id`, `league_id`, `event_type`, `reason`, `before_state`, and `after_state`, but lacks indexed columns for the target entity (`entity_type` and `entity_id`).
* **Recommendation:** Add `entity_type VARCHAR(64)` and `entity_id UUID` (with index `(league_id, entity_type, entity_id)`). This enables fast querying of audit logs for a specific castaway, scoring event, or member roster without table-scanning JSON state payloads.

---

## 4. Security, Authorization & Privacy

### 4.1 Token Invalidation vs. Local Account Revocation

* **The Issue:** The design mentions: *"Revoke or invalidate Supabase sessions before owner-initiated account deletion; deleting only the local row does not itself invalidate an already-issued token."*
  Supabase Auth JWTs are bearer tokens valid until expiration (typically 1 hour).
* **Recommendation:** FastAPI’s authentication dependency should query the local `ACCOUNT` table by `supabase_user_id = token.sub` on every request. If `account.deleted_at IS NOT NULL` or the account does not exist, reject the request with `HTTP 401 Unauthorized` immediately. This guarantees that local account deactivation takes effect instantly without waiting for JWT expiration or relying on provider session termination.

### 4.2 Commissioner Proxy-Wager vs. Wager Secrecy Tension

* **The Issue:** The design specifies that:
  1. Commissioners cannot see any other player's unlocked wagers.
  2. Commissioners *are* permitted to submit a first complete allocation on behalf of an unsubmitted player before lock.
* **Observation:** If a commissioner submits wagers on behalf of a player, the commissioner inherently knows that player's picks and amounts.
* **Recommendation:** Acknowledge this edge case in the security section: proxy submissions by commissioners are strictly an administrative fallback for unresponsive players; commissioner-entered wagers create a detailed audit record, but inevitably compromise that specific player's allocation secrecy relative to the acting commissioner.

### 4.3 Email Normalization and Invitation Matching

* **The Issue:** Case sensitivity discrepancies between Supabase Auth and application tables can lead to failed identity lookups (e.g. `User@Example.com` vs `user@example.com`).
* **Recommendation:** Enforce case-insensitive email normalization (`LOWER(TRIM(email))`) on all invitations, account linking, and existing-user membership lookups.

---

## 5. Deployment & Operational Architecture

### 5.1 Single-Origin SPA Routing on FastAPI

* **The Issue:** Serving compiled React static assets from FastAPI requires specific handling of client-side routing (HTML5 History API / React Router).
* **Recommendation:** Ensure the FastAPI server configuration includes a fallback route that returns `index.html` for all non-API GET requests that do not match physical static asset files:

  ```python
  # Static asset mount for Vite build output
  app.mount("/assets", StaticFiles(directory="dist/assets"), name="assets")

  # Catch-all route for SPA client-side routing
  @app.get("/{full_path:path}")
  async def serve_spa(full_path: str):
      if full_path.startswith("api/"):
          raise HTTPException(status_code=404, detail="API endpoint not found")
      return FileResponse("dist/index.html")
  ```

### 5.2 Railway Healthcheck vs. Supabase Free-Tier Inactivity

* **The Issue:** Supabase free-tier projects automatically pause after 7 days of inactivity. If Railway's `/health/ready` check actively queries PostgreSQL, the service will enter a crash loop or fail readiness checks when the database is paused.
* **Recommendation:**
  * Separate `/health/live` (process running) from `/health/ready` (database connected).
  * Note in the runbook that if the Supabase project pauses in the off-season, an operator must unpause it in the Supabase Dashboard; the application should gracefully surface a clean "Database connecting/paused" message rather than crash Railway container orchestration.

### 5.3 On-Demand Standings Query Efficiency

* **The Issue:** Standings and ledgers are computed on demand. Without careful SQL aggregation, this could lead to N+1 query patterns in Python service code.
* **Recommendation:** Structure the standings calculation as a single composable SQL query using Common Table Expressions (CTEs):
  1. `RosterPicksCTE`: Active roster picks joined to castaways and buckets.
  2. `ScoringCTE`: `SUM(sa.points)` grouped by `castaway_id`.
  3. `BettingCTE`: Evaluated payout based on wager lock state and castaway status.
  4. Aggregate and calculate final totals per `LEAGUE_MEMBERSHIP` in one round-trip.

---

## 6. Prioritized Action Checklist

| Priority | Category | Action Item |
| --- | --- | --- |
| **High** | Concurrency | Add row lock on `BETTING_CONFIG` during `reset_wagers` and `lock_wagers` to prevent duplicate concurrent executions. |
| **High** | Concurrency | Add partial unique index for single active `WAGER_SET` (`WHERE finalized_at IS NULL`). |
| **High** | Domain / Math | Specify tie-breaking comparison algorithm in unambiguous step-by-step logic. |
| **High** | Data Model | Add explicit UUID primary keys to `ROSTER_PICK` and `WAGER`. |
| **Medium** | Data Model | Add notification tracking table (`notification_dispatch`) for Resend retry tracking. |
| **Medium** | Data Model | Add `entity_type` and `entity_id` indexed columns to `AUDIT_EVENT`. |
| **Medium** | Database | Define PostgreSQL partial unique indexes for soft-deleted entities. |
| **Medium** | Database | Enforce half-point scoring constraint in PostgreSQL schema (`CHECK (points * 2 = ROUND(points * 2))`). |
| **Low** | Architecture | Add SPA catch-all fallback routing specification to FastAPI deployment section. |
| **Low** | Security | Confirm case normalization (`LOWER(TRIM(email))`) on identity verification and invite flows. |

---

## Conclusion

The `survivor-fantasy.md` document is of high engineering quality, exhibiting careful thought around game mechanics, budget constraints, and simplicity. Addressing the concurrency locks on state transitions, formalizing the tie-breaker algorithm, and fleshing out the missing schema support columns (audit entity references, notification tracking, explicit PKs) will ensure smooth implementation without architectural backtracking.
