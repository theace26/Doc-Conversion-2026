# MarkFlow — CLAUDE.md

Auto-loaded by Claude Code at session start. Detailed references split into `docs/` files.

### When to read the reference docs

Read these files **on demand** — they are not loaded automatically. Use your judgement:

| File | Read it when... |
|------|-----------------|
| [`docs/gotchas.md`](docs/gotchas.md) | You're modifying or debugging a subsystem (check its section before writing code) |
| [`docs/key-files.md`](docs/key-files.md) | You need to locate a file by purpose, or understand what a file does |
| [`docs/version-history.md`](docs/version-history.md) | You need context on why something was built, what changed in a version, or feature scope |
| [`docs/phase-1-instructions.md`](docs/phase-1-instructions.md) | Rarely — only if revisiting the original Phase 1 design spec |

**Rule of thumb:** If a task touches bulk/lifecycle/auth/password/GPU/OCR/search, read the
relevant gotchas section first. Most bugs in these areas have already been hit and documented.

---

## Project

**Doc-Conversion-2026** (internal name: MarkFlow) — a Python/FastAPI web app that converts
documents bidirectionally between their original format and Markdown. Runs in Docker.
GitHub: `github.com/theace26/Doc-Conversion-2026`

---

## Current Status — v0.17.3

v0.17.3: Skip reason tracking + startup crash fix. New `skip_reason` column on
`bulk_files` (migration #18) records why each file was skipped during conversion:
path too long, output collision, OCR confidence below threshold, unchanged since
last scan. Job detail page displays skip reasons in the Details column (amber text,
matching error_msg pattern). Also fixed missing `Query` import in
`api/routes/bulk.py` that caused the container to crash-loop on startup.

Previous (v0.17.2): UI layout cleanup and pending files viewer. System Status
health check moved from Convert page to Status page. Pending Files viewer on
History page with live count, search, pagination, color-coded status. Convert
page: Browse button for output dir, session-sticky path, Conversion Options
with disclaimer.

Previous (v0.17.1): Job config modal with per-job overrides, "Browse All" on
search page, auto-converter backlog fix for orphaned pending files.

Previous (v0.17.0): Job detail page, enhanced viewer, scanner fix.

Previous (v0.16.9): Multi-source scanning within single job/run.

Previous (v0.16.8): Job History cleanup. Timestamps now use `formatLocalTime()` for
human-readable display (e.g. "Apr 1, 2026, 3:13 PM" instead of raw ISO).
Status labels title-cased ("Completed" not "COMPLETED"). Stats show
"X of Y converted" when total file count is available.

Previous (v0.16.7): Collapsible settings sections. All 16 Settings page sections are now
wrapped in native `<details>/<summary>` elements. Only Locations and Conversion
are open by default; all others start collapsed. "Expand All / Collapse All"
toggle button in the page header. Animated chevron indicator, smooth slide-down
on open. Significantly reduces visual clutter on the Settings page.

Previous (v0.16.6): Location exclusions. New "Exclude Location" feature on the Locations
page lets users define paths to skip during scanning. Uses prefix matching —
excluding `/host/c/Archive` skips all files and subdirectories under that path.
New `location_exclusions` DB table with full CRUD API
(`/api/locations/exclusions`). Both bulk scanner and lifecycle scanner load
exclusion paths at scan start and filter at the `os.walk()` level (excluded
directories are never descended into). UI mirrors the existing Add Location
form with Browse, Check Access, and inline edit/delete.

Previous (v0.16.5): Activity log pagination. Resources page activity log now uses per-page
buttons (10/30/50/100/All) matching the search page pattern. Fixed-height
scrollable container (600px max) with sticky header. Default reduced from 100
to 10 rows. Shows "Showing X of Y events" count summary.

Previous (v0.16.4): Filename search normalization. New `filename_search` field in all three
Meilisearch indexes (documents, adobe-files, transcripts) normalizes filenames
for search by splitting on underscores, dots, dashes, camelCase boundaries,
and letter/number transitions. Searching "PENINSULA SMALL WORKS" now matches
`PENINSULA_SMALL_WORKS.pdf`, `wage.sheets` matches `wage.sheets.pdf`, and
`IBEWLocal46` matches as `IBEW Local 46`. Original filenames preserved in
`source_filename` for display. Rebuild Index button added to Bulk page pipeline
controls.

Previous (v0.16.3): Search hover preview. Hovering over a search result shows a preview
popup of the file content. Smart hybrid strategy: inline source for PDFs/images/
text (via sandboxed iframe), converted markdown text for other formats, snippet
fallback when neither is available. User-configurable via Settings page:
`preview_enabled` (on/off), `preview_size` (small/medium/large), `preview_delay_ms`
(100-2000ms hover delay before popup appears). Preview cache avoids redundant
API calls. Doc-info metadata fetched on hover to determine best preview strategy.

Previous (v0.16.2): Streamlining audit complete (24/24 resolved) + search viewer UX fix.
Search viewer back button now closes the tab (returning to search results)
instead of navigating within the viewer tab. Final 3 streamlining items:
**STR-05** — Split monolithic `database.py` (2,300 lines) into `core/db/` package
with 8 domain modules (connection, schema, preferences, bulk, conversions,
catalog, lifecycle, auth). `core/database.py` is now a backward-compatible
re-export wrapper — all existing imports unchanged.
**STR-13** — Converted `upsert_source_file()` from SELECT-then-INSERT/UPDATE
to single-statement `INSERT ... ON CONFLICT DO UPDATE`, handling dynamic
`**extra_fields` in both the insert and conflict-update clauses.
**STR-17** — Replaced 40+ `_add_column_if_missing()` / `PRAGMA table_info()`
calls with a `schema_migrations` table and 16 versioned migration batches.
Startup now checks one table instead of running 40+ schema introspection queries.
Security audit (62 findings) documented in `docs/security-audit.md` — not yet
addressed (planned for dedicated session).

Previous (v0.16.1): Code streamlining pass. Resolved 21 of 24 identified code quality
issues. Key changes: shared ODF utils (`formats/odf_utils.py`), consolidated
`now_iso()` and `db_write_with_retry()` in database.py, `ALLOWED_EXTENSIONS`
now derived from handler registry (auto-syncs with new format handlers),
`verify_source_mount()` shared between scanners, singleton `get_search_indexer()`
usage enforced in flag_manager, hoisted deferred imports in scheduler/lifecycle/
bulk modules, `_count_by_status()` helper, `upsert_adobe_index` uses ON CONFLICT,
removed legacy `formatDate()` (all callers use `formatLocalTime()`), extracted
`_throwOnError()` helper in app.js, removed dead imports, fixed logger naming
inconsistencies.

Previous (v0.16.0): File flagging & content moderation. Self-service file flagging lets any
authenticated user temporarily suppress a file from search and download. Admins
manage flags through dedicated page with three-action escalation: dismiss (restore),
extend (keep suppressed longer), or remove (permanent blocklist). New `file_flags`
and `blocklisted_files` tables. Meilisearch `is_flagged` filterable attribute on
all 3 indexes. Blocklist enforced during scanning — prevents re-indexing of removed
files. Webhook notifications for all flag events. Hourly auto-expiry scheduler job.
Flag button on search results, admin flagged files page with filters/sort/pagination.
File size fix: search results now show original source file size instead of markdown
output size. New preferences: `flag_webhook_url`, `flag_default_expiry_days`.

Previous (v0.15.1): Cloud file prefetch system. Platform-agnostic background prefetch for
cloud-synced source directories (OneDrive, Google Drive, Nextcloud, Dropbox,
iCloud, NAS tiered storage). `CloudDetector` probes files via disk block
allocation and read latency. `PrefetchManager` runs background workers with
rate limiting, adaptive timeouts, retry with backoff, and backpressure. Scanner
enqueues files for prefetch; converter waits for prefetch before reading. New
preferences: `cloud_prefetch_enabled`, `cloud_prefetch_concurrency`,
`cloud_prefetch_rate_limit`, `cloud_prefetch_timeout_seconds`,
`cloud_prefetch_min_size_bytes`, `cloud_prefetch_probe_all`. Health check shows
prefetch stats. Settings page has Cloud Prefetch section.

Previous (v0.15.0): Search UX overhaul + enterprise scanner robustness. New unified search
endpoint (`/api/search/all`) queries all 3 Meilisearch indexes concurrently
(documents, adobe-files, transcripts) and merges results. Faceted format
filtering with clickable chips, sort by relevance/date/size/format. New
document viewer page (`viewer.html`) — click a search result to view the
original source file (PDF inline, other formats show fallback), toggle between
Source and Markdown views, download button. Source file serving endpoints:
`/api/search/source/{index}/{doc_id}`, `/api/search/download/{index}/{doc_id}`,
`/api/search/doc-info/{index}/{doc_id}`. Batch download via
`POST /api/search/batch-download` (multi-select checkboxes, creates ZIP).
Per-page buttons (10/30/50/100), fixed autocomplete (was broken due to
competing input handlers), local time display via global `formatLocalTime()`.
`search_indexer.py` now looks up `source_path` from `source_files` DB table
when frontmatter lacks it. Enterprise scanner robustness: AD-credentialed
folder `onerror` callbacks on all `os.walk()` calls, FileNotFoundError
handling (AV quarantine), NTFS ADS filtering (skip files with `:` in name),
stale SMB connection retry, explicit PermissionError logging.

Previous (v0.14.1): Health-gated startup + pipeline watchdog. Startup no longer does an
immediate force-scan; instead `core/pipeline_startup.py` waits the configured
delay (default 5 min), polls health checks, and only triggers the first scan
once critical services (DB, disk) pass. Preferred services (Meilisearch,
Tesseract, LibreOffice) produce warnings but do not block. New pipeline
watchdog in `scheduler.py` logs WARN hourly and ERROR daily when the pipeline
is disabled, then auto-re-enables after `pipeline_auto_reset_days` (default 3).
Pipeline status API now includes `disabled_info` with auto-reset countdown.
Bulk page shows a disabled warning banner. New preferences:
`pipeline_startup_delay_minutes`, `pipeline_auto_reset_days`.

Previous (v0.14.0): Automated conversion pipeline. The lifecycle scanner is now
the sole trigger for conversion — when it detects new or changed files, it
automatically spins up bulk conversion. New `pipeline_enabled` master toggle and
`pipeline_max_files_per_run` cap. Pipeline API (`/api/pipeline/status`,
`pause`, `resume`, `run-now`). Pipeline status card on Bulk page with
live refresh. Pipeline settings section on Settings page.

Previous (v0.13.9): Source files dedup + expanded format support. New `source_files`
table eliminates cross-job row duplication in `bulk_files` — one row per
unique `source_path` with file-intrinsic data. All cross-job queries
(admin stats, lifecycle, trash) now use `source_files`. Also: ImageHandler
for .jpg/.png/.tif/.bmp/.gif/.eps, DocxHandler handles .docm/.wpd via
LibreOffice, AdobeHandler handles .ait/.indt templates.

Previous (v0.13.7): Legacy Office format support + scheduler coordination.
`.xls` and `.ppt` files now convert via LibreOffice preprocessing →
existing openpyxl/python-pptx pipelines. Shared `core/libreoffice_helper.py`
replaces duplicated LibreOffice logic across all three legacy handlers.
Lifecycle scan now yields to active bulk jobs — prevents "database is locked"
errors from concurrent DB access.

**Pre-production checklist:**
- Lifecycle timers are set to testing values — **MUST** restore before production:
  - `lifecycle_grace_period_hours`: currently **12** (production: 36+)
  - `lifecycle_trash_retention_days`: currently **7** (production: 60+)
  - Set via Settings UI or `PUT /api/preferences/<key>`

**Known issues:**
- None currently blocking.

Previous (v0.13.6): ErrorRateMonitor integrated across all I/O subsystems. Meilisearch
index rebuild aborts early if search service is unreachable. Cloud transcriber
disables itself for the session after repeated API failures (expired key, rate
limit, outage). EML/MSG attachment processing aborts on cascading failures.
Archive password cracking distinguishes I/O errors (file unreadable) from
wrong-password exceptions and aborts only on the former.

Previous (v0.13.5): Archive batch extraction + parallel conversion.
(v0.13.4): OCR Quality dashboard + Scan Throttle History.
(v0.13.3): Error-rate monitoring for scanners/workers.
(v0.13.2): Feedback-loop throttling. (v0.13.1): Adaptive scan parallelism.

Previous (v0.13.0): Media transcription pipeline. Audio/video files convert to
Markdown transcripts with timestamped segments. Local Whisper (GPU auto-detect)
with cloud fallback (OpenAI Whisper API, Gemini audio). Caption files
(SRT/VTT/SBV) parsed automatically. Meilisearch transcript search. 2 MCP
tools: search_transcripts, read_transcript. Visual enrichment interleaved
into video transcripts. Transcription settings section. Health check includes
Whisper availability.

**Planned:** External log shipping to Grafana Loki / ELK stack. The current local log
archive system is an interim solution — once external aggregation is in place, local
retention can be reduced and the archive scheduler retired.

For full version-by-version changelog, see [`docs/version-history.md`](docs/version-history.md).

---

## Phase Checklist

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Docker scaffold, project structure, DB schema, health check | Done |
| 1 | Foundation: DOCX → Markdown (DocumentModel, DocxHandler, metadata, upload UI) | Done |
| 2 | Round-trip: Markdown → DOCX with fidelity tiers | Done |
| 3 | OCR pipeline (multi-signal detection, review UI, unattended mode) | Done |
| 4 | Remaining formats: PDF, PPTX, XLSX/CSV (both directions) | Done |
| 4b | Universal format support: RTF, ODT/ODS/ODP, TXT, HTML, EPUB, EML/MSG, XML, Adobe, media indexing | Done |
| 5 | Testing & debug infrastructure (full test suite, structlog, debug dashboard) | Done |
| 6 | Full UI, batch progress, history page, settings, polish | Done |
| 7 | Bulk conversion, Adobe indexing, Meilisearch search, Cowork integration | Done |
| 8b | Visual enrichment: scene detection, keyframe extraction, AI frame descriptions | Done |
| 8c | Unknown & unrecognized file cataloging with MIME detection | Done |
| 9 | File lifecycle management, version tracking, DB health | Done |
| 10 | Auth layer, role guards, API keys, UnionCore integration contract | Done |
| 11 | Media transcription: Whisper + cloud fallback + caption ingest, transcript search | Done |

Phase 1 implementation instructions (historical): [`docs/phase-1-instructions.md`](docs/phase-1-instructions.md)

---

## Architecture Reminders

- **Per-machine paths via `.env`** — `docker-compose.yml` uses `${SOURCE_DIR}`, `${OUTPUT_DIR}`, `${DRIVE_C}`, `${DRIVE_D}` variables. Each machine gets its own `.env` (gitignored). See `.env.example` for the template.
- **No Pandoc** — library-level only
- **No SPA** — vanilla HTML + fetch calls
- **Fail gracefully** — one bad file never crashes a batch
- **Fidelity tiers**: Tier 1 = structure (guaranteed), Tier 2 = styles (sidecar), Tier 3 = original file patch
- **Content-hash keying** — sidecar JSON keyed by SHA-256 of normalized paragraph/table content
- **Format registry** — handlers register by extension, converter looks up by extension
- **Unified scanning** — no separate Adobe/convertible split; all formats go through same pipeline
- **Font recognition** — handlers extract font declarations in `extract_styles()` for Tier 2 reconstruction
- **Source files registry** — `source_files` table is the single source of truth for file-intrinsic data
  (path, size, lifecycle status). `bulk_files` links jobs to source files via `source_file_id`.
  Cross-job queries (admin stats, lifecycle, trash) use `source_files`. Per-job queries use `bulk_files`.
- **Folder drop** — Convert page accepts entire folders via drag-and-drop, auto-scans for valid formats

---

## Key Files

Full file reference table: [`docs/key-files.md`](docs/key-files.md)

Critical files to know:

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, lifespan, mounts all routers |
| `core/database.py` | Backward-compatible re-export wrapper for core/db/ |
| `core/db/` | Domain-split DB package: connection, schema, preferences, bulk, conversions, catalog, lifecycle, auth |
| `core/converter.py` | Pipeline orchestrator (single-file conversion) |
| `core/libreoffice_helper.py` | Shared LibreOffice headless conversion for legacy formats (.doc/.xls/.ppt) |
| `core/bulk_worker.py` | Worker pool: BulkJob, pause/resume/cancel, SSE |
| `core/auth.py` | JWT validation, role hierarchy, API key verification |
| `core/scheduler.py` | APScheduler: lifecycle scan, trash expiry, DB maintenance, log archive |
| `core/progress_tracker.py` | RollingWindowETA, ProgressSnapshot, format_eta for all job types |
| `core/log_archiver.py` | Compress rotated logs to gzip archives, purge old archives |
| `core/auto_converter.py` | Auto-conversion decision engine |
| `core/pipeline_startup.py` | Health-gated startup: waits for services, triggers initial scan+convert |
| `core/storage_probe.py` | Storage latency probe: auto-detects SSD/HDD/NAS for scan parallelism |
| `core/cloud_detector.py` | Platform-agnostic cloud placeholder detection (disk blocks + read latency) |
| `core/cloud_prefetch.py` | Background prefetch worker pool with rate limiting, adaptive timeouts |
| `formats/rtf_handler.py` | RTF ingest/export with control-word parser |
| `formats/html_handler.py` | HTML/HTM with BeautifulSoup, font extraction |
| `formats/odt_handler.py` | OpenDocument Text via odfpy |
| `formats/adobe_handler.py` | PSD/AI/INDD/AEP/PRPROJ/XD — unified Adobe handler |
| `formats/archive_handler.py` | ZIP/TAR/7z/RAR/CAB/ISO — recursive extraction + conversion |
| `core/archive_safety.py` | Zip-bomb protection: ratio, size, depth, quine checks |
| `formats/json_handler.py` | JSON ingest/export with summary + structure outline |
| `formats/yaml_handler.py` | YAML/YML with multi-document support |
| `formats/ini_handler.py` | INI/CFG/CONF/properties with section-aware parsing |
| `formats/image_handler.py` | Image file handler (.jpg, .png, .tif, .bmp, .gif, .eps) |
| `formats/audio_handler.py` | Audio file handler (.mp3, .wav, .flac, etc.) |
| `formats/media_handler.py` | Video file handler (.mp4, .mov, .mkv, etc.) |
| `core/media_probe.py` | ffprobe wrapper: codec detection, duration, transcode decision |
| `core/audio_extractor.py` | Extract audio from video, convert to Whisper-compatible WAV |
| `core/whisper_transcriber.py` | Local Whisper with GPU auto-detect, lazy model loading |
| `core/cloud_transcriber.py` | Cloud fallback: OpenAI Whisper API, Gemini audio |
| `core/transcription_engine.py` | Fallback orchestrator: caption → Whisper → cloud |
| `core/caption_ingestor.py` | SRT/VTT/SBV caption file parser |
| `core/transcript_formatter.py` | Output formatter: .md + .srt + .vtt generation |
| `core/media_orchestrator.py` | Top-level media conversion coordinator |
| `api/routes/media.py` | Media transcript API: get transcript, segments, download |
| `api/routes/pipeline.py` | Pipeline control: status, pause, resume, run-now |
| `api/routes/search.py` | Search API: unified search, autocomplete, source file serving, batch download |
| `core/flag_manager.py` | Flag business logic, blocklist checks, Meilisearch is_flagged sync, webhooks |
| `api/routes/flags.py` | Flag API: user flagging + admin triage (dismiss/extend/remove/blocklist) |
| `static/flagged.html` | Admin flagged files page with filters, sort, pagination |
| `static/viewer.html` | Document viewer: source/rendered/raw modes, in-document search, markdown rendering (marked.js + DOMPurify) |
| `static/job-detail.html` | Job detail page: summary header, stats, files/errors/info tabs with search and filtering |
| `static/app.js` | Shared JS: API helpers, dynamic nav, toast |
| `static/markflow.css` | Design system: CSS variables, dark mode |
| `Dockerfile.base` | Base image: all apt system deps (build once, ~25 min on HDD) |
| `Dockerfile` | App image: pip + code copy on top of markflow-base (~3-5 min) |
| `docker-compose.yml` | Port 8000, MCP 8001, Meilisearch 7700 |

---

## Gotchas & Fixes

Full list (~90 items organized by subsystem): [`docs/gotchas.md`](docs/gotchas.md)

**Most commonly needed:**

- **aiosqlite**: Always `async with aiosqlite.connect(path) as conn` — never `await` then `async with`
- **structlog**: Use `structlog.get_logger(__name__)` everywhere, never `logging.getLogger()`. Must `import structlog` in every file that calls it.
- **pdfminer logging suppressed**: All `pdfminer.*` loggers set to WARNING in `configure_logging()`. Without this, debug log grows 500+ MB per bulk job.
- **mistune v3**: Must pass `plugins=["table", "strikethrough", "footnotes"]` or tables silently vanish
- **DEV_BYPASS_AUTH=true** is the default — production must set to `false`
- **`python-jose` not `PyJWT`** — they conflict
- **Source share is read-only**: `/mnt/source` mounted `:ro`, never write to it
- **Lifecycle scanner needs a `bulk_jobs` parent row**: Creates synthetic job if none exists
- **Lifecycle scan yields to bulk jobs**: `run_lifecycle_scan()` checks `get_all_active_jobs()` and skips if any bulk job is scanning/running/paused. Prevents "database is locked" contention.
- **Pipeline has two pause layers**: `pipeline_enabled` (persistent DB preference, survives restarts) and `_pipeline_paused` (in-memory in `scheduler.py`, resets on restart). Scheduler checks both before lifecycle scans. "Run Now" bypasses both.
- **pipeline_max_files_per_run caps batch size**: Applied in `_execute_auto_conversion()`. Overrides auto-conversion engine's batch size decision (takes minimum). 0 = no cap.
- **Pipeline startup is health-gated**: `pipeline_startup.py` waits the configured delay then polls health checks. Critical services (DB, disk) must pass; preferred services (Meilisearch, Tesseract, LibreOffice) produce warnings but don't block. Max additional wait: 3 minutes of retries.
- **Pipeline watchdog auto-reset**: When pipeline is disabled, `_pipeline_watchdog()` in `scheduler.py` logs hourly WARNINGs and daily ERRORs. After `pipeline_auto_reset_days` (default 3), it auto-re-enables. `pipeline_disabled_at` preference tracks the timestamp.
- **Stop is cooperative**: Workers finish current file before stopping
- **Password handling**: Preprocessing step before `handler.ingest()`, not a handler change
- **MCP server is separate**: Port 8001, own process, no JWT auth (uses `MCP_AUTH_TOKEN`)
- **MCP server binding**: `FastMCP.run()` does NOT accept `host` or `port` kwargs. Use `uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port)` directly. Without this, Uvicorn defaults to 127.0.0.1:8000 which is unreachable from outside the Docker container.
- **MCP display URL**: Always use `localhost:{port}/sse` — never `socket.gethostbyname()` (returns Docker-internal IP) and never `/mcp` (wrong path, endpoint is `/sse`).
- **MCP health endpoint**: `FastMCP.sse_app()` has no `/health` route. Must append a Starlette `Route("/health", handler)` manually before passing to uvicorn.
- **Log files**: Never use bare `FileHandler` or `TimedRotatingFileHandler` — always `RotatingFileHandler` (size-based). Defaults: 50 MB main, 100 MB debug. Configurable via `LOG_MAX_SIZE_MB` / `DEBUG_LOG_MAX_SIZE_MB` env vars.
- **Log archives**: Rotated files are auto-compressed to `logs/archive/*.gz` every 6 hours. 90-day retention (configurable via `LOG_ARCHIVE_RETENTION_DAYS`). Interim solution — planned migration to Grafana Loki / ELK.
- **File downloads**: Never use `fetch()` + blob for file downloads — use `window.location.href` or `<a>` tags. Backend must set explicit `Content-Length` header.
- **Archive handler**: Follows EML handler pattern — `ingest()` produces a DocumentModel with summary + recursive inner content. Temp dirs cleaned in `finally` blocks. Max depth 20 (env: `ARCHIVE_MAX_DEPTH`).
- **Compound extensions**: `.tar.gz`, `.tar.bz2`, `.tar.xz` require compound extension lookup in both `formats/base.py` and `core/bulk_scanner.py`. `Path.suffix` only returns `.gz` — use `_get_compound_extension()` / `_get_effective_extension()`.
- **Archive passwords**: Full cracking cascade — known passwords, dictionary + mutations, brute-force. Uses same user preferences as PDF/Office handler (`password_brute_force_enabled`, `password_brute_force_charset`, `password_brute_force_max_length`, `password_timeout_seconds`). Successful passwords saved to `config/archive_passwords.txt` and reused session-wide. Never log actual passwords.
- **hashcat -I requires cwd**: hashcat resolves its `OpenCL/` kernel directory relative to the current working directory, not its binary location. Scripts must `cd` to hashcat's install dir before running `hashcat -I`, or it fails silently with `./OpenCL/: No such file or directory`.
- **PowerShell Set-Content BOM**: `Set-Content -Encoding UTF8` writes a UTF-8 BOM on Windows PowerShell 5.x. Python's `json.loads()` rejects this. Use `[IO.File]::WriteAllText()` for BOM-free output. Python readers should use `encoding="utf-8-sig"` defensively.
- **PowerShell stderr from native commands**: Native command stderr (e.g., hashcat's `nvmlDeviceGetFanSpeed(): Not Supported`) becomes a `RemoteException` via `2>&1`, caught by `try/catch` and silently aborting. Set `$ErrorActionPreference = 'SilentlyContinue'` around the call.
- **GPU health component needs ok/version**: The convert page renders health components generically using `s.ok` and `s.version`. The GPU component in `health.py` must include both fields or it renders as FAIL with blank detail.
- **Whisper model lazy-load**: Model is loaded on first transcription call, NOT at startup. Lazy import `import whisper` inside `_load_model()` to avoid slow lifespan. Model cached as class-level state.
- **Whisper torch CPU index**: `Dockerfile.base` installs torch from `--index-url https://download.pytorch.org/whl/cpu` to avoid pulling CUDA packages (~2GB savings). GPU containers should override this.
- **Transcription fallback chain**: caption file → local Whisper → cloud providers (in priority order). Caption files checked alongside media files using `caption_file_extensions` preference.
- **MediaHandler sync/async bridge**: `FormatHandler.ingest()` is synchronous but MediaOrchestrator is async. Handlers use `asyncio.run()` in a ThreadPoolExecutor when called from a running event loop.
- **Adaptive scan parallelism**: `storage_probe.py` probes sequential-vs-random stat() latency before each scan. Ratio > 3x = HDD (stay serial), ratio < 2x + high latency = NAS (go parallel). Never parallelize HDD — causes seek thrashing. Default preference `scan_max_threads` = `"auto"`.
- **Parallel scan architecture**: Thread workers walk subdirectories concurrently, push `(path, ext, size, mtime)` to `queue.Queue`. Single async consumer drains to SQLite. Both `BulkScanner` and lifecycle scanner use this pattern.
- **Scan throttler (backpressure)**: `ScanThrottler` in `storage_probe.py` monitors rolling stat() latency during parallel scans. Workers call `should_pause(worker_id)` — if congested, higher-ID workers sleep. Consumer calls `check_and_adjust()` every 500 files. 5-second cooldown prevents oscillation. Overhead is negligible (~0.001ms per stat call).
- **source_files vs bulk_files**: File-intrinsic data (path, size, hash, lifecycle) lives in `source_files`. Job-specific data (status, error_msg, converted_at) lives in `bulk_files`. Always update both when changing file-intrinsic fields. Cross-job queries must use `source_files` to avoid counting duplicates.
- **Error-rate abort**: `ErrorRateMonitor` in `storage_probe.py` tracks rolling success/failure. If >50% of last 100 ops fail or 20 consecutive errors, triggers abort. Used by both scanners (stat failures) and bulk worker (conversion failures). Protects against NAS disconnects mid-operation.
- **AD-credentialed folders**: All `os.walk()` calls in scanners and storage probe use `onerror` callbacks that log `scan_permission_denied` with an AD hint. Without this, permission-denied folders are silently skipped.
- **NTFS ADS filtering**: Files with `:` in the name (NTFS Alternate Data Streams) are skipped during scanning. These are metadata streams, not real files.
- **Search source_path DB fallback**: `search_indexer.py` looks up `source_path` from the `source_files` DB table when frontmatter doesn't contain it. Without this fallback, source file serving and batch download fail for older converted files.
- **AV quarantine FileNotFoundError**: Scanners catch `FileNotFoundError` from `os.stat()` — antivirus can quarantine a file between `os.walk()` discovering it and `stat()` reading it.
- **Multiple flags per file**: File stays hidden while ANY flag has `status` in (`active`, `extended`). `is_flagged` only set to `false` when the last active/extended flag resolves/expires.
- **Flag + index rebuild**: `search_indexer.py` checks `file_flags` during indexing and sets `is_flagged=true` for any file with an active/extended flag. Flag state survives re-indexing.
- **Blocklist dual-match**: Scanner checks both `content_hash` and `source_path` against `blocklisted_files`. A file can be blocklisted by hash (catches copies) or by path (catches re-appearances).
- **Flag routes ordering**: In `api/routes/flags.py`, fixed-path routes (`/mine`, `/stats`, `/blocklist`, `/lookup-source`) must be defined BEFORE `/{flag_id}` catch-all, or FastAPI matches the literal path segment as a flag_id.
- **`_is_excluded` must be a class method on BulkScanner**: Was a local function in `run_scan()` but referenced in `_walker_thread()` inside `_parallel_scan()`. Closures don't cross method boundaries — all worker threads crashed with `NameError`. Now `self._is_excluded()`.
- **Viewer markdown rendering**: Uses marked.js + DOMPurify (CDN). DOMPurify whitelist is explicit — no `script`, no event handlers. Raw view uses `textContent` only. In-document search uses `TreeWalker` to find text nodes.
- **Job detail `cancellation_reason`**: Migration #17 adds column. Populated by cancel(), error-rate abort, fatal exceptions, and orphan cleanup. Displayed as a banner on the job detail page.
- **Auto-converter backlog detection**: `on_scan_complete()` now checks `bulk_files WHERE status='pending'` when 0 new files found. Prevents orphaned pending files from failed jobs sitting forever. Only triggers if no active job is running.
- **Search empty query = browse all**: `/api/search/all` accepts `q=""`. Meilisearch returns all docs. Empty queries skip highlighting and sort by date. "Browse All" button on search page.
- **Per-job overrides**: `BulkJob.overrides` dict stores per-job settings. Scanner/converter should use `self.overrides.get(key)` with fallback to global preference.
- **`skip_reason` on bulk_files**: General-purpose column (migration #18) recording why a file was skipped. Set at every skip point: unchanged mtime, path safety, OCR threshold. The older `ocr_skipped_reason` is retained for OCR-specific queries. Path safety skips now properly mark status as `"skipped"` with counter increments (previously left as `"pending"` forever).

---

## Supported Formats (v0.13.9)

| Category | Extensions | Handler |
|----------|-----------|---------|
| Office | .docx, .doc, .docm, .pdf, .pptx, .ppt, .xlsx, .xls, .csv, .tsv | DocxHandler, PdfHandler, PptxHandler, XlsxHandler, CsvHandler |
| WordPerfect | .wpd | DocxHandler (via LibreOffice preprocessing) |
| Rich Text | .rtf | RtfHandler |
| OpenDocument | .odt, .ods, .odp | OdtHandler, OdsHandler, OdpHandler |
| Markdown & Text | .md, .txt, .log, .text | MarkdownHandler, TxtHandler |
| Web & Data | .html, .htm, .xml, .epub | HtmlHandler, XmlHandler, EpubHandler |
| Data & Config | .json, .yaml, .yml, .ini, .cfg, .conf, .properties | JsonHandler, YamlHandler, IniHandler |
| Email | .eml, .msg | EmlHandler (with recursive attachment conversion) |
| Archives | .zip, .tar, .tar.gz, .tgz, .tar.bz2, .7z, .rar, .cab, .iso | ArchiveHandler |
| Adobe | .psd, .ai, .indd, .aep, .prproj, .xd, .ait, .indt | AdobeHandler |
| Media (audio) | .mp3, .wav, .m4a, .flac, .ogg, .aac, .wma | AudioHandler |
| Media (video) | .mp4, .mov, .avi, .mkv, .webm, .m4v, .wmv | MediaHandler |
| Captions | .srt, .vtt, .sbv | CaptionIngestor (via AudioHandler) |
| Images | .jpg, .jpeg, .png, .tif, .tiff, .bmp, .gif, .eps | ImageHandler |

---

## Running the App

```bash
# First time only -- build the base image (slow, ~25 min HDD / ~5 min SSD):
docker build -f Dockerfile.base -t markflow-base:latest .

# Normal operation:
docker-compose up -d          # start
docker-compose logs -f        # watch logs
curl localhost:8000/api/health # verify
docker-compose down           # stop
```

After code changes: `docker-compose build && docker-compose up -d`
(Only rebuilds pip + code layer -- base image is cached.)
