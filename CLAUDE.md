# MarkFlow — CLAUDE.md

Auto-loaded by Claude Code at session start. Keep this up to date after each phase.

---

## Project

**Doc-Conversion-2026** (internal name: MarkFlow) — a Python/FastAPI web app that converts
documents bidirectionally between their original format and Markdown. Runs in Docker.
GitHub: `github.com/theace26/Doc-Conversion-2026`

---

## Current Status

**Phase 0 complete** — Docker scaffold running. All system deps verified.
**Phase 1 complete** — DOCX → Markdown pipeline fully implemented. 60 tests passing. Tagged v0.1.0.
**Phase 2 complete** — Markdown → DOCX round-trip with fidelity tiers. 96 tests passing. Tagged v0.2.0.
**Phase 3 complete** — OCR pipeline: multi-signal detection, preprocessing, Tesseract extraction,
  confidence flagging, review API + UI, unattended mode, SQLite persistence. Tagged v0.3.0.
**Phase 4 complete** — PDF, PPTX, XLSX/CSV format handlers (both directions). 231 tests passing. Tagged v0.4.0.
**Phase 5 complete** — Full test suite (350+ tests), structured JSON logging throughout all
  pipeline stages, debug dashboard at /debug. Tagged v0.5.0.
**Phase 6 complete** — Full UI: live SSE batch progress, history page (filter/sort/search/
  redownload), settings page (preferences with validation), shared CSS design system,
  dark mode, comprehensive error UX. 378 tests passing. Tagged v0.6.0.
**Phase 7 complete** — Bulk conversion pipeline (scanner, worker pool, pause/resume/cancel),
  Adobe Level 2 indexing (.ai/.psd text + .indd/.aep/.prproj/.xd metadata), Meilisearch
  full-text search (documents + adobe-files indexes), search UI, bulk job UI,
  Cowork search API. 467 tests. Tagged v0.7.0.
**v0.7.1** — Named Locations system: friendly aliases for container paths used in bulk jobs.
  First-run wizard guides setup. Bulk form uses dropdowns instead of raw path inputs.
  Backwards compatible with BULK_SOURCE_PATH / BULK_OUTPUT_PATH env vars. 496 tests.
**v0.7.2** — Directory browser: Windows drives mounted at /host/c, /host/d etc.
  Browse endpoint (GET /api/browse) with path traversal protection.
  FolderPicker widget on Locations page — no need to type container paths manually.
  Unmounted drives show setup instructions inline.
**v0.7.3** — OCR confidence visibility and bulk skip-and-review. Confidence scores
  (mean, min, pages below threshold) recorded per file and shown in history with
  color-coded badges. Bulk mode skips PDFs below confidence threshold into a review
  queue instead of failing them. Post-job review UI (bulk-review.html) lets user
  convert anyway, skip permanently, or open per-page OCR review per file.
**v0.7.4** — LLM providers (Anthropic, OpenAI, Gemini, Ollama, custom), API key
  encryption, connection verification, opt-in OCR correction + summarization +
  heading inference. Auto-OCR gap-fill for PDFs converted without OCR.
  MCP server (port 8001) exposes 7 tools to Claude.ai (later expanded to 10): search, read, list,
  convert, adobe search, get summary, conversion status. 543 tests.
**v0.7.4b** — Path safety and collision handling. Deeply nested paths checked
  against configurable max length (default 240 chars). Output path collisions
  (same stem, different extension) detected at scan time and resolved per
  strategy: rename (default, no data loss), skip, or error. Case-sensitivity
  collisions detected separately. All issues recorded in bulk_path_issues table,
  reported in manifest, downloadable as CSV.
**v0.7.4c** — Active file display in bulk progress. Collapsible panel shows
  one row per worker with current filename. Worker count matches Settings value.
  Collapse state persists in localStorage. Hidden when preference is off.
  `file_start` SSE event added; `worker_id` added to all worker SSE events.
**v0.8.1** — Visual enrichment pipeline. Scene detection (PySceneDetect), keyframe
  extraction (ffmpeg), and AI frame descriptions via the existing LLM provider system.
  VisionAdapter wraps the active provider for image input (Anthropic, OpenAI, Gemini,
  Ollama). Vision preferences stored in existing preferences table (not a separate
  settings system). DB: scene_keyframes table, vision columns on conversion_history.
  Meilisearch index extended with frame_descriptions field. Settings UI Vision section
  with provider display linking to existing providers.html. History detail panel shows
  scenes/enrichment/descriptions. Debug dashboard shows vision stats.
**v0.8.2** — Unknown & unrecognized file cataloging. Bulk scanner records every
  file it encounters, even without a handler. MIME detection via python-magic with
  extension fallback classifies files into categories (disk_image, raster_image,
  video, audio, archive, executable, database, font, code, unknown). New columns
  mime_type and file_category on bulk_files. Unrecognized files get
  status='unrecognized' (distinct from failed/skipped). API: GET /api/unrecognized
  (list, filter, paginate), /stats, /export (CSV). UI: /unrecognized.html with
  category cards, filters, table. Bulk progress shows unrecognized count pill.
  MCP tool: list_unrecognized (8th tool).
**v0.8.5** — File lifecycle management, version tracking & database health.
  APScheduler runs lifecycle scans every 15 min during business hours. Detects
  new/modified/moved/deleted files in source share. Soft-delete pipeline:
  active → marked_for_deletion (36h grace) → in_trash (60d retention) → purged.
  Full version history with unified diff patches and bullet summaries per file.
  Trash management page, DB health dashboard, lifecycle badges on all file views.
  6 new preference keys for scanner and lifecycle config. DB maintenance: weekly
  compaction, integrity checks, stale data detection. WAL mode enabled.
  MCP tools 9-10: list_deleted_files, get_file_history.
**v0.9.0** — Auth layer & UnionCore integration contract. JWT-based auth
  middleware with HS256 validation (UnionCore as identity provider). Role-based
  route guards: search_user < operator < manager < admin. API key service
  accounts for UnionCore backend (BLAKE2b hashed, `mf_` prefixed). Admin panel
  for key management. CORS configured for UnionCore origin. DEV_BYPASS_AUTH=true
  for local dev (all requests treated as admin). `/` redirects to search page.
  Role-aware dynamic navigation (nav items filtered by user role). Preferences
  split: system-level keys require manager role. Integration contract at
  `docs/unioncore-integration-contract.md`. New env vars: UNIONCORE_JWT_SECRET,
  UNIONCORE_ORIGIN, DEV_BYPASS_AUTH, API_KEY_SALT.
**v0.9.1** — Search autocomplete & scan progress visibility.
  Autocomplete dropdown on search.html powered by Meilisearch (debounced 200ms,
  keyboard navigable, deduplicates across documents + adobe-files indexes).
  `GET /api/search/autocomplete` endpoint. Bulk scan phase now emits
  `scan_progress` SSE events (count, pct, current_file) every 50 files with
  pre-counted total estimate. Background lifecycle scanner exposes in-memory
  `_scan_state` via `GET /api/scanner/progress` (polled every 3s by UI).
  Lifecycle scan status bar on bulk.html and db-health.html shows progress
  or last-scan timestamp. New tests in test_search.py and test_scanner.py.
**v0.9.2** — Admin page: resource controls, task manager & stats dashboard.
  `core/resource_manager.py` wraps psutil for CPU affinity, process priority,
  and live metrics. Admin page gains three sections: Repository Overview
  (KPI cards, file/lifecycle/OCR/format/Meilisearch/scheduler/error stats),
  Task Manager (per-core CPU bars, memory, threads, 2s polling), Resource
  Controls (worker count, priority, core pinning). New endpoints:
  `PUT /api/admin/resources`, `GET /api/admin/system/metrics`,
  `GET /api/admin/stats`. New preferences: worker_count, cpu_affinity_cores,
  process_priority. `get_scheduler_status()` added to scheduler.py.
  psutil primed at startup in lifespan. 16 new tests in test_admin.py.
**v0.9.3** — Global stop controls, active jobs panel, admin DB tools, locations
  flagged for UX redesign. `core/stop_controller.py`: cooperative global stop
  flag checked by bulk workers, bulk scanner, and lifecycle scanner before each
  file. `POST /api/admin/stop-all` cancels all registered asyncio tasks.
  `POST /api/admin/reset-stop` clears the flag. `GET /api/admin/active-jobs`
  returns all running jobs for the global status bar. Persistent floating status
  bar (`global-status-bar.js`) on every page shows job count, STOP ALL button,
  and stop-requested banner. Active Jobs slide-in panel (`active-jobs-panel.js`)
  shows per-job detail with progress bars, active workers, per-directory stats,
  and individual stop buttons. `dir_stats` on BulkJob tracks top-level
  subdirectory counts. Admin DB Tools section: quick health check, full integrity
  check, dump-and-restore repair (blocked if jobs running). Locations page flagged
  for UX redesign with visible banner. New tests in test_stop_controller.py,
  test_active_jobs.py, and additions to test_admin.py.
**v0.9.4** — Status page & nav redesign. Floating global-status-bar and
  slide-in active-jobs-panel replaced by dedicated `/status.html` with
  stacked per-job cards (progress bars, active workers, per-dir stats,
  pause/resume/stop controls). STOP ALL button and lifecycle scanner card
  live on status page. Nav gains "Status" link with active-job count
  badge (pulses red when stop requested). `global-status-bar.js` rewritten
  to badge-only polling; `active-jobs-panel.js` retired and deleted.
  `app.js` dynamically loads badge script after `buildNav()`. Old `.gsb-*`
  and `.ajp-*` CSS replaced by `.job-card`, `.status-pill`, `.nav-badge`
  design system classes. No backend changes.
**v0.9.5** — Configurable logging levels with dual-file strategy. Three levels:
  Normal (WARNING+), Elevated (INFO+), Developer (DEBUG + frontend trace).
  Operational log always active (logs/markflow.log, 30-day rotation).
  Debug trace log (logs/markflow-debug.log, 7-day) only active in Developer mode.
  Dynamic level switching — no container restart required. Settings UI Logging section
  with log file downloads. POST /api/log/client-event instruments ~15 JS actions in
  Developer mode (rate-limited, silently dropped at other levels).
  log_level is a system-level preference requiring Manager role.

---

## Phase Checklist

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Docker scaffold, project structure, DB schema, health check | ✅ Done |
| 1 | Foundation: DOCX → Markdown (DocumentModel, DocxHandler, metadata, upload UI) | ✅ Done |
| 2 | Round-trip: Markdown → DOCX with fidelity tiers | ✅ Done |
| 3 | OCR pipeline (multi-signal detection, review UI, unattended mode) | ✅ Done |
| 4 | Remaining formats: PDF, PPTX, XLSX/CSV (both directions) | ✅ Done |
| 5 | Testing & debug infrastructure (full test suite, structlog, debug dashboard) | ✅ Done |
| 6 | Full UI, batch progress, history page, settings, polish | ✅ Done |
| 7 | Bulk conversion, Adobe indexing, Meilisearch search, Cowork integration | ✅ Done |
| 8b | Visual enrichment: scene detection, keyframe extraction, AI frame descriptions | ✅ Done |
| 8c | Unknown & unrecognized file cataloging with MIME detection | ✅ Done |
| 9 | File lifecycle management, version tracking, DB health | ✅ Done |
| 10 | Auth layer, role guards, API keys, UnionCore integration contract | ✅ Done |

---

## Phase 1 Instructions

Implement the full DOCX → Markdown pipeline end-to-end:

1. **`core/document_model.py`** — All dataclasses: `DocumentModel`, `Element`, `ElementType`,
   `DocumentMetadata`, `ImageData`. Content hash (SHA-256 of normalized text). Serialize/deserialize
   to dict. Helpers: `add_element()`, `get_elements_by_type()`, `to_markdown()`, `from_markdown()`.

2. **`formats/base.py`** — Abstract `FormatHandler` with methods: `ingest(file_path) → DocumentModel`,
   `export(model, output_path, sidecar=None)`, `extract_styles(file_path) → dict`,
   `supports_format(extension) → bool` (classmethod). Registry pattern for lookup by extension.

3. **`formats/markdown_handler.py`** — `export(model) → str` (all ElementTypes → Markdown + YAML
   frontmatter). `ingest(md_string) → DocumentModel` (use mistune, not regex). Split frontmatter first.

4. **`formats/docx_handler.py`** — `ingest`: walk paragraphs + tables, map styles to ElementTypes,
   extract images (hash-named PNG), footnotes, nested tables. `extract_styles`: font/size/spacing
   per element + document-level page settings, keyed by content hash. `export`: Tier 1 structure always.

5. **`core/image_handler.py`** — `extract_image(data, fmt) → (hash_filename, png_data, metadata)`.
   Hash: `sha256(data).hexdigest()[:12] + ".png"`. Convert EMF/WMF/TIFF → PNG via Pillow.

6. **`core/metadata.py`** — `generate_frontmatter(model)`, `parse_frontmatter(md_text)`,
   `generate_manifest(batch_id, files)`, `generate_sidecar(model, style_data)`, `load_sidecar(path)`.

7. **`core/style_extractor.py`** — Wrapper with content-hash keying, `schema_version: "1.0.0"`.

8. **`core/converter.py`** — `ConversionOrchestrator.convert_file()`. Pipeline: validate → detect
   format → ingest → build model → extract styles → generate output → write metadata → record in DB.
   `asyncio.to_thread()` for CPU-bound work. Copy original to `output/<batch_id>/_originals/`.

9. **`api/models.py`** — Pydantic models: `ConvertRequest/Response`, `BatchStatus`, `FileStatus`,
   `PreviewRequest/Response`, `HistoryRecord`, `HistoryListResponse`, `StatsResponse`, `PreferenceUpdate`.

10. **`api/middleware.py`** — Already implemented (request ID + timing). No changes needed.

11. **`api/routes/convert.py`** — `POST /api/convert` (upload + validate + start conversion → batch_id).
    `POST /api/convert/preview` (analyze without converting). Validate: size limits, extension whitelist,
    zip bomb check. Update `last_source_directory` preference.

12. **`api/routes/batch.py`** — `GET /api/batch/{id}/status`, `GET /api/batch/{id}/download` (zip),
    `GET /api/batch/{id}/download/{filename}`, `GET /api/batch/{id}/manifest`.

13. **`api/routes/history.py`** — `GET /api/history` (paginated, filterable), `GET /api/history/{id}`,
    `GET /api/history/stats`.

14. **`api/routes/preferences.py`** — `GET /api/preferences`, `PUT /api/preferences/{key}`.

15. **`static/index.html`** — Already implemented. Minor updates if needed for new API shape.

16. **`static/results.html`** — Download links, "Download All" zip, manifest link, summary stats.

17. **Tests** — `tests/generate_fixtures.py`: create `simple.docx` and `complex.docx` programmatically.
    `tests/test_document_model.py`, `tests/test_docx.py`, `tests/test_api.py` (initial), `tests/conftest.py`.

### Phase 1 Done Criteria
- Upload a `.docx` → get a `.md` with correct headings, paragraphs, tables, images
- YAML frontmatter in output `.md`
- Manifest JSON generated in output directory
- Style sidecar JSON with content-hash keys
- Original file preserved in `_originals/`
- Conversion recorded in SQLite `conversion_history`
- Upload UI works (drag-and-drop, preview, convert, download)
- All tests pass

---

## Architecture Reminders

- **No Pandoc** — library-level only
- **No SPA** — vanilla HTML + fetch calls
- **Fail gracefully** — one bad file never crashes a batch
- **Fidelity tiers**: Tier 1 = structure (guaranteed), Tier 2 = styles (sidecar), Tier 3 = original file patch
- **Content-hash keying** — sidecar JSON keyed by SHA-256 of normalized paragraph/table content
- **Format registry** — handlers register by extension, converter looks up by extension

---

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, lifespan, mounts all routers + `/ocr-images` static |
| `core/database.py` | SQLite connection, schema, preference + history + ocr_flags helpers |
| `core/health.py` | Startup checks for Tesseract, LibreOffice, Poppler, WeasyPrint, disk, DB |
| `core/logging_config.py` | structlog JSON logging, rotating file handler |
| `core/converter.py` | Pipeline orchestrator; `from_md` path detects sidecar + original → tier 1/2/3 |
| `core/ocr_models.py` | OCR dataclasses: OCRWord, OCRFlag, OCRPage, OCRConfig, OCRResult, OCRFlagStatus |
| `core/ocr.py` | OCR engine: `needs_ocr`, `preprocess_image`, `ocr_page`, `flag_low_confidence`, `run_ocr` |
| `formats/docx_handler.py` | DOCX ingest + export; `_add_inline_runs`, `_plain_text_hash`, `_patch_from_original` |
| `formats/markdown_handler.py` | MD ingest + export; `_extract_formatted_text` for inline bold/italic/code |
| `formats/pdf_handler.py` | PDF ingest (pdfplumber + OCR) + export (WeasyPrint); font-size heading detection |
| `formats/pptx_handler.py` | PPTX ingest (slides→H2 sections) + export; Tier 3 text patching |
| `formats/xlsx_handler.py` | XLSX ingest (sheets→H2+TABLE) + export; formula/merge/style restoration |
| `formats/csv_handler.py` | CSV/TSV ingest (pandas + stdlib fallback) + export; delimiter/encoding preserved |
| `api/middleware.py` | Request ID injection, timing, debug headers |
| `api/routes/review.py` | OCR review endpoints: list, counts, single-flag, resolve, accept-all |
| `api/routes/debug.py` | Debug dashboard API: /debug, /debug/api/health, /debug/api/activity, /debug/api/logs, /debug/api/ocr_distribution |
| `api/routes/batch.py` | Batch status, download, manifest + SSE stream (`/api/batch/{id}/stream`) |
| `api/routes/history.py` | History list (filter/sort/search/paginate), stats, redownload |
| `api/routes/preferences.py` | Preferences CRUD with per-key validation + schema metadata |
| `static/markflow.css` | Shared design system: CSS variables, dark mode, components |
| `static/index.html` | Upload UI: drag-and-drop, direction toggle, format badges |
| `static/progress.html` | Live SSE batch progress: per-file status, progress bar, OCR banners |
| `static/history.html` | History browser: filter, sort, search, pagination, inline detail |
| `static/settings.html` | Preferences form: range sliders, toggles, validation, reset dialog |
| `static/results.html` | Redirect shim → history page (legacy bookmark support) |
| `static/review.html` | Interactive OCR review page (side-by-side image + editable text) |
| `static/debug.html` | Developer debug dashboard — health pills, activity, OCR distribution, log viewer |
| `static/app.js` | Shared JS: API helpers, formatters, toast, nav link highlighter |
| `core/bulk_scanner.py` | File discovery: walks source dir, upserts to bulk_files, mtime tracking |
| `core/bulk_worker.py` | Worker pool: BulkJob class, pause/resume/cancel, SSE events, job registry |
| `core/adobe_indexer.py` | Adobe Level 2 indexing: exiftool metadata + text extraction (.ai/.psd) |
| `core/search_client.py` | Thin async Meilisearch HTTP client via httpx, graceful degradation |
| `core/search_indexer.py` | Manages Meilisearch indexes, document/adobe indexing, rebuild |
| `api/routes/bulk.py` | Bulk job API: create, list, status, pause/resume/cancel, files, errors, SSE |
| `api/routes/search.py` | Full-text search API: search, autocomplete, index status, rebuild |
| `api/routes/cowork.py` | AI assistant search: full .md content inline, token-budget-aware |
| `static/search.html` | Search UI: debounced search, highlights, format/index filters, pagination |
| `static/bulk.html` | Bulk job UI: location dropdowns, SSE progress, pause/cancel, job history |
| `static/locations.html` | Locations management: add/edit/delete, path validation, setup wizard |
| `api/routes/locations.py` | Locations CRUD API + path validation endpoint |
| `api/routes/browse.py` | Directory browser API: GET /api/browse with path traversal protection |
| `static/js/folder-picker.js` | FolderPicker widget: modal directory browser for locations page |
| `static/bulk-review.html` | Post-job OCR review queue: per-file convert/skip/review actions |
| `docs/drive-setup.md` | Setup instructions for mounting Windows drives into Docker |
| `core/crypto.py` | Fernet encryption/decryption for API keys stored at rest |
| `core/llm_providers.py` | PROVIDER_REGISTRY: known providers (Anthropic, OpenAI, Gemini, Ollama, custom) |
| `core/llm_client.py` | Unified async LLM client — routes to provider-specific API implementations |
| `core/llm_enhancer.py` | Enhancement tasks: OCR correction, summarization, heading inference |
| `api/routes/llm_providers.py` | LLM provider CRUD, verify, activate, Ollama model fetch |
| `api/routes/mcp_info.py` | GET /api/mcp/connection-info for settings UI |
| `static/providers.html` | LLM provider management: add/edit/delete/verify/activate |
| `core/path_utils.py` | Path safety: length check, collision detection, resolution strategies |
| `core/mime_classifier.py` | MIME detection (python-magic) + extension fallback file classification |
| `api/routes/unrecognized.py` | Unrecognized files: list, stats, CSV export |
| `static/unrecognized.html` | Unrecognized files UI: category cards, filters, table, CSV export |
| `core/vision_adapter.py` | VisionAdapter: wraps active LLM provider for image/vision calls |
| `core/scene_detector.py` | PySceneDetect wrapper: scene boundary detection in video files |
| `core/keyframe_extractor.py` | ffmpeg keyframe extraction at scene midpoints |
| `core/visual_enrichment_engine.py` | Orchestrates scene detection + keyframe + frame description |
| `mcp_server/server.py` | MCP server entry point — 7 tools exposed via SSE transport |
| `mcp_server/tools.py` | MCP tool implementations: search, read, list, convert, adobe, summary, status, deleted, history |
| `core/differ.py` | Unified diff engine + bullet summary generator |
| `core/lifecycle_manager.py` | Lifecycle state transitions: mark, restore, trash, purge, move, content change |
| `core/lifecycle_scanner.py` | Source share walker, change detection, move detection via content hash; `get_scan_state()` exposes in-memory `_scan_state` |
| `core/scheduler.py` | APScheduler setup: lifecycle scan, trash expiry, DB maintenance jobs |
| `core/db_maintenance.py` | VACUUM, integrity checks, stale data detection, health summary |
| `api/routes/lifecycle.py` | Version history and diff API endpoints |
| `api/routes/trash.py` | Trash management API: list, restore, purge, empty |
| `api/routes/scanner.py` | Scanner status, progress, trigger, run history API |
| `api/routes/db_health.py` | Database health and maintenance API |
| `static/js/lifecycle-badge.js` | Reusable lifecycle status badge component |
| `static/js/version-panel.js` | Version history timeline + compare modal |
| `static/js/deletion-banner.js` | Dismissible banner for search results with deleted files |
| `static/trash.html` | Trash management page with restore/delete controls |
| `static/db-health.html` | Admin database health dashboard |
| `core/auth.py` | JWT validation, role hierarchy, API key verification, FastAPI dependencies |
| `api/routes/auth.py` | GET /api/auth/me — current user identity and role |
| `api/routes/admin.py` | API key CRUD, system info, resource controls, stats dashboard — admin only |
| `core/resource_manager.py` | psutil wrapper: CPU affinity, process priority, live metrics |
| `core/stop_controller.py` | Global stop flag, task registry, should_stop() / request_stop() / reset_stop() |
| `static/js/global-status-bar.js` | Badge-only polling: updates nav badge with active-job count |
| `api/routes/client_log.py` | POST /api/log/client-event — frontend action logging (developer mode) |
| `api/routes/logs.py` | GET /api/logs/download/{filename} — log file downloads (manager role) |
| `static/status.html` | Dedicated status page: per-job cards, STOP ALL, lifecycle scanner, pause/resume/stop |
| `static/admin.html` | Admin panel: stats dashboard, task manager, resource controls, API keys |
| `docs/unioncore-integration-contract.md` | Standalone spec for UnionCore team |
| `pytest.ini` | Test configuration: asyncio_mode, custom markers (slow, ocr, integration, bulk) |
| `docker-compose.yml` | Port 8000, MCP 8001, Meilisearch 7700, volumes: input/output/logs/source/output-repo |

---

## Gotchas & Fixes Found

- **aiosqlite pattern**: Use `async with aiosqlite.connect(path) as conn` — never
  `conn = await aiosqlite.connect(path)` then `async with conn` (starts the thread twice → RuntimeError).
  All DB helpers use `@asynccontextmanager` + `async with aiosqlite.connect()`.

- **Debian trixie package name**: `libgdk-pixbuf-2.0-0` (not `libgdk-pixbuf2.0-0`).

- **structlog + stdlib**: Call `configure_logging()` once at module level in `main.py` before
  the app is created. The formatter must be set on `logging.root.handlers`.

- **DB path**: `DB_PATH` env var (default `markflow.db` locally, `/app/data/markflow.db` in container).
  The Docker volume `markflow-db` mounts to `/app/data`.

- **mistune v3 table plugin**: `create_markdown(renderer=None)` does NOT parse tables by default.
  Must pass `plugins=["table", "strikethrough", "footnotes"]` or tables silently become paragraphs.
  Discovered in Phase 2 round-trip testing.

- **Sidecar hash mismatch**: `extract_styles()` keys sidecar by `para.text` (plain text), but
  `_process_paragraph` stores element content with markdown markers (`**bold**`). Use `_plain_text_hash()`
  (strips markers before hashing) when looking up sidecar entries during export.

- **Tier 3 detection**: In `from_md` direction, converter looks for original `.docx` in the same
  directory as the `.md` file. If user uploads `report.md` + `report.styles.json` + `report.docx`
  together, all land in the same `tmp_dir` and tier is automatically promoted to 3.

- **`FormatHandler.export()` signature**: `original_path: Path | None = None` was added in Phase 2.
  All handlers must accept it (they can ignore it). `MarkdownHandler.export()` accepts but ignores it.

- **OCR deskew is slow**: `_detect_skew()` does 31 coarse + up to 9 fine-step rotations via Pillow.
  On large (A4@300 DPI) page images this can take several seconds per page. Keep page images at
  reasonable sizes for tests (< 1000 px wide) or disable preprocessing with `OCRConfig(preprocess=False)`.

- **Tesseract `-1` confidence**: `pytesseract.image_to_data()` returns `conf == -1` for rows that
  are not words (block/paragraph/line separators). These are clamped to `0.0` in `ocr_page()` and
  should not appear as actual words (the `text` field is empty for those rows so they are skipped).

- **review router route ordering**: The `accept-all` POST route (`/{batch_id}/review/accept-all`)
  must be registered **before** `/{batch_id}/review/{flag_id}` POST route. FastAPI matches routes
  in registration order — the parametric route would capture the literal "accept-all" string as a
  `flag_id` and the bulk-accept endpoint would never be reached. Fixed in `review.py` by ordering
  `accept-all` first in the file.

- **`/ocr-images` static mount**: Served from `OUTPUT_DIR` (default `output/`). If `output/` does
  not exist at startup, `os.makedirs` creates it before `StaticFiles` is mounted.

- **OCR flag image paths**: Stored in DB as forward-slash paths relative to CWD
  (e.g., `output/<batch_id>/_ocr_debug/stem_flag_<uuid>.png`). The review API strips the
  `output/` prefix to build `/ocr-images/…` URLs.

- **python-pptx `placeholder_format`**: Accessing `.placeholder_format` on non-placeholder
  shapes (e.g., `GraphicFrame` for tables) raises `ValueError`, not returns `None`. Must wrap
  in `try/except (ValueError, AttributeError)`. Same for `run.font.color.rgb` on `_NoneColor`.

- **pdfplumber text extraction**: Returns `\n`-separated lines, not `\n\n`-separated paragraphs.
  Heading detection uses char-level font sizes (larger than body font = heading). Without char
  data, falls back to heuristic (title case, ALL CAPS, short lines).

- **PDF export via WeasyPrint**: Always Tier 1 or Tier 2 — PDF internal structure is too complex
  for Tier 3 patching. Export path: DocumentModel → HTML → `weasyprint.HTML().write_pdf()`.

- **XLSX dual workbook open**: `openpyxl.load_workbook(data_only=True)` for computed values,
  `load_workbook(data_only=False)` for formulas. Both needed for full fidelity extraction.

- **XLSX merged cells**: Must unmerge and duplicate the top-left value into all cells of the
  merge range before building the TABLE element, or the table will have `None` holes.

- **CSV encoding detection**: Try `utf-8-sig` (handles BOM) → `utf-8` → `latin-1` → `cp1252`.
  pandas `read_csv` with `dtype=str, keep_default_na=False` prevents type coercion surprises.

- **fpdf2 `new_x`/`new_y` API**: fpdf2 v2.8+ uses `new_x="LMARGIN", new_y="NEXT"` instead of
  the deprecated `ln=True` parameter for `cell()` calls.

- **structlog + stdlib coexistence**: All `core/` and `formats/` modules must use
  `structlog.get_logger(__name__)`, not `logging.getLogger(__name__)`. The stdlib `logging`
  import is only allowed in `core/logging_config.py` (for configuring the underlying handlers).
  Format handlers were migrated from stdlib to structlog in Phase 5.

- **`/api/health` response envelope**: Phase 5 wrapped the health response in
  `{"status", "timestamp", "uptime_seconds", "components": {...}}`. Tests must check
  `data["components"]["database"]` not `data["database"]`.

- **XLSX `MergedCell.value` is read-only**: When patching values in Tier 3 export
  (`_try_tier3_export`), cells in merged ranges raise `AttributeError` on write. Must
  wrap in `try/except AttributeError` and skip merged cells.

- **`MarkdownHandler.ingest()` takes a file Path**: Use `ingest(path)` not `ingest(text)`.
  For string input, use `ingest_text(md_string)` or the internal `_ingest_text()`.

- **Log file is `markflow.json` not `markflow.log`**: Phase 5 changed the rotating file handler
  output to JSON format with `.json` extension for machine-parseable log tailing.

- **Debug dashboard always mounted**: `/debug` routes are no longer behind `DEBUG=true`.
  The dashboard is a developer tool and is always available at `/debug`.

- **SSE progress queues**: `_progress_queues` in `converter.py` is a module-level
  `dict[str, asyncio.Queue]`. One queue per active batch. The SSE endpoint reads from it;
  the queue is cleaned up when the SSE stream ends or after the `done` event. If the batch
  completes before the SSE client connects, events are replayed from the DB instead.

- **`GET /api/preferences` response envelope changed in Phase 6**: Now returns
  `{"preferences": {...}, "schema": {...}}` instead of a flat `{key: value}` dict.
  Frontend code uses `data.preferences || data` for backwards compat. Tests updated.

- **History `page`/`per_page` vs `limit`/`offset`**: Phase 6 added page-based pagination
  (`page=1&per_page=25`). The old `limit`/`offset` params are still accepted but
  `per_page` takes precedence for pagination math. Tests use page/per_page.

- **Preference validation**: `PUT /api/preferences/{key}` now validates values server-side
  based on `_PREFERENCE_SCHEMA`. Out-of-range numbers return 422 with a descriptive message.
  Read-only keys (`last_source_directory`, `last_save_directory`) return 403.

- **No Pico CSS in Phase 6**: All user-facing pages migrated from Pico CSS to `markflow.css`.
  The shared CSS file defines CSS variables for light and dark themes. Dark mode activates
  via `@media (prefers-color-scheme: dark)` — no JS toggle needed.

- **`review.html` and `debug.html` excluded from nav**: These pages have their own headers.
  `review.html` uses `markflow.css` for shared component styles but has a contextual
  "OCR Review" header instead of the main nav bar.

- **Meilisearch primary key IDs**: Document IDs for Meilisearch must be strings without
  slashes. Use `sha256(source_path)[:16]` hex digest as the primary key. If you use raw
  file paths, Meilisearch rejects them (slashes are not allowed in document IDs).

- **Meilisearch graceful degradation**: All `MeilisearchClient` methods catch connection
  errors and return safe defaults. `health_check() -> False`, `search() -> {"hits": []}`.
  If Meilisearch is down, bulk conversion continues — indexing failures are logged, not
  treated as conversion failures. The search API returns 503 explicitly.

- **`psd-tools` layer traversal**: PSD files have nested layer groups. Must recurse into
  groups to find type layers. `layer.kind == "type"` identifies text layers. Accessing
  `layer.text` on non-type layers raises `AttributeError` — wrap in try/except.

- **exiftool subprocess timeout**: `subprocess.run` with `timeout=30` for exiftool.
  Large files (multi-GB InDesign) can take a long time. The indexer catches
  `TimeoutExpired` and returns `{"_error": "exiftool timeout"}` instead of raising.

- **asyncio.Queue sentinel pattern**: Workers use `None` sentinel in the queue to signal
  shutdown. After enqueueing all files, enqueue N `None` values (one per worker). Each
  worker breaks its loop when it receives `None`. Cancel sets an event and also unblocks
  pause so workers can drain and exit.

- **Bulk SSE separate from single-file SSE**: `_bulk_progress_queues` in `bulk_worker.py`
  is separate from `_progress_queues` in `converter.py` to avoid key collisions between
  batch IDs and bulk job IDs.

- **Source share is read-only**: `/mnt/source` is mounted `:ro` in docker-compose.
  MarkFlow must never write to it. The output repo at `/mnt/output-repo` mirrors the
  source directory structure. Sidecar files go in `_markflow/` subdirectories.

- **httpx is now a runtime dependency**: Phase 7 uses httpx for the Meilisearch client.
  It was previously test-only. Moved from testing section to utilities in requirements.txt.

- **Locations validate endpoint timeout**: `file_count_estimate` walks the directory tree
  capped at 10 seconds via asyncio.wait_for. If it times out, returns null — not an error.
  Don't treat null file_count_estimate as a failure in tests.

- **Locations type filter includes 'both'**: GET /api/locations?type=source returns locations
  with type='source' AND type='both'. The filter is "show me what I can use as a source",
  not "show me locations where type exactly equals source".

- **Locations nav decision**: Locations page is NOT in the main nav bar. It is linked from
  Settings page and the bulk job wizard only — keeps the main nav clean for end users.

- **Browse API allowed roots**: Only /host/* and /mnt/output-repo are browsable.
  Any path outside these roots returns 403. This is enforced in _validate_browse_path()
  before any filesystem access. Do not relax this without security review.

- **Drive detection via env var**: MOUNTED_DRIVES env var (e.g. "c,d,e") tells the
  browse API which drive letters to show in the drives list. A drive showing as
  "unmounted" means /host/{letter} doesn't exist or isn't readable — not that the
  Windows drive doesn't exist.

- **item_count can be null**: Directory entry item_count is best-effort. Permission
  errors or slow directories return null. Never treat null as 0 in the UI.

- **FolderPicker uses <dialog> element**: showModal() / close() API. Backdrop via
  ::backdrop pseudo-element. No polyfill — requires Chrome 98+ / Firefox 98+.
  Docker Desktop's bundled browser meets this requirement.

- **Confidence pre-scan is an estimate**: `_estimate_ocr_confidence()` uses pdfplumber
  text density and Tesseract OSD — not a full OCR pass. The actual post-conversion
  confidence may differ. The pre-scan is a cheap filter, not a guarantee.

- **OSD vs full OCR confidence scales differ**: Tesseract OSD confidence is 0–100 but
  measures script/orientation detection confidence, not text recognition quality.
  It's used as a rough proxy only. The review queue UI shows "estimated" not "measured".

- **review_queue_count in bulk_jobs**: Incremented by bulk_worker when files are
  skipped for review. Not decremented when resolved — it's a total count, not a
  pending count. Use `get_review_queue_summary(job_id)` for current pending count.

- **SSE done event deferred until review queue resolved**: The bulk job SSE stream
  does not send the done event until both the main job and review queue are fully
  resolved. Clients that close the EventSource on `job_complete` will miss review
  queue events. `bulk-review.html` opens its own EventSource connection.

- **Permanently skipped files**: `bulk_files.ocr_skipped_reason = 'permanently_skipped'`
  causes `get_unprocessed_bulk_files()` to exclude the file on future runs. This is
  intentional — permanently skipped files never re-enter the conversion queue.

- **SECRET_KEY required for LLM providers**: If any LLM provider is configured,
  SECRET_KEY env var must be set or the app raises ValueError on startup.
  Generate with: python -c "import secrets; print(secrets.token_hex(32))"

- **MCP server is a separate process**: markflow-mcp runs independently of the
  main app. It shares the database and filesystem but has its own port (8001).
  If the main app is down, MCP tools that need live conversion will fail gracefully.

- **Ollama OpenAI-compat endpoint**: _complete_ollama() tries /v1/chat/completions
  first (available in Ollama 0.1.24+). Falls back to /api/generate if 404.
  The fallback uses a different request/response shape — both are handled.

- **LLM enhancement is always opt-in**: All three preference toggles default to
  false. An active provider with all toggles off does nothing to conversions.
  The verify/ping still works regardless of toggle state.

- **MCP tool docstrings are functional**: Claude.ai uses tool docstrings to decide
  when to call each tool. Do not simplify or shorten them without considering
  how that affects Claude's tool selection behavior.

- **Path safety pass runs during scan, not during conversion**: All path length
  and collision checks happen in BulkScanner._run_path_safety_pass() before any
  file is queued for conversion. The worker trusts resolved_paths — it does not
  re-check. If a file appears in the worker without a resolved_paths entry, that
  is a bug, not a handled edge case.

- **resolve_collision() is deterministic**: Sort order is by str(source_path)
  ascending. For strategy='skip', the alphabetically-first source path always
  wins. This is intentional — predictable behavior matters more than any
  particular ordering preference.

- **Case collision detection only flags same-output-path pairs**: Two files
  that differ only by case in the directory portion (DEPT vs dept) AND produce
  the same lowercased output path are flagged. Files that differ by case but
  produce different output paths are NOT flagged (the Linux container handles
  them correctly as separate files).

- **Renamed output paths use source extension**: report.pdf.md not
  report_pdf.md or report(1).md. The double extension is intentional —
  it makes the source format visible in the filename and is unambiguous.

- **Auto-OCR gap-fill candidates**: A PDF is a gap-fill candidate if
  source_format='pdf', ocr_page_count IS NULL, and status='success'. The gap-fill
  pass updates ocr_page_count so the file won't be a candidate again.

- **Unrecognized files are database-only**: No stub .md files, no Meilisearch
  entries for unrecognized files. Only bulk_files gets a record with
  status='unrecognized'. Keeps the knowledge base signal clean.

- **python-magic requires libmagic1**: The `python-magic` package wraps
  libmagic. Without `libmagic1` installed in the container, `import magic`
  succeeds but `magic.from_file()` fails at runtime. Always install both.

- **`get_unprocessed_bulk_files()` excludes unrecognized**: Files with
  `status='unrecognized'` are cataloged but never enter the worker conversion
  queue. They become processable only when a handler is added and their status
  is explicitly reset to `pending`.

- **MIME detection fallback chain**: python-magic (libmagic) first, then
  extension heuristic. If both fail, returns `("application/octet-stream", "unknown")`.
  MIME detection failure never crashes the scanner.

- **worker_id in SSE events**: `file_start` events include `worker_id` (int 1..N)
  for the active file display. `file_converted`, `file_failed`, and
  `file_skipped_for_review` events also include `worker_id` so the UI can clear
  the correct worker slot when a file finishes. Worker IDs are 1-based in SSE
  events (internal code uses 0-based, +1 applied at emission).

- **truncatePath() trims from left**: Long paths in the active workers panel are
  trimmed from the directory portion, not the filename. The filename is always
  fully visible. The prefix ".../" indicates truncation occurred.

- **active-workers-panel display:none by default**: The panel starts hidden in
  HTML and is shown by JS after the first `file_start` event. This prevents a
  flash of empty worker rows during page load and during the scan phase.

- **VisionAdapter uses active LLM provider**: Vision does NOT have its own
  separate provider system. It uses `get_active_provider()` from database.py
  (the same provider configured in the LLM providers system). One provider
  config, two uses (text + vision). Do not build a separate vision_providers
  package or settings_manager — this was the Conflict Analysis correction.

- **Vision preferences in existing system**: Vision settings (enrichment_level,
  frame_limit, save_keyframes, frame_prompt) are stored in the `user_preferences`
  table via `_PREFERENCE_SCHEMA`, not in a separate `settings` table. There is
  no `core/settings_manager.py` and no `MARKFLOW_SECRET_KEY` env var — use the
  existing `SECRET_KEY` and `core/crypto.py` for encryption.

- **SceneDetector always returns at least 1 scene**: If PySceneDetect finds
  zero scenes (static video, animation) or crashes, the detector returns a
  single SceneBoundary covering the full video. This ensures at least one
  keyframe is always extracted.

- **KeyframeExtractor concurrency**: Up to 4 concurrent ffmpeg processes via
  `asyncio.Semaphore(4)`. VisionAdapter API calls use `Semaphore(3)` — lower
  because API calls are expensive and rate-limited.

- **scenedetect[opencv] pulls opencv-python-headless**: The headless variant
  (no GUI) is correct for Docker. If opencv-python (full) is already installed,
  there may be a conflict. Do not install both.

- **APScheduler lifespan pattern**: Scheduler starts in `lifespan()` via
  `start_scheduler()` and stops in yield cleanup via `stop_scheduler()`.
  Do not use `@app.on_event("startup")` — it's deprecated. One immediate
  lifecycle scan fires on startup via `asyncio.create_task()`, regardless
  of business hours.

- **WAL mode set in `_ensure_schema()`**: After all table creation and
  column additions, `init_db()` runs `PRAGMA journal_mode = WAL` and
  `PRAGMA wal_autocheckpoint = 1000`. This is safe to run every startup —
  SQLite ignores if already in WAL mode.

- **Trash path mirrors output-repo structure**: `.trash/` is a subdirectory
  of the output-repo root. Files in `.trash/` keep their relative path from
  output-repo. Example: `/mnt/output-repo/dept/doc.md` → `/mnt/output-repo/.trash/dept/doc.md`.
  A README.txt is auto-created in `.trash/` on first use.

- **Lifecycle status column default**: New `lifecycle_status` column defaults to
  `'active'` so existing rows are automatically active. No data migration needed.

- **Version numbers are per-file monotonic**: `get_next_version_number()` returns
  `MAX(version_number) + 1` for that `bulk_file_id`. Version numbers never reset.

- **Scan run isolation**: Each lifecycle scan gets a UUID `scan_run_id` recorded
  in `scan_runs`. Errors are caught per-file and appended to `error_log` (JSON
  array). The scan continues after single-file errors.

- **VACUUM defers if scan running**: `run_db_compaction()` checks `scan_runs`
  for any `status='running'` row. If found, it reschedules itself +30 minutes.

- **Scheduler business hours check is sync**: `_is_business_hours()` is
  intentionally synchronous — it uses default hours (06:00-18:00 Mon-Fri)
  without async DB lookups to avoid blocking the scheduler thread.

- **`python-jose` not `PyJWT`**: Auth uses `python-jose[cryptography]` for JWT
  validation. Do not install both — they conflict. `python-jose` provides better
  HS256 + claims validation ergonomics.

- **`DEV_BYPASS_AUTH=true` is the default**: docker-compose.yml defaults to
  `DEV_BYPASS_AUTH=true` so existing local dev setups work without credentials.
  Production must explicitly set it to `false`. When true, `get_current_user()`
  returns an admin user immediately — no JWT or API key required.

- **`/api/health` stays unauthenticated**: Health endpoint has no auth dependency.
  Docker healthchecks, load balancers, and monitoring probe it without credentials.

- **MCP server auth is separate**: The MCP server on port 8001 does NOT use JWT
  auth. It's a separate process used by Claude.ai. MCP auth via `MCP_AUTH_TOKEN`
  env var is an independent concern. Do not add `require_role()` to MCP tools.

- **CORS + SSE limitation**: `EventSource` does not send custom headers, so SSE
  endpoints cannot use Bearer token auth via headers. SSE endpoints currently
  require `search_user` role minimum. In dev bypass mode, this works without
  credentials. In production, SSE auth via query-param token is a follow-up.

- **API key salt never rotates**: `API_KEY_SALT` is set once on initial setup.
  Rotating it invalidates ALL existing API key hashes stored in the `api_keys`
  table. There is no migration path — all keys would need to be regenerated.
  Use `hashlib.blake2b(raw_key + salt, digest_size=32).hexdigest()`.

- **API key raw value shown once**: `POST /api/admin/api-keys` returns the raw
  key exactly once. It is never stored — only the BLAKE2b hash is persisted.
  If the raw key is lost, generate a new one and revoke the old one.

- **Preferences role split**: `PUT /api/preferences/{key}` requires `OPERATOR`
  base role. System-level keys (worker_count, scanner_*, lifecycle_*, etc.) in
  `_SYSTEM_PREF_KEYS` additionally require `MANAGER`. The check happens AFTER
  the base `OPERATOR` gate, inline in the endpoint function body.

- **Root redirect changed**: `/` now returns `RedirectResponse(url="/search.html")`
  instead of serving `index.html`. This makes search the default landing page
  for all users (including `search_user` who cannot access Convert).

- **Nav is dynamic**: All HTML pages use `<div id="main-nav" class="nav-links"></div>`
  instead of hardcoded links. `app.js::buildNav()` fetches `/api/auth/me` on page load
  and renders only the nav items the user's role permits. If `/api/auth/me` fails,
  nav falls back to `search_user` level (only Search visible).

- **Lifecycle scanner needs a `bulk_jobs` parent row**: `bulk_files.job_id` has an FK
  constraint referencing `bulk_jobs(id)`. If no bulk jobs exist (fresh DB or all deleted),
  the lifecycle scanner creates a synthetic "lifecycle" job via `create_bulk_job()` before
  inserting files. Using `scan_run_id` or any other non-existent ID as `job_id` will
  cause `FOREIGN KEY constraint failed` on every file insert.

- **FastMCP no longer accepts `description` kwarg**: The `mcp` library removed the
  `description` parameter from `FastMCP.__init__()`. Pass the server name as the first
  positional argument only. Check `inspect.signature(FastMCP.__init__)` when upgrading.

- **Lifecycle scan state is in-memory**: `_scan_state` in `lifecycle_scanner.py` is a
  module-level dict, not persisted to SQLite. If the container restarts mid-scan,
  `running` will be `false` and `scanned` will be `0`. The scheduler fires a new scan
  at the next scheduled interval. This is intentional.

- **Bulk scan pre-count capped at 10s**: `BulkScanner.scan()` runs `_count_files()` in
  a thread with `asyncio.wait_for(timeout=10)`. If it times out, `total_estimate=0`
  and progress events report `pct: null`. The UI shows an indeterminate bar in this case.

- **`GET /api/scanner/progress` uses `SEARCH_USER` role**: Unlike `/api/scanner/status`
  which requires `MANAGER`, the progress endpoint is lighter-weight and available to
  any authenticated user so the bulk.html lifecycle bar works for operators too.

- **`psutil.cpu_affinity()` not available on macOS Docker**: Always returns False
  from `apply_affinity()`, log warning, continue. Linux containers work correctly.

- **`psutil.cpu_percent(interval=None)` requires priming**: Call once with
  `interval=0.1` at startup or first call returns 0.0 for all cores. Primed
  in `main.py` lifespan before scheduler starts.

- **Stats endpoint never returns 500**: All sub-queries in `GET /api/admin/stats`
  are wrapped in `_safe()` + `asyncio.gather(return_exceptions=True)`. If a query
  fails, its section is null in the response.

- **Stop is cooperative, not instant**: `request_stop()` cancels asyncio tasks and
  sets a flag. Workers check the flag before each file. A worker mid-conversion will
  finish that file before stopping. Hard kill (`SIGKILL`) is not used — it would
  corrupt the SQLite WAL. If a worker is hung on a single file, the only option is
  container restart.

- **`dir_stats` tracks top-level directories only**: Tracking the full directory tree
  would create an unbounded dict on deep repositories. Top-level subdirectories only.
  Full tree tracking is a future enhancement.

- **`reset_stop()` must be called before starting new jobs**: If the stop flag is set
  and not reset, new bulk jobs will immediately stop at the first file. `POST /api/bulk/jobs`
  calls reset automatically. Manual reset available at `POST /api/admin/reset-stop`.

- **DB repair acquires exclusive lock**: All in-flight requests will wait during a
  dump-and-restore repair. The repair endpoint checks `stop_controller.registered_tasks`
  and refuses to run if any tasks are active. User must stop all jobs first.

- **Locations UX flagged for redesign**: static/locations.html and api/routes/locations.py
  are functional but the layout and workflow have been flagged for UX revision.
  Do NOT refactor until a redesign spec is written. A banner is shown to users.
  Core functions (add/edit/delete location, path validation, FolderPicker) work correctly.
  Tracked: LOCATIONS_UX_REDESIGN (search this token to find all related notes).

- **`active-jobs-panel.js` is deleted**: The slide-in panel was replaced by
  `/status.html` in v0.9.4. Do not recreate it. All job status UI lives on the
  dedicated status page now.

- **`global-status-bar.js` is badge-only**: v0.9.4 stripped the floating bar. The
  file now only exports `initStatusBadge()` which polls `/api/admin/active-jobs`
  and updates a `<span class="nav-badge">` inside the Status nav link. It is
  loaded dynamically by `app.js` after `buildNav()` — no per-page `<script>` tag.

- **Status nav link visible to all roles**: The "Status" entry in `NAV_ITEMS` uses
  `minRole: "search_user"` so every authenticated user can see active job status.
  The STOP ALL / pause / cancel buttons on `status.html` call admin/manager endpoints
  that enforce their own role checks server-side.

- **Dual-file logging strategy**: `logs/markflow.log` (operational, always active)
  and `logs/markflow-debug.log` (debug trace, developer mode only). Both use
  `TimedRotatingFileHandler` with daily rotation. Operational keeps 30 days,
  debug keeps 7 days. Both write structlog JSON format.

- **`log_level` preference maps to handler levels, not root level**: The `LEVEL_MAP`
  maps "normal"→WARNING, "elevated"→INFO, "developer"→DEBUG. The operational
  handler uses `_OPERATIONAL_LEVEL_MAP` (WARNING for normal, INFO for elevated/developer).
  Root logger level matches the LEVEL_MAP value.

- **`update_log_level()` is synchronous**: Called from the async preferences
  endpoint, but only touches logging module state (no DB or async I/O). Safe
  to call from sync or async contexts.

- **Client event endpoint never errors**: `POST /api/log/client-event` catches
  all exceptions internally and always returns 204. Malformed JSON, missing
  fields, rate limit exceeded — all return 204 silently. This prevents
  frontend logging from ever disrupting the user experience.

- **Client event rate limit is per-IP in-memory**: Uses `defaultdict(deque)`
  token bucket. Max 50 events/second per IP. Not persistent — resets on
  container restart. No Redis dependency.

- **Log file download is whitelist-only**: `GET /api/logs/download/{filename}`
  only accepts `markflow.log` or `markflow-debug.log`. Any other filename
  returns 400. Path traversal is blocked by the whitelist check before any
  filesystem access.

- **`configure_logging()` is idempotent**: The `_configured` flag prevents
  double initialization. The initial call happens at module level in `main.py`.
  The lifespan then reads the DB preference and calls `update_log_level()` if
  the stored level differs from "normal".

- **Log file renamed from markflow.json to markflow.log**: v0.9.5 changed the
  operational log filename. The file still contains JSON-formatted structlog
  output — only the extension changed for clarity in the dual-file naming.

---

## Running the App

```bash
docker-compose up -d          # start
docker-compose logs -f        # watch logs
curl localhost:8000/api/health # verify
docker-compose down           # stop
```

After code changes: `docker-compose build && docker-compose up -d`
