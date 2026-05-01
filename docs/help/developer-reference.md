# Developer Reference

This is the **canonical deep-dive** for everyone integrating with,
extending, or operating MarkFlow at the API / database / shell level.
Everything operator-facing lives in the other help articles; this one
is for engineers + integrators.

The auto-generated OpenAPI spec lives at:

- `http://localhost:8000/docs` -- Swagger UI, every endpoint with
  request/response shapes
- `http://localhost:8000/redoc` -- ReDoc rendering of the same spec
- `http://localhost:8000/openapi.json` -- raw JSON for tooling

Bookmark `/docs` -- it's authoritative for the full surface area. The
sections below cover the most-used parts in human-readable form, plus
the operational details Swagger doesn't capture (auth flow, log event
taxonomy, schema relationships, runbook).

---

## Contents

1. [Quick start](#quick-start)
2. [Authentication](#authentication)
3. [API surface (high-level)](#api-surface-high-level)
4. [Active Operations Registry (v0.35.0)](#active-operations-registry-v0350)
5. [New UX Architecture (v0.36.0)](#new-ux-architecture-v0360)
6. [Premiere project cross-reference (v0.34.0)](#premiere-project-cross-reference-v0340)
7. [LLM cost subsystem (v0.33.x)](#llm-cost-subsystem-v033x)
8. [Search + AI Assist](#search--ai-assist)
9. [Pipeline / bulk conversion](#pipeline--bulk-conversion)
10. [Lifecycle + Trash](#lifecycle--trash)
11. [Storage + mounts](#storage--mounts)
12. [Analysis (image-vision) queue](#analysis-image-vision-queue)
13. [Logs + log management](#logs--log-management)
14. [Database schema](#database-schema)
15. [Log event taxonomy](#log-event-taxonomy)
16. [Format handler architecture](#format-handler-architecture)
17. [Docker / CLI workflows](#docker--cli-workflows)
18. [Environment variables](#environment-variables)
19. [Runbook](#runbook)

---

## Quick start

```bash
# Build (first time, or after Dockerfile.base changes — apt packages,
# torch version, etc.)
docker build -f Dockerfile.base -t markflow-base:latest .

# Build app image (rebuilds pip + code layer; reuses cached base)
docker-compose build

# Bring everything up
docker-compose up -d

# Verify
curl localhost:8000/api/health | jq .

# Tail logs
docker-compose logs -f markflow

# Stop
docker-compose down
```

**Default ports:**

| Port | Service |
|------|---------|
| 8000 | FastAPI app (HTTP API + static UI) |
| 8001 | MCP server (Model Context Protocol over SSE; endpoint `/sse`) |
| 7700 | Meilisearch (full-text index) |
| 6333 | Qdrant (vector index — best-effort, optional) |

The app loads codebase + user instructions from `CLAUDE.md` at the
repo root; routes register through `app.include_router()` in `main.py`.

---

## Authentication

MarkFlow has three auth surfaces. **In production every endpoint above
SEARCH_USER role requires a valid token.**

### 1. JWT (issued by UnionCore — Phase 10 integration)

The user's browser carries a JWT cookie issued by UnionCore. Every API
request includes either:

```
Authorization: Bearer <token>
```

or the cookie is sent automatically with `credentials: 'same-origin'`
when calling from same-origin static pages.

The JWT carries:

- `sub` -- stable user id
- `email` -- user's email
- `role` -- one of `search_user` / `operator` / `manager` / `admin`

`UNIONCORE_JWT_SECRET` env var must match what UnionCore signed with.

### 2. `X-API-Key` (service accounts)

External programs (IP2A, asset-management dashboards, scripts) get a
service-account API key issued by an admin via:

```
POST /api/admin/api-keys
{
  "label": "ip2a-prod-readonly",
  "role": "operator"
}
```

Response includes the **plaintext key once** -- store it. Subsequent
list endpoints only show the prefix + key id. Use it in every request:

```
X-API-Key: mk_live_<prefix>_<secret>
```

The key is hashed (PBKDF2) with the `API_KEY_SALT` env var server-side.

### 3. `DEV_BYPASS_AUTH=true` (dev only)

Setting `DEV_BYPASS_AUTH=true` in `.env` skips token validation and
treats every request as `admin`. **Production must set this to `false`.**
The lifespan startup will refuse to start in production mode if
`UNIONCORE_JWT_SECRET`, `API_KEY_SALT`, or `SECRET_KEY` is missing or
weak (<32 chars).

### Role hierarchy

```
search_user < operator < manager < admin
```

Routes use `Depends(require_role(UserRole.OPERATOR))`. A request with
role `manager` satisfies `operator` requirements -- the hierarchy is
strictly inclusive.

### Logging an authentication failure

Every 401 / 403 emits a log event:

```bash
curl 'http://localhost:8000/api/logs/search?q=auth_failed'
```

---

## API surface (high-level)

Routers register from `api/routes/*.py` in `main.py`. As of v0.36.0 the
prefixes you'll likely care about:

| Prefix | Module | Purpose |
|--------|--------|---------|
| `/api/auth/*` | `auth` | Token issuance / validation pass-through |
| `/api/admin/*` | `admin`, `db_health`, `db_backup`, `log_management` | Admin panel + DB ops + log archive |
| `/api/admin/llm-costs` | `llm_costs` | Rate table + reload |
| `/api/admin/api-keys` | `admin` | Service-account key management |
| `/api/convert` | `convert` | Single-file convert |
| `/api/batch/*` | `batch` | Multi-file convert (deprecated; use `/api/bulk`) |
| `/api/bulk/*` | `bulk` | Bulk conversion jobs (start, pause, resume, cancel, status) |
| `/api/pipeline/*` | `pipeline` | Auto-conversion pipeline (run-now, pause, status) |
| `/api/search/*` | `search` | Full-text + AI-assisted search |
| `/api/analysis/*` | `analysis`, `llm_costs` | Image-analysis queue + cost-estimation |
| `/api/preview/*` | `preview` | File detail / preview page (path-keyed) |
| `/api/prproj/*` | `prproj` | Premiere project cross-reference (v0.34.0) |
| `/api/lifecycle/*` | `lifecycle` | Mark-for-deletion workflow |
| `/api/trash/*` | `trash` | Trash management (empty, restore, list) |
| `/api/scanner/*` | `scanner` | Lifecycle scanner control + progress |
| `/api/storage/*` | `storage`, `mounts`, `browse` | Source / output directory + SMB / NFS mounts |
| `/api/logs/*` | `logs`, `client_log`, `log_management` | Log search + live tail (SSE) + bundle download |
| `/api/locations` | `locations` | Named source / output locations |
| `/api/llm-providers/*` | `llm_providers` | Configure providers (Anthropic / OpenAI / Gemini / Ollama) |
| `/api/flags/*` | `flags` | Content moderation / flagged files |
| `/api/help/*` | `help` | Help wiki (public, no auth) |
| `/api/health` | `admin` | System health check |
| `/api/active-ops` | `active_ops` | Active Operations Registry — list running ops + cancel (v0.35.0) |
| `/api/me` | `me` | Authenticated user identity, role, and build info. OPERATOR+. |
| `/api/activity/summary` | `activity` | Activity dashboard aggregator — scan health, file delta, pipeline state, recent ops. OPERATOR+. |
| `/api/user-prefs` | `user_prefs` | Per-user preferences (layout, pinned folders, density, onboarding state). Portable across machines. AUTH_USER+. |
| `/api/telemetry` | `telemetry` | UI event sink — ui.* events (button clicks, navigation). Accepts unauthenticated POSTs from the browser. |

For the full list, hit `/openapi.json`.

### Active Operations Registry (v0.35.0)

Two endpoints. Auth: JWT or `X-API-Key`.

**`GET /api/active-ops`** — OPERATOR+

Returns `{"ops": [...]}` — all running operations plus those finished within the last 30 seconds. Each op includes `op_id`, `op_type`, `label`, `icon`, `done`, `total`, `started_at_epoch`, `finished_at_epoch`, `cancellable`, `origin_url`, `started_by`, `error_msg`.

```bash
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/active-ops \
  | jq '.ops[] | {label, op_type, done, total}'
```

Response includes `Cache-Control: no-cache`.

**`POST /api/active-ops/{op_id}/cancel`** — MANAGER+

Requests cancellation of a running operation. Returns `{"cancelled": true}` on success. Returns `400` if the op is uncancellable or already finished; `404` if the `op_id` is unknown.

```bash
curl -s -X POST -H "X-API-Key: $KEY" \
  http://localhost:8000/api/active-ops/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/cancel
```

---

## New UX Architecture (v0.36.0)

### Feature flag

`ENABLE_NEW_UX` in `.env` controls which home page the app serves. When
`true`, `GET /` serves `static/index-new.html`; when unset or `false` it
serves `static/index.html` (the legacy UI). Read server-side via
`core.feature_flags.is_new_ux_enabled()`. Set `ENABLE_NEW_UX=true` in
`.env` to activate the new UX for a machine.

### Page structure

No SPA. Each page is a standalone HTML file the browser loads fresh on
navigation. JavaScript modules are vanilla ES5 IIFEs:

```javascript
(function(global) {
  'use strict';
  // ...
})(window);
```

No bundler, no transpiler, no build step. Every file is exactly what
ships to the browser.

### Boot pattern

Each page has a corresponding `*-boot.js` file that orchestrates
startup in four steps:

1. Calls `MFPrefs.load()` to hydrate the page from `localStorage`.
2. Calls `fetch('/api/me')` to get the current user's identity and role.
3. Runs any page-specific API fetches inside a `Promise.all()` so they
   execute in parallel.
4. Calls `ComponentName.mount(slot, data)` with the resolved data to
   render the page.

Boot scripts check the `role` returned by `/api/me` and redirect
`search_user` members away from OPERATOR+ pages before rendering.

### Component pattern

Components are global objects registered on `window`
(e.g. `window.MFCostCapDetail`, `window.MFOnboarding`). Each exposes a
`mount(slot, opts)` function that accepts a DOM element and a data
options object.

All DOM construction uses `createElement` / `textContent` / `appendChild`
exclusively. `innerHTML` with template literals is banned by project
convention -- the linter enforces this. Never bypass the convention with
`insertAdjacentHTML`, `outerHTML`, or similar.

### Design tokens

Colors, spacing, and typography are defined in
`static/css/design-tokens.css` as CSS custom properties (`--mf-*`).
Component styles live in `static/css/components.css` and consume tokens
via `var(--mf-*)`. Never hardcode hex values in component CSS -- always
reference a token, adding one to `design-tokens.css` if needed.

### Per-user preferences (`MFPrefs`)

`static/js/preferences.js` exposes three functions:

| Function | Signature | Notes |
|----------|-----------|-------|
| `MFPrefs.load()` | `() -> Promise<void>` | Fetches `GET /api/user-prefs` and merges into `localStorage`. Call once at boot. |
| `MFPrefs.get(key)` | `(string) -> string\|null` | Reads from `localStorage` synchronously. |
| `MFPrefs.set(key, value)` | `(string, string) -> void` | Writes to `localStorage` immediately and debounces a `PUT /api/user-prefs/{key}` within 500ms. |

`localStorage` is the fast-path for reads; the server is the persistence
layer. On a new device, `MFPrefs.load()` at boot restores the user's
settings before the page renders.

Supported keys (validated server-side against a whitelist):

| Key | Values | Purpose |
|-----|--------|---------|
| `layout` | `maximal` / `recent` / `minimal` | Home page document-card layout |
| `density` | `cards` / `compact` / `list` | Document grid density |
| `pinned_folders` | JSON array string | Folders pinned to the sidebar |
| `onboarding_done` | `1` / null | Whether the onboarding overlay has been dismissed |
| `advanced_actions_inline` | `1` / null | Whether advanced actions appear inline or in a menu |

### `/api/me` endpoint

`GET /api/me` — OPERATOR+. Returns:

```json
{
  "email": "xerxes@example.com",
  "role": "operator",
  "avatar_initials": "XS",
  "version": "0.36.0",
  "features": {
    "new_ux": true
  }
}
```

`role` is one of `search_user` / `operator` / `manager` / `admin`.
`features` is a flat object of feature flags; boot scripts use this to
conditionally enable UI surfaces without a server restart. Boot scripts
redirect `search_user` members away from OPERATOR+ pages.

### `/api/activity/summary` endpoint

`GET /api/activity/summary` — OPERATOR+. Returns a point-in-time
snapshot of the auto-conversion subsystem:

```json
{
  "scan_runs": 142,
  "source_count": 18420,
  "indexed_count": 18103,
  "pending_count": 317,
  "pipeline_state": "running",
  "recent_ops": [
    {
      "op_type": "bulk_job",
      "label": "Q4-archive",
      "done": 4102,
      "total": 4102,
      "finished_at_epoch": 1746000000
    }
  ]
}
```

The Activity dashboard renders from this endpoint. `pending_count` uses
the NOT EXISTS join pattern (never `COUNT(*) WHERE status='pending'` --
see bulk_files pending count quirk in `docs/gotchas.md`).

### `/api/user-prefs` endpoints

Two endpoints. Auth: JWT or `X-API-Key`. Minimum role: `AUTH_USER`
(any authenticated user).

**`GET /api/user-prefs`** -- returns all stored prefs for the current
user (keyed by the `sub` claim from their JWT):

```json
{ "prefs": { "layout": "maximal", "density": "cards" } }
```

**`PUT /api/user-prefs/{key}`** -- upserts a single preference. Body:

```json
{ "value": "compact" }
```

Returns `400` if the key is not in the server-side whitelist. Returns
`200 {"ok": true}` on success. `MFPrefs.set()` in the browser calls
this automatically within 500ms of a local write.

### `/api/telemetry` endpoint

`POST /api/telemetry` -- no authentication required (the browser sends
this on navigation before the user's token is guaranteed to be present).

Body:

```json
{
  "event": "ui.nav.click",
  "properties": { "target": "activity", "from": "home" }
}
```

Events are logged at `structlog` INFO level under the `telemetry.*`
prefix. No storage beyond the log file -- telemetry is append-only and
reviewed via `api/logs/search?q=telemetry`.

### Settings routing note

Routes under `/settings/ai-providers/cost` must be registered **before**
the `{section}` catch-all (`/settings/{section}`) in `main.py`. The
catch-all matches only one path segment -- it would 404 the
multi-segment sub-path otherwise. Always add new multi-segment settings
routes above the catch-all in the router registration block.

### Onboarding flow

`MFOnboarding.show(opts)` mounts a full-viewport overlay on top of the
home page without replacing the underlying content. Signature:

```javascript
MFOnboarding.show({
  fetchSources: () => Promise<source[]>,  // lazy-fetched at Step 3
  onComplete: () => void,
  onSkip: () => void
});
```

`fetchSources` is a callback, not a resolved value -- the sources list
is only fetched when the user reaches Step 3 of the wizard, not at
mount time. On `onComplete` or `onSkip`, the overlay calls
`MFPrefs.set('onboarding_done', '1')` and removes itself from
`document.body`. The home page underneath remains intact throughout.

---

## Premiere project cross-reference (v0.34.0)

Three OPERATOR+ endpoints. Use the standard JWT or `X-API-Key` auth.

### `GET /api/prproj/references?path=<media_path>`

Reverse lookup: which Premiere projects reference a given media file?

```bash
curl -s 'http://localhost:8000/api/prproj/references?path=/footage/C0042.MP4' \
  -H 'X-API-Key: mk_live_xxx' | jq .
```

Response:

```json
{
  "media_path": "/footage/C0042.MP4",
  "count": 3,
  "projects": [
    {
      "project_id": "ab12cd34...",
      "project_path": "/projects/promo_v3.prproj",
      "media_name": "C0042.MP4",
      "media_type": "video",
      "recorded_at": "2026-04-28T15:42:01+00:00"
    },
    ...
  ]
}
```

Returns `count: 0` and `projects: []` when no project references the
path. HTTP 200 either way; HTTP 404 is reserved for routing errors.

### `GET /api/prproj/{project_id}/media`

Forward lookup: every media path a given project references.

```bash
curl -s 'http://localhost:8000/api/prproj/ab12cd34.../media' \
  -H 'X-API-Key: mk_live_xxx' | jq .
```

Response:

```json
{
  "project_id": "ab12cd34...",
  "count": 137,
  "media": [
    {
      "media_path": "\\\\NAS\\Footage\\BCAMERA\\C0042.MP4",
      "media_name": "C0042.MP4",
      "media_type": "video",
      "duration_ticks": null,
      "in_use_in_sequences": null,
      "recorded_at": "2026-04-28T15:42:01+00:00"
    },
    ...
  ]
}
```

### `GET /api/prproj/stats`

Aggregate stats across the whole cross-reference table.

```json
{
  "n_projects": 12,
  "n_media_refs": 1843,
  "top_5_most_referenced": [
    {"media_path": "/library/intro_sting.wav", "n_projects": 11},
    {"media_path": "/library/logo.psd", "n_projects": 8},
    ...
  ]
}
```

### Python integrator example

```python
import requests
API = "http://localhost:8000"
KEY = "mk_live_xxx"
HEADERS = {"X-API-Key": KEY}

def projects_for(media_path: str) -> list[dict]:
    r = requests.get(f"{API}/api/prproj/references",
                     params={"path": media_path}, headers=HEADERS)
    r.raise_for_status()
    return r.json()["projects"]

print(projects_for("/footage/C0042.MP4"))
```

### JavaScript example

```javascript
async function projectsFor(mediaPath) {
  const url = '/api/prproj/references?path=' + encodeURIComponent(mediaPath);
  const r = await fetch(url, { credentials: 'same-origin' });
  if (!r.ok) return [];
  return (await r.json()).projects;
}
```

### How the data gets there

1. The bulk scanner finds a `.prproj` file on disk.
2. `core/converter.py` invokes `formats/prproj/handler.py:PrprojHandler`.
3. `formats/prproj/parser.py:parse_prproj()` streams the gzipped XML
   through `lxml.iterparse` and harvests media-path leaves.
4. The handler renders Markdown (sequence list, media list, bin tree)
   AND calls `core/db/prproj_refs.py:upsert_media_refs_sync()` to
   populate `prproj_media_refs`.
5. The Markdown is written to the output directory and indexed by
   Meilisearch.

If the parse fails (corrupt gzip, encrypted project, unknown schema
root), the handler falls back to AdobeHandler-style metadata-only
output -- the bulk job continues, no rows are written to
`prproj_media_refs`. See `prproj.deep_parse_failed` in the log.

---

## LLM cost subsystem (v0.33.x)

Six endpoints. Every estimate carries the rate-table row used so the
calculation is verifiable.

| Endpoint | Role | Purpose |
|---|---|---|
| `GET /api/admin/llm-costs` | OPERATOR | Read the rate table |
| `POST /api/admin/llm-costs/reload` | ADMIN | Hot-reload the table from disk |
| `GET /api/analysis/cost/file/{entry_id}` | OPERATOR | Per-row cost estimate |
| `GET /api/analysis/cost/batch/{batch_id}` | OPERATOR | Per-batch summary + per-file breakdown |
| `GET /api/analysis/cost/period[?days=N]` | OPERATOR | Current billing cycle (or `?days=N` window) |
| `GET /api/analysis/cost/period.csv[?days=N]` | OPERATOR | Same data, CSV (for spreadsheet imports) |
| `GET /api/analysis/cost/staleness` | OPERATOR | `{is_stale, age_days, threshold_days}` |

**Rate table on disk:** `core/data/llm_costs.json`. Edit then
`POST /api/admin/llm-costs/reload` to apply -- no container restart.

**Audit trail:** every cost calculation emits a `llm_cost.computed`
log event. Search with:

```bash
curl 'http://localhost:8000/api/logs/search?q=llm_cost' -H 'X-API-Key: ...'
```

Other emitted events: `llm_cost.no_rate` (rate-table miss),
`llm_cost.csv_exported`, `llm_costs.stale` (daily check at 03:30),
`llm_costs.loaded` / `llm_cost.rate_table_reloaded`.

---

## Search + AI Assist

```bash
# Plain Meilisearch query
curl 'http://localhost:8000/api/search?q=annual+report' -H 'X-API-Key: ...'

# Filter by index (documents | adobe-files | transcripts)
curl 'http://localhost:8000/api/search?q=...&index=adobe-files'

# Filter by file type
curl 'http://localhost:8000/api/search?q=...&format=prproj'

# AI-assisted answer synthesis (LLM cost applies; OPERATOR+)
curl -X POST http://localhost:8000/api/ai-assist/synthesize \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: ...' \
  -d '{"query": "summarise the latest sales projections"}'

# Vector / semantic search (best-effort; returns Meili if Qdrant offline)
curl 'http://localhost:8000/api/search?q=...&mode=semantic'
```

---

## Pipeline / bulk conversion

```bash
# Start a bulk job (BodyParam in JSON; OPERATOR+)
curl -X POST http://localhost:8000/api/bulk/start \
  -H 'Content-Type: application/json' \
  -d '{"source_path": "/mnt/source/Q4-archive",
       "output_path": "/mnt/output-repo/Q4-md",
       "config": {"force_ocr": false, "worker_count": 8}}'

# Status (active jobs only; SSE alternative at /api/bulk/{job_id}/events)
curl 'http://localhost:8000/api/bulk/active' | jq .

# Pause / resume / cancel
curl -X POST http://localhost:8000/api/bulk/{job_id}/pause
curl -X POST http://localhost:8000/api/bulk/{job_id}/resume
curl -X POST http://localhost:8000/api/bulk/{job_id}/cancel

# Pipeline (auto-conversion master switch)
curl -X POST http://localhost:8000/api/pipeline/run-now    # bypass schedule
curl -X POST http://localhost:8000/api/pipeline/pause      # disable
curl    http://localhost:8000/api/pipeline/status

# Selectively convert pending files (OPERATOR+; cap 100; v0.31.6)
curl -X POST http://localhost:8000/api/pipeline/convert-selected \
  -H 'Content-Type: application/json' \
  -d '{"file_ids": ["abc123", "def456"]}'
```

---

## Lifecycle + Trash

```bash
# Mark-for-deletion (file enters grace period; default 36h)
curl -X POST http://localhost:8000/api/lifecycle/mark \
  -d '{"path": "/mnt/source/old.docx"}'

# Restore from grace
curl -X POST http://localhost:8000/api/lifecycle/restore -d '{"path": "..."}'

# Trash list (paginated; v0.32.3 returns true count)
curl 'http://localhost:8000/api/trash?per_page=25&page=1' | jq .

# Empty trash (whole pile, async; check /status for progress)
curl -X POST http://localhost:8000/api/trash/empty
curl 'http://localhost:8000/api/trash/empty/status'

# Restore everything
curl -X POST http://localhost:8000/api/trash/restore-all
curl 'http://localhost:8000/api/trash/restore-all/status'
```

---

## Storage + mounts

```bash
# Validate a path (used by Storage page Save button)
curl -X POST http://localhost:8000/api/storage/validate \
  -d '{"path": "/host/d/Doc-Conv_Test", "mode": "output"}'

# List drives MarkFlow can see
curl 'http://localhost:8000/api/browse?path=/host'

# SMB / NFS mounts
curl http://localhost:8000/api/storage/mounts
curl -X POST http://localhost:8000/api/storage/mounts -d '{...}'

# Sources + output directory
curl http://localhost:8000/api/storage/config
curl -X POST http://localhost:8000/api/storage/sources -d '{...}'
```

---

## Analysis (image-vision) queue

```bash
# Queue + worker status
curl http://localhost:8000/api/analysis/status

# Pause submission (v0.30.0; presets: 1h, 2h, 6h, 8h, off-hours, indef)
curl -X POST http://localhost:8000/api/analysis/pause \
  -d '{"duration_hours": 6}'

# Resume
curl -X POST http://localhost:8000/api/analysis/resume

# Per-batch list (filterable by status)
curl 'http://localhost:8000/api/analysis/batches?status=completed' | jq .

# Per-row detail
curl 'http://localhost:8000/api/analysis/queue/{entry_id}'

# Re-analyze (delete + re-INSERT semantics; v0.31.0)
curl -X POST http://localhost:8000/api/analysis/queue/{entry_id}/re-analyze

# Circuit breaker state (v0.29.9)
curl 'http://localhost:8000/api/analysis/circuit-breaker' | jq .

# Reset breaker (MANAGER+)
curl -X POST http://localhost:8000/api/analysis/circuit-breaker/reset

# ZIP bulk download (v0.31.4; cap 500 files / ~2 GiB; OPERATOR+)
curl -X POST http://localhost:8000/api/analysis/files/download-bundle \
  -d '{"file_ids": [...]}' --output bundle.zip
```

---

## Logs + log management

```bash
# Search archived + active logs (paginated)
curl 'http://localhost:8000/api/logs/search?q=prproj&limit=50' | jq .

# SSE live tail (multi-tab in /log-viewer.html)
curl -N 'http://localhost:8000/api/logs/tail/markflow'

# Inventory (admin)
curl http://localhost:8000/api/admin/log-management/inventory

# Bundle download (admin; ADMIN role)
curl http://localhost:8000/api/admin/log-management/bundle?range=7d --output logs.zip

# Manual archive run
curl -X POST http://localhost:8000/api/admin/log-management/archive
```

---

## Database schema

The DB is SQLite on disk (`markflow.db`), WAL journal mode. Connection
goes through a single-writer pool (`core/db/pool.py`) for writes and a
small read-pool for reads. See `core/db/schema.py:_SCHEMA_SQL` for the
full DDL.

Major tables (current as of v0.36.0):

| Table | Purpose |
|-------|---------|
| `bulk_jobs` | Bulk conversion job rows |
| `bulk_files` | Per-file conversion state inside a job (`UNIQUE(source_path)`) |
| `source_files` | Single source of truth for file-intrinsic data (path, size, hash, lifecycle) |
| `conversion_history` | Single-file conversion audit log |
| `file_versions` | Version history for changed files (Phase 9) |
| `scan_runs` | Lifecycle scanner run history |
| `analysis_queue` | Image-analysis queue (per-image LLM call) |
| `prproj_media_refs` | **v0.34.0** — Premiere project ↔ media cross-reference |
| `adobe_index` | Level-2 Adobe metadata catalogue |
| `file_flags` | Content moderation flags |
| `blocklisted_files` | Content blocklist |
| `api_keys` | Service-account credentials (hashed) |
| `locations` | Named source / output paths |
| `llm_providers` | Provider configs (Anthropic / OpenAI / etc.) |
| `system_metrics` | Resource monitoring time-series |
| `db_maintenance_log` | DB compaction / integrity history |
| `schema_migrations` | Applied migration versions |
| `user_preferences` | Singleton key-value config |
| `active_operations` | **v0.35.0** — Active Operations Registry. In-memory dict + DB write-through. Daily auto-purge of old finished rows. |
| `mf_user_prefs` | **v0.36.0** — Per-user preferences keyed by UnionCore `sub` claim. JSON value, schema-versioned. Distinct from `user_preferences` (system singletons). |

Cross-reference relationships:

- `bulk_files.source_file_id` -> `source_files.id`
- `bulk_files.job_id` -> `bulk_jobs.id`
- `prproj_media_refs.project_id` -> `bulk_files.id` (ON DELETE CASCADE)
- `file_flags.source_file_id` -> `source_files.id`
- `bulk_path_issues.job_id` -> `bulk_jobs.id`

**WAL safety note:** `shutil.copy2` of `markflow.db` can miss
committed transactions still in the `-wal` file. Always use the
SQLite online backup API (`POST /api/admin/db/backup` -- v0.24.0) for
a clean snapshot.

### Querying the DB inside the container

```bash
docker-compose exec markflow sqlite3 /app/markflow.db
sqlite> SELECT COUNT(*) FROM prproj_media_refs;
sqlite> .schema prproj_media_refs
sqlite> .quit
```

Or from the host (read-only mount):

```bash
docker-compose exec markflow sqlite3 -readonly /app/markflow.db ".schema bulk_files"
```

### Migrations

`core/db/schema.py:_MIGRATIONS` is a list of `(version, description,
[SQL])` tuples. `init_db()` runs `_run_migrations()` after the schema
DDL, recording applied versions in `schema_migrations`. Migrations are
idempotent -- ALTER TABLE "column already exists" is caught and ignored;
all other DDL failures propagate.

Latest migration: **30** -- adds `mf_user_prefs` (v0.36.0). Migration 29 adds `active_operations` (v0.35.0). Migration 28 adds `prproj_media_refs` (v0.34.0).

---

## Log event taxonomy

Every `log.info(...)` call emits a structured record with an `event`
key. Search via `/api/logs/search?q=<event>` or grep
`logs/markflow.log` directly.

Useful prefixes:

| Prefix | What it covers |
|--------|----------------|
| `prproj.*` | **v0.34.0** Premiere parse + cross-ref events (parsed, schema_unknown, deep_parse_failed, encrypted, media_ref_recorded, cross_ref_lookup) |
| `llm_cost.*` | Per-call cost estimation (computed, no_rate, csv_exported) |
| `llm_costs.*` | Subsystem lifecycle (loaded, rate_table_reloaded, stale) |
| `bulk_files.*` | Bulk worker lifecycle (start, pause, resume, cancel, complete) |
| `scanner.*` | Lifecycle scanner (run_started, run_complete, scan_progress) |
| `pipeline.*` | Auto-conversion pipeline (run_now, paused, resumed, decision) |
| `analysis.*` | Image-vision queue (claim, batch_submitted, batch_completed, ...) |
| `vision_circuit.*` | Vision API circuit breaker (open, half_open, closed, reset) |
| `auth.*` | Token validation (auth_failed, jwt_expired, role_satisfies, ...) |
| `db.*` | DB lifecycle (migrations_applied, integrity_check_*, vacuum_*) |
| `lifecycle.*` | File lifecycle (mark_for_deletion, restore, purge) |
| `mount.*` | SMB / NFS mounts (probe, success, failure) |
| `markflow.*` | App lifespan (startup, db_ready, shutdown) |
| `active_ops.*` | **v0.35.0** Active Operations Registry (register, update, finish, cancel, purge, hydrate) |
| `telemetry.*` | **v0.36.0** UI event sink (event received, event logged) |
| `user_prefs.*` | **v0.36.0** Per-user prefs (loaded, set, schema_mismatch) |

Worth knowing:

- The Log Viewer (`/log-viewer.html`) accepts `?q=<text>` and
  `?mode=history` URL params (v0.32.1) -- deep-linkable.
- Events from MarkFlow's own structlog go to `logs/markflow.log` (60d
  retention, configurable).
- A daily 02:00 cron archives + compresses old logs (gzipped).

---

## Format handler architecture

Handlers live under `formats/`. Each handler:

1. Subclasses `formats.base.FormatHandler` (ABC).
2. Declares `EXTENSIONS = ["abc", "xyz"]` -- the file extensions it
   handles, lower-case, no leading dot.
3. Decorates the class with `@register_handler` (registers each
   extension into the global registry).
4. Implements three methods:
   - `ingest(file_path) -> DocumentModel` -- read + parse
   - `export(model, output_path, sidecar=None, original_path=None)` --
     write Markdown (or back to the original format)
   - `extract_styles(file_path) -> dict` -- per-element style data

The registry is **last-writer-wins**: if two handlers register for the
same extension, whichever one's module imports later in
`formats/__init__.py` takes the slot. `PrprojHandler` (v0.34.0) wins
over `AdobeHandler` for `.prproj` because the import order in
`formats/__init__.py` puts `prproj.handler` after `adobe_handler`.

### Adding a new handler

1. Create `formats/myformat/handler.py` (or a flat
   `formats/myformat_handler.py`).
2. Subclass `FormatHandler`, decorate with `@register_handler`,
   implement `ingest` / `export` / `extract_styles`.
3. Add `from formats.myformat.handler import MyHandler  # noqa: F401`
   to `formats/__init__.py` (side-effect import). Place it after any
   handler whose extensions you want to override.
4. Drop a fixture into `tests/fixtures/`, write a unit test in
   `tests/test_myformat_handler.py`.
5. Add a row to `docs/key-files.md` and a section to the relevant help
   article (e.g. `docs/help/document-conversion.md`).

See `formats/prproj/parser.py` + `formats/prproj/handler.py` (v0.34.0)
for a recent worked example with synthetic-fixture testing,
defensive degradation, and a Phase 2 DB hook.

---

## Docker / CLI workflows

### Build cache layout

`Dockerfile.base` -- system deps (apt packages, libreoffice, ghostscript,
exiftool, hashcat, ffmpeg, ocrmypdf, etc.) + python install of large
deps (torch, whisper, lxml, etc.). Slow to build (~25 min HDD).

`Dockerfile` -- pip-install of `requirements.txt` + COPY of the
codebase. Fast to build (~2 min) when only Python code or small deps
change.

**When does the base need rebuilding?** Any change to `Dockerfile.base`
itself or the `apt-get install` line. Check after pulling a branch:

```bash
git diff <last-known-good-sha>..HEAD -- Dockerfile.base requirements.txt
```

If non-empty and touching apt packages, do the full sequence:

```bash
docker build -f Dockerfile.base -t markflow-base:latest .
docker-compose build
docker-compose up -d --force-recreate
```

### Common ops

```bash
# Force-recreate (when volume / deploy config changed)
docker-compose up -d --force-recreate

# Open a Python shell inside the running container
docker-compose exec markflow python

# Run pytest inside the container
docker-compose exec markflow pytest tests/test_prproj_handler.py -v

# Inspect a job's DB state
docker-compose exec markflow sqlite3 /app/markflow.db \
  "SELECT id, status, source_path FROM bulk_jobs ORDER BY created_at DESC LIMIT 5"

# Dump the prproj cross-ref table
docker-compose exec markflow sqlite3 /app/markflow.db \
  "SELECT project_path, COUNT(*) FROM prproj_media_refs GROUP BY project_path"

# Tail logs with structured filtering (jq)
docker-compose logs --tail=200 markflow | grep prproj | jq -R 'fromjson?'
```

### One-off scripts in the container

`Scripts/work/` holds operational helpers (overnight rebuild,
nightly DB compaction, bulk-job cleanup). Most are PowerShell for the
Windows host; the in-container ones are Python / bash.

The overnight rebuild pipeline (`Scripts/work/overnight-rebuild.ps1`)
does:

1. **Phase 0** -- preflight checks
2. **Phase 1** -- source sync (3 retries)
3. **Phase 1.5** -- anchor `:latest` as `:last-good` (BEFORE build, since
   BuildKit GC's the old image on tag reassignment)
4. **Phase 2** -- image build (2 retries)
5. **Phase 3** -- start + 45s lifespan pause + race override
6. **Phase 4** -- verify (`/api/health`, GPU expectation, MCP health)
7. **Phase 5** -- success / blue-green rollback on failure

Five exit codes: 0 = success, 1 = pre-commit failure, 2 = rollback
succeeded, 3 = rollback failed (stack DOWN), 4 = compose-divergence
refused.

---

## Environment variables

Read from `.env` (gitignored, per-machine). All optional unless
`DEV_BYPASS_AUTH=false`.

| Var | Default | Purpose |
|-----|---------|---------|
| `DB_PATH` | `markflow.db` | SQLite path (overridden in container to `/app/markflow.db`) |
| `DEV_BYPASS_AUTH` | `false` | Treat every request as `admin`. **Production must be `false`.** |
| `DEFAULT_LOG_LEVEL` | `normal` | `quiet` / `normal` / `elevated` / `developer` |
| `DEBUG` | `false` | Verbose error pages |
| `UNIONCORE_JWT_SECRET` | (unset) | **Required in prod.** Shared secret for JWT validation. |
| `UNIONCORE_ORIGIN` | (unset) | CORS allow-origin in prod. |
| `API_KEY_SALT` | (unset) | **Required in prod.** PBKDF2 salt for hashing API keys. |
| `SECRET_KEY` | (unset) | **Required in prod**, >=32 chars, not a known weak default. |
| `SOURCE_DIR` | (unset) | Per-machine source mount (used by `docker-compose.yml`) |
| `OUTPUT_DIR` | (unset) | Per-machine output mount |
| `DRIVE_C` / `DRIVE_D` | (unset) | Per-machine drive-letter mounts (Windows hosts) |
| `BULK_SOURCE_PATH` | (unset) | Default source for first-run wizard |
| `BULK_OUTPUT_PATH` | (unset) | Default output for first-run wizard |
| `ENABLE_NEW_UX` | (unset) | Set to `true` to serve `static/index-new.html` at `/` instead of the legacy UI. Read via `core.feature_flags.is_new_ux_enabled()`. |

`docker-compose.override.yml` is gitignored (v0.29.3) so per-machine
GPU / Apple-Silicon configs don't leak into the repo. macOS scripts
auto-seed it from `docker-compose.apple-silicon.yml`.

---

## Runbook

### "database is locked" errors

WAL mode + busy_timeout=10000 makes this rare. When it happens:

1. **Scheduled job collision.** Lifecycle scan, trash expiry, DB
   compaction, integrity check, stale-data check all call
   `get_all_active_jobs()` and skip if any bulk job is scanning /
   running / paused. If you see a lock from one of those events,
   check whether they're correctly yielding.
2. **Long-running write.** A migration or vacuum can hold the writer.
   Wait it out.
3. **Mid-process restart.** A killed write can leave a `.db-wal` and
   `.db-shm`. SQLite recovers on next open; if not, restart the
   container.

Never delete `markflow.db-wal` while the app is running.

### Job stuck in `scanning`

Container restart auto-clears via `cleanup_stale_jobs()` in
`core/db/migrations.py` (v0.30.3 extended this to include `scanning`).
Manual recovery:

```bash
docker-compose exec markflow sqlite3 /app/markflow.db \
  "UPDATE bulk_jobs SET status='interrupted',
   completed_at=datetime('now')
   WHERE status='scanning' AND last_heartbeat < datetime('now', '-30 minutes')"
```

### GPU not detected on NVIDIA host

Check `nvidia-container-toolkit` on the host. v0.29.3 fixed a
regression where a committed `docker-compose.override.yml` (for Apple
Silicon devs) silently wiped the NVIDIA reservation. Verify:

```bash
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

If that works but `docker-compose.yml` doesn't, recreate:

```bash
docker-compose up -d --force-recreate
```

### "MarkFlow can't see my files"

Check the mount in the container:

```bash
docker-compose exec markflow ls /mnt/source
docker-compose exec markflow ls /host/d/Doc-Conv_Test
```

If empty: the host path in `.env` (`SOURCE_DIR`, `DRIVE_D`, etc.)
isn't right or the volume isn't being applied. Recreate.

### Vision API circuit breaker open

After 5 consecutive 5xx / 429 from the active provider, the breaker
opens. Cooldown doubles each cycle (60s -> 2m -> 4m -> 8m -> 15m cap).
Reset manually (MANAGER+ only) once you've fixed the upstream:

```bash
curl -X POST http://localhost:8000/api/analysis/circuit-breaker/reset
```

### Cross-reference data missing

If `/api/prproj/stats` returns `n_projects: 0` after a bulk run that
processed Premiere files, check:

1. Were the projects parsed? `/api/logs/search?q=prproj.parsed`
2. Did persistence fail? `/api/logs/search?q=prproj.media_ref_record_failed`
3. Did the parse fall back? `/api/logs/search?q=prproj.deep_parse_failed`

If you see lots of `prproj.refs_sync_table_missing` events, an older
DB is missing the v28 migration -- restart the container so `init_db()`
applies it.

### Log search returns nothing useful

`/api/logs/search` paginates active + archived logs. Searches against
gzipped archives are slower; an EWMA-based ETA hint shows in the UI
(v0.31.5). Cap your query window with `?since=24h` for fast searches.

---

## Where to ask for more

- **OpenAPI auto-docs:** `/docs` (Swagger UI) — search by tag.
- **Source code:** `core/` for business logic, `api/routes/` for
  endpoints, `formats/` for handlers, `static/js/` for frontend.
- **Architectural decisions:** `docs/version-history.md` (one entry
  per release with full context).
- **Already-hit foot-guns:** `docs/gotchas.md`.
- **What lives where:** `docs/key-files.md` (189-row file map).
- **Implementation plans:** `docs/superpowers/plans/*.md` (the
  pre-implementation specs) -- once a plan ships, the canonical doc
  is `version-history.md`, but the plan often has the original
  rationale and rejected alternatives.
