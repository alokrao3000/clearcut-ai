# ClearCut AI — Build Plan

## Stack decisions (and where they differ from the spec)

| Layer | Choice | Why |
|---|---|---|
| API | **FastAPI + SQLAlchemy 2 + Pydantic v2** (Python 3.12) | Same ecosystem as the LLM, PDF, and scraping libraries we need. One language for API + workers. |
| DB | **PostgreSQL 16** (Docker). SQLite for unit tests. | Relational hierarchy for rightsholders; `pg_trgm` for fuzzy directory search once the directory is large. |
| Fuzzy matching | **rapidfuzz** in-process now, `pg_trgm` later | A curated directory of a few thousand entities fits in memory. Elasticsearch is not needed until the asset catalog is huge. |
| Background jobs | **arq (Redis)** starting M3, FastAPI BackgroundTasks before that | Celery is heavy for this workload. arq is async-native and matches FastAPI. |
| Frontend | **Next.js (App Router) + TypeScript + Tailwind + shadcn/ui + TanStack Table** | As spec'd. Dense grids + Kanban. |
| Docs/PDF | **Jinja2 HTML → PDF via WeasyPrint** | One template powers both the tokenized web view and the PDF. |
| Email | **Postmark or SendGrid** outbound + inbound webhook | Tokenized reply-to addresses per task. |
| LLM | **Claude API** with structured (tool-use) JSON output | Script extraction and reply-intent parsing. |

### Deliberate deviations

1. **No residential proxies / UA rotation.** Evading Getty/YouTube anti-bot controls breaches their terms and is a bad look for a legal-clearance product sold to studios' own lawyers. Instead, ingestion uses sanctioned paths:
   - YouTube and Vimeo **oEmbed** (no key) plus the YouTube Data API v3 (key) for upload date/description.
   - **Internet Archive** metadata API (public).
   - **Getty, Shutterstock, Pond5** partner APIs when keys are configured. Without keys, a single polite OpenGraph fetch, and if blocked, the asset is created with the URL + platform + ID parsed from the URL and flagged for manual entry.
   - Per-domain rate limiting + exponential backoff remain.
2. **Composite assets are the default, not the edge case.** Every asset is a parent; *clearance tasks* are the unit that moves through the Kanban. Each task has a rights **layer** (footage, master recording, composition, still image, performance/likeness, trademark/logo). A YouTube movie clip gets footage + master + composition tasks by default.
3. **Audit ledger is application-level** (SQLAlchemy flush hook) writing field-level diffs with actor type (`user` / `system` / `scraper` / `llm`). Portable, testable, and it captures *who* in a way DB triggers cannot. A Postgres trigger can be added later as a belt-and-braces check.
4. **Budget estimates are ranges with provenance.** Each estimate records the rate card, multipliers, and units used, so a producer can see why a number is what it is.

## Milestones

### M1 — Core domain + API (this session)
- Data model: projects, assets, clearance tasks (layers), rightsholders (hierarchy + aliases + contact profile), rate cards, audit log, disclaimer acceptances.
- Disclaimer gate: every mutating endpoint returns 428 until the current user has accepted the current disclaimer version.
- URL ingest: platform detection, ID parsing, oEmbed/Archive/OpenGraph metadata, normalized immutable ingest payload.
- Rights mapping: fuzzy match of owner/title/keywords against the directory, confidence scores, auto-assign above threshold, candidates list below it, manual override.
- Budget matrix: rate card × distribution × tier × units → low/high range with breakdown.
- Kanban stages with validated transitions; board endpoint.
- Seed directory (sample entities, clearly marked as placeholder data).
- Tests.

### M2 — Frontend
- Next.js app: project list, project scope form, URL batch-ingest box, asset cards with thumbnails, task datagrid, Kanban board (drag = stage transition), rightsholder picker with match candidates, audit history drawer, disclaimer modal.

### M3 — Script ingestion + workers
- Redis + arq. Move ingest and mapping to jobs.
- Parse .pdf (pypdf), .docx (python-docx), .fdx (XML). Scene-chunk the text.
- Claude extraction with a strict schema: asset mentions, scene heading, quote, suggested layers. Every extracted asset links back to page/scene.
- Thumbnail caching to S3-compatible storage (MinIO locally).

### M4 — Outreach packets + secure context views
- Clearance inquiry template (HTML → PDF), per-rightsholder template preferences.
- Tokenized, expiring (14-day) context views with a recipient-specific watermark tiled across the page and rendered into images for excerpts. Access logged.
- Scripts are never downloadable. Only excerpts the user explicitly selects are shared.

### M5 — Mail loop + cost ledger
- Outbound email with per-task reply-to tokens.
- Inbound webhook → Claude intent parser (approved / denied / quote / needs-info) → proposed transition. **Human confirms** before stage changes, because a misparsed quote is a real financial error. Auto-apply only above a confidence threshold, if the user opts in.
- Project cost ledger: estimated vs quoted vs signed.

### M6 — Hardening
- Auth (org / user / roles), multi-tenancy, Alembic migrations, Postgres audit trigger, E&O audit export (CSV/PDF), observability, deployment.

## Open risks
- **The rightsholder directory is the product.** Contacts and rate cards need a sourcing and verification process (manual research, user-contributed corrections with review). Seed data is placeholder only.
- **Rate cards are sensitive and vary widely.** Show estimates as ranges with a confidence label and never as quotes.
- **Legal positioning.** Keep the disclaimer gate, avoid "cleared" wording in UI, and get counsel review before launch.
