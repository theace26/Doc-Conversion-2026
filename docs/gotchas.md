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

- **bulk_files table duplicates across jobs (mitigated v0.22.7)**:
  `upsert_bulk_file()` is keyed by `(job_id, source_path)`, so each new scan job
  inserts its own copy of every file. After ~10 jobs, 12,847 distinct files
  balloon to 120K+ rows and the pipeline status badge reports inflated pending
  counts (observed: 325,186 pending for 34,814 unique files). The single source
  of truth for unique files is `source_files`, NOT `bulk_files`.
  - **Mitigation (v0.22.7):** A scheduled job `bulk_files_self_correction`
    runs every 6 hours and prunes phantom rows (source_path no longer in
    source_files), purged rows (lifecycle_status='purged'), and cross-job
    duplicates (keeps only the latest job's row per source_path). Active jobs
    are excluded from cleanup. Manual trigger:
    `POST /api/admin/cleanup-bulk-files`.
  - The underlying schema is unchanged — bulk_files is still per-job by design.
    For per-job counts, query `WHERE job_id=?` (always accurate). For total
    pending across the repo, query `source_files` and JOIN to the latest
    bulk_files row, NOT `SELECT COUNT(*) FROM bulk_files`.

- **bulk_files upsert must be atomic (v0.18.1)**: `upsert_bulk_file()` now uses
  `INSERT ... ON CONFLICT DO UPDATE` instead of SELECT-then-INSERT. The old pattern
  caused `UNIQUE constraint failed` errors on rescans (race between check and insert).
  This blocked lifecycle scans from completing and prevented auto-conversion from
  ever triggering. Do NOT revert to the SELECT-then-INSERT pattern.

- **Conversion is decoupled from scan completion (v0.19.0)**: The backlog poller
  in `_run_deferred_conversions` starts conversion batches independently of the
  lifecycle scanner. Do NOT re-introduce a dependency where conversion requires
  `on_scan_complete()` — on large NAS mounts, scans may never finish in one interval.

- **Fast NAS misclassified as SSD (v0.19.0)**: `storage_probe.py` checks filesystem
  type to distinguish local SSD from fast network mounts. Without this, fast NAS
  (2.5/10GbE) gets 1 thread instead of 4 because latency looks like local SSD.

- **Preferences table name is `user_preferences` (v0.19.6.4)**: Raw SQL must reference
  `user_preferences`, not `preferences`. The v0.19.5 incremental scan counter functions
  used the wrong name, crashing all scans. Always use the DB helper layer in
  `core/db/preferences.py` when possible; if writing raw SQL, double-check the table name.

- **DB contention logging is TEMPORARY (v0.19.6.5)**: `core/db/contention_logger.py`
  adds three dedicated log files (`db-contention.log`, `db-queries.log`, `db-active.log`)
  with instrumentation in `core/db/connection.py`. These logs are high-volume during
  scans (every DB call is logged). **Deactivate once "database is locked" errors are
  diagnosed and fixed** — remove the module, undo the imports and instrumentation in
  `connection.py`, and restore the original lean functions.

- **Batch upsert fallback (v0.19.3)**: `upsert_bulk_files_batch()` in `core/db/bulk.py`
  wraps each batch of 200 files in a single transaction. If the batch write fails
  (e.g., lock contention, unexpected schema error), it catches the exception, logs
  `batch_upsert_fallback`, and retries every file in the batch individually via the
  original `upsert_bulk_file()`. This ensures correctness at the cost of speed
  — do NOT silently swallow the fallback log event, it indicates a transaction problem
  worth investigating.

- **Concurrent bulk jobs deadlock SQLite (v0.19.1)**: Two code paths can create
  bulk jobs: the backlog poller (`scheduler.py:_run_deferred_conversions`) and
  the lifecycle scan auto-trigger (`lifecycle_scanner.py:_execute_auto_conversion`).
  Both must check for active jobs before creating new ones. The in-memory
  `get_all_active_jobs()` must correctly report `"scanning"` status (not `"done"`)
  during the scan phase — use the `_scanning` flag on `BulkJob`. The backlog poller
  also double-checks the DB as a fallback since in-memory state can be stale.

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

- **Pipeline files UNION query must wrap in subquery (v0.19.6)**: `GET /api/pipeline/files`
  uses multi-table UNION queries across `source_files`, `bulk_files`, and `analysis_queue`.
  Column names (e.g., `status`, `source_path`) are ambiguous when referenced in ORDER BY
  or outer WHERE clauses after a UNION. Fix: wrap the entire UNION in a subquery
  (`SELECT * FROM (... UNION ...) AS sub ORDER BY ...`). Without this, SQLite raises
  "ambiguous column name" errors → HTTP 500.

- **HTML files must use HTML entities, not JS unicode escapes (v0.19.6)**: JavaScript
  `\u2190` (←), `\u2014` (—) etc. are only valid inside `<script>` blocks. In HTML
  attribute values, `href`, `title`, or anywhere outside a script tag, they render as
  literal backslash-u sequences. Use HTML entities instead: `&larr;`, `&mdash;`,
  `&rarr;`, `&times;`, etc.

- **Provider verify auto-requeues failed analysis items (v0.19.6)**: After a successful
  `POST /api/llm-providers/{id}/verify`, all `analysis_queue` rows with `status='failed'`
  are reset to `status='pending'` with `retry_count=0`. The API response includes a
  `requeued_analysis` count. This handles providers that were misconfigured when images
  were first processed — they re-enter the queue automatically without manual intervention.

- **`API.delete` is invalid JS — use `API.del` (v0.19.6)**: `delete` is a JavaScript
  reserved word. It cannot be used as a method name in dot-notation calls like
  `API.delete(url)`. The shared `app.js` API helper exposes the method as `API.del`.
  Using `API.delete` silently fails (no call is made, no error thrown in some browsers).

- **Pipeline files "indexed" status uses Meilisearch, not SQLite (v0.19.4)**:
  `GET /api/pipeline/files` handles all statuses via UNION queries on `source_files`
  and `bulk_files` — except `indexed`, which is resolved by browsing the Meilisearch
  `documents` index via `_browse_search_index()`. This means `indexed` results will
  be missing if Meilisearch is unreachable; the endpoint returns an empty list for
  that status (not an error). Do NOT attempt to back-fill `indexed` from SQLite —
  there is no `status='indexed'` in `bulk_files`; indexed state lives only in Meilisearch.

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

- **`~$*` Office lock files MUST be filtered at scan time (v0.22.19)**:
  Microsoft Office (Word/Excel/PowerPoint/Visio) creates a hidden ~162-byte
  sentinel file with the same name prefixed by `~$` whenever a document is
  opened, e.g. `~$report.docx`. Office cleans them up on close — but they
  linger forever if Office crashes or the file is on a network share that
  briefly disconnects. Pre-v0.22.19 the bulk scanner picked them up
  (valid `.doc`/`.docx`/`.xlsx` extensions), queued them in `bulk_files`,
  and a worker shipped them to LibreOffice, which correctly exited
  non-zero. The pre-v0.22.18 helper then raised a misleading
  `"LibreOffice not found"` error — sending users on a wild goose chase
  for a Dockerfile bug that didn't exist (`libreoffice-writer` and
  `libreoffice-impress` are correctly installed in `Dockerfile.base`).
  Fix: `core/bulk_scanner.is_junk_filename()` filters them at scan time
  alongside `Thumbs.db`, `desktop.ini`, `.DS_Store`, `~WRL*.tmp`. Wired
  into `BulkScanner._is_excluded()` AND both `_is_excluded` closures in
  `core/lifecycle_scanner.py` (serial walk + parallel walk). Rule of
  thumb: any file whose basename starts with `~$` is Office bookkeeping,
  never user data — trust the prefix and skip without inspecting contents.

- **Lifecycle scanner cancel-checks must run between INDIVIDUAL files, not
  just between directories or batches (v0.22.18)**: Pre-v0.22.18, the
  scheduler-level "skip if a bulk job is active" guard fired only at scan
  *kickoff* (`scheduler.py` lines 96-100). Once a 45-min lifecycle scan was
  running, a bulk job starting on minute 2 would call `cancel_lifecycle_scan()`
  via the scan_coordinator, but the serial walk only re-checked
  `_should_cancel()` at the directory boundary and the parallel walk only at
  the batch boundary (up to 500 files). A 10k-file folder kept writing for
  several minutes after cancellation, colliding with the bulk job's writes
  and producing ~1,929 `lifecycle_scan.file_error` "database is locked"
  events / 24h. Fix: cancel checks now run between individual files in both
  walks, AND `_process_file_with_retry()` wraps the per-file write with
  3-attempt exponential-backoff retry on `OperationalError("database is
  locked")` — mirroring the `db_write_with_retry` pattern bulk_worker has
  used from day one. Rule of thumb: any long-running scan loop that races
  with writers needs both an inner-loop cancel check AND retry-on-lock.

- **Adobe files need TWO conversion passes (v0.22.9)**: `_worker()` in
  `core/bulk_worker.py` dispatches every file through `_process_convertible()`
  for the regular markdown conversion (which lands in the `documents`
  Meilisearch index). Adobe files (`ext in ADOBE_EXTENSIONS and
  self.include_adobe`) ALSO need to go through `_index_adobe_l2()`
  immediately after, which calls `AdobeIndexer.index_file()` to populate the
  `adobe_index` SQLite table and then `search_indexer.index_adobe_file()` to
  push rich metadata + text layers into the `adobe-files` Meilisearch index.
  Skipping the L2 step (as the unified-dispatch refactor accidentally did
  pre-v0.22.9) leaves `adobe_index` and `adobe-files` empty even though
  .ai/.psd files appear `converted` in `bulk_files`. The L2 step does NOT
  update `bulk_files` status; the markdown conversion handles that.

- **`_process_adobe()` is dead code (v0.22.9)**: kept for now but never
  called from `_worker()`. The L2 indexing path is `_index_adobe_l2()`
  which runs alongside the unified dispatch. Don't add the old method back
  to the dispatch loop — it would compete with `_process_convertible()` for
  the same `bulk_files` row.


- **RollingWindowETA hates burst completions (v0.22.5)**: `RollingWindowETA` in
  `core/progress_tracker.py` stores `(time.monotonic(), completed_count)` tuples
  in a 100-slot deque and computes `fps = (newest_count - oldest_count) /
  (newest_ts - oldest_ts)`. Any code path that calls `record_completion()` N
  times in a tight loop stamps N entries with near-identical timestamps,
  producing nonsense rates like 783,184 files/sec and a `~0s` ETA. The bulk
  scanner's parallel drain loop hit this — it drained batches of up to 200
  files from the worker queue and iterated per-file. Fix: pass
  `count=len(batch)` in a single call so each drain yields exactly one window
  entry, and fps reflects real wall-clock pacing between drains. Rule of
  thumb: one window entry per real pacing event, never per item in a burst.

- **asyncio.Queue sentinel pattern**: Workers break on `None` sentinel. N sentinels for N workers.

- **Bulk SSE separate from single-file SSE**: `_bulk_progress_queues` vs `_progress_queues`.

- **Source share is read-only**: `/mnt/source` mounted `:ro`. Never write to it.
  Media/audio handlers previously wrote `_markflow/` sidecars to `file_path.parent`
  which fails on the read-only mount. Fixed in v0.19.6.11 — handlers now use a
  temp dir; the bulk worker places sidecars in the output tree.

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

- **`scan_dir_mtimes` is shared between bulk and lifecycle scanners**: Both scanners read from and
  write to the same `scan_dir_mtimes` table (keyed by `location_id + dir_path`). Whichever scanner
  ran last provides the cache for the next run — bulk and lifecycle scans complement rather than
  duplicate each other's mtime data. Do NOT scope the table per-scanner.

- **Incremental scan counter is a preference key, not a table column**: `scan_incremental_count`
  is stored via `get_preference()`/`set_preference()` in `core/db/preferences.py` (one of the
  5 new helpers: `get_incremental_scan_count`, `increment_scan_count`, `reset_scan_count`).
  Resetting the counter to 0 forces the next scan to do a full walk regardless of mtime cache.

- **Full walk forced outside business hours**: The incremental mtime skip is bypassed when the
  scan start time falls outside `scanner_business_hours_start` / `scanner_business_hours_end`
  (e.g., nightly/weekend scans). This ensures the mtime cache gets periodically refreshed even
  if the per-N-scan full-walk interval hasn't been reached yet.

- **`_current_dir_mtimes` dict is safe to write from multiple walker threads**: Each thread in
  the parallel scan walks a distinct set of directories (round-robin subdirectory assignment),
  so there is no key collision between threads. No locking is needed. Do NOT share dict keys
  between threads — if the round-robin assignment changes, add a threading.Lock.

- **Serial scan async overlap: await before creating a new task**: The serial scan path launches
  DB writes as `asyncio.create_task()` to overlap with the next stat() round. However, each
  pending write task must be `await`ed before a new `create_task()` is issued — otherwise
  tasks pile up unboundedly and SQLite write contention spikes. Pattern:
  `if pending_write: await pending_write; pending_write = asyncio.create_task(flush_batch(...))`.

- **Lifecycle scanner flushes counters every 500 files**: `_flush_counters_to_db()`
  persists `scan_run` counters periodically during both serial and parallel walks,
  so a container crash mid-scan leaves partial progress recorded rather than
  resetting everything to zero on the next startup.

- **`bulk_files.status='pending'` is NOT the same as "files left to convert"
  (v0.22.9)**: `bulk_files` is keyed by `(job_id, source_path)`, so each new
  scan job inserts its own pending row for every file — including files that
  were already converted in older jobs. The naive `COUNT(*) FROM bulk_files
  WHERE status='pending'` query reports 2-3× the real number of unconverted
  files. Always count truly-pending source files via a NOT EXISTS join:

  ```sql
  SELECT COUNT(*) FROM source_files sf
  WHERE sf.lifecycle_status = 'active'
    AND NOT EXISTS (
        SELECT 1 FROM bulk_files bf
        WHERE bf.source_path = sf.source_path
          AND bf.status = 'converted'
    )
  ```

  v0.22.9 also added a 4th step to `cleanup_stale_bulk_files()`
  (`pending_superseded_deleted`) that prunes pending rows whose source_path
  has any converted row in any job, so the table itself stays sane between
  cleanup runs.

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

## Vector Search & Qdrant (v0.22.0)

- **Vector search is best-effort**: `get_vector_indexer()` returns `None` when Qdrant is unreachable or `QDRANT_HOST` is empty. All call sites must handle `None`. Never make vector search a hard dependency — keyword search must always work independently.

- **Embedding model loaded lazily**: First embedding call loads ~80MB `all-MiniLM-L6-v2` model into RAM. Lazy import `sentence_transformers` inside `_load_model()` to avoid slow lifespan. Same pattern as Whisper model. Cached as module-level singleton.

- **Chunk IDs are deterministic**: SHA256 of `doc_id:chunk_index`. Re-indexing the same document produces the same chunk IDs — idempotent upserts in Qdrant. No stale chunks accumulate.

- **Qdrant container has no curl**: Health check uses `bash -c 'echo > /dev/tcp/localhost/6333'` instead of `curl`. The Qdrant Docker image is minimal and doesn't include curl or wget.

- **qdrant-client 1.17+ API change**: `.search()` is removed. Use `.query_points()` which returns a response object — access `.points` for the scored results list. This bit us during the initial integration.

- **Single Qdrant collection**: All document types (documents, adobe-files, transcripts) go into one collection `markflow_chunks` with a `source_index` payload field for filtering. Not three separate collections.

- **Embedding model version tracking**: The model name is known to the index manager. When swapping models (e.g., `all-MiniLM-L6-v2` → `nomic-embed-text`), all vectors must be re-generated. The pluggable provider interface supports this — just change `EMBEDDING_MODEL` env var and trigger a rebuild.

- **Rebuild path indexes to both Meilisearch and Qdrant**: `search_indexer.rebuild_index()` loops over all converted files. Each file is indexed to Meilisearch first, then vector-indexed to Qdrant (best-effort). Vector failures don't interrupt the rebuild.

- **RRF constant k=60**: Reciprocal Rank Fusion uses k=60 (standard from Cormack et al.). Changing this affects how keyword vs. vector rankings blend. Lower k = more weight to top-ranked results. Don't tune without the evaluation framework.

- **Query preprocessor temporal detection**: Queries containing "current", "latest", "recent", etc. trigger a sort bias toward `converted_at:desc` in keyword results. This is lightweight and runs on every query — no LLM call involved.

- **`AsyncQdrantClient` default timeout is 5s — too low under bulk load
  (v0.22.18)**: qdrant-client's default httpx timeout is 5 seconds, which
  trips on legitimate slow upserts during sustained bulk runs. Pre-v0.22.18
  this produced 381 `bulk_vector_index_fail` warnings / 24h, all
  `ResponseHandlingException(ReadTimeout)`. Vector indexing runs in a
  detached background task in `bulk_worker._index_vector_async`, so the
  bulk_worker isn't blocked by the timeout — but the warnings made the
  vector index incomplete. Fix: `get_vector_indexer()` now passes
  `timeout=int(os.environ.get("QDRANT_TIMEOUT_S", "60"))` to
  `AsyncQdrantClient(...)`. 60s is harmless to throughput because the
  upsert is async-detached.

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

- **Anthropic vision has TWO size limits — request AND per-image (v0.22.18)**:
  Anthropic enforces 32 MB per *request* AND a separate 5 MB per *individual
  image* (base64-encoded). Pre-v0.22.18, `vision_adapter._batch_anthropic`
  enforced the request-level cap (24 MB sub-batch envelope) but had no
  per-image enforcement, so a single 22 MB camera image in a batch of 10
  would pass the request envelope check and then explode on the per-image
  limit with `messages.0.content.1.image.source.base64: image exceeds 5 MB
  maximum`. Fix: `_compress_image_for_vision()` enforces a 3.5 MB raw
  budget per image (≈4.7 MB base64) — pass-through under budget; otherwise
  PIL longest-edge resize to 1568 px (Anthropic's recommended vision max)
  and JPEG q=85 re-encode, q=70 fallback. Wired into `describe_frame` and
  all four `_batch_*` providers (the cap is sensible everywhere, even for
  OpenAI/Gemini's looser 20 MB limits, since it keeps token cost / latency
  in check). Pillow is already a base dep (used by EPS/raster handlers).
  Rule of thumb: API providers always have multiple stacked limits — the
  envelope check is necessary but not sufficient.

- **`libreoffice_helper.py` "not found" error message was ambiguous
  pre-v0.22.18**: The helper raised `RuntimeError("LibreOffice not found.
  Install libreoffice-headless.")` in TWO different cases: (a) neither
  `libreoffice` nor `soffice` was on PATH, and (b) one of the binaries
  ran fine but the conversion exited nonzero (e.g. corrupt input file).
  This produced 14 misleading "missing dependency" errors / 24h that were
  actually file-level conversion failures — `Dockerfile.base` does install
  `libreoffice-writer` + `libreoffice-impress`. Fix: track a `binary_found`
  flag across the loop and raise a separate, accurate error in case (b)
  with the actual stderr / exit code, e.g. `"LibreOffice failed to convert
  FOO.doc to docx (exit=77): source file could not be loaded"`. Rule of
  thumb: never reuse one error message across structurally different
  failure modes.

- **AI Assist provider lookup is a 3-step chain (v0.22.11)**:
  `core/ai_assist.py:_get_provider_config()` resolves its API key, model,
  and base URL in this order:
    1. **Opted-in provider** — the row with `llm_providers.use_for_ai_assist=1`,
       set via the "Use for AI Assist" checkbox/button on the Providers
       page (`core.db.catalog.get_ai_assist_provider()`). This is the
       preferred path. The flag is mutually exclusive across rows
       (managed by `set_ai_assist_provider()` which clears all others
       in the same transaction).
    2. **Active provider** — `get_active_provider()` (the row used by the
       image scanner). Backward-compat fallback for users who haven't
       opted in a specific AI Assist provider yet.
    3. **`ANTHROPIC_API_KEY` env var** — last-resort legacy fallback.
       Deprecated, slated for removal.
  In all paths AI Assist requires the chosen provider to be `anthropic`
  (the SSE format and `x-api-key` header are Anthropic-specific). If the
  chosen provider is OpenAI/Gemini/etc, `_get_provider_config()` returns
  `compatible: False` with a clear error message that distinguishes
  "wrong opted-in provider" from "wrong active provider" so the UI can
  point users to the right fix. The `provider_source` field
  (`opted_in` / `active_fallback` / `env_fallback` / `none`) tells the
  frontend which path was taken.

- **AI Assist `use_for_ai_assist` flag is independent from `is_active`
  (v0.22.11)**: They are two separate columns. The image scanner reads
  `is_active`; AI Assist reads `use_for_ai_assist` (with `is_active` as
  fallback). Admins can have one provider active for image analysis and
  a totally different provider opted in for AI Assist. Both flags are
  mutually exclusive within their own column but never compete with each
  other.


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

- **AI Assist uses `httpx` for streaming, not `aiohttp`**: `core/ai_assist.py`
  streams SSE from the Anthropic API via `httpx.AsyncClient.stream()`. Keep
  `httpx` in `requirements.txt`. `ANTHROPIC_API_KEY` env var gates the feature;
  when absent, the UI toggle is hidden and endpoints return clear errors.

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
  Runs before the scheduler starts. Immediately followed by `reset_coordinator()` which clears
  in-memory coordinator flags (run_now_running, lifecycle_running, etc.) to prevent ghost state.
  A stale scan watchdog (`check_stale_scans()`, every 5 min) also resets scans stuck beyond 4 hours.

- **Stop banner CSS**: `.stop-banner[hidden] { display: none !important; }` in markflow.css.
  JS uses `style.display` not `.hidden` attribute because CSS `display:flex` overrides `hidden`.

- **`display: flex/grid` overrides HTML `hidden` attribute**: The browser's `hidden` attribute
  sets `display: none`, but any CSS rule that explicitly sets `display: flex` or `display: grid`
  wins the cascade and overrides it. Result: the element renders visibly even though `hidden` is
  present. Fix: default the element to `display: none` in CSS, remove the `hidden` attribute from
  HTML, and use a `.visible` class that sets `display: flex/grid`. Toggle with
  `el.classList.add/remove('visible')` instead of toggling the `hidden` attribute.

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

- **All scheduled jobs yield to bulk jobs**: Lifecycle scan, trash expiry, DB
  compaction, integrity check, and stale data check all call `get_all_active_jobs()`
  and skip if any bulk job is scanning/running/paused. Bulk jobs hold the DB heavily —
  running both concurrently causes "database is locked" errors. The deferred conversion
  runner also inherits this guard since it calls `run_lifecycle_scan()` internally.

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

- **`get_gpu_info_live()` must re-resolve execution_path (v0.22.8)**: The live
  re-read updates `host_worker_*` fields but the derived `execution_path`,
  `effective_gpu_name`, and `effective_backend` are computed once during
  `detect_gpu()` at startup. If `worker_capabilities.json` appears AFTER
  startup (common during dev), the cached `execution_path="container_cpu"`
  persists and the health page reports `gpu: FAIL / CPU` even though
  `host_worker_available=true` with the correct GPU. Fix: re-run the same
  resolution logic at the end of `get_gpu_info_live()`.

- **`worker_capabilities.json` is per-machine (v0.22.1)**: This file is gitignored and
  generated at deploy time by the refresh/reset scripts. Do NOT commit it — each machine
  (Windows/macOS/Linux) has different GPU hardware. The `.json.example` shows the schema.

- **hashcat --force required in Docker**.

- **hashcat potfile conflicts**: Each attack uses unique temp potfile.

- **hashcat `-I` requires cwd**: hashcat resolves its `OpenCL/` kernel directory
  relative to the current working directory, not its binary location. Scripts
  must `cd` to the hashcat install dir before running `hashcat -I`, otherwise
  it fails silently with `./OpenCL/: No such file or directory`.

- **GPU health component needs `ok` and `version`**: The convert page renders
  health components generically using `s.ok` and `s.version`. The GPU block in
  `core/health.py` must include both fields or it renders as a FAIL with blank
  detail even when the GPU is working.

- **PowerShell `Set-Content -Encoding UTF8` writes a BOM on PS 5.x**: Python's
  `json.loads()` rejects the BOM. Use `[IO.File]::WriteAllText()` for BOM-free
  output. Python readers of files that might come from PS should use
  `encoding="utf-8-sig"` defensively.

- **PowerShell stderr from native commands becomes RemoteException**: When
  redirecting native stderr with `2>&1` (e.g., hashcat's
  `nvmlDeviceGetFanSpeed(): Not Supported`), PS 5.1 wraps each stderr line as a
  `RemoteException`, which is caught by `try/catch` and silently aborts the
  script. Set `$ErrorActionPreference = 'SilentlyContinue'` around the call, or
  redirect stderr to `$null`.

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

- **Scan priority coordinator**: `core/scan_coordinator.py` manages priority: Bulk > Run Now > Lifecycle. Bulk starting cancels lifecycle and pauses run-now. Run-now starting cancels lifecycle. Lifecycle never pauses — only cancels and waits for next scheduled run. All signals use asyncio Events (cheap bool reads in walker loops). `reset_coordinator()` on startup clears all flags. `check_stale_scans()` watchdog (every 5 min) auto-resets scans stuck beyond 4 hours (configurable via `STALE_SCAN_TIMEOUT_S`).

- **Lifecycle cancel skips deletion detection**: When a lifecycle scan is cancelled mid-walk, it must NOT run deletion detection. The `seen_paths` set is incomplete, so any file not yet walked would be incorrectly marked as deleted. The cancelled scan sets `status='cancelled'` and returns.

- **Run-now pause/resume on bulk**: When a bulk job starts while run-now is active, run-now blocks on `_run_now_pause` Event (cleared = blocked). When all bulk jobs finish, `notify_bulk_completed()` sets the event, unblocking run-now. If run-now hasn't started scanning yet and bulk is active, it waits before calling `run_lifecycle_scan()`.

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
- **torch is CUDA 12.1 in Dockerfile.base (v0.22.15)**: `pip install torch --index-url https://download.pytorch.org/whl/cu121` ships the CUDA-enabled wheel (~2.5 GB vs ~200 MB CPU-only). On hosts without an NVIDIA GPU, `torch.cuda.is_available()` returns `False` and Whisper transparently falls back to CPU — same binary works everywhere. Previous CPU-only wheel silently capped Whisper at CPU speed even on GPU hosts.
- **GPU passthrough is a docker-compose.yml concern (v0.22.15)**: Installing the CUDA torch wheel is not enough — the `markflow` service must also have a `deploy.resources.reservations.devices` block requesting `driver: nvidia`. Without it, the container sees zero CUDA devices no matter what torch ships. Friend-deploys on GPU-less hosts should comment out the block (the app still runs, just CPU-only).
- **Host prereq for GPU (Windows)**: Docker Desktop on Windows runs containers inside WSL2. NVIDIA Container Toolkit must be installed **inside the WSL2 distro**, not on Windows itself. Smoke test: `docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi`. If that fails, `docker-compose up` will also fail to start the markflow service.
- **Transcription fallback chain order**: caption file → local Whisper → cloud providers. Each step tried in order; first success wins. Cloud tries ALL configured audio-capable providers with an API key, in priority order (active first).
- **Anthropic has no audio support — graceful fail (v0.22.15)**: `AUDIO_CAPABLE_PROVIDERS` maps only OpenAI and Gemini to `True`; Anthropic, Ollama, and "custom" are skipped. `CloudTranscriber.transcribe()` pre-flights the eligible-provider list; if empty, it raises `NoAudioProviderError` (distinct from generic provider failures). `transcription_engine.py` catches that specifically and raises a user-facing `RuntimeError` telling the user to add an OpenAI/Gemini key or fix Whisper. **If you add a new provider type, you MUST update `AUDIO_CAPABLE_PROVIDERS`** or audio transcription will silently skip it.
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

## Timestamps & Timezones (v0.22.1)

- **All backend timestamps are UTC**: `now_iso()` uses `datetime.now(timezone.utc).isoformat()`.
  Docker containers default to UTC. Never use naive `datetime.now()` — always pass `timezone.utc`.

- **UTC offset can be stripped by SQLite round-trip**: When a timestamp like
  `2026-04-06T13:09:00+00:00` is stored in SQLite TEXT and read back via aiosqlite,
  the `+00:00` suffix sometimes gets lost. Without it, JS `new Date()` treats bare
  ISO strings as local time, displaying UTC values without conversion.

- **`parseUTC()` is the fix**: All frontend date parsing must go through `parseUTC()`
  (in `app.js`), which appends `Z` to bare ISO strings. Do NOT use `new Date(isoString)`
  directly — always `parseUTC(isoString)` or `formatLocalTime(isoString)`.

- **`pipeline-files.html` has its own `formatLocalTime()`**: It shadows the global one
  from `app.js`. Updated to use `parseUTC()` internally, but be aware of the shadowing.

## Deploy Scripts (v0.22.1)

- **No non-ASCII in `.ps1` files**: Windows PowerShell 5.1 reads BOM-less UTF-8 as
  Windows-1252. Byte `0x94` (from UTF-8 em dash `E2 80 94`) becomes a right double quote
  `"` in Windows-1252, breaking string parsing. Use `--` not `—`, `-` not `─`, ASCII only.

- **`.sh` scripts tolerate UTF-8 but keep ASCII for consistency**: macOS Terminal and Linux
  bash handle UTF-8 fine, but SSH sessions with misconfigured locale may not render
  box-drawing characters. Use ASCII decoration for portability.

## Overnight Rebuild & PowerShell Native-Command Handling (v0.22.16+)

- **`Start-Transcript` does not capture native-command output in PS 5.1**: docker, git,
  curl, nvidia-smi, and every other native `.exe` bypass the PowerShell host and write
  straight to the console device, so `Start-Transcript` logs the section headers but
  leaves their bodies empty. The fix is the `Invoke-Logged` helper in
  `Scripts/work/overnight/rebuild.ps1`: run `& $Command 2>&1` into a variable, then
  render each item via `Write-Host` (projecting `ErrorRecord.Exception.Message` for
  stderr lines). This forces every line through the host, which the transcript captures.

- **PS 5.1 auto-displays `NativeCommandError` records before a `2>&1` pipeline can
  stringify them — only `SilentlyContinue` + variable capture actually suppresses it**:
  Wrapping `& docker-compose up -d 2>&1 | ForEach-Object { Write-Host $_ }` looks correct
  but fails. With `$ErrorActionPreference='Continue'` (the default), PS 5.1 emits native
  stderr lines as `NativeCommandError` records and **auto-displays them to the host with
  full `CategoryInfo` / `FullyQualifiedErrorId` decoration BEFORE they reach the
  `ForEach-Object` stage**. Your stringification is too late — the transcript already
  logged the decorated form. Two things have to happen together: (1) set
  `$ErrorActionPreference = 'SilentlyContinue'` so PS suppresses the auto-display, and
  (2) capture `$captured = & $cmd 2>&1` into a variable so nothing touches the host
  pipeline until you render it manually. Restore EAP in a `finally`. See the
  `Invoke-Logged` comment block in `Scripts/work/overnight/rebuild.ps1` for the exact
  pattern. The 2026-04-08 11:37:31 overnight failure log showed every docker-compose call
  decorated with `NativeCommandError : ... FullyQualifiedErrorId : NativeCommandError`
  until this fix landed.

- **`$ErrorActionPreference = "SilentlyContinue"` is the only EAP that reliably
  suppresses `NativeCommandError` auto-display — `Continue` is NOT enough, even
  with `2>$null`**: A tempting "fix" when you want to tolerate a native command's
  stderr is `$ErrorActionPreference = "Continue"` + `command 2>$null`. It looks
  right — `Continue` means "don't stop on errors", and `2>$null` discards the
  error stream. In practice PS 5.1 still auto-displays each native stderr line
  wrapped as a `NativeCommandError` ErrorRecord to the host, with full
  `CategoryInfo` / `FullyQualifiedErrorId` decoration, BEFORE the `2>$null`
  redirection takes effect. The entire transcript fills up with 8-line error
  blocks per call. The ONLY reliable suppression in PS 5.1 is
  `$ErrorActionPreference = "SilentlyContinue"`, which disables the auto-display
  path entirely. This bit `Test-StackHealthy` on the 2026-04-08 15:15:12 staged
  rebuild — the function set `Continue` locally as a workaround for
  docker-compose's symlink warning, but every probe attempt still flooded the
  transcript. Apply this rule to any helper that wraps a native command with
  known-benign stderr: either set EAP to `SilentlyContinue` inside the helper,
  or use `Invoke-Logged`'s capture pattern.

- **Post-`docker-compose up -d` health probes need a 20-second lifespan pause,
  even on the race-override path**: `docker-compose up -d` sometimes exits
  non-zero due to its post-start container cleanup losing a race with Docker
  Desktop's reconciler (v0.22.16 compose race). The instinct on seeing exit 1
  is to immediately probe the stack and override if it's actually healthy —
  that's what `Test-StackHealthy` is for. BUT: even when the compose race path
  is the real cause, the new containers are still mid-lifespan. FastAPI lifespan
  startup is ~20 seconds for MarkFlow; before that window closes, `/api/health`
  hasn't bound its handlers yet and curl returns connection refused. Without a
  lifespan pause, `Test-StackHealthy`'s 3x5s retry budget is not enough and the
  race-override reports false negative on a genuinely-healthy new build,
  triggering a rollback that's purely the probe's fault. Caught on the
  2026-04-08 15:15:12 staged rebuild, which rolled back a functionally-identical
  new build because Phase 3 probed too fast. Fix: `Start-Sleep -Seconds 20`
  after every `up -d` exit (zero OR non-zero), BEFORE any health probe, on both
  the initial-start and the --force-recreate rollback paths.

- **`docker-compose build` garbage-collects the previous `:latest` image
  instantly — capture rollback targets with a TAG, not a sha alone**: A common
  rollback pattern is "before the build, record the current `:latest` image
  sha, and after the build, retag that sha as `:last-good`." This assumes the
  old image stays resident in the image store between Phase 1 and Phase 2,
  reachable only by sha. On modern BuildKit that's false: the moment the new
  build tags `:latest`, the old image's only tag reference is dropped, and if
  nothing else references it, BuildKit's image GC evicts it from the store
  within milliseconds. By the time you try `docker tag <old-sha> :last-good`
  you get `Error response from daemon: No such image: sha256:...`. The fix is
  to tag the old image as `:last-good` BEFORE the build runs. The `:last-good`
  tag itself becomes the second reference that keeps the image resident across
  the build. Applies to `Scripts/work/overnight/rebuild.ps1` Phase 1.5.

- **Always surface native-command stderr on failure in retry wrappers — never
  `Out-Null` the combined stream**: The v0.22.17 overnight `Invoke-RetagImage`
  helper initially silenced retries with `& docker tag ... 2>&1 | Out-Null` to
  keep successful runs quiet. When the retag started failing (the BuildKit GC
  issue above), the morning log said "attempt 1 failed (exit 1)" with no clue
  why. The diagnostic was "manually re-run the tag command in a fresh shell to
  see the real error" — which defeats the purpose of overnight diagnostics.
  Rule: on failure, helpers MUST render the command's combined output to the
  transcript (with `ErrorRecord -> Exception.Message` projection for stderr
  lines). Silence is acceptable on the success path only.

- **`docker-compose ps --format json` — do NOT regex across fields, parse NDJSON
  line-by-line with `ConvertFrom-Json`**: The `Publishers` field in each compose-ps entry
  contains nested `{...}` subobjects (one per published port, with `URL`, `TargetPort`,
  `PublishedPort`, `Protocol`). A regex like `"Name":"markflow-1"[^}]*"State":"running"`
  looks harmless but the `[^}]*` negated class terminates at the first inner `}` inside
  Publishers, long before reaching `State`. Result: a perfectly-healthy stack matches
  zero times and the script reports "containers not both Up yet" on every attempt,
  making the race-override path permanent. The fix is to read NDJSON one line at a
  time and `ConvertFrom-Json` each line individually (each compose-ps entry is shallow
  enough for PS 5.1's parser). Also redirect `docker-compose` stderr to `$null` — the
  symlink warning it emits on every invocation contaminates the NDJSON stream being
  parsed. Same class of bug applies to any regex over `/api/health` with nested
  subobjects: use `[^{}]*` (not `[^}]*`) to scope a match to a specific subobject,
  so an inner `{}` can't swallow the `ok` flag lookahead.
