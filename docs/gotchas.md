# MarkFlow Gotchas & Fixes Found

Hard-won lessons discovered during development. Read this file when working on
the relevant subsystem. Referenced from CLAUDE.md.

---

## Database & aiosqlite

- **aiosqlite pattern**: Use `async with aiosqlite.connect(path) as conn` — never
  `conn = await aiosqlite.connect(path)` then `async with conn` (starts the thread twice → RuntimeError).
  All DB helpers use `@asynccontextmanager` + `async with aiosqlite.connect()`.

- **source_files vs bulk_files**: File-intrinsic data (path, size, hash, lifecycle) lives in
  `source_files` (unique per source_path). Job-specific data (status, error_msg, converted_at)
  lives in `bulk_files` (linked via `source_file_id`). Always update both when changing
  file-intrinsic fields. Cross-job queries must use `source_files` to avoid counting duplicates.

- **DB path**: `DB_PATH` env var (default `markflow.db` locally, `/app/data/markflow.db` in container).
  The Docker volume `markflow-db` mounts to `/app/data`.

- **SQLite WAL mode**: Always enabled at connection time. `get_db()` in `database.py`
  sets `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=10000`. All code that opens
  DB connections should use `get_db()` or set these PRAGMAs manually.

- **DB compaction runs concurrently**: No scan-running guard. Uses `PRAGMA optimize` +
  `incremental_vacuum`, not full VACUUM (unless freelist > 25%). Safe in WAL mode.

- **DB repair acquires exclusive lock**: All in-flight requests will wait during a
  dump-and-restore repair. The repair endpoint checks `stop_controller.registered_tasks`
  and refuses to run if any tasks are active.

- **bulk_files table duplicates across jobs**: `upsert_bulk_file()` is keyed by
  `(job_id, source_path)`, so each new scan job inserts its own copy of every file.
  12,847 distinct files → 34K+ rows after 5 jobs. Per-job counts are accurate, but
  cross-job aggregation or total row count overcounts. Needs a dedup strategy or a
  separate global file registry.

## Logging

- **structlog + stdlib**: Call `configure_logging()` once at module level in `main.py` before
  the app is created. The formatter must be set on `logging.root.handlers`.

- **structlog + stdlib coexistence**: All `core/` and `formats/` modules must use
  `structlog.get_logger(__name__)`, not `logging.getLogger(__name__)`. The stdlib `logging`
  import is only allowed in `core/logging_config.py`.

- **structlog must be imported in every file that uses it**: If a module calls
  `structlog.get_logger()`, it must `import structlog` at the top. Missing import in
  `database.py` caused a startup crash loop (v0.12.3 fix — `cleanup_orphaned_jobs()`
  called `structlog.get_logger()` without the import, crashing the lifespan handler).

- **Noisy third-party loggers are suppressed**: `configure_logging()` sets WARNING level
  on `uvicorn.access`, `aiosqlite`, `PIL`, `weasyprint`, and all `pdfminer.*` loggers.
  pdfminer (used internally by pdfplumber) emits thousands of debug/info messages per PDF
  page — including "Cannot set non-stroke color: 5 components" warnings for spot-color PDFs.
  Without suppression, a single bulk job can inflate the debug log to 500+ MB.

- **Dual-file logging strategy**: `logs/markflow.log` (operational, always active)
  and `logs/markflow-debug.log` (debug trace, developer mode only). Both use
  `RotatingFileHandler` with size-based rotation. Operational: 50 MB / 5 backups,
  debug: 100 MB / 3 backups. Configurable via `LOG_MAX_SIZE_MB`, `DEBUG_LOG_MAX_SIZE_MB`,
  `LOG_BACKUP_COUNT`, `DEBUG_LOG_BACKUP_COUNT` env vars. Both write structlog JSON format.

- **Never use TimedRotatingFileHandler or bare FileHandler**: A single day's debug log
  can grow to 4 GB+. Always use size-based `RotatingFileHandler` to cap file growth.

- **Log archives preserve rotated content**: The `log_archiver` scheduler job (every 6h)
  compresses rotated `.log.N` files into `logs/archive/*.gz` (~10:1 compression).
  Archives retained for 90 days (configurable via `LOG_ARCHIVE_RETENTION_DAYS`).
  This is interim — planned migration to Grafana Loki / ELK for external aggregation.

- **`log_level` preference maps to handler levels, not root level**: The `LEVEL_MAP`
  maps "normal"→WARNING, "elevated"→INFO, "developer"→DEBUG.

- **Developer Mode toggle is UI-only**: The checkbox at the top of Settings sets both
  `log_level` and `auto_convert_decision_log_level` to `developer` or `normal`. It does NOT
  create a separate preference — it modifies the existing ones. Must still click Save.

- **`update_log_level()` is synchronous**: Safe to call from sync or async contexts.

- **`configure_logging()` is idempotent**: The `_configured` flag prevents double init.

- **Log file renamed from markflow.json to markflow.log**: v0.9.5 changed the extension.

- **Log file download is whitelist-only**: Only `markflow.log` or `markflow-debug.log` accepted.

- **Log download size guard**: Files over 500 MB (configurable via `LOG_DOWNLOAD_MAX_MB`)
  return HTTP 413. The explicit `Content-Length` header is required — without it, browsers
  can't track progress and may restart the download in a loop.

- **File downloads must use native browser download**: Never use `fetch()` + blob URL for
  file downloads — use `<a href="...">` or `window.location.href`. The `fetch` API can
  silently retry on timeout, causing infinite download loops on large files.

- **Client event endpoint never errors**: `POST /api/log/client-event` always returns 204.

- **Client event rate limit is per-IP in-memory**: Max 50 events/second per IP. Resets on restart.

## Format Handlers

- **Archive handler follows EML pattern**: `ingest()` extracts to a per-archive temp dir,
  recursively converts each inner file via the format registry, and returns a single
  `DocumentModel` with summary table + subsections. Temp dir is always cleaned in `finally`.

- **Compound extensions (.tar.gz etc.)**: `Path.suffix` returns only `.gz`. Both
  `formats/base.py:_get_compound_extension()` and `core/bulk_scanner.py:_get_effective_extension()`
  check the last two suffixes for registered compound forms. If adding new compound
  extensions, update both functions AND add to `SUPPORTED_EXTENSIONS` / `ALLOWED_EXTENSIONS`.

- **Archive zip-bomb protection**: `core/archive_safety.py` — ratio check (200:1 per entry),
  total size cap (50 GB default), entry count cap (100K), depth limit (20), quine detection.
  `ExtractionTracker` accumulates across the entire recursion chain.

- **Archive passwords**: Loaded from `config/archive_passwords.txt`. Empty string always tried
  first. Never log actual passwords — log the index. `.tar` and `.cab` are never encrypted.

- **py7zr + p7zip-full**: py7zr handles most .7z natively in Python. Some compression methods
  (LZMA2 with BCJ filter) need the system `7z` binary. Both are installed for coverage.

- **rarfile needs unrar**: `unrar-free` is installed in the Dockerfile. RAR5 format may need
  full `unrar` from non-free repos — `unrar-free` handles most cases.

- **Legacy Office format preprocessing**: `.doc`, `.xls`, `.ppt` files are converted to their
  modern equivalents (`.docx`, `.xlsx`, `.pptx`) via LibreOffice headless before ingestion.
  The shared helper is `core/libreoffice_helper.py:convert_with_libreoffice()`. Temp files
  are cleaned in `finally` blocks. Default timeout is 120s (legacy files can be slow).

- **mistune v3 table plugin**: `create_markdown(renderer=None)` does NOT parse tables by default.
  Must pass `plugins=["table", "strikethrough", "footnotes"]` or tables silently become paragraphs.

- **Sidecar hash mismatch**: `extract_styles()` keys by `para.text` (plain text), but
  `_process_paragraph` stores content with markdown markers (`**bold**`). Use `_plain_text_hash()`.

- **Tier 3 detection**: In `from_md` direction, converter looks for original `.docx` in the same
  directory as the `.md` file.

- **`FormatHandler.export()` signature**: `original_path: Path | None = None` was added in Phase 2.
  All handlers must accept it.

- **`MarkdownHandler.ingest()` takes a file Path**: Use `ingest(path)` not `ingest(text)`.
  For string input, use `ingest_text(md_string)`.

- **python-pptx `placeholder_format`**: Accessing `.placeholder_format` on non-placeholder
  shapes raises `ValueError`, not returns `None`. Must wrap in `try/except`.

- **pdfplumber text extraction**: Returns `\n`-separated lines, not `\n\n`-separated paragraphs.

- **PDF export via WeasyPrint**: Always Tier 1 or Tier 2 — no Tier 3 patching.

- **XLSX dual workbook open**: `data_only=True` for values, `data_only=False` for formulas.

- **XLSX merged cells**: Must unmerge and duplicate values before building TABLE element.

- **XLSX `MergedCell.value` is read-only**: Wrap in `try/except AttributeError` and skip.

- **CSV encoding detection**: Try `utf-8-sig` → `utf-8` → `latin-1` → `cp1252`.

- **fpdf2 `new_x`/`new_y` API**: v2.8+ uses `new_x="LMARGIN", new_y="NEXT"` not `ln=True`.

## OCR

- **OCR deskew is slow**: Keep page images < 1000 px wide in tests or use `OCRConfig(preprocess=False)`.

- **Tesseract `-1` confidence**: Clamped to `0.0` in `ocr_page()`. Rows with empty text are skipped.

- **Confidence pre-scan is an estimate**: Uses pdfplumber text density and Tesseract OSD, not full OCR.

- **OSD vs full OCR confidence scales differ**: OSD measures script/orientation, not text quality.

- **Auto-OCR gap-fill candidates**: PDF with `ocr_page_count IS NULL` and `status='success'`.

## API & Routes

- **review router route ordering**: `accept-all` POST must be registered before `{flag_id}` POST.

- **`/ocr-images` static mount**: Served from `OUTPUT_DIR`. Created at startup if missing.

- **OCR flag image paths**: Stored as forward-slash paths relative to CWD.

- **`/api/health` response envelope**: Check `data["components"]["database"]` not `data["database"]`.

- **SSE progress queues**: Module-level `dict[str, asyncio.Queue]`. Cleaned up after `done` event.

- **`GET /api/preferences` response envelope**: Returns `{"preferences": {...}, "schema": {...}}`.

- **History pagination**: `page`/`per_page` (Phase 6). Old `limit`/`offset` still accepted.

- **Preference validation**: Out-of-range returns 422. Read-only keys return 403.

- **Debug dashboard always mounted**: Not behind `DEBUG=true`.

- **Stats endpoint never returns 500**: All sub-queries wrapped in `_safe()` + `asyncio.gather`.

- **Disk usage endpoint is not auto-polled**: Manual Refresh only. Can take 5-10s on large repos.

## Bulk & Lifecycle

- **asyncio.Queue sentinel pattern**: Workers break on `None` sentinel. N sentinels for N workers.

- **Bulk SSE separate from single-file SSE**: `_bulk_progress_queues` vs `_progress_queues`.

- **Source share is read-only**: `/mnt/source` mounted `:ro`. Never write to it.

- **worker_id in SSE events**: 1-based in events (internal 0-based, +1 applied at emission).

- **active-workers-panel display:none by default**: Shown by JS after first `file_start` event.

- **truncatePath() trims from left**: Directory portion trimmed, filename always visible.

- **review_queue_count in bulk_jobs**: Total count, not pending. Use `get_review_queue_summary()`.

- **SSE done event deferred until review queue resolved**.

- **Permanently skipped files**: `ocr_skipped_reason = 'permanently_skipped'` excludes from future runs.

- **Unrecognized files are database-only**: No stub .md files, no Meilisearch entries.

- **`get_unprocessed_bulk_files()` excludes unrecognized**: Status must be reset to `pending` first.

- **Lifecycle scanner needs a `bulk_jobs` parent row**: Creates synthetic job if none exists.

- **Lifecycle scan state is in-memory**: `_scan_state` not persisted. Resets on container restart.

- **Lifecycle status column default**: Defaults to `'active'` so existing rows work.

- **Version numbers are per-file monotonic**: Never reset.

- **Scan run isolation**: Each scan gets a UUID. Errors caught per-file, scan continues.

- **Bulk scan pre-count capped at 10s**: Timeout → `total_estimate=0`, UI shows indeterminate bar.

- **Lifecycle scan FK error (2026-03-25)**: One-time boot issue, self-resolved. Six stuck scan_runs cleaned.

- **`dir_stats` tracks top-level directories only**: Prevents unbounded dict on deep repos.

- **`skip_reason` column on `bulk_files`**: General-purpose skip reason (migration #18). Set at every
  skip point: unchanged mtime (upsert), path safety (worker), OCR threshold (prescan). The older
  `ocr_skipped_reason` column is retained for OCR-specific queries but `skip_reason` is now the
  single column to check for any skip reason. Path safety skips now properly mark status as
  `"skipped"` with counter increments (previously left as `"pending"` forever).

## Path Safety & Collisions

- **Path safety pass runs during scan, not conversion**: Worker trusts resolved_paths.

- **resolve_collision() is deterministic**: Sort by `str(source_path)` ascending.

- **Case collision detection**: Only flags same-output-path pairs.

- **Renamed output paths use source extension**: `report.pdf.md` not `report_pdf.md`.

## Search & Meilisearch

- **Meilisearch primary key IDs**: Use `sha256(source_path)[:16]` hex. No slashes allowed.

- **Meilisearch graceful degradation**: Connection errors return safe defaults. Search returns 503.

- **httpx is a runtime dependency**: Moved from testing section in Phase 7.

- **source_path DB fallback in indexer**: `search_indexer.py` looks up `source_path` from the
  `source_files` DB table when the converted file's frontmatter doesn't contain it. This is
  needed for older converted files that predate the frontmatter change. Without the fallback,
  source file serving and batch download silently fail (no path to resolve).

- **Competing input handlers in search (fixed v0.15.0)**: The search page had both a debounced
  `input` handler and an autocomplete `input` handler on the same field, causing race conditions
  where typing triggered both a full search and an autocomplete request. Fixed by consolidating
  into a single handler that dispatches to the appropriate code path.

- **Filename search normalization**: `filename_search` is a shadow searchable field that
  normalizes filenames by splitting on `_`, `.`, `-`, camelCase boundaries, and letter/number
  transitions. Original `source_filename` is preserved for display. Both fields are in
  `searchableAttributes` so queries match either form. After adding this field, existing
  documents require an index rebuild (`POST /api/search/index/rebuild`) to populate it.

- **Extension stripping in normalizer**: `normalize_filename_for_search()` strips extensions
  by iterating `rsplit(".", 1)` from the right, stopping when the trailing segment is >5 chars
  or contains a space (not a real extension). This handles compound extensions like `.tar.gz`.

## Locations & Browse

- **Locations validate endpoint timeout**: `file_count_estimate` capped at 10s. Null is not an error.

- **Locations type filter includes 'both'**: `type=source` returns `source` AND `both`.

- **Locations nav decision**: NOT in main nav. Linked from Settings and bulk wizard only.

- **Browse API allowed roots**: Only `/host/*` and `/mnt/output-repo`. Others get 403.

- **Drive detection via env var**: `MOUNTED_DRIVES` env var (e.g. "c,d,e").

- **item_count can be null**: Permission errors or slow directories. Never treat as 0.

- **FolderPicker uses `<dialog>` element**: Requires Chrome 98+ / Firefox 98+.

- **Locations UX flagged for redesign**: Do NOT refactor until redesign spec written. Token: LOCATIONS_UX_REDESIGN.

## LLM & Vision

- **SECRET_KEY required for LLM providers**: Must be set if any provider configured.

- **MCP server is a separate process**: Port 8001, shares DB and filesystem.

- **Ollama OpenAI-compat endpoint**: Tries `/v1/chat/completions` first, falls back to `/api/generate`.

- **LLM enhancement is always opt-in**: All toggles default to false.

- **MCP tool docstrings are functional**: Claude.ai uses them for tool selection.

- **FastMCP no longer accepts `description` kwarg**: Pass server name as first positional arg only.

- **FastMCP.run() does not accept host/port kwargs**: Calling `mcp.run(transport="sse", host=..., port=...)`
  crashes with TypeError. Setting `UVICORN_HOST`/`UVICORN_PORT` env vars before `mcp.run()` is also
  ignored. The only working approach is to bypass `mcp.run()` entirely and call
  `uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port)` directly.

- **FastMCP.sse_app() has no /health route**: Must append one manually via
  `app.routes.append(Route("/health", handler))` before passing to `uvicorn.run()`.

- **MCP display URL must use localhost, not socket.gethostbyname()**: Inside a Docker container,
  `socket.gethostbyname(hostname)` returns the Docker bridge IP (172.20.x.x), unreachable from
  the host. Always use `localhost:{port}/sse`. The endpoint path is `/sse`, NOT `/mcp`.

- **VisionAdapter uses active LLM provider**: No separate provider system. One provider, two uses.

- **Vision preferences in existing system**: Stored in `user_preferences` via `_PREFERENCE_SCHEMA`.

- **SceneDetector always returns at least 1 scene**: Falls back to single full-video boundary.

- **KeyframeExtractor concurrency**: 4 ffmpeg, 3 API calls (separate semaphores).

- **scenedetect[opencv] pulls opencv-python-headless**: Don't install full opencv-python alongside.

## Auth & Security

- **`python-jose` not `PyJWT`**: They conflict. Don't install both.

- **`DEV_BYPASS_AUTH=true` is the default**: Production must set to `false`.

- **`/api/health` stays unauthenticated**: For healthchecks and monitoring.

- **MCP server auth is separate**: No JWT. Uses `MCP_AUTH_TOKEN` env var.

- **CORS + SSE limitation**: EventSource can't send Bearer tokens. SSE uses role minimum.

- **API key salt never rotates**: Rotating invalidates ALL hashes. No migration path.

- **API key raw value shown once**: Only the hash is persisted.

- **Preferences role split**: Base OPERATOR, system keys need MANAGER.

- **Root redirect**: `/` → `/search.html`.

- **Nav is dynamic**: `app.js::buildNav()` fetches `/api/auth/me` and filters nav items by role.

## Startup & Lifecycle

- **Orphan cleanup runs at startup**: `cleanup_orphaned_jobs()` in `core/database.py` cancels
  any bulk_jobs in scanning/running/pending and interrupts any scan_runs still in running state.
  Runs before the scheduler starts. This is why the stop banner doesn't stick after restarts.

- **Stop banner CSS**: `.stop-banner[hidden] { display: none !important; }` in markflow.css.
  JS uses `style.display` not `.hidden` attribute because CSS `display:flex` overrides `hidden`.

## Scanner & Mount Readiness

- **Source mount verification**: Both `BulkScanner.scan()` and `run_lifecycle_scan()` verify
  the source path is populated before scanning. An empty mountpoint (SMB not connected) aborts
  gracefully with status `failed`. Uses `os.scandir()` + `next()` to check for at least one entry.

- **AD-credentialed folders**: All `os.walk()` calls in `bulk_scanner.py`, `lifecycle_scanner.py`,
  and `storage_probe.py` use `onerror` callbacks that log `scan_permission_denied` with an AD hint
  (e.g., "check folder ACL or AD group membership"). Without this, PermissionError from
  domain-controlled folders is silently swallowed by `os.walk()` and the folder is just skipped.

- **NTFS Alternate Data Streams**: Files with `:` in the name (e.g., `file.txt:Zone.Identifier`)
  are NTFS ADS metadata, not real user files. Scanners filter these out to prevent downstream
  errors (the colon is illegal in most file operations outside NTFS).

- **AV quarantine race condition**: Antivirus can quarantine a file between `os.walk()` discovering
  it and the subsequent `os.stat()` call. Scanners catch `FileNotFoundError` from `stat()` and log
  it as `scan_file_quarantined` rather than crashing the scan.

- **Stale SMB connection retry**: On `OSError` during `os.walk()`, scanners log the error with a
  hint to check SMB connectivity. The error-rate monitor handles sustained failures via its
  existing abort threshold.

- **Multi-source scanning**: Both lifecycle scanner and `BulkJob` scan multiple source roots
  sequentially within a single run/job. Each root gets its own storage probe (mounts may differ).
  Counters, `seen_paths`, and error tracking accumulate across roots. If one root fails, the
  error is logged and the scan continues to the next root. `should_stop()` is checked between
  roots. This is NOT parallel — it's sequential, same queue, same DB pipeline.

- **Location exclusions (prefix match)**: Exclusion paths from `location_exclusions` table are
  loaded once at scan start (both bulk and lifecycle). Filtering happens at the `os.walk()` level:
  excluded directories are pruned from `dirnames[:]` so Python never descends into them. File-level
  checks are a safety net. The fast walk counter also respects exclusions. Exclusions are stored
  on `self._exclusion_paths` (bulk scanner) or passed as a parameter (lifecycle scanner).

- **`_is_excluded` must be a class method**: The exclusion check function was originally a local
  function inside `run_scan()`, but `_walker_thread` lives inside `_parallel_scan()` — a separate
  method. Python closures don't cross method boundaries, so all worker threads crashed with
  `NameError`. Fix: `_is_excluded` is now a method on `BulkScanner`, using `self._exclusion_paths`.
  The lifecycle scanner defines its own `_is_excluded` locally within each function that needs it
  (no cross-method issue there).

- **Adaptive scan parallelism**: `storage_probe.py` runs a ~200ms latency probe before each
  scan, measuring sequential vs random `stat()` times. The ratio discriminates storage types:
  ratio > 3x = spinning disk (stay serial), ratio < 2x + high latency = NAS (go parallel).
  This is load-invariant — a busy HDD still shows the seek penalty ratio even under contention.

- **Parallel scan architecture**: For NAS/SMB sources, multiple thread workers walk different
  subdirectories concurrently (hiding network latency), pushing `(path, ext, size, mtime)`
  tuples into a `queue.Queue`. A single async consumer drains the queue and writes to SQLite.
  SQLite is single-writer but local SSD writes are ~100x faster than NAS reads, so the
  consumer never falls behind.

- **scan_max_threads preference**: Defaults to `"auto"` (probe decides). Set to `"1"` to force
  serial. The probe result is capped by this value. Max hard cap: 12 threads.

- **Don't parallelize HDD scans**: Parallel `stat()` calls on a spinning disk cause seek
  thrashing — the read head bounces between locations instead of streaming sequentially.
  The storage probe detects this via the random/sequential latency ratio and stays serial.

- **Scan throttler (backpressure)**: `ScanThrottler` monitors rolling stat() latency during
  parallel scans. If NAS gets congested (latency > 3x baseline), higher-ID workers are parked
  via `should_pause(worker_id)`. When latency recovers below 1.5x baseline, workers are restored
  one at a time. 5-second cooldown prevents oscillation. Overhead is negligible — `record_latency()`
  is a deque append (~0.001ms), `should_pause()` is a lock-free int read.

- **Throttler cooldown matters**: Without the 5-second cooldown, the throttler could oscillate:
  shed threads → latency drops → restore threads → latency spikes → shed again. The cooldown
  lets the system stabilize after each adjustment before re-evaluating.

- **Error-rate abort (NAS disconnect protection)**: `ErrorRateMonitor` tracks rolling success/failure
  across scanners and workers. Triggers on >50% error rate in last 100 ops OR 20 consecutive errors.
  Once triggered, abort is sticky (idempotent) — prevents the scan from resuming in a broken state.
  Used by: bulk scanner serial/parallel, lifecycle scanner serial/parallel, bulk conversion workers.

- **Archive batch extraction**: `extractall()` is used by default — falls back to per-member if it fails.
  Batch is dramatically faster over NAS (one archive read vs N). The per-member functions are kept as
  fallback for corrupted archives or selective extraction.

- **Archive parallel conversion is CPU-bound**: Inner files are extracted to local temp dir first, so
  conversion threads are CPU-bound (parsing), not I/O-bound. Thread count is `min(file_count, cpu_count, 8)`.
  Don't increase above CPU count — it just adds context-switch overhead.

- **Archive error-rate abort cleans up**: If `ErrorRateMonitor` triggers mid-archive (NAS disconnect),
  the `finally` block still runs — temp dir is always removed. The model returned contains whatever
  was converted before the abort, plus an `[ABORTED]` summary line.

- **Nested archives are always sequential**: Recursive depth tracking via `ExtractionTracker` is not
  thread-safe (quine detection, total size cap). Nested archives go through the serial path even when
  regular files are parallelized.

- **Cloud transcriber error monitor is session-scoped**: `_cloud_error_monitor` is a module-level
  singleton in `cloud_transcriber.py`. Once it triggers (60% failure rate in last 20 calls), ALL
  subsequent cloud transcription calls fast-fail without attempting the API. This is intentional —
  if the API key is expired or the service is down, retrying per-file is wasteful.

- **Password cracking error monitor uses 95% threshold**: Wrong-password exceptions are expected
  (most attempts fail). The monitor only detects I/O errors (OSError/IOError = file unreadable)
  vs password errors (other exceptions). This prevents false abort from normal cracking behavior.

- **EML/MSG monitors are per-email**: Each email gets a fresh ErrorRateMonitor because attachments
  are self-contained. One email with corrupted attachments shouldn't affect the next email.

- **Bulk worker error-rate abort cancels the job**: When the error monitor triggers in a bulk worker,
  it sets `_cancel_event` which causes all workers to drain their queues and stop. The job is marked
  as cancelled, not failed — this is intentional because the files themselves aren't broken, the
  source just became unreachable. Re-running the job after mount recovery will pick up where it left off.

- **Static file cache headers**: Middleware in `main.py` adds `Cache-Control: no-cache, must-revalidate`
  to all `/static/` responses. Prevents stale JS/CSS after deploys.

## Scheduler & Metrics

- **Lifecycle scan yields to bulk jobs**: `run_lifecycle_scan()` checks
  `get_all_active_jobs()` and skips if any bulk job is scanning/running/paused.
  Bulk jobs hold the DB heavily — running both concurrently causes "database is locked"
  errors. The deferred conversion runner also inherits this guard since it calls
  `run_lifecycle_scan()` internally.

- **collect_metrics interval**: 120s with `coalesce=True`, `misfire_grace_time=60`.
  Do not reduce below 60s — causes massive skip storms under bulk load.

- **collect_metrics timeout**: Wrapped in `asyncio.wait_for(timeout=30)` to prevent
  indefinite blocking when SQLite is locked during heavy writes.

- **structlog event arg**: First positional arg IS the event. Never also pass `event=`
  as kwarg. Use `msg=` for human-readable descriptions.

- **Log download**: Uses `FileResponse` + `<a href=...>` tags, NOT fetch+blob.
  The fetch+blob pattern causes download loops on large files.

## Scheduler & Stop Controls

- **APScheduler lifespan pattern**: Start in `lifespan()`, stop in yield cleanup.
  Don't use `@app.on_event("startup")`.

- **Scheduler business hours check is sync**: Uses default hours without async DB lookups.

- **Stop is cooperative, not instant**: Workers finish current file before stopping.

- **`reset_stop()` must be called before starting new jobs**: `POST /api/bulk/jobs` calls it automatically.

- **`active-jobs-panel.js` is deleted**: Replaced by `/status.html` in v0.9.4.

- **`global-status-bar.js` is badge-only**: Only exports `initStatusBadge()`. Loaded by `app.js`.

- **Status nav link visible to all roles**: Uses `minRole: "search_user"`.

## Admin & Resources

- **`psutil.cpu_affinity()` not available on macOS Docker**: Returns False, logs warning.

- **`psutil.cpu_percent(interval=None)` requires priming**: Call with `interval=0.1` at startup.

- **CPU percent can exceed 100%**: 100% = one core. Y-axis max = `cpu_count * 100`.

- **I/O counters are cumulative**: Compute deltas between adjacent samples.

- **Resources page is MANAGER role, not ADMIN**.

- **Repository Overview is duplicated**: Appears on both admin and resources pages.

- **Task Manager moved to Resources page**: Admin shows link card.

- **Metrics collector samples every 30 seconds**: `max_instances=1` prevents stacking.

- **Disk snapshots every 6 hours**: Immediate snapshot at startup.

- **Metrics retention is 90 days**: Purge runs daily at 03:00.

- **Activity events are fire-and-forget**: Never disrupts the recorded operation.

- **Summary endpoint computes p95 in Python**: SQLite lacks PERCENTILE_CONT.

- **`idle_baseline_percent`**: Computed from samples where all task counters are zero.

- **Chart.js loaded from CDN**: Bundle in `static/vendor/` as fallback.

- **Trash is subtracted from output-repo total**: `.trash/` excluded to avoid double-counting.

- **Trash path mirrors output-repo structure**: Files keep their relative path.

## Password & GPU

- **Password handling is a converter preprocessing step**: Runs before `handler.ingest()`.

- **Two distinct protection layers**: Restrictions (stripped instantly) vs encryption (needs password).

- **pikepdf opens owner-password PDFs without any password**.

- **msoffcrypto OfficeFile detection order**: Call `is_encrypted()` first.

- **Found passwords are in-memory only**: Never written to disk or database.

- **msoffcrypto encrypt vs decrypt**: Don't confuse them in test fixtures.

- **`john` is optional**: Silently skipped if not installed.

- **Brute-force is disabled by default**: `password_brute_force_enabled` defaults to `"false"`.

- **Temp file cleanup**: System temp dir via `tempfile.mkstemp()`. Cleaned after conversion.

- **OOXML restriction stripping rewrites the ZIP**: Preserves content, modifies XML whitespace.

- **`password_locked` status**: Distinct from `'error'` for UI differentiation.

- **GPU passthrough requires NVIDIA Container Toolkit**: Without overlay, `detect_gpu()` returns False.

- **AMD/Intel GPUs need the host worker**: Docker on WSL2 can't pass them through.

- **Host worker capabilities**: Cached at startup, re-read live on health check.

- **hashcat --force required in Docker**.

- **hashcat potfile conflicts**: Each attack uses unique temp potfile.

- **Host worker queue is fire-and-forget**: Jobs accumulate if worker not running.

## Cloud Prefetch

- **Cloud prefetch is purely additive**: Disabling `cloud_prefetch_enabled` changes nothing about
  existing behavior. The wait in `converter.py` short-circuits immediately when prefetch is off.
  No conversion logic or file-handling paths are altered.

- **Prefetch state is ephemeral**: The queue and worker pool are in-memory only. Container restart
  clears all state. The next lifecycle or bulk scan re-enqueues any remaining placeholders
  automatically — no manual recovery needed.

- **Rate limit tokens refill per minute, not per second**: `PrefetchManager` uses a token-bucket
  with a per-minute refill interval. Bursty traffic is expected at startup when many placeholders
  are discovered at once; the bucket smooths sustained throughput over time, not within a single
  second.

- **`st_blocks` check may not detect all placeholders on all mount types**: On most FUSE-based
  cloud mounts (OneDrive, Google Drive, Nextcloud), `st_blocks == 0` reliably identifies
  placeholders. Some mount types do not populate `st_blocks` correctly. Set
  `cloud_prefetch_probe_all = true` to force the timed read-latency probe on every file, or use it
  as a diagnostic when placeholder detection seems unreliable.

- **Inline prefetch in converter runs when file wasn't in the queue**: If a file reaches
  `converter.py` without having been pre-queued (single-file upload, file discovered after queue
  drain), the converter performs an inline prefetch that blocks the conversion worker. This is
  correct behavior — never a failure — but it is slower than pre-queued prefetch. Pre-queued
  prefetch is always preferred because it runs concurrently with the scan.

- **HASHCAT_QUEUE_DIR must be a bind mount**: Not a named volume.

- **hashcat exit codes**: 0=cracked, 1=exhausted. Check output file, not exit code.

- **docker-compose.gpu.yml is an overlay**: Use with `-f` flag.

- **Host paths are per-machine via `.env`**: `docker-compose.yml` uses `${SOURCE_DIR}`,
  `${OUTPUT_DIR}`, `${DRIVE_C}`, `${DRIVE_D}`. Each machine gets its own `.env` (gitignored).
  See `.env.example` for the template. Never hardcode host paths in the compose file.

- **macOS `.env` must set `DRIVE_C`/`DRIVE_D`**: Defaults are `C:/` and `D:/` (Windows).
  On macOS, Docker fails with `invalid volume specification: 'C:/:/host/c:ro'`. Set
  `DRIVE_C=/Users/yourname` and `DRIVE_D=/Users/yourname/Documents` (or any valid path).
  The `Scripts/macos/reset-markflow.sh` handles this automatically.

- **No OpenCL on Apple Silicon**: Metal backend only for ARM Macs.

- **Rosetta hashcat has no Metal**: Must be native arm64 binary.

- **Apple Silicon thermal throttling is normal**: 500→200 MH/s expected.

- **`system_profiler` is slow (1-3s)**: Called once at startup, cached.

- **hashcat `-w 4` causes thermal shutdown on fanless Macs**: Default to `-w 2`.

## Help Wiki

- **Help articles are cached in-memory**: Container restart needed to see edits.

- **mistune rendering must include table plugin**.

- **Help routes bypass auth**: Intentionally public.

- **data-help attributes are passive**: Don't break if article doesn't exist.

- **help-link.js is idempotent**: Safe to call after dynamic content loads.

- **Article slugs are validated**: Only lowercase alphanumeric + hyphens. Path traversal blocked.

## Auto-Conversion

- **Default is `immediate` mode with 10 workers**: Fresh deployments auto-scan and auto-convert.
  Existing installs keep their saved preferences — only a DB reset applies new defaults.

- **Auto-conversion mode override is ephemeral**: Resets on container restart.

- **Auto-conversion creates real bulk jobs**: `auto_triggered=1` in `bulk_jobs`.

- **`max_files` on BulkJob is cooperative**: Worker checks after each file.

- **`auto_metrics` is separate from `system_metrics`**: Hourly aggregates vs raw 30s samples.

- **Hourly aggregation runs at :05**: 5-minute offset ensures last sample is in DB.

- **`psutil.getloadavg()` not available on all platforms**: Falls back to zeros.

- **Conservatism factor stacks during business hours**: 0.7 * 0.7 = 0.49 effective.

- **Deferred conversion runner re-triggers lifecycle scan**: Re-evaluates decision with fresh data.

- **Pipeline has two pause layers**: `pipeline_enabled` is a persistent DB preference (survives restarts). `_pipeline_paused` is in-memory state in `scheduler.py` (resets on container restart). The scheduler checks both before running lifecycle scans. "Run Now" bypasses both via `force=True`.

- **pipeline_max_files_per_run caps batch size**: Applied in `_execute_auto_conversion()` in `lifecycle_scanner.py`. If set to a positive number, it overrides the auto-conversion engine's batch size decision (takes the minimum). 0 = no cap.

- **Pipeline startup is health-gated**: `core/pipeline_startup.py` replaces the old immediate
  force-scan at boot. After the configured `pipeline_startup_delay_minutes` delay (default 5 min),
  it polls health checks. Critical services (DB, disk) must pass; preferred services (Meilisearch,
  Tesseract, LibreOffice) produce warnings but do not block the first scan. Max additional retry
  window: 3 minutes. If critical services never pass, the startup task logs an ERROR and aborts
  without triggering a scan.

- **Pipeline watchdog auto-reset**: When the pipeline is disabled, `_pipeline_watchdog()` in
  `scheduler.py` runs hourly. It logs WARN every hour and ERROR every 24h. After
  `pipeline_auto_reset_days` days (default 3), it auto-re-enables the pipeline and clears the
  `pipeline_disabled_at` preference. This is a self-healing safeguard — operators don't need to
  remember to re-enable after maintenance. `pipeline_disabled_at` is set whenever the pipeline is
  disabled and read by the watchdog to compute the reset deadline.

## Container & Dependencies

- **Debian trixie package name**: `libgdk-pixbuf-2.0-0` (not `libgdk-pixbuf2.0-0`).

- **No Pico CSS**: All pages use `markflow.css`. Dark mode via `@media (prefers-color-scheme: dark)`.

- **`review.html` and `debug.html` excluded from nav**: Have their own headers.

- **`psd-tools` layer traversal**: Must recurse into groups. `layer.kind == "type"` for text.

- **exiftool subprocess timeout**: 30s timeout. Returns `{"_error": "exiftool timeout"}`.

- **python-magic requires libmagic1**: Both must be installed.

- **MIME detection fallback chain**: libmagic → extension heuristic → `application/octet-stream`.

- **`psutil.getloadavg()` not on all platforms**: Catch `AttributeError`.

- **`GET /api/scanner/progress` uses `SEARCH_USER` role**: Lighter than `/api/scanner/status`.

## Data Format Handlers

- **YAML `safe_load` only**: Never use `yaml.load()` — it allows arbitrary code execution.
  Always `yaml.safe_load()` or `yaml.safe_load_all()` for multi-document files.

- **INI `interpolation=None`**: ConfigParser interpolation causes `%` chars in values to
  raise errors. Always disable interpolation for raw config file reading.

- **`.conf` is ambiguous**: Many apps use `.conf` for non-INI formats (nginx, Apache, systemd).
  IniHandler detects this and falls back to plain text. Don't add special-case parsers for
  specific config formats — that's an infinite rabbit hole.

- **Secret redaction is best-effort**: The key-name heuristic catches common patterns but
  won't catch `db_pw` or `cred_str`. That's acceptable — the original file is accessible
  anyway. The redaction is a courtesy in the searchable summary, not a security boundary.

## Email Attachments

- **Recursion depth limit is 3**: Prevents infinite loops from circular email references.
  If you see "depth limit reached" in logs, it's working correctly — don't increase the limit.

- **Attachment conversion uses format registry**: If a new handler is added later (e.g.,
  for .zip or .rar), email attachments of that type will automatically start converting.
  No changes to EmlHandler needed.

- **MSG library attachments**: The `olefile` library exposes MSG attachments differently than
  stdlib `email`. Both code paths handle attachment conversion — check both when modifying.

## Media & Transcription

- **Whisper model is lazy-loaded**: Model loaded on first transcription call, not at startup. Uses `import whisper` inside `_load_model()` to avoid slow lifespan. Cached as class-level state — reloaded only if model name or device changes.
- **torch CPU index in Dockerfile.base**: `pip install torch --index-url https://download.pytorch.org/whl/cpu` avoids pulling CUDA packages (~2GB savings). GPU containers should override with the CUDA index.
- **Transcription fallback chain order**: caption file → local Whisper → cloud providers. Each step tried in order; first success wins. Cloud tries ALL configured providers in priority order (active first).
- **Anthropic has no audio support**: `AUDIO_CAPABLE_PROVIDERS` map skips Anthropic. Only OpenAI (Whisper API) and Gemini (inline audio) are attempted for cloud fallback.
- **MediaHandler sync/async bridge**: `FormatHandler.ingest()` is synchronous but `MediaOrchestrator` is async. Handlers use `asyncio.run()` inside a `ThreadPoolExecutor` when called from a running event loop (bulk worker context).
- **Caption file encodings**: Try UTF-8-BOM → UTF-8 → latin-1 → cp1252 (same chain as CSV handler). Windows caption tools often produce latin-1.
- **SRT HTML tags**: Some SRT files contain `<i>`, `<b>` tags. `CaptionIngestor._parse_srt()` strips all HTML tags via regex.
- **Album art in ffprobe**: Video streams with `disposition.attached_pic == 1` (album art) are ignored by `MediaProbe`. Without this check, MP3 files with cover art are misclassified as video.
- **ffprobe frame_rate is a fraction**: `r_frame_rate` from ffprobe is a string fraction like "30000/1001". Must parse as division, not float().
- **Whisper device preference "auto"**: Resolves via `torch.cuda.is_available()` at runtime. Requesting "cuda" when CUDA is unavailable gracefully falls back to "cpu" with a warning log.
- **Transcript segments stored in DB**: `transcript_segments` table stores individual timestamped segments for API access. The full `.md` file is the authoritative source for the formatted transcript.
- **Three output files**: Every media conversion produces `.md` + `.srt` + `.vtt`. The `.srt` and `.vtt` paths are stored in `conversion_history.media_caption_path` and `media_vtt_path`.
- **Meilisearch transcripts index**: Separate from `documents` index. `raw_text` is the full transcript content (searchable). Search API accepts `?index=transcripts`.

## File Flagging

- **Multiple flags per file**: A file stays hidden from search/download while ANY flag has `status`
  in (`active`, `extended`). The `is_flagged` Meilisearch attribute is only set to `false` when the
  last active/extended flag is resolved or expires. Always check for remaining active flags before
  clearing `is_flagged`.

- **Flag + index rebuild**: `search_indexer.py` checks the `file_flags` table during indexing and
  sets `is_flagged=true` for any file with an active or extended flag. This ensures flag state
  survives a full Meilisearch index rebuild. Without this check, rebuilding indexes would silently
  un-flag all files.

- **Blocklist dual-match**: The scanner checks both `content_hash` and `source_path` against the
  `blocklisted_files` table. A file can be blocklisted by hash (catches copies moved to new
  locations) or by path (catches files that reappear at the same location). Either match causes
  the file to be skipped during scanning.

- **Flag routes ordering**: In `api/routes/flags.py`, fixed-path routes (`/mine`, `/stats`,
  `/blocklist`, `/lookup-source`) must be defined BEFORE the `/{flag_id}` catch-all route, or
  FastAPI matches the literal path segment (e.g., "mine") as a flag_id parameter. This is a
  standard FastAPI routing gotcha but easy to break when adding new endpoints.

---

## Viewer & Job Detail

- **Viewer markdown rendering**: `viewer.html` uses marked.js + DOMPurify for safe markdown
  rendering. DOMPurify whitelist is explicit — only structural/formatting tags allowed, no `img`
  `src` or `script`. The Raw view uses `textContent` (no HTML parsing). The search highlight
  system uses `TreeWalker` to find text nodes and wraps matches in `<span>` elements.

- **Search preview also renders markdown**: `search.html` preview popup loads marked.js +
  DOMPurify and renders the first 5000 chars of markdown. Same DOMPurify whitelist as viewer.

- **Preview popup `pointer-events`**: The popup uses `pointer-events: auto` (not `none`) so
  users can interact with it (scroll, click "Open" link). A `previewMouseOnPopup` flag prevents
  the row's `mouseleave` from hiding the popup when the mouse moves onto it. 300ms grace period
  bridges the gap between leaving the row and entering the popup.

- **Preview auto-dodge idle timer**: After 2s of no `mousemove` on the popup, it applies a
  `.dodged` class (`transform: translateY(120vh)`) to slide offscreen. `mouseenter` and
  `mousemove` on the popup remove `.dodged` and restart the idle timer. The dodge is visual
  only — DOM content stays loaded.

- **Job detail `cancellation_reason` column**: Added via migration #17. Populated by:
  user cancel ("Cancelled by user"), error-rate abort ("Aborted: error rate X%..."),
  fatal exceptions ("Fatal error: ..."), and orphan cleanup ("Cancelled: container restarted...").
  The `cancel()` method on `BulkJob` accepts an optional `reason` parameter.

- **Job detail page auto-serves**: The catch-all `/{page_name}.html` route in `main.py`
  (line 322) serves any `.html` file from `static/`. No registration needed for new pages.

- **Auto-converter only triggered on new/modified files**: The auto-converter's
  `on_scan_complete()` checked `new_files + modified_files == 0` and returned immediately.
  If a prior bulk job failed mid-scan, pending files were orphaned forever. Fixed: now checks
  `bulk_files WHERE status='pending'` as a backlog count and triggers conversion if >0 and no
  active job. This also prevents double-triggering (checks `get_all_active_jobs()` first).

- **Search empty query = browse all**: Meilisearch natively supports empty-string queries
  (returns all documents). The `/api/search/all` endpoint's `q` parameter changed from
  `min_length=2` to `min_length=0`. Empty queries skip highlighting and default to sort-by-date.

- **Per-job overrides are optional**: `CreateBulkJobRequest` has nullable override fields.
  Only non-None values are included in the `job_overrides` dict passed to `BulkJob`. The
  `overrides` dict defaults to `{}`. Scanner/converter code should check `self.overrides.get(key)`
  with a fallback to the global preference.
