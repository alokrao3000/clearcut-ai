# ClearCut AI

Pre-production asset sourcing and clearance workflow for film and media.
See [BUILD_PLAN.md](BUILD_PLAN.md) for architecture decisions and milestones.

**Status: M1 (core domain + API), M2 (frontend), M3 (script ingestion + workers), M3.5 (contact
resolution) and M4 (outreach packets + secure context views) complete.**
The mail loop and cost ledger are M5.

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
| Outreach | `GET /api/outreach/templates`, `GET /api/outreach/pdf-status`, `GET /api/projects/{id}/packet-groups`, `GET/POST /api/projects/{id}/packets` |
| Packets | `GET/PATCH/DELETE /api/packets/{id}`, `GET .../preview`, `GET .../pdf`, `POST .../finalize`, `POST .../excerpts`, `DELETE /api/excerpts/{id}` |
| Context views | `GET/POST /api/packets/{id}/context-views`, `POST /api/context-views/{id}/revoke`, `GET .../accesses` |
| Public (no auth) | `GET /view/{token}`, `GET /view/{token}/excerpt/{id}.png` |

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
| `/projects/{id}/outreach` | Tasks bundled by licensing desk, letter drafting, excerpt sharing, context links and their access logs |

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

## Who to contact

Every task carries a ranked answer to "who do we approach, and why", recomputed whenever the
asset or the directory changes. `GET /api/tasks/{id}/contacts` returns it; the task drawer shows it.

Three scores, kept separate because they answer different questions:

| Score | Question | Inputs |
|---|---|---|
| **Identity** | Can this party actually grant the right? | The matcher's name score, raised when the material itself credits them; a manual assignment counts as certain |
| **Reliability** | Will approaching them work? | Standing (major / notable / independent / unknown), whether a human verified the contact, how direct the licensing intake is, and reply history once M5 records it |
| **Cost** | What will it cost? | The budget matrix, run per candidate |

**Cost only breaks ties among parties that could plausibly grant the right.** A cheap licence
from someone who does not own the work clears nothing, so anything below
`CLEARCUT_CONTACT_MIN_IDENTITY` (default 60) is listed with a blocker and never recommended.
When a cheaper option loses to a more reliable one, the recommendation says so and names it —
Sony Music beating a one-person production company on reliability is visible, not hidden.

Reliability is a weighted mean over the components that have data, and every component ships
its own note, so the score can be argued with rather than taken on faith.

### Where the evidence comes from

Automatic, from material already held — the equivalent of checking the copyright page:

- `℗ 2019 RCA Records` → the **master recording** owner
- `© 1987 Sony Music Publishing` → the **underlying work**
- `Provided to YouTube by …`, `Licensed by …`, `Courtesy of …`, `Published by …`, `Photo: …`

These are the owner's own assertion, so they outrank name similarity, and the quote that
produced the match is shown next to the recommendation.

### Where it stops, and why

The registries people actually use for this are not machine-readable:

| Source | Status |
|---|---|
| U.S. Copyright Office (CPRS) | No documented public API. Set `CLEARCUT_COPYRIGHT_OFFICE_API_URL` at a gateway or a loaded copy of the bulk data to enable direct lookups |
| WATCH (Harry Ransom Center) | Searchable web database, no API, no stated terms for automated access — we do not scrape it |
| BISG Find a Rightsholder | Commercial; set `CLEARCUT_BISG_API_KEY` |
| Copyright Clearance Center | Commercial; set `CLEARCUT_CCC_API_KEY` |

So when nothing credible is found, the task produces **research leads** instead: pre-filled
searches against the right registry for that layer, plus the Copyright Alliance guide for
estates, probate records and firms-out-of-business. A lead marked `automatable` is one we hold
credentials for; the rest are honest homework for a person.

## Outreach packets and secure context views (M4)

A **packet** is one clearance inquiry addressed to one *licensing desk*, covering however many
tasks route there. The grain is the desk, not the task: a group that handles six clips from the
same archive wants one letter listing six items. `GET /api/projects/{id}/packet-groups` does that
bundling, walking up the corporate hierarchy — Warner Bros. Animation keeps its own intake, while
RCA's master recordings route to Sony Music Entertainment.

Templates are Jinja2, one per rightsholder kind, chosen from the directory's
`preferred_templates` and overridable per packet. One template renders both the on-screen preview
and the PDF, so what a producer approves is what goes out. Finalizing freezes the rendered HTML on
the packet: the ledger has to hold the bytes that were sent, not a re-render of them months later.

**Budget estimates never appear in the recipient-facing render.** They are shown only when
`internal=true`, which the public token route cannot set. Quoting your own range to a licensing
desk anchors the negotiation against the production.

### Context views

A **context view** is a tokenized, expiring, recipient-specific page:

- The token is 256 bits from `secrets`, stored only as a SHA-256 digest and looked up by digest, so
  a database dump yields no working links. The plaintext appears once, in the response that mints it.
- Expiry (14 days by default) is checked on every request; revocation is immediate.
- Expired, revoked and unknown tokens all render the **same** 404 page. Telling a stranger that a
  link used to work confirms it existed and who held it.
- Every hit is logged, refusals included — repeated attempts on a dead token are exactly what a
  clearance audit wants to see.
- A recipient-specific watermark is tiled across the page and burned into every excerpt image. It
  is deterrence and attribution, not DRM, and is not claimed to be more.

**The screenplay is never downloadable.** Only passages a user explicitly selects are shared, the
text is frozen at selection time so later edits cannot widen what an issued link discloses, and each
passage is served as a rasterized PNG rather than as text.

### PDF rendering

WeasyPrint wraps native Pango/cairo libraries that `pip install` does not provide. The import is
probed once at startup, so a host without them degrades to a 503 naming what to install rather than
a stack trace from inside cffi — the HTML letter works regardless. `GET /api/outreach/pdf-status`
reports the state and the frontend disables the download button and shows the hint.

On Windows, install the [GTK3 runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases)
and restart the API. On Debian/Ubuntu, `apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi-dev`.
On macOS, `brew install pango`.
