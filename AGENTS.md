# Agent Working Agreement

## Source of truth

- GitHub issues are the unit of work. Implement one issue per branch and pull request.
- `docs/design/survivor-fantasy.md` is the product and architecture source of truth.
- If an issue conflicts with the design, stop and surface the conflict in the issue instead of silently changing a domain rule.

## Before coding

1. Read the issue, its dependency list, and the linked design sections.
2. Confirm every blocking issue is closed or that the required interface already exists on the base branch.
3. Keep the change inside the issue scope. Record follow-up work as a new GitHub issue.

## Architecture boundaries

- React talks to Supabase only for authentication. All application data goes through `/api/v1`.
- FastAPI owns authorization and every domain mutation.
- Domain writes that touch multiple records use one PostgreSQL transaction.
- League-scoped records are never fetched or mutated without a league predicate.
- Scores and betting contributions are derived from authoritative events and wager records; do not persist mutable standings totals.
- Application tables belong in a private, unexposed PostgreSQL schema.
- Never expose database credentials, Supabase secret/service-role keys, or Resend keys to the browser.

## Definition of done

- Acceptance criteria in the issue are covered by automated tests at the lowest useful layer.
- Cross-league and role-denial paths are tested for protected domain work.
- Backend changes pass `uv run ruff check .`, `uv run mypy backend`, and `uv run pytest`.
- Frontend changes pass `npm run lint`, `npm run typecheck`, `npm run test -- --run`, and `npm run build` from `frontend/`.
- API contract changes regenerate the checked-in TypeScript API types.
- User-facing behavior is responsive, keyboard accessible, and has explicit loading, empty, error, and success states.
- The pull request links the issue with `Closes #<number>` and documents verification performed.

