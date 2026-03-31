# MarkFlow Gotchas & Fixes Found

Hard-won lessons discovered during development. Read this file when working on
the relevant subsystem. Referenced from CLAUDE.md.

---

## Database & aiosqlite

- **aiosqlite pattern**: Use `async with aiosqlite.connect(path) as conn` — never
  `conn = await aiosqlite.connect(path)` then `async with conn` (starts the thread twice → RuntimeError).
  All DB helpers use `@asynccontextmanager` + `async with aiosqlite.connect()`.

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

## Path Safety & Collisions

- **Path safety pass runs during scan, not conversion**: Worker trusts resolved_paths.

- **resolve_collision() is deterministic**: Sort by `str(source_path)` ascending.

- **Case collision detection**: Only flags same-output-path pairs.

- **Renamed output paths use source extension**: `report.pdf.md` not `report_pdf.md`.

## Search & Meilisearch

- **Meilisearch primary key IDs**: Use `sha256(source_path)[:16]` hex. No slashes allowed.

- **Meilisearch graceful degradation**: Connection errors return safe defaults. Search returns 503.

- **httpx is a runtime dependency**: Moved from testing section in Phase 7.

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

- **Static file cache headers**: Middleware in `main.py` adds `Cache-Control: no-cache, must-revalidate`
  to all `/static/` responses. Prevents stale JS/CSS after deploys.

## Scheduler & Metrics

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

- **HASHCAT_QUEUE_DIR must be a bind mount**: Not a named volume.

- **hashcat exit codes**: 0=cracked, 1=exhausted. Check output file, not exit code.

- **docker-compose.gpu.yml is an overlay**: Use with `-f` flag.

- **Host paths are per-machine via `.env`**: `docker-compose.yml` uses `${SOURCE_DIR}`,
  `${OUTPUT_DIR}`, `${DRIVE_C}`, `${DRIVE_D}`. Each machine gets its own `.env` (gitignored).
  See `.env.example` for the template. Never hardcode host paths in the compose file.

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
