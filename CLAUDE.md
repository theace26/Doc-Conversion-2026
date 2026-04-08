# MarkFlow — CLAUDE.md

Auto-loaded by Claude Code at session start. Detailed references live in `docs/`.

## Project

**Doc-Conversion-2026** (internal name: MarkFlow) — Python/FastAPI web app that converts
documents bidirectionally between their original format and Markdown. Runs in Docker.
GitHub: `github.com/theace26/Doc-Conversion-2026`

## Project documentation map

Read on demand — none of these are auto-loaded. Listed by role.

### Core engineering references (read these first when working on code)

| File | Role / read it when... |
|------|------------------------|
| [`docs/gotchas.md`](docs/gotchas.md) | Hard-won subsystem-specific lessons (~100 items, organized by subsystem). **Always check the relevant section before modifying or debugging code in that area** — most foot-guns here have already been hit. |
| [`docs/key-files.md`](docs/key-files.md) | 189-row file reference table mapping every important file to its purpose. Read when locating a file by what it does or understanding what an unfamiliar file is for. |
| [`docs/version-history.md`](docs/version-history.md) | Detailed per-version changelog (one entry per release, full context: problem, fix, modified files, why-it-matters). The canonical "why was this built" reference. Append a new entry on every release. |

### Pre-production / hardening

| File | Role / read it when... |
|------|------------------------|
| [`docs/security-audit.md`](docs/security-audit.md) | Findings-only security audit performed at v0.16.0. **62 findings, 3 critical + 5 high — pre-prod blocker.** Read when working on auth, input validation, JWT, role guards, or anything customer-data-sensitive. |
| [`docs/streamlining-audit.md`](docs/streamlining-audit.md) | Code-quality / DRY audit performed at v0.16.0. All 24 items resolved across v0.16.1–v0.16.2. Read only when you want history of how the codebase was tightened (e.g., why `core/db/` is split into 8 modules). |

### Integration / contracts (Phase 10+)

| File | Role / read it when... |
|------|------------------------|
| [`docs/unioncore-integration-contract.md`](docs/unioncore-integration-contract.md) | The agreed-upon API contract between MarkFlow and UnionCore (Phase 10 auth integration). Two surfaces: user-facing search render + backend webhook. Read when touching `/api/search/*` shape, JWT validation, or anything UnionCore consumes. |
| [`docs/MarkFlow-Search-Capabilities.md`](docs/MarkFlow-Search-Capabilities.md) | Stakeholder-facing capability brief (last updated v0.22.0). Sales / executive tone. Read when the user asks for a feature summary suitable for non-engineers, or when updating it after major search/index changes. |

### Operations

| File | Role / read it when... |
|------|------------------------|
| [`docs/drive-setup.md`](docs/drive-setup.md) | End-user instructions for sharing host drives with the Docker container (Windows/Mac/Linux). Read when troubleshooting "MarkFlow can't see my files" or updating Docker mount setup. |
| [`docs/phase-1-instructions.md`](docs/phase-1-instructions.md) | Original Phase 1 design spec (DocumentModel, DocxHandler, metadata, upload UI). **Historical only** — read only if revisiting the foundation architecture. |

### User-facing help wiki (`docs/help/*.md` — 18 articles)

These render in the in-app help drawer (`/help.html`). Update them when shipping
user-visible features or changing UX. Article inventory:

| Article | Covers |
|---------|--------|
| [`getting-started.md`](docs/help/getting-started.md) | First-time user walkthrough |
| [`document-conversion.md`](docs/help/document-conversion.md) | Single-file Convert page |
| [`bulk-conversion.md`](docs/help/bulk-conversion.md) | Bulk Convert page, jobs, pause/resume/cancel |
| [`auto-conversion.md`](docs/help/auto-conversion.md) | Auto-conversion pipeline (modes, workers, batch sizing, master switch) |
| [`search.md`](docs/help/search.md) | Search page, filters, batch download, hover preview |
| [`fidelity-tiers.md`](docs/help/fidelity-tiers.md) | Tier 1/2/3 round-trip explanation |
| [`ocr-pipeline.md`](docs/help/ocr-pipeline.md) | OCR detection, confidence, review queue |
| [`file-lifecycle.md`](docs/help/file-lifecycle.md) | Active → marked → trashed → purged states + timers |
| [`adobe-files.md`](docs/help/adobe-files.md) | Adobe Level-2 indexing (.psd/.ai/.indd) |
| [`unrecognized-files.md`](docs/help/unrecognized-files.md) | Catalog page, MIME detection |
| [`llm-providers.md`](docs/help/llm-providers.md) | Provider setup, AI Assist, image analysis |
| [`gpu-setup.md`](docs/help/gpu-setup.md) | NVIDIA Container Toolkit, host worker, hashcat |
| [`password-recovery.md`](docs/help/password-recovery.md) | PDF/Office/archive password cascade |
| [`mcp-integration.md`](docs/help/mcp-integration.md) | Port 8001 MCP server, tools, auth token |
| [`nfs-setup.md`](docs/help/nfs-setup.md) | NFS mount Settings UI |
| [`status-page.md`](docs/help/status-page.md) | System Status page, health checks |
| [`resources-monitoring.md`](docs/help/resources-monitoring.md) | Resources page, activity log |
| [`admin-tools.md`](docs/help/admin-tools.md) | Admin-only pages (flagged files, users, providers) |
| [`settings-guide.md`](docs/help/settings-guide.md) | Settings page section-by-section reference |
| [`keyboard-shortcuts.md`](docs/help/keyboard-shortcuts.md) | Page-level keyboard shortcuts |
| [`troubleshooting.md`](docs/help/troubleshooting.md) | Common problems + fixes by symptom |

### Implementation plans / specs (`docs/superpowers/`)

`docs/superpowers/plans/*.md` and `docs/superpowers/specs/*.md` contain the
written plans and design specs for major features (image-analysis-queue,
hdd-scan-optimizations, pipeline-file-explorer, nfs-mount-support, vector-search,
cloud-prefetch, file-flagging, source-files-dedup, auto-conversion-pipeline).
**Historical / context-only** — once a plan is shipped, the canonical
documentation lives in `version-history.md` and the code itself. Read a plan
only when investigating a feature's original intent or design rationale.

### Rule of thumb

If a task touches **bulk / lifecycle / auth / password / GPU / OCR / search / vector**,
read the relevant `gotchas.md` section first. Most bugs in those areas have already
been hit and documented. For "what changed and why" questions, jump to
`version-history.md`. For "where does X live" questions, jump to `key-files.md`.

---

## Current Version — v0.22.14

Four fixes from the v0.22.13 log diagnostic:

1. **Vector indexing no longer blocks the bulk worker.** `core/bulk_worker.py`
   used to `await vec_indexer.index_document(...)` inline, blocking up to
   60s per file when Qdrant timed out. Conversion rate dropped to ~0.05
   files/sec. Now wrapped in `asyncio.create_task()` via the new
   `_index_vector_async()` helper. Should restore 5-10x throughput.
   Also: vector-fail logs now use `repr(exc)` and `exc_type` so
   `TimeoutError()` no longer logs an empty error string.
2. **`database is locked` no longer marks files as failed.** The bulk
   worker top-level handler now distinguishes the transient SQLite WAL
   contention error from real conversion failures and `continue`s
   (leaves the file `pending`) instead of marking it `failed`. Adobe L2
   indexer routes its `upsert_adobe_index()` through `db_write_with_retry`.
   Analysis worker drain and auto_metrics aggregator downgrade lock errors
   to warnings (next scheduled tick retries naturally).
3. **Vision API 400 errors now log the response body.** `vision_adapter.py`
   captures `exc.response.text[:500]` and the failing image path so the
   actual provider error reason ("Image too large", "Invalid base64", etc)
   is visible instead of the generic "Client error '400 Bad Request'"
   wrapper. The 1,150-failed analysis_queue backlog can now be diagnosed.
4. **Ghostscript installed in Docker.** Added to `Dockerfile.base` for the
   long term, plus a temporary `apt-get install ghostscript` line in the
   app `Dockerfile` so this fix ships without a 25-min base rebuild. EPS
   files now convert via Pillow + Ghostscript instead of failing with
   "Unable to locate Ghostscript on paths".

Previous (v0.22.13): Active Connections widget on the Resources page.
- **`core/active_connections.py`** — new in-memory tracker with two
  counters: recently-active users (sliding window, last-seen per `user.sub`)
  and live SSE/streaming connections (bucketed by short endpoint label).
  No DB schema; resets on container restart by design.
- **`core/auth.py`** — `get_current_user()` now stashes the resolved user
  on `request.state.user` so the middleware can read it after the response.
- **`api/middleware.py`** — `RequestContextMiddleware` reads
  `request.state.user` and calls `record_request_activity()` on every
  successful authenticated request.
- **SSE generators wrapped** with `async with track_stream(<endpoint>):`
  in `bulk.py` (`bulk_job_events`, `ocr_gap_fill`), `batch.py`
  (`batch_progress`), and `ai_assist.py` (`ai_assist_search`,
  `ai_assist_expand`).
- **`GET /api/resources/active`** — admin-only endpoint returning
  `{users, total_users, total_streams, streams_by_endpoint, window_seconds}`.
- **`static/resources.html`** — new "Active Connections" section between
  Live System Metrics and Activity Log. Two cards (Active Users + Live
  Streams) polled every 5 seconds. Safe DOM construction. Pauses when
  the tab is hidden.

Previous (v0.22.12): AI Assist Settings copy fix + live provider info badge.
- The blurb under "Enable AI Assist" still said "Requires `ANTHROPIC_API_KEY`
  in the environment" — stale since v0.22.10. Replaced with explicit text
  saying AI Assist uses the same provider system as Vision & Frame
  Description and AI Enhancement.
- New live "Provider: anthropic · claude-opus-4-6 · opted-in via 'Use for
  AI Assist'" badge on the AI Assist Settings section. Pulls
  `provider_source` and `model` from `/api/ai-assist/status` so admins can
  see exactly which provider AI Assist will use and which lookup path
  produced it (`opted_in` / `active_fallback` / `env_fallback` / `none`).
- Includes a "Manage Providers →" link directly in the badge.

Previous (v0.22.11): per-provider "Use for AI Assist" opt-in checkbox.
- **Migration #25** adds `use_for_ai_assist INTEGER NOT NULL DEFAULT 0` to
  `llm_providers`. Mutually exclusive across rows (like `is_active`).
- **`core/db/catalog.py`** — new `get_ai_assist_provider()` and
  `set_ai_assist_provider(provider_id|None)` helpers.
- **`core/ai_assist.py`** — `_get_provider_config()` now follows a 3-step
  lookup: opted-in provider → active provider (fallback) → env var (legacy).
  Decouples AI Assist from the image scanner's active provider so admins
  can pick a different provider for each.
- **`api/routes/llm_providers.py`** — Create/Update accept the new
  `use_for_ai_assist` field; new endpoint
  `POST /api/llm-providers/{id}/use-for-ai-assist` (or `id=none` to clear).
- **`static/providers.html`** — checkbox in the add form, "Use for AI
  Assist" / "Disable AI Assist" button on each card, purple "AI Assist"
  badge next to the opted-in provider. Card rendering refactored to safe
  DOM construction (no innerHTML).
- **Status endpoint** carries a new `provider_source` field
  (`opted_in` / `active_fallback` / `env_fallback` / `none`) for UI clarity.

Previous (v0.22.10): AI Assist now reads its API key from the same
`llm_providers` row as the image scanner (instead of `ANTHROPIC_API_KEY`
env var). Provider record's model and api_base_url are honored.
- **`core/ai_assist.py`** — `_get_provider_config()` reads the active
  `llm_providers` row via `core.db.catalog.get_active_provider()` (the same
  source the image scanner / vision pipeline uses). It honors the provider's
  `api_key`, `model`, and `api_base_url`. Falls back to `ANTHROPIC_API_KEY`
  env var only if no provider record exists at all (legacy compat).
- **Provider compatibility check** — AI Assist requires an `anthropic`
  provider (because the SSE format and `x-api-key` header are
  Anthropic-specific). If the active provider is OpenAI/Gemini/etc, the
  status endpoint returns a clear `provider_error` and the UI tells the user
  to switch the active provider on the Providers page.
- **Frontend UX** — both the search-page drawer and the Settings page now
  link to `/providers.html` instead of asking users to edit `.env`. Server
  status response carries `provider_source`, `provider_compatible`,
  `provider_error`, and `model` so the UI can render an accurate notice.

Previous (v0.22.9): UX + data-integrity pass — search default view, AI
Assist needs-config UX, pipeline pending count NOT EXISTS rewrite,
bulk_files self-correction 4th step, adobe-files L2 indexing rewire.

All earlier versions (v0.13.x – v0.22.7) are documented per-release in
[`docs/version-history.md`](docs/version-history.md). Do NOT duplicate that here.

**Planned:** External log shipping to Grafana Loki / ELK. The current local
log archive system is interim.

---

## Pre-production checklist

- **Lifecycle timers are at testing values** — MUST restore before production:
  - `lifecycle_grace_period_hours`: currently **12** (production: 36+)
  - `lifecycle_trash_retention_days`: currently **7** (production: 60+)
  - Set via Settings UI or `PUT /api/preferences/<key>`
- **Security audit** (62 findings in `docs/security-audit.md`) not yet addressed.

**Temporary instrumentation (deactivate when resolved):**
- **DB contention logging (v0.19.6.5):** `db-contention.log`, `db-queries.log`,
  `db-active.log` via `core/db/contention_logger.py`. High-volume during scans.
  Remove once "database is locked" is fully diagnosed.

---

## Architecture Reminders

- **Per-machine paths via `.env`** — `docker-compose.yml` uses `${SOURCE_DIR}`, `${OUTPUT_DIR}`, `${DRIVE_C}`, `${DRIVE_D}`. Each machine gets its own gitignored `.env`. See `.env.example`.
- **No Pandoc** — library-level only.
- **No SPA** — vanilla HTML + fetch calls.
- **Fail gracefully** — one bad file never crashes a batch.
- **Fidelity tiers:** Tier 1 = structure (guaranteed), Tier 2 = styles (sidecar), Tier 3 = original file patch.
- **Content-hash keying** — sidecar JSON keyed by SHA-256 of normalized paragraph/table content.
- **Format registry** — handlers register by extension, converter looks up by extension.
- **Unified scanning** — all formats go through the same pipeline (no Adobe/convertible split).
- **source_files vs bulk_files** — `source_files` is the single source of truth for file-intrinsic data (path, size, hash, lifecycle); `bulk_files` links jobs to source files via `source_file_id`. Cross-job queries MUST use `source_files` to avoid duplicates.
- **Scan priority:** Bulk > Run Now > Lifecycle. Enforced by `core/scan_coordinator.py`.
- **Folder drop** — Convert page accepts whole folders via drag-and-drop.

All phases 0–11 are **Done**. Phase 1 historical spec: [`docs/phase-1-instructions.md`](docs/phase-1-instructions.md).

---

## Critical Files (full table: [`docs/key-files.md`](docs/key-files.md))

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, lifespan, router mounts |
| `core/db/` | Domain-split DB package (connection, schema, bulk, lifecycle, auth, ...) |
| `core/converter.py` | Pipeline orchestrator (single-file conversion) |
| `core/bulk_worker.py` | Worker pool: BulkJob, pause/resume/cancel, SSE |
| `core/scan_coordinator.py` | Scan priority coordinator (Bulk > Run Now > Lifecycle) |
| `core/scheduler.py` | APScheduler: lifecycle scan, trash expiry, DB maintenance, pipeline watchdog |
| `core/auth.py` | JWT validation, role hierarchy, API key verification |
| `Dockerfile.base` / `Dockerfile` | Base (system deps) + app (pip + code) |
| `docker-compose.yml` | Ports: 8000 app, 8001 MCP, 7700 Meilisearch |

---

## Top Gotchas (full list: [`docs/gotchas.md`](docs/gotchas.md))

The ones that bite hardest and most often — read the full file for the rest.

- **aiosqlite**: Always `async with aiosqlite.connect(path) as conn`. Never `await` then `async with`.
- **structlog**: Use `structlog.get_logger(__name__)` everywhere, never `logging.getLogger()`. `import structlog` in every file that calls it.
- **pdfminer logging**: Must set `pdfminer.*` loggers to WARNING in `configure_logging()`, or debug log grows 500+ MB per bulk job.
- **`python-jose` not `PyJWT`** — they conflict.
- **`DEV_BYPASS_AUTH=true` is the default** — production must set to `false`.
- **Source share is read-only**: `/mnt/source` mounted `:ro`.
- **Scheduled jobs yield to bulk jobs**: lifecycle scan, trash expiry, DB compaction, integrity check, stale data check all call `get_all_active_jobs()` and skip if any bulk job is scanning/running/paused. Prevents "database is locked".
- **Pipeline has two pause layers**: `pipeline_enabled` (persistent DB pref) and `_pipeline_paused` (in-memory, resets on restart). Scheduler checks both. "Run Now" bypasses both.
- **Frontend timestamps must use `parseUTC()`**: SQLite round-trips can strip the `+00:00` offset. `parseUTC()` in `app.js` appends `Z`. Never `new Date(isoString)` directly for backend timestamps.
- **Vector search is best-effort**: `get_vector_indexer()` returns `None` when Qdrant is unreachable. All call sites must handle `None`.
- **No non-ASCII in `.ps1` scripts**: Windows PowerShell 5.1 reads BOM-less UTF-8 as Windows-1252 and em-dashes become `â€"`, breaking string parsing. ASCII only.
- **`worker_capabilities.json` is per-machine**: gitignored, generated by refresh/reset scripts. Never commit.
- **MCP server binding**: `FastMCP.run()` does NOT accept `host`/`port`. Use `uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port)`. Endpoint is `/sse`, not `/mcp`. `/health` must be added manually as a Starlette route.

---

## Supported Formats

| Category | Extensions | Handler |
|----------|-----------|---------|
| Office | .docx, .doc, .docm, .pdf, .pptx, .ppt, .xlsx, .xls, .csv, .tsv | DocxHandler, PdfHandler, PptxHandler, XlsxHandler, CsvHandler |
| WordPerfect | .wpd | DocxHandler (LibreOffice preprocessing) |
| Rich Text | .rtf | RtfHandler |
| OpenDocument | .odt, .ods, .odp | OdtHandler, OdsHandler, OdpHandler |
| Markdown & Text | .md, .txt, .log, .text | MarkdownHandler, TxtHandler |
| Web & Data | .html, .htm, .xml, .epub | HtmlHandler, XmlHandler, EpubHandler |
| Data & Config | .json, .yaml, .yml, .ini, .cfg, .conf, .properties | JsonHandler, YamlHandler, IniHandler |
| Email | .eml, .msg | EmlHandler (recursive attachment conversion) |
| Archives | .zip, .tar, .tar.gz, .tgz, .tar.bz2, .7z, .rar, .cab, .iso | ArchiveHandler |
| Adobe | .psd, .ai, .indd, .aep, .prproj, .xd, .ait, .indt | AdobeHandler |
| Media (audio) | .mp3, .wav, .m4a, .flac, .ogg, .aac, .wma | AudioHandler |
| Media (video) | .mp4, .mov, .avi, .mkv, .webm, .m4v, .wmv | MediaHandler |
| Captions | .srt, .vtt, .sbv | CaptionIngestor (via AudioHandler) |
| Images | .jpg, .jpeg, .png, .tif, .tiff, .bmp, .gif, .eps, .heic, .heif | ImageHandler |

---

## Running the App

```bash
# First time only — build the base image (slow, ~25 min HDD / ~5 min SSD):
docker build -f Dockerfile.base -t markflow-base:latest .

# Normal operation:
docker-compose up -d          # start
docker-compose logs -f        # watch logs
curl localhost:8000/api/health # verify
docker-compose down           # stop
```

After code changes: `docker-compose build && docker-compose up -d`
(Only rebuilds pip + code layer — base image is cached.)
