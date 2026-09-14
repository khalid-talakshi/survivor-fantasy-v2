# Survivor Fantasy

An invitation-only fantasy game for a private *Survivor* league. The application is a modular monolith: a React/TypeScript frontend and FastAPI backend deployed as one Railway service, with Supabase Auth and PostgreSQL and Resend email delivery.

The complete product and architecture specification is in [docs/design/survivor-fantasy.md](docs/design/survivor-fantasy.md). The agent-oriented implementation backlog is in [docs/planning/github-backlog.md](docs/planning/github-backlog.md).

## Local prerequisites

- Node.js 22
- Python 3.12
- `uv`
- PostgreSQL 15 or newer, or a local Supabase stack

## Setup

```bash
cp .env.example .env
uv sync
npm ci --prefix frontend
```

Run the API:

```bash
uv run uvicorn backend.app.main:app --reload
```

Use separate database identities for schema migrations and application traffic. The migration
creates a restricted `survivor_fantasy_runtime` login without a password and clears any accepted
pre-existing password before applying grants. Provision or reprovision its password out of band
with your database provider after migration, then set `DATABASE_URL` to that login. The local
example uses the development-only password `runtime`.

Set `MIGRATION_DATABASE_URL` to an identity allowed to create schemas and manage the runtime role,
then apply migrations with:

```bash
uv run alembic upgrade head
```

For the local-only credentials in `.env.example`, provision the example password after every
migration that creates or normalizes the runtime role (use your provider's secure SQL console
instead in production):

```sql
ALTER ROLE survivor_fantasy_runtime PASSWORD 'runtime';
```

When `MIGRATION_DATABASE_URL` is absent, Alembic falls back to `DATABASE_URL`; that fallback is
only suitable when the referenced identity has migration privileges. Review downgrades before
use; to revert the current schema migration explicitly, run `uv run alembic downgrade base`.
Downgrade removes the private schema and its database-local grants but deliberately retains the
cluster-global runtime login so another database on the same PostgreSQL cluster is not disrupted.
It also retains the revocation of `CREATE` on the `public` schema from both `PUBLIC` and the
runtime role as intentional database hardening; restoring broad object-creation access during a
rollback would be unsafe.

Run the frontend in another terminal:

```bash
npm run dev --prefix frontend
```

The Vite development server proxies `/api` and `/health` to FastAPI. Production builds are served by FastAPI from `frontend/dist`.

## Validation

```bash
uv run ruff check .
uv run ty check backend
uv run pytest
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm run test --prefix frontend -- --run
npm run build --prefix frontend
```

## Delivery workflow

GitHub issues are intentionally sized for autonomous agents. Pick an unblocked issue, create a dedicated branch, meet the issue acceptance criteria, and open a focused pull request. See [AGENTS.md](AGENTS.md) for the working agreement.
