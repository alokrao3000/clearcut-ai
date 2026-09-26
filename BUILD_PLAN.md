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

### M1 — Core domain + API — **done**
- Data model: projects, assets, clearance tasks (layers), rightsholders (hierarchy + aliases + contact profile), rate cards, audit log, disclaimer acceptances.
- Disclaimer gate: every mutating endpoint returns 428 until the current user has accepted the current disclaimer version.
- URL ingest: platform detection, ID parsing, oEmbed/Archive/OpenGraph metadata, normalized immutable ingest payload.
- Rights mapping: fuzzy match of owner/title/keywords against the directory, confidence scores, auto-assign above threshold, candidates list below it, manual override.
- Budget matrix: rate card × distribution × tier × units → low/high range with breakdown.
- Kanban stages with validated transitions; board endpoint.
- Seed directory (sample entities, clearly marked as placeholder data).
- Tests.

### M2 — Frontend — **done**
- Next.js app: project list, project scope form, URL batch-ingest box, asset cards with thumbnails, task datagrid, Kanban board (drag = stage transition), rightsholder picker with match candidates, audit history drawer, disclaimer modal.

### M3 — Script ingestion + workers — **done**
- Redis + arq. Move ingest and mapping to jobs.
- Parse .pdf (pypdf), .docx (python-docx), .fdx (XML). Scene-chunk the text.
- Claude extraction with a strict schema: asset mentions, scene heading, quote, suggested layers. Every extracted asset links back to page/scene.
- Thumbnail caching to S3-compatible storage (MinIO locally).

### M3.5 — Contact resolution — **done**
- Ownership evidence read from credit lines: (P)/(C) notices, "provided to YouTube by",
  "courtesy of", "published by", caption credits. The owner's own assertion outranks name matching.
- Per-task ranking of who to approach on three separate axes: identity (can they grant it),
  reliability (will they respond), cost (budget matrix per candidate). Cost only breaks ties
  among credible owners; below the identity floor an option is shown with a blocker, never recommended.
- Reliability = standing x verification x contact directness x reply history, weighted over the
  components that have data, each carrying its own note.
- No public API exists for CPRS or WATCH, and BISG/CCC are commercial, so unresolved tasks get
  pre-filled research links instead of a pretend lookup. Each registry turns into a live provider
  once its key or endpoint is configured.

### M4 — Outreach packets + secure context views — **done**
- Clearance inquiry templates (Jinja2 HTML → PDF), one per rightsholder kind, chosen from the
  directory's `preferred_templates` and overridable per packet. One template renders the preview
  and the PDF; finalizing freezes the HTML as the record of what was sent.
- A packet addresses one *licensing desk*, not one task, so the grouping walks up the corporate
  hierarchy. Internal budget estimates are excluded from every recipient-facing render.
- Tokenized, expiring (14-day) context views with a recipient-specific watermark tiled across the page and rendered into images for excerpts. Access logged.
- Scripts are never downloadable. Only excerpts the user explicitly selects are shared.
- Tokens are stored as SHA-256 digests and shown once. Expired, revoked and unknown tokens render
  an identical page, so a refusal never confirms that a link existed.
- WeasyPrint's native stack is probed once and degrades to a 503 with install instructions rather
  than failing the request; the HTML letter never depends on it.

### M5 — Mail loop + cost ledger — **done**
- Outbound email behind a provider seam (Postmark, SendGrid, and a `console` default that
  records the send without touching the network). Sending is refused to reserved `.example`
  domains and to unverified placeholder contacts unless explicitly overridden, so a dev box
  cannot mail a real licensing desk by accident.
- **Reply-to tokens are per packet, not per task** — a deviation from the original line above,
  and a consequence of M4: a packet is what gets sent, so a reply belongs to the letter rather
  than to one of the items in it. The parser attributes outcomes to individual tasks. The token
  is stored in plaintext because it rides in the headers of every message we send; the webhook
  signature, not the token, is the trust boundary.
- Inbound webhook → Claude intent parser (approved / denied / quote / needs-info / unclear) →
  proposed transition. **Human confirms** before stage changes. Every proposal carries the
  verbatim span of the reply it came from, and is pre-checked against the workflow guards so the
  queue shows what is actually actionable rather than offering a button that will fail.
- Auto-apply is opt-in and threshold-gated, and **never applies a proposal carrying an amount**.
  A wrong stage is visible on the board; a wrong fee becomes a number in a budget.
- Storing a reply comes before reading it: an unavailable or crashing parser costs the reading,
  never the message. Unroutable replies are kept, and the webhook answers identically either way
  so it cannot be used to discover which tokens are live.
- Project cost ledger: estimated vs quoted vs signed per task, with variance against the top of
  the estimate range and contingency applied only to the part still being guessed.

### M6 — Hardening — **done**
- **Auth.** Opaque session tokens stored as SHA-256 digests, not JWTs: a clearance file is
  evidence, and "revoke this person now" has to mean now. bcrypt for passwords, with the cost
  configurable because it travels inside each hash. Login answers identically — and takes the
  same time — for a wrong password, an unknown address and a disabled account.
- **Roles** are ranked (`owner > admin > member > viewer`) and checked as "at least this", so
  adding a role later cannot silently widen an existing permission. A role change or a
  disabled account ends that user's sessions immediately.
- **Multi-tenancy.** The organization rides on the session, the same way the audit actor
  already did, so a loader cannot forget to pass something it never had to pass. Every
  cross-tenant access is a **404, not a 403**: confirming an id is real but not yours turns an
  id-guessing loop into a census of other tenants' projects. The seeded directory is shared
  (`org_id IS NULL`) and read-only; a tenant's own entries are private to it.
- **Alembic** owns the schema. `create_all` silently added tables and never columns, which is
  why a model change used to appear to work and then fail at the first query. The tenancy
  migration backfills existing projects — and their audit history — into an adopting
  organization rather than failing on a NOT NULL column.
- **PostgreSQL audit trigger** writes to a separate `db_audit_log`. The value is the *gap*
  between it and the application ledger: a row with no matching application entry is a change
  made outside the app. On SQLite the export says the check was unavailable rather than
  implying a clean result.
- **E&O export** (JSON, two CSVs and an HTML/PDF report) is built around provenance rather
  than status: per item, who decided what, on what basis, and when, with the actor type on
  every ledger entry so an automated decision is distinguishable from a human one.
- **Observability**: a request id on every log line and response, JSON logs behind a flag, and
  readiness that names the failing component. Only the database can make the service unready —
  Redis, object storage, PDF and the LLM are reported but never fail the check, because the
  product is deliberately usable without them.
- **Deployment**: Dockerfiles for both halves (the API image installs the Pango stack, so PDF
  works on a server where nobody can read an install hint), a production compose file where
  migrations are their own service, and a documented `.env.example`.

## Open risks
- **The rightsholder directory is the product.** Contacts and rate cards need a sourcing and verification process (manual research, user-contributed corrections with review). Seed data is placeholder only.
- **Rate cards are sensitive and vary widely.** Show estimates as ranges with a confidence label and never as quotes.
- **Legal positioning.** Keep the disclaimer gate, avoid "cleared" wording in UI, and get counsel review before launch.
