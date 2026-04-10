# MarkFlow Bug Log

## 2026-04-03 — Concurrent Bulk Jobs Race Condition (v0.19.1)

### Bug 20: Two bulk jobs run simultaneously, deadlocking SQLite

**Symptom:** After container restart, auto-conversion pipeline stalled permanently.
Database showed two bulk jobs stuck in `status='scanning'` with `total_files=NULL`
and `converted=0`. 398K+ files pending, zero converted in 7+ hours. APScheduler
logged "maximum number of running instances reached" every cycle for both
`run_lifecycle_scan` and `_run_deferred_conversions`.

**Root cause — two independent bugs:**

1. **`_execute_auto_conversion()` had no concurrency guard.** When the lifecycle
   scan completed at 10:05 and found 20K new files, it called
   `_execute_auto_conversion()` which created a new bulk job without checking if
   the backlog poller had already started one at 08:04. Result: two bulk jobs
   scanning the same `/mnt/source` into the same `bulk_files` table.

2. **`get_all_active_jobs()` misreported scanning jobs as `"done"`.** During the
   scan phase, `_total_pending == 0` (not yet set) and `_converted == 0`, so the
   status derivation fell through to `"done"`. The backlog poller's guard
   (`if not active`) passed because it saw no "active" jobs, even though a job
   was mid-scan. This is what allowed the backlog poller to create job `d1712de9`
   while the lifecycle scanner later created `ce8de7ca`.

Both jobs had 4 scanner threads each, all upserting into `bulk_files` with the
same `source_path` values. SQLite WAL mode can handle concurrent reads but
serializes writes — 8 threads contending on INSERT/UPDATE caused escalating lock
wait times. Both jobs stalled at 85-90% completion and never transitioned to the
conversion phase.

**Fix:**
- `core/bulk_worker.py`: Added `_scanning` flag, set `True` at init, cleared
  before transition to "running". `get_all_active_jobs()` now returns
  `"scanning"` when the flag is set, preventing the false `"done"` report.
- `core/lifecycle_scanner.py`: `_execute_auto_conversion()` now checks
  `get_all_active_jobs()` and refuses to create a job if any existing job
  has status `scanning`, `running`, or `paused`.
- `core/scheduler.py`: Backlog poller now explicitly checks for active statuses
  (not just `if not active`) AND double-checks the DB as a fallback in case
  in-memory state is stale.

**Files changed:** `core/bulk_worker.py`, `core/lifecycle_scanner.py`,
`core/scheduler.py`, `core/version.py`

---

## 2026-04-03 — Bulk Upsert UNIQUE Constraint Race (v0.18.1)

### Bug: `upsert_bulk_file()` SELECT-then-INSERT race condition

**Symptom:** Lifecycle scanner logs flooded with `UNIQUE constraint failed:
bulk_files.job_id, bulk_files.source_path` errors — 286+ per scan cycle. Pipeline
stats showed 89,527 files scanned, 89,526 pending conversion, 0 in search index.
No files were being converted or indexed despite the scanner running continuously.

**Root cause:** `core/db/bulk.py:upsert_bulk_file()` used a non-atomic SELECT-then-INSERT
pattern. On rescans, the SELECT checked `bulk_files` for an existing `(job_id, source_path)`
pair, found nothing (likely due to connection/transaction timing), then attempted INSERT
which hit the UNIQUE constraint because the row already existed. Each error was caught
per-file so the scan continued, but the cumulative overhead of processing 89K+ files on
a NAS mount with per-file exception handling prevented the scan from completing within
the 15-minute scheduler interval. Since `on_scan_complete()` was never reached,
auto-conversion was never triggered.

**Fix:** Replaced SELECT-then-INSERT with atomic `INSERT ... ON CONFLICT(job_id, source_path)
DO UPDATE SET ...`. The skip/pending logic is preserved via SQL CASE expressions comparing
`bulk_files.stored_mtime` against `excluded.source_mtime`.

**Files changed:** `core/db/bulk.py` (upsert_bulk_file function)

**Impact:** CRITICAL — entire conversion+indexing pipeline was blocked. No files could
reach the search index.

---

## 2026-04-02 — Auto-Conversion Kwarg + GPU Staleness (v0.18.0)

### Bug 1: Lifecycle scanner auto-conversion silently broken

**Symptom:** Lifecycle scans completed, detected new files, decided to auto-convert, but
no conversion ever ran. No visible error in normal logs.

**Root cause:** `core/lifecycle_scanner.py:924` called `BulkJob(source_path=...)` but
`BulkJob.__init__` expects `source_paths=` (plural). Every auto-conversion triggered by
the lifecycle scanner failed with `BulkJob.__init__() got an unexpected keyword argument
'source_path'`, caught by the generic exception handler at line 398.

**Fix:** Changed `source_path=` to `source_paths=` in the `BulkJob()` constructor call.

**Impact:** HIGH — auto-conversion via lifecycle scanner was silently broken since v0.17.x.

### Bug 2: Stale GPU displayed from disconnected workstation

**Symptom:** Health check showed "NVIDIA GeForce GTX 1660 Ti" as the active GPU even
when the workstation was disconnected. The GPU had been detected by the hashcat worker
on a different machine and cached in `worker_capabilities.json`.

**Root cause:** `core/gpu_detector.py:_read_host_worker_report()` trusted the cached
`worker_capabilities.json` without checking if the worker was still alive.

**Fix:** Added `worker.lock` presence and timestamp freshness checks. Hashcat worker now
writes a 2-minute heartbeat to `worker.lock`. Stale capabilities (no lock file or lock
older than 5 minutes) are ignored.

**Files changed:** `core/gpu_detector.py`, `tools/markflow-hashcat-worker.py`

---

## 2026-03-25 — MCP Crash + Lifecycle FK Constraint

### Bug 1: MCP Server Crash-Looping

**Symptom:** Container `doc-conversion-2026-markflow-mcp-1` restarted every ~30 seconds.
Logs showed:
```
TypeError: FastMCP.__init__() got an unexpected keyword argument 'description'
```

**Root cause:** The `mcp` library updated its API. `FastMCP.__init__()` no longer accepts
a `description` keyword argument.

**Fix:** Already applied in a prior session. `mcp_server/server.py` line 24 uses
`FastMCP("MarkFlow")` with only the positional name argument. No `description` kwarg.

**Verified (2026-03-26):** `inspect.signature(FastMCP.__init__)` confirms `description`
is not in the parameter list. Container stays up with clean startup logs. No crash loop.

---

### Bug 2: Lifecycle Scanner FK Constraint Failures

**Symptom:** Lifecycle scan at 2026-03-25T17:46:43 scanned 12,847 files but recorded
`files_new=0` and `errors=7055`. Every supported-format file insert failed with
`FOREIGN KEY constraint failed`.

**Diagnostic findings (2026-03-26):**

- `bulk_files.job_id` references `bulk_jobs(id)` via FK constraint.
- At 17:46, `bulk_jobs` had **zero rows** — no user-created bulk jobs existed yet.
- The scanner code (`lifecycle_scanner.py:150-161`) has synthetic job creation logic
  that should have created a parent `bulk_jobs` row. However, no synthetic job was
  found in the DB. The code path either didn't execute (stale Docker image) or
  failed silently.
- The issue **self-resolved** when the first user-created bulk_job was added at 18:05.
  All subsequent scans (67 total) completed with `errors=0`.
- Scan at 20:30 successfully added 2,074 new files after the FK parent existed.

**Secondary issue:** 6 `scan_runs` were stuck with `status='running'` forever (never
finished). These occurred around bulk_job creation times, suggesting concurrent access
issues. Stuck scans would cause `run_db_compaction()` to defer indefinitely (it checks
for running scans before proceeding).

**Actions taken:**
1. Cleaned up 6 stuck `scan_runs` → set `status='failed'`
2. Verified current lifecycle scanner works: 12,847 files scanned, 0 errors
3. Documented findings in CLAUDE.md gotchas section

**Current state:** No code fix needed — the synthetic job creation code is already
correct in the current codebase. The FK error was a one-time boot issue. Current
scans work correctly.

**Files changed:** None (DB cleanup only via Python script in container)

---

## 2026-03-26 — "Stop Requested" Banner Never Clears

**Symptom:** Clicking "Reset & allow new jobs" on `status.html` calls
`POST /api/admin/reset-stop` successfully (returns `{ok: true}`) but the yellow
"Stop requested — jobs are winding down" banner never disappears. The nav badge
(showing `!`) also persists until the next poll cycle.

**Root cause:** The reset handler called `poll()` immediately after the API call,
but `poll()` re-fetches `/api/admin/active-jobs` and re-renders. If the backend
hasn't fully committed the flag change before the poll response arrives, the banner
reappears. There was no immediate UI feedback — the banner hide/show relied entirely
on the next poll result.

**Fix:**
1. `static/status.html`: Hide the banner (`hidden = true`) and re-enable the Stop All
   button immediately after the reset API returns `ok`, before calling `poll()`. Added
   error handling for failed resets.
2. `static/js/global-status-bar.js`: Exposed `window.refreshStatusBadge()` so the
   status page can trigger an immediate badge refresh after reset, clearing the `!`
   badge without waiting for the 5-second poll interval.

**Files changed:**
- `static/status.html` (reset handler, ~6 lines)
- `static/js/global-status-bar.js` (1 line: expose `window.refreshStatusBadge`)

---

## 2026-03-29 — Full Log Analysis → v0.12.1 Stability Patch

Three troubleshooting sessions analyzing `markflow-debug.log` and `markflow-tail.log`
from a 19-hour production window (39,276 main + 6,691 debug log lines, 00:00–19:02 UTC).
Produced the v0.12.1 stability patch fixing 10 bugs and adding 3 stability improvements.

### Bug 3: structlog double `event=` kwarg (lifecycle_scanner.py)

**Symptom:** `BoundLogger.error() got multiple values for argument 'event'` after every
auto-convert decision. The real auto-convert trigger exception was swallowed.

**Impact:** HIGH — Two lifecycle scans found 60,959 and 3,613 new files respectively,
decided to convert them, and then crashed with the real exception hidden by the broken
error handler.

**Root cause:** structlog's first positional arg IS the event. Code also passed `event=`
as a keyword: `log.info("auto_convert_job_created", event="auto_convert_job_created", ...)`

**Fix:** Removed duplicate `event=` kwarg from 2 calls in `core/lifecycle_scanner.py`.

### Bug 4: SQLite "database is locked" cascade

**Symptom:** 5 bulk worker file conversions failed, 4 metrics collections failed, plus
a 45-minute cascade of 88 skipped `collect_metrics` jobs.

**Root cause:** Multiple concurrent writers (lifecycle scanner + metrics collector + bulk
worker) with some connections missing WAL mode and busy_timeout. `metrics_collector.py`
used direct `aiosqlite.connect(DB_PATH)` bypassing `get_db()`.

**Fix:** Migrated all direct `aiosqlite.connect()` calls to use `get_db()` (which sets
WAL + busy_timeout). Added retry wrapper with exponential backoff on metrics INSERT.

**Files changed:** `core/metrics_collector.py`, `core/auto_metrics_aggregator.py`,
`core/scheduler.py`, `core/lifecycle_scanner.py`, `core/auto_converter.py`

### Bug 5: collect_metrics 88 consecutive skips

**Symptom:** 30s interval caused one stuck instance to block all subsequent triggers.
88 warnings of `maximum number of running instances reached` in 45 minutes.

**Fix:** Increased interval from 60s to 120s, added `misfire_grace_time=60`,
wrapped inner function in `asyncio.wait_for(timeout=30)`.

### Bug 6: DB compaction permanently deferred

**Symptom:** 5 consecutive deferrals (02:00–04:00 UTC) — `scan_running` from an
orphaned job made the guard permanently true.

**Fix:** Removed `scan_running` guard entirely. Compaction uses `PRAGMA optimize` +
`incremental_vacuum` which are WAL-safe for concurrent execution.

### Bug 7: MCP server unreachable (ConnectError)

**Symptom:** Health check at `/api/mcp/connection-info` failed with
`ConnectError(OSError('All connection attempts failed'))`.

**Root cause:** `mcp_info.py` used `http://localhost:{port}` for health check.
Inside Docker, `localhost` is the markflow container, not the MCP container.

**Fix:** Read `MCP_HOST` env var (default `markflow-mcp` — Docker service name).
Added `MCP_HOST=markflow-mcp` to `docker-compose.yml`.

### Bug 8: Orphaned jobs persist across container restarts

**Symptom:** Container restart mid-job leaves `bulk_jobs` and `scan_runs` in
`scanning`/`running` status permanently. Causes stop banner, compaction deferral,
and stale progress data.

**Fix:** Added `cleanup_orphaned_jobs()` in `core/database.py`. Called from lifespan
before scheduler starts. Cancels stuck bulk_jobs, interrupts stuck scan_runs.
Also calls `reset_stop()` to clear in-memory stop flag.

### Bug 9: Stop banner stuck visible after restart

**Symptom:** `.stop-banner { display: flex }` in CSS overrides the HTML `hidden`
attribute, keeping banner visible even after orphan cleanup.

**Fix:** Added `.stop-banner[hidden] { display: none !important; }`. Changed JS
to use `style.display` toggle instead of `.hidden` attribute.

### Bug 10: Bulk scan 0 files on unmounted SMB share

**Symptom:** Scan at 17:02 UTC found 0 files in 2ms on `/mnt/source` — SMB mount
not ready. Reported success with 0 files instead of failing.

**Fix:** Added `_verify_source_mount()` to `core/bulk_scanner.py` and mount-empty
check to `core/lifecycle_scanner.py`. Empty mountpoints abort gracefully.

### Fix: Static files served without cache-control

**Fix:** Added HTTP middleware in `main.py` setting
`Cache-Control: no-cache, must-revalidate` on `/static/` responses.

### Fix: DEFAULT_LOG_LEVEL env var

**Fix:** `main.py` reads `DEFAULT_LOG_LEVEL` env var at startup. DB preference
wins if user set non-normal level; otherwise env var is applied.

**All files changed across v0.12.1:**
`core/lifecycle_scanner.py`, `core/metrics_collector.py`, `core/auto_metrics_aggregator.py`,
`core/scheduler.py`, `core/auto_converter.py`, `core/database.py`, `core/bulk_scanner.py`,
`api/routes/mcp_info.py`, `main.py`, `static/markflow.css`, `static/status.html`,
`docker-compose.yml`, `tests/test_bugfix_patch.py`, `tests/test_bugfix_v0121.py` (new)

---

## 2026-03-30 — MCP Server Fixes (3 bugs) + Multi-Machine Docker

### Bug 11: MCP server crash — unsupported host/port kwargs

**Symptom:** Container `markflow-mcp` crash-looping with:
```
TypeError: FastMCP.run() got an unexpected keyword argument 'host'
```

**Root cause:** `FastMCP.run()` does not accept `host` or `port` keyword arguments
in the installed version. The previous code passed `mcp.run(transport="sse", host="0.0.0.0", port=port)`.

**Investigation sequence:**
1. First fix attempt: pass `host="0.0.0.0", port=port` kwargs to `mcp.run()` → TypeError crash
2. Second fix attempt: set `os.environ["UVICORN_HOST"]` and `os.environ["UVICORN_PORT"]`
   before `mcp.run(transport="sse")` → Uvicorn ignored the env vars, still bound to 127.0.0.1:8000
3. Final fix: bypass `mcp.run()` entirely, call `uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port)` directly

**Fix:** `mcp_server/server.py` — replaced `mcp.run()` with direct `uvicorn.run(mcp.sse_app(), ...)`.

### Bug 12: MCP info panel shows Docker-internal IP and wrong path

**Symptom:** Settings page MCP panel displayed `http://172.20.0.3:8001/mcp` — unreachable
from the host and wrong endpoint path.

**Root cause:** `api/routes/mcp_info.py` used `socket.gethostbyname(hostname)` which returns
the Docker bridge network IP (172.20.x.x) inside the container. The path `/mcp` was wrong —
FastMCP's SSE endpoint is at `/sse`.

**Fix:** Replaced `socket.gethostbyname()` with hardcoded `localhost`, changed `/mcp` to `/sse`.
Removed unused `socket` import. Updated JS fallback URLs in `settings.html`.

**Files changed:** `api/routes/mcp_info.py`, `static/settings.html`

### Bug 13: MCP health check returns 404

**Symptom:** UI showed "MCP server not detected" even though the MCP container was running
and serving SSE connections. The main app's backend health check hit `GET /health` which
returned 404.

**Root cause:** `FastMCP.sse_app()` does not include a `/health` endpoint. The main app's
`mcp_info.py` route correctly pings `/health` using the Docker service name, but the MCP
server had no route to handle it.

**Fix:** `mcp_server/server.py` — build the SSE app via `mcp.sse_app()`, append a Starlette
`Route("/health", health_check)` that returns `{"status": "ok", "service": "markflow-mcp", "port": 8001}`,
then pass the app to `uvicorn.run()`.

**Files changed:** `mcp_server/server.py`

### Infrastructure: Multi-machine Docker support

**Problem:** `docker-compose.yml` had hardcoded Windows paths (`C:/Users/Xerxes/T86_Work/...`,
`D:/Doc-Conv_Test`). Working from a MacBook at home required local edits that couldn't be
committed without breaking the work machine.

**Fix:** Replaced hardcoded paths with environment variables (`${SOURCE_DIR}`, `${OUTPUT_DIR}`,
`${DRIVE_C}`, `${DRIVE_D}`). Each machine gets its own `.env` (gitignored). Added `.env.example`
template with Windows defaults.

**Files changed:** `docker-compose.yml`, `.env.example`, `.env` (local, not committed)

**All files changed across v0.12.10:**
`mcp_server/server.py`, `api/routes/mcp_info.py`, `static/settings.html`,
`docker-compose.yml`, `.env.example`, `CLAUDE.md`, `core/database.py` (default preferences),
`api/routes/preferences.py` (worker count options),
`Scripts/work/reset-markflow.ps1`, `Scripts/work/refresh-markflow.ps1`

---

## 2026-03-30 — Startup Crash + Log Explosion (v0.12.9)

### Bug 14: Container restart loop — missing import

**Symptom:** Container crash-looped with exit code 3 on startup.

**Root cause:** `core/database.py:cleanup_orphaned_jobs()` used `structlog.get_logger()`
but the `import structlog` statement was missing from the file. The function was added
in v0.12.1 (orphan cleanup) but the import was omitted.

**Fix:** Added `import structlog` to `core/database.py`.

### Bug 15: pdfminer debug log flooding (4GB+)

**Symptom:** `markflow-debug.log` grew to 4+ GB during bulk PDF conversion jobs.

**Root cause:** `pdfminer.*` loggers emit per-token debug output. With thousands of PDFs
processing, the debug log became unbounded.

**Fix:** Suppressed `pdfminer.*` loggers to WARNING level in `core/logging_config.py`.

### Bug 16: Log rotation missing — unbounded log growth

**Symptom:** After the pdfminer fix, logs still grew without bound using
`TimedRotatingFileHandler` (daily rotation, but no size cap within a day).

**Fix:** Replaced with `RotatingFileHandler`: operational log 50 MB / 5 backups,
debug log 100 MB / 3 backups. Added `LOG_MAX_SIZE_MB` and `DEBUG_LOG_MAX_SIZE_MB`
env vars. Added 413 size guard on log download endpoint for files >500 MB (prevented
browser download loops on oversized files).

**Files changed:** `core/database.py`, `core/logging_config.py`, `api/routes/logs.py`,
`docker-compose.yml`

---

## 2026-03-31 — Hashcat GPU Detection Chain (3 bugs)

### Bug 17: hashcat -I fails outside install directory

**Symptom:** Settings GPU panel showed "not detected" even on a machine with a GPU
and hashcat installed.

**Root cause:** hashcat resolves its `OpenCL/` kernel directory relative to the current
working directory, not its binary location. Scripts ran `hashcat -I` from the repo
directory, causing it to fail silently.

**Fix:** Changed PowerShell and bash scripts to `cd` to hashcat's install directory
before running `hashcat -I`.

### Bug 18: hashcat stderr aborts PowerShell

**Symptom:** Even after the cwd fix, GPU detection still failed on some machines.

**Root cause:** hashcat's `nvmlDeviceGetFanSpeed()` emits a stderr warning that
PowerShell treats as a `RemoteException`. This triggered the try/catch error handler,
aborting backend detection before `hashcat_backend` was set.

**Fix:** Wrapped hashcat invocation with `$ErrorActionPreference = 'SilentlyContinue'`
to let stderr through without triggering the catch block.

### Bug 19: UTF-8 BOM in worker_capabilities.json

**Symptom:** GPU still showed as "not detected" even after fixes 17-18.

**Root cause:** PowerShell's `Set-Content -Encoding UTF8` writes a UTF-8 BOM (byte
order mark). Python's `json.loads()` throws `Unexpected UTF-8 BOM` on read, which was
silently caught, leaving `host_worker_available = false`.

**Fix:** PowerShell now writes via `[IO.File]::WriteAllText()` (no BOM). Python reads
with `utf-8-sig` encoding as defensive fallback.

**Files changed (all 3 bugs):** `Scripts/work/refresh-markflow.ps1`,
`Scripts/work/reset-markflow.ps1`, `core/gpu_detector.py`

---

## 2026-04-10 — Bulk Conversion Pipeline Stalled (v0.23.2)

### Bug 21: ON CONFLICT(source_path) vs UNIQUE(job_id, source_path) mismatch

**Symptom:** Every scheduled bulk conversion job failed immediately with
`ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint`.
1,654 files stuck in pending state, zero conversions processing. Error repeated
every 15 minutes (13 occurrences logged before detection).

**Root cause:** The audit remediation work (v0.23.0, 2026-04-09) changed the
upsert SQL in `core/db/bulk.py` from `ON CONFLICT(job_id, source_path)` to
`ON CONFLICT(source_path)` to support cross-job deduplication. However, the
`bulk_files` table schema still had `UNIQUE(job_id, source_path)` — SQLite
requires the ON CONFLICT target to exactly match a declared constraint.

**Fix:** Migration 26 rebuilds `bulk_files` with `UNIQUE(source_path)` instead
of `UNIQUE(job_id, source_path)`. Data is preserved by deduplicating on
`MAX(ROWID)` per source_path. Base DDL updated to match.

**Files changed:** `core/db/schema.py`

### Bug 22: Unawaited async coroutine in scheduler and admin endpoint

**Symptom:** `RuntimeWarning: coroutine 'get_all_active_jobs' was never awaited`
at `core/scheduler.py:481`. The `_bulk_files_self_correction` job always skipped
(coroutine object is truthy), and the admin cleanup endpoint always returned 409.

**Root cause:** `get_all_active_jobs()` is `async def` but was called without
`await` in two locations: `scheduler.py:481` and `admin.py:421`.

**Fix:** Added `await` to both call sites.

**Files changed:** `core/scheduler.py`, `api/routes/admin.py`

### Bug 23: Vision adapter sends wrong MIME type for mislabeled images

**Symptom:** Anthropic API returned HTTP 400: "image was specified using
image/jpeg media type, but the image appears to be a image/gif image". Entire
10-image batches failed (completed=0, failed=10).

**Root cause:** All four vision provider paths used `path.suffix` (file
extension) to determine MIME type via `mimetypes.guess_type()`. Files with
mismatched extensions (e.g. a GIF saved as `.png` or `.jpg`) got the wrong
`media_type`. The correct `detect_mime()` function (magic-byte header detection)
was already defined in the same file but unused in these code paths.

**Fix:** Replaced `path.suffix` / `image_path.suffix` with `detect_mime(path)`
in all four locations: `_batch_anthropic`, `_batch_openai`, `_batch_gemini`,
and the single-image describe path.

**Files changed:** `core/vision_adapter.py`
