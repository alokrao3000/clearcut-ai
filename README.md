# ClearCut AI

Pre-production asset sourcing and clearance workflow for film and media.
See [BUILD_PLAN.md](BUILD_PLAN.md) for architecture decisions and milestones.

**Status: M1 (core domain + API), M2 (frontend) and M3 (script ingestion + workers) complete.**
Outreach packets and tokenized context views are M4.

## Run

```bash
docker compose up -d --wait            # Postgres 5435, Redis 6382, MinIO 9002/9003
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

## Scripts and background jobs (M3)

Upload a screenplay and it is parsed into scenes immediately; reading it with Claude happens
as a background job, so a slow or unconfigured model never blocks the upload.

```bash
curl -X POST $B/api/projects/<id>/scripts -F "file=@screenplay.fdx"
curl $B/api/scripts/<script_id>/scenes      # what the parser found
curl $B/api/scripts/<script_id>/mentions    # what the extractor proposed
curl -X POST $B/api/mentions/<mention_id>/confirm -H 'content-type: application/json' \
  -d '{"usage_seconds": 40}'                # a human accepts -> asset + layer tasks
```

- **.pdf** (pypdf), **.docx** (python-docx) and **.fdx** (Final Draft XML) are supported. Scenes
  split on sluglines (`INT.` / `EXT.` / `I/E` / `EST.`); `.fdx` uses its declared structure.
  A scanned PDF with no text layer is rejected with a message rather than silently yielding nothing.
- **Nothing the model says becomes an asset on its own.** Extraction writes *mentions*: a title,
  the verbatim script quote, the scene and page it came from, suggested layers and a confidence.
  Confirming one is a user action, and only then do the matcher and budget matrix run.
- The uploaded file is never stored — only its parsed text.
- Extraction needs credentials (`CLEARCUT_ANTHROPIC_API_KEY`, `ANTHROPIC_API_KEY`, or `ant auth login`).
  Without them the script still parses and the job reports `extraction: unavailable`.

### Workers

Jobs run inline by default, so nothing extra is needed to develop or test. To run them out of
process:

```bash
CLEARCUT_USE_WORKER=true .venv/Scripts/python -m arq app.worker.WorkerSettings
```

Set `CLEARCUT_USE_WORKER=true` for the API too, and script extraction, `POST .../ingest` with
`{"defer": true}`, re-mapping and thumbnail caching all queue to Redis instead. If Redis is
unreachable the enqueue falls back to running inline rather than losing the work. Job state is a
row in `jobs`, readable at `GET /api/jobs/{id}`, so progress never depends on Redis being up.

Thumbnail caching to MinIO is off until `CLEARCUT_THUMBNAIL_CACHE_ENABLED=true`.
