# MarkFlow Version History

Detailed changelog for each version/phase. Referenced from CLAUDE.md.

---

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

**v0.9.6** — Admin disk usage dashboard. `GET /api/admin/disk-usage` walks all
  MarkFlow directories in a thread and reports per-directory byte counts, file
  counts, and volume info. Trash excluded from output-repo total (no double-count).
  DB + WAL reported separately in API, combined in UI. Admin page gains Disk Usage
  section with volume progress bars, breakdown cards, and manual Refresh button.
  No auto-polling — directory walks can take seconds on large repos.

**v0.9.7** — Resources page & activity monitoring. New `system_metrics` table
  (30s samples via APScheduler), `disk_metrics` (6h snapshots), `activity_events`
  (bulk start/end, lifecycle scan, index rebuild, startup/shutdown, DB maintenance).
  `core/metrics_collector.py` owns collection, queries, and 90-day purge.
  Resources page (`/resources.html`, manager+ role) with: executive summary card
  (IT admin pitch with description sentences), CPU/memory Chart.js time-series,
  disk growth stacked area chart, live system metrics (moved from Admin), activity
  log with type filters and expandable metadata, repository overview. CSV export
  for all three metrics tables. Admin Task Manager replaced with link card to
  Resources; resource controls remain on Admin. 5 new API endpoints under
  `/api/resources/` (metrics, disk, events, summary, export).

**v0.9.8** — Password-protected document handling. `core/password_handler.py`
  detects two layers: restrictions (edit/print flags stripped automatically via
  pikepdf/lxml) and real encryption (password cascade: empty → user-supplied →
  org list → found-reuse → dictionary → brute-force → john). `pikepdf` handles
  PDF owner/user passwords. `msoffcrypto-tool` handles OOXML + legacy Office
  encryption. OOXML restriction tags (`documentProtection`, `sheetProtection`,
  `workbookProtection`, `modifyVerifier`) stripped via ZIP+lxml rewrite.
  Converter preprocesses files before `handler.ingest()` — no handler signature
  changes. Bulk worker shares `PasswordHandler` instance across files for
  found-password reuse. Convert page gains password input field. Settings page
  gains Password Recovery section (6 new preferences). DB columns:
  `protection_type`, `password_method`, `password_attempts` on both
  `conversion_history` and `bulk_files`. `john` installed in Docker for
  enhanced PDF cracking. Bundled `common.txt` dictionary (top passwords).

**v0.9.9** — GPU auto-detection & dual-path hashcat integration.
  `core/gpu_detector.py` probes container for NVIDIA (nvidia-smi) and reads
  host worker capabilities from `/mnt/hashcat-queue/worker_capabilities.json`.
  Execution path priority: NVIDIA container > host worker > hashcat CPU > none.
  `tools/markflow-hashcat-worker.py` runs outside Docker, watches shared queue
  volume for crack jobs, runs hashcat with host GPU (AMD ROCm, Intel OpenCL).
  Job queue is file-based JSON over a bind-mounted volume. `docker-compose.gpu.yml`
  overlay provides NVIDIA Container Toolkit GPU reservation. Dockerfile adds
  hashcat, OpenCL packages, clinfo. `CrackMethod` enum gains `HASHCAT_GPU`,
  `HASHCAT_CPU`, `HASHCAT_HOST`. New preferences: `password_hashcat_enabled`,
  `password_hashcat_workload`. Health endpoint reports dual-path GPU info.
  Settings page gains GPU Acceleration status card. Container starts normally
  with no GPU present — graceful degradation to CPU/john fallback.
  Apple Silicon Macs: Metal backend detection, unified memory estimation,
  Rosetta 2 binary guard, hashcat >= 6.2.0 version gate, thermal-safe
  workload profile (-w 2). macOS Intel discrete GPUs (Radeon Pro) supported
  via OpenCL.

**v0.10.0** — In-app help wiki & contextual help system. 19 markdown articles
  in `docs/help/` rendered via mistune at `GET /api/help/article/{slug}`.
  Searchable via `GET /api/help/search?q=`. Help page (`/help.html`) with sidebar
  TOC, search, hash-based navigation. Contextual "?" icons via `data-help`
  attributes + `static/js/help-link.js`. Nav gains "Help" link (all roles, no auth).
  Help API endpoints are public. CSS: help-layout classes in markflow.css.

**v0.10.1** — Apple Silicon Metal support for GPU hashcat worker.
  `tools/markflow-hashcat-worker.py` gains macOS detection: Apple Silicon
  (M1/M2/M3/M4) via Metal backend, Intel Mac discrete GPU via OpenCL.
  Rosetta 2 binary warning prevents silent Metal loss. hashcat version
  gated at >= 6.2.0 for Metal. Unified memory estimation (~75% of system
  RAM) replaces VRAM reporting on Apple Silicon. Thermal-safe workload
  profile (-w 2, not -w 3) prevents throttling on fanless Macs.
  `core/gpu_detector.py` recognizes vendor=apple/backend=Metal in worker
  capabilities. Settings GPU status card updated for Apple display.

**v0.11.0** — Intelligent auto-conversion engine. When the lifecycle
  scanner finds new/modified files, the engine decides whether, when,
  and how aggressively to convert them. Three modes: immediate (same
  scan cycle), queued (background task), scheduled (time-window only).
  Dynamic worker scaling and batch sizing based on real-time CPU/memory
  load + historical hourly averages. `core/auto_converter.py` (decision
  engine), `core/auto_metrics_aggregator.py` (hourly rollup from
  system_metrics into auto_metrics table). Two new SQLite tables:
  `auto_metrics` (hourly aggregated system metrics for pattern learning),
  `auto_conversion_runs` (decision/execution audit log). 9 new preferences
  (auto_convert_mode, workers, batch_size, schedule_windows,
  decision_log_level, metrics_retention_days, business_hours_start/end,
  conservative_factor). `BulkJob` gains `max_files` parameter for batch
  capping. `bulk_jobs` gains `auto_triggered` column. APScheduler gains
  hourly aggregation job (:05 past each hour) and 15-min deferred
  conversion runner. Status page gains mode override card (ephemeral,
  resets on container restart). Settings page gains Auto-Conversion
  section. API: GET/POST/DELETE /api/auto-convert/override,
  GET /api/auto-convert/status, /history, /metrics.

**v0.12.0** — Universal format support, unified scanning & folder drop UI.
  10 new format handlers: RTF (`rtf_handler.py`, control-word parser with font
  mapping), HTML/HTM (`html_handler.py`, BeautifulSoup + CSS font extraction),
  ODT/ODS/ODP (`odt_handler.py`, `ods_handler.py`, `odp_handler.py` via odfpy),
  TXT/LOG (`txt_handler.py`, encoding detection + heading heuristics),
  XML (`xml_handler.py`, DOM traversal + element extraction),
  EPUB (`epub_handler.py`, ebooklib chapter structure preservation),
  EML/MSG (`eml_handler.py`, RFC 5322 + Outlook OLE via olefile),
  Adobe unified handler (`adobe_handler.py`, PSD/AI/INDD/AEP/PRPROJ/XD
  metadata extraction via exiftool). Total supported extensions: 26 across
  16 handlers. Bulk scanner unified — no separate Adobe/convertible split;
  all formats go through the same scanning pipeline with single-pass
  extension lookup against the format registry. Font recognition added to
  `extract_styles()` across handlers for Tier 2 reconstruction fidelity.
  Convert page (`index.html`) gains folder drop: drag-and-drop entire
  directories, auto-scans for valid formats, queues matching files for
  conversion. `formats/__init__.py` imports all new handlers at module load.
  `core/bulk_scanner.py` refactored to use `list_supported_extensions()`
  instead of hardcoded extension sets. `core/converter.py` and
  `core/bulk_worker.py` updated for new handler lookup path.

**v0.12.1** — Data format handlers + recursive email attachment conversion.
  Three new handlers: `json_handler.py` (JSON with summary + structure outline +
  secret redaction), `yaml_handler.py` (YAML/YML with multi-document support,
  comments preservation in source block), `ini_handler.py` (INI/CFG/CONF/properties
  with configparser + line-by-line fallback; `.conf` without sections treated as
  plain text). All three produce Summary + Structure + Source markdown layout.
  Secret value redaction (password, token, api_key, credential, auth key patterns).
  EmlHandler upgraded with recursive attachment conversion — attachments with
  registered handlers are converted and embedded inline under `## Attachments`.
  Depth-limited to 3 for nested emails. Non-fatal failures. MSG attachments
  supported via olefile stream traversal. 7 new extensions registered:
  `.json`, `.yaml`, `.yml`, `.ini`, `.cfg`, `.conf`, `.properties`.
  Total supported extensions: 33 across 19 handlers. Convert page and folder
  drop UI updated for new extensions.

**v0.12.2** — Size-based log rotation + settings download loop fix.
  Replaced `TimedRotatingFileHandler` with `RotatingFileHandler` (50 MB main,
  100 MB debug, configurable via `LOG_MAX_SIZE_MB` / `DEBUG_LOG_MAX_SIZE_MB`).
  Log download endpoint gets size guard (HTTP 413 for files >500 MB) and
  explicit `Content-Length` header to prevent browser download restart loops.

**v0.12.3** — Compressed file scanning, archive extraction, file tracking.
  New `ArchiveHandler` for ZIP, TAR, TAR.GZ, 7z, RAR, CAB, ISO. Recursive
  extraction and conversion of inner documents (depth limit 20). Archive
  summary markdown per file. Zip-bomb protection (`core/archive_safety.py`):
  ratio check, total size cap, entry count cap, quine detection. Compound
  extension support in format registry (`_get_compound_extension()`) and
  bulk scanner (`_get_effective_extension()`). New `archive_members` DB table.
  Dependencies: py7zr, rarfile, pycdlib, cabextract, unrar-free, p7zip-full.
  Password file at `config/archive_passwords.txt`. 12 new extensions registered.
  Total supported extensions: 45 across 20 handlers.

**v0.12.4** — Archive password writeback and session-level reuse.
  Successful archive passwords saved back to `archive_passwords.txt` and
  cached in-memory for the process lifetime. Found passwords tried first
  on subsequent archives. Thread-safe via lock.

**v0.12.5** — Full password cracking cascade for encrypted archives.
  Archive handler now mirrors the PDF/Office password handler cascade:
  known passwords, dictionary attack (common.txt + mutations), brute-force.
  Respects user preferences for charset, max length, timeout. Settings read
  sync-safely via direct sqlite3 connection.

**v0.12.6** — Brute-force charset fixed to all printable characters as default
  for both archive and PDF/Office crackers. Fallback charset updated.

**v0.12.7** — Full ASCII charset (0x01-0x7F) including control characters.
  New `all_ascii` charset option in Settings UI. Default for both archive
  and PDF/Office brute-force. Encrypted ZIP, 7z, and RAR archives —
  including nested ones — get the full cracking cascade at every depth.

**v0.12.8** — Progress tracking and ETA for scan and bulk conversion jobs.
  New `core/progress_tracker.py`: `RollingWindowETA` (last 100 items),
  `ProgressSnapshot`, `format_eta()`, `estimate_single_file_eta()`.
  Concurrent fast-walk counter in `bulk_scanner.py` via `asyncio.create_task`
  — scan starts immediately, file count arrives in parallel (no blocking).
  Bulk worker writes ETA to DB every 2s and emits `progress_update` SSE
  events with `eta_human`, `files_per_second`, `percent`. All job status
  API endpoints (`GET /api/bulk/jobs/{id}`, active jobs) return `progress`
  block. DB: added `eta_seconds`, `files_per_second`, `eta_updated_at`,
  `total_files_counted`, `count_status` columns to `scan_runs`, `bulk_jobs`,
  `conversion_history`. UI: ETA display and speed indicator on bulk page,
  scan progress shows "X of Y files" with streaming count.

**v0.12.9** — Startup crash fix, log noise suppression, Docker build optimization (2026-03-30).
**Bugfixes:**
- Fixed: `NameError: name 'structlog' is not defined` in `database.py` — missing
  `import structlog` caused `cleanup_orphaned_jobs()` to crash on every startup,
  putting the markflow container in a restart loop (exit code 3).
- Suppressed pdfminer debug/info logging — pdfminer (used internally by pdfplumber)
  emits thousands of per-token debug messages during PDF extraction. A single bulk job
  was inflating the debug log to 500+ MB. All `pdfminer.*` loggers now set to WARNING
  in `configure_logging()`, matching existing pattern for noisy third-party libraries.
**Infrastructure:**
- Split Dockerfile into `Dockerfile.base` (system deps, ~25-30 min on HDD) and
  `Dockerfile` (pip + code copy, ~3-5 min). Daily rebuilds skip the heavy apt layer.
- Added deployment scripts for Windows work machine: `build-base.ps1` (one-time base
  image builder), `refresh-markflow.ps1` (quick code-only rebuild), `reset-markflow.ps1`
  and `pull-logs.ps1` (PowerShell equivalents of the Proxmox bash scripts).
- Updated reset scripts (both Proxmox and Windows) to preserve `markflow-base:latest`
  during Docker prune, auto-building it if missing.

**v0.12.10** — MCP server fixes, multi-machine Docker support, settings UI improvements (2026-03-30).
**Bugfixes:**
- Fixed: MCP server crash loop — `FastMCP.run()` does not accept `host` or `port` kwargs.
  First attempted kwargs (TypeError crash), then UVICORN env vars (ignored). Final fix:
  `uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port)` — bypass `mcp.run()` entirely.
- Fixed: MCP info panel showed `http://172.20.0.3:8001/mcp` (Docker-internal IP, wrong
  path). Replaced `socket.gethostbyname()` with hardcoded `localhost`, `/mcp` with `/sse`.
- Fixed: MCP health check 404 — `FastMCP.sse_app()` has no `/health` route. Added
  Starlette `Route("/health")` to the SSE app before passing to uvicorn.
**Features:**
- Multi-machine Docker support — `docker-compose.yml` volume paths now use `${SOURCE_DIR}`,
  `${OUTPUT_DIR}`, `${DRIVE_C}`, `${DRIVE_D}` from `.env` (gitignored). Same compose file
  works on Windows workstation and MacBook VM without edits. `.env.example` template added.
- MCP settings panel: replaced generic setup instructions with connection methods for
  Claude Code, Claude Desktop, and Claude.ai (web with ngrok tunnel).
- "Generate Config for Claude Desktop" button — merges markflow MCP entry into user's
  existing `claude_desktop_config.json` non-destructively (client-side JS, no backend).
- PowerShell deployment scripts (`reset-markflow.ps1`, `refresh-markflow.ps1`) gain `-GPU`
  switch to include `docker-compose.gpu.yml` override.
- Developer Mode checkbox at top of Settings page — toggles both `log_level` and
  `auto_convert_decision_log_level` between `developer` and `normal`. Syncs bidirectionally
  with the log level dropdown.
**Default preference changes (fresh deployments):**
- `auto_convert_mode`: `off` → `immediate` (scan + convert automatically)
- `auto_convert_workers`: `auto` → `10`
- `worker_count`: `4` → `10`
- `max_concurrent_conversions`: `3` → `10`
- `ocr_confidence_threshold`: `80` → `70`
- `max_output_path_length`: `240` → `250`
- `scanner_interval_minutes`: `15` → `30`
- `collision_strategy`: `rename` (unchanged, confirmed as desired default)
- `bulk_active_files_visible`: `true` (unchanged, confirmed)
- `password_brute_force_enabled`: `false` → `true`
- `password_brute_force_max_length`: `6` → `8`
- `password_brute_force_charset`: `alphanumeric` → `all_ascii`
- Auto-conversion worker select gains "10" option in UI.

**v0.12.1** — Bugfix + Stability Patch (2026-03-29).
**Bugfixes (from log analysis):**
- Fixed: structlog double `event` argument in lifecycle_scanner (two instances)
- Fixed: SQLite "database is locked" — all direct `aiosqlite.connect()` calls now use
  `get_db()` or set `PRAGMA busy_timeout=10000`; retry wrapper on metrics INSERT
- Fixed: collect_metrics interval increased from 60s to 120s with `misfire_grace_time=60`;
  added 30s timeout wrapper via `asyncio.wait_for`
- Fixed: DB compaction always deferred — removed `scan_running` guard, compaction now runs
  concurrently with scans (safe in WAL mode)
- Fixed: MCP server unreachable — health check now uses `MCP_HOST` env var (default
  `markflow-mcp` Docker service name) instead of hardcoded `localhost`
**Stability improvements:**
- Added: Startup orphan job recovery — auto-cancels stuck bulk_jobs and interrupts
  stuck scan_runs on container start (before scheduler starts)
- Fixed: Stop banner CSS — `.stop-banner[hidden]` override prevents `display:flex`
  from overriding the HTML `hidden` attribute; JS uses `style.display` toggle
- Note: Lifecycle scanner progress tracking + ETA already existed (v0.12.8)
- Added: Mount-readiness guard — bulk scanner and lifecycle scanner verify source mount
  is populated before scanning. Empty mountpoints (SMB not connected) abort gracefully.
- Added: Static file `Cache-Control: no-cache, must-revalidate` headers via middleware
- Added: `DEFAULT_LOG_LEVEL` env var for container-start log level override
