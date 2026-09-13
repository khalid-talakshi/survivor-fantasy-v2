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

Run the frontend in another terminal:

```bash
npm run dev --prefix frontend
```

The Vite development server proxies `/api` and `/health` to FastAPI. Production builds are served by FastAPI from `frontend/dist`.

## Validation

```bash
uv run ruff check .
uv run mypy backend
uv run pytest
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm run test --prefix frontend -- --run
npm run build --prefix frontend
```

## Delivery workflow

GitHub issues are intentionally sized for autonomous agents. Pick an unblocked issue, create a dedicated branch, meet the issue acceptance criteria, and open a focused pull request. See [AGENTS.md](AGENTS.md) for the working agreement.

