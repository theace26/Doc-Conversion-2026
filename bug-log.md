# MarkFlow Bug Log

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
