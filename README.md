# ClearCut AI

Pre-production asset sourcing and clearance workflow for film and media.
See [BUILD_PLAN.md](BUILD_PLAN.md) for architecture decisions and milestones.

**Status: M1 (core domain + API) and M2 (frontend) complete.** Script ingestion and workers are M3.

## Run

```bash
docker compose up -d --wait            # Postgres on localhost:5435
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
cp .env.example .env                   # points at the compose database
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for the interactive API. Without `.env` the app falls back to a local SQLite file.

Then the frontend, in a second terminal:

```bash
cd frontend
npm install
cp .env.example .env.local             # NEXT_PUBLIC_API_BASE, NEXT_PUBLIC_USER_ID
npm run dev                            # http://localhost:3000
```

The API only allows CORS from `http://localhost:3000`, so keep that port.

Tests (in-memory SQLite, no network):

```bash
cd backend && .venv/Scripts/python -m pytest -q
```

## Try it

```bash
B=http://localhost:8000
curl -X POST $B/api/disclaimer/accept          # writes return 428 until this is done
curl -X POST $B/api/projects -H 'content-type: application/json' \
  -d '{"name":"Diner","distribution_scope":"worldwide_streaming","production_tier":"sag_moderate_low"}'
curl -X POST $B/api/projects/<id>/ingest -H 'content-type: application/json' \
  -d '{"items":[{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","notes":"jukebox in diner","usage_seconds":40}]}'
curl $B/api/projects/<id>/board
curl $B/api/projects/<id>/budget
```

Identity is the `X-User-Id` header (default `dev-user`) until auth lands in M6.

## Concepts

- **Asset** is a composite parent created from a URL. Its scraped fields are editable; `ingest_payload` is a frozen snapshot.
- **Clearance task** is one right on one asset: footage, still image, master recording, composition, performance, or trademark. Tasks move through the Kanban independently. YouTube and Vimeo assets start with footage + master + composition.
- **Rightsholder** directory has a parent hierarchy. Contact details resolve upward to the nearest entity with a licensing intake.
- **Rights matching** scores the owner, title, and keywords against names and aliases. It auto-assigns only on a strong, unambiguous match and never overwrites a manual assignment.
- **Budget** is rate card × distribution multiplier × tier factor × units. Rate cards resolve entity, then parent, then industry default. Approved budgets are never recalculated silently.
- **Audit log** records every field change with actor type (`user`, `system`, `scraper`, `llm`) and actor id.

## Seed data

The directory and rate cards in `backend/app/seed.py` are **unverified placeholders**. Emails use the reserved `.example` domain so nothing can reach a real licensing desk.

## API surface

| Area | Endpoints |
|---|---|
| Disclaimer | `GET /api/disclaimer`, `POST /api/disclaimer/accept` |
| Projects | `GET/POST /api/projects`, `GET/PATCH/DELETE /api/projects/{id}` |
| Ingest and views | `POST /api/projects/{id}/ingest`, `GET .../assets`, `.../tasks`, `.../board`, `.../budget`, `POST .../estimate` |
| Assets | `GET/PATCH/DELETE /api/assets/{id}`, `POST .../layers`, `POST .../remap` |
| Tasks | `GET/PATCH /api/tasks/{id}`, `POST .../transition`, `POST .../estimate`, `GET .../history` |
| Directory | `GET/POST /api/rightsholders`, `GET/PATCH /api/rightsholders/{id}` |
| Audit | `GET /api/audit?table=&row_id=&actor_type=` |

## Frontend

Next.js 16 App Router + TypeScript + Tailwind v4 + shadcn-style components, TanStack Table v9 for the
datagrid, dnd-kit for the board, TanStack Query for server state.

| Route | What it does |
|---|---|
| `/` | Project list, create and delete |
| `/projects/{id}` | Batch URL ingest box, asset cards with thumbnails, per-layer task rows, metadata correction, add layer, re-map |
| `/projects/{id}/tasks` | Task datagrid: sort, text filter, stage filter |
| `/projects/{id}/board` | Kanban; drag a card to request a transition (keyboard: space, arrows, space) |
| `/projects/{id}/budget` | Estimates grouped by layer with totals and contingency |

Clicking any task opens a drawer with the allowed transitions, the rightsholder picker (filtered to the
kinds that can own that layer), the matcher's candidates and scores, the estimate breakdown, quote and
agreed fields, and the audit history for that task.

The disclaimer modal is non-dismissible and mirrors the server gate: writes return 428 until it is accepted.
Workflow rejections (409) surface as toasts carrying the server's own message, so the rules stay in one place.

```bash
cd frontend
npx tsc --noEmit && npx eslint . && npm run build
```
