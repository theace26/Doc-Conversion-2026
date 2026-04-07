# MarkFlow — CLAUDE.md

Auto-loaded by Claude Code at session start. Detailed references live in `docs/`.

## Project

**Doc-Conversion-2026** (internal name: MarkFlow) — Python/FastAPI web app that converts
documents bidirectionally between their original format and Markdown. Runs in Docker.
GitHub: `github.com/theace26/Doc-Conversion-2026`

## When to read the reference docs

Read on demand — not loaded automatically:

| File | Read it when... |
|------|-----------------|
| [`docs/gotchas.md`](docs/gotchas.md) | Modifying or debugging a subsystem — check its section before writing code |
| [`docs/key-files.md`](docs/key-files.md) | Locating a file by purpose or understanding what a file does |
| [`docs/version-history.md`](docs/version-history.md) | Needing context on why something was built or what changed in a version |
| [`docs/security-audit.md`](docs/security-audit.md) | Working on auth, input validation, or pre-prod hardening |
| [`docs/phase-1-instructions.md`](docs/phase-1-instructions.md) | Rarely — only if revisiting the original Phase 1 design spec |

**Rule of thumb:** If a task touches bulk/lifecycle/auth/password/GPU/OCR/search/vector,
read the relevant `gotchas.md` section first. Most bugs there have already been hit and documented.

---

## Current Version — v0.22.11

Per-provider "Use for AI Assist" opt-in checkbox:
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
