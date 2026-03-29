# MarkFlow v0.12.1 — Bugfix + Stability Patch
# Log Analysis Fixes + Orphan Recovery + Progress Tracking — 2026-03-29

**Version:** v0.12.0 → v0.12.1
**Prerequisite:** v0.12.0 codebase, CLAUDE.md loaded
**Execution:** Single Claude Code session. Fix in order listed — some fixes depend on earlier ones.

**Scope:** 7 log-analysis bugfixes + 3 stability/UX improvements:
- Fixes 1–7: Bugs found via `markflow-debug.log` and `markflow-tail.log` analysis
- Fix 8: Startup orphan job recovery (auto-clean stuck DB records on container start)
- Fix 9: Stop banner CSS/JS fix (banner stuck visible after orphan cleanup)
- Fix 10: Lifecycle scanner progress tracking + ETA display

---

## 0. Read First

Load `CLAUDE.md` before writing a single line. Read `docs/gotchas.md` — especially the
aiosqlite, structlog, and scheduler sections.

**Important:** Fixes 1–7 are targeted edits to existing files. Fixes 8–10 involve one new
file (`core/progress_tracker.py`), one DB schema migration, and frontend updates.

Before making ANY code changes, run the diagnostic steps in Section 0.1. The diagnostics
confirm the exact code patterns causing each bug so you fix the right lines.

### 0.1 Diagnostic Steps (run these FIRST, report findings)

```bash
# Bug 1: Find the admin stats queries referencing missing columns
grep -n 'provider_type\|file_size' api/routes/admin.py

# Bug 2: Find structlog double-event calls
grep -n '\.error\(.*event=' core/lifecycle_scanner.py
grep -n '\.info\(.*event=' core/auto_metrics_aggregator.py

# Bug 3: Check if WAL mode is already set
grep -n 'journal_mode\|WAL\|busy_timeout' core/database.py

# Bug 4: Find the collect_metrics interval
grep -n 'collect_metrics\|interval.*seconds\|add_job.*collect' core/scheduler.py

# Bug 5: Find the compaction deferral logic
grep -n 'compaction\|scan_running\|deferred' core/scheduler.py

# Bug 6: Check MCP container config and connection logic
grep -n 'mcp\|8001\|MCP' docker-compose.yml
grep -n 'connection.info\|connect.*mcp\|MCP.*host\|MCP.*port' api/routes/mcp.py 2>/dev/null || echo "No mcp route file found"
grep -rn 'mcp.*connection\|connection.*mcp' api/routes/ --include='*.py'

# Bug 7: Find the log download handler
grep -n 'download\|logs.*download\|FileResponse\|StreamingResponse' api/routes/admin.py api/routes/settings.py 2>/dev/null
grep -rn '/api/logs/download' api/ --include='*.py'
# And the frontend download button handler
grep -n 'download.*log\|markflow.log\|markflow-debug.log\|blob\|createObjectURL' static/settings.html static/settings.js 2>/dev/null

# Fix 8: Find startup/lifespan code and stop controller
grep -n 'lifespan\|startup\|on_startup\|app_startup' main.py
grep -n 'stop_requested\|reset_stop\|clear_stop' core/stop_controller.py
# Check for existing orphan cleanup
grep -rn 'orphan\|stuck.*job\|cleanup.*start' core/ main.py --include='*.py'

# Fix 9: Find the stop banner CSS and JS
grep -n 'stop-banner\|stop_banner\|stopBanner' static/markflow.css static/status.html static/app.js static/status.js 2>/dev/null

# Fix 10: Check existing progress infrastructure
grep -rn 'progress_tracker\|RollingWindowETA\|total_files\|eta' core/ --include='*.py' | head -20
# Check the lifecycle scanner's progress reporting
grep -n 'files_scanned\|progress\|total' core/lifecycle_scanner.py | head -20
# Check the status page SSE/polling for scanner progress
grep -n 'scanner.*progress\|lifecycle.*progress\|files_scanned' api/routes/ --include='*.py'
grep -n 'filesScanned\|files_scanned\|total_files\|eta\|progress' static/status.html static/status.js 2>/dev/null
# Check DB schema for scan_runs table
grep -n 'scan_runs\|CREATE TABLE.*scan' core/database.py | head -10
```

**STOP here.** Report the diagnostic output before proceeding to fixes.
The grep results will reveal the exact line numbers and patterns for each bug.

---

## 1. Fix: Missing DB columns in admin stats (ERROR)

**File:** `api/routes/admin.py`
**Log evidence:**
```
{"error": "no such column: provider_type", "event": "admin.stats_query_failed"}
{"error": "no such column: file_size", "event": "admin.stats_query_failed"}
```

**Root cause:** The `/api/admin/stats` endpoint has SQL queries that reference `provider_type`
and `file_size` columns, but these columns were never added to the SQLite schema.

**Fix approach:** Remove the broken queries from the stats endpoint. These columns belong to
a future LLM provider stats feature (v0.7.4) that was never wired into the main schema.
Do NOT add the columns — the data isn't being populated anywhere, so adding empty columns
would just mask the problem.

**Steps:**

1. In `api/routes/admin.py`, find the `/api/admin/stats` endpoint function.
2. Locate the SQL query or queries that reference `provider_type`. It will look something like
   `SELECT provider_type, COUNT(*) ... GROUP BY provider_type` or similar.
3. Remove or comment out that query block. Replace with a hardcoded empty dict or skip that
   section of the stats response:
   ```python
   # LLM provider stats — columns not yet in schema, disabled until migration
   # stats["provider_breakdown"] = ...
   stats["provider_breakdown"] = {}
   ```
4. Do the same for `file_size`. Find the query referencing it (likely something like
   `SELECT SUM(file_size) ...` or `AVG(file_size)`). Remove or stub it:
   ```python
   # File size stats — column not yet in schema
   stats["total_file_size"] = 0
   stats["avg_file_size"] = 0
   ```
5. **Keep the try/except blocks** that currently catch these errors — they're providing
   graceful degradation. But the goal is to stop the error from happening at all.

**Verify:** After fix, visit the Admin page and confirm no `admin.stats_query_failed` warnings
appear in the log for subsequent `/api/admin/stats` requests.

---

## 2. Fix: Structlog double `event` argument (ERROR)

**Files:** `core/lifecycle_scanner.py`, `core/auto_metrics_aggregator.py`
**Log evidence:**
```
{"error": "BoundLogger.error() got multiple values for argument 'event'",
 "event": "lifecycle_scan.auto_convert_trigger_failed"}
{"error": "BoundLogger.info() got multiple values for argument 'event'",
 "event": "auto_metrics_aggregation_failed"}
```

**Root cause:** structlog's `BoundLogger.info()` / `.error()` / `.warning()` treat the first
positional argument as the `event` parameter. When code does:
```python
log.error("Some description", event="lifecycle_scan.auto_convert_trigger_failed")
```
…it passes `event` twice — once positionally ("Some description") and once as a keyword.

**Fix pattern:** For every affected call, move the descriptive text into a `msg` kwarg and
keep the structured event name as the positional (first) argument:

```python
# BEFORE (broken):
log.error("Auto-convert trigger failed", event="lifecycle_scan.auto_convert_trigger_failed", error=str(e))

# AFTER (fixed):
log.error("lifecycle_scan.auto_convert_trigger_failed", msg="Auto-convert trigger failed", error=str(e))
```

**Steps:**

1. **`core/lifecycle_scanner.py`** — Find the `.error()` call near the auto-convert trigger
   block (after the `lifecycle_scan.complete` event). The diagnostic grep will show the exact
   line. Apply the fix pattern above.

2. **`core/auto_metrics_aggregator.py`** — Find the `.info()` call with the double event.
   Apply the same fix pattern.

3. **Scan for other instances** — run:
   ```bash
   grep -rn '\.info\(.*event=\|\.error\(.*event=\|\.warning\(.*event=\|\.debug\(.*event=' core/ api/ --include='*.py'
   ```
   Fix any other occurrences using the same pattern. The first positional arg IS the event.
   If you want a human-readable description alongside it, use `msg=`.

**Verify:** Restart the container. Wait for a lifecycle scan to complete (runs every 15 min).
Confirm no `got multiple values for argument 'event'` errors appear in logs.

---

## 3. Fix: SQLite "database is locked" during metrics collection (WARNING)

**File:** `core/database.py`
**Log evidence:**
```
{"event": "metrics_collection_failed", "exception": "...sqlite3.OperationalError: database is locked"}
```
Occurs at `core/metrics_collector.py:147` in `_insert_system_metrics()`.

**Root cause:** Multiple concurrent writers (lifecycle scanner + metrics collector + bulk worker)
without WAL mode or adequate busy timeout. SQLite's default journal mode uses exclusive locks
for writes.

**Fix:** Apply three changes in `core/database.py`:

### 3a. Enable WAL mode at connection time

Find the function that creates/opens the database connection (likely `get_db()` or `init_db()`
or wherever `aiosqlite.connect()` is called). After opening the connection, add:

```python
await conn.execute("PRAGMA journal_mode=WAL")
await conn.execute("PRAGMA busy_timeout=10000")  # 10 second wait before "locked" error
```

If there's a connection factory or helper that all callers use, add it there so every
connection gets WAL mode. WAL mode is persistent (survives restarts once set), but setting
it on every connection is harmless and ensures it's always active.

**Important:** If the code opens connections in multiple places (e.g., a context manager in
`database.py` AND direct `aiosqlite.connect()` calls in other files), add the PRAGMAs to
ALL connection sites. Search with:
```bash
grep -rn 'aiosqlite.connect' core/ api/ --include='*.py'
```

### 3b. Add retry wrapper to metrics collector

**File:** `core/metrics_collector.py`

Find the `_insert_system_metrics()` function (around line 115). Wrap the INSERT in a retry:

```python
import asyncio

MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds

async def _insert_system_metrics(snapshot):
    for attempt in range(MAX_RETRIES):
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute("PRAGMA busy_timeout=10000")
                await conn.execute(
                    "INSERT INTO ...",  # existing INSERT statement
                    (...)               # existing parameters
                )
                await conn.commit()
            return  # success
        except Exception as e:
            if "database is locked" in str(e) and attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                continue
            raise
```

Adapt this to the existing code structure — the INSERT statement and parameters stay the same,
just wrap them in the retry loop.

**Verify:** Run a lifecycle scan while metrics collection is active. Confirm no
`metrics_collection_failed` warnings with `database is locked` in the logs.

---

## 4. Fix: APScheduler `collect_metrics` job overruns (WARNING)

**File:** `core/scheduler.py`
**Log evidence:** 88 skips + 32 misses in a ~17-hour window. The interval was 30s in the
older log entries and 60s in newer entries (after a container restart). Even at 60s the job
gets stuck during bulk operations.

**Fix:** Three changes:

### 4a. Increase interval to 120 seconds

Find the `add_job('collect_metrics', ...)` call. Change the interval:

```python
# BEFORE:
scheduler.add_job(collect_metrics, 'interval', seconds=60, ...)

# AFTER:
scheduler.add_job(collect_metrics, 'interval', seconds=120, id='collect_metrics',
                  max_instances=1, coalesce=True,
                  misfire_grace_time=60)
```

The key additions:
- `seconds=120` — 2 minutes between collections (plenty for metrics)
- `coalesce=True` — if multiple runs were missed, run only once when available
- `misfire_grace_time=60` — don't bother running if it's more than 60s late

### 4b. Verify max_instances is 1

Confirm `max_instances=1` is set. We do NOT want to increase this — two concurrent
metrics collectors would make the SQLite contention worse, not better.

### 4c. Add timeout to the metrics collection function itself

**File:** `core/metrics_collector.py`

If the `collect_metrics()` function doesn't already have a timeout, add one to prevent
it from running indefinitely when SQLite is locked:

```python
import asyncio

async def collect_metrics():
    try:
        await asyncio.wait_for(_do_collect_metrics(), timeout=30.0)
    except asyncio.TimeoutError:
        log.warning("metrics_collection_timeout", msg="Metrics collection timed out after 30s")
    except Exception as e:
        log.warning("metrics_collection_failed", error=str(e))
```

(Adapt `_do_collect_metrics` to whatever the existing function name/structure is.)

**Verify:** After fix, watch logs for 10+ minutes. Confirm no `skipped: maximum number
of running instances reached` warnings for `collect_metrics`.

---

## 5. Fix: DB compaction never runs (WARNING)

**File:** `core/scheduler.py`
**Log evidence:** 5 consecutive deferrals, all with `reason: scan_running`. Lifecycle scans
run every 15 minutes and take 1–60+ minutes (280K files). Compaction retries every 30 minutes
but always finds a scan running.

**Root cause:** The compaction check is:
```python
if scan_is_running():
    log.warning("scheduler.compaction_deferred", reason="scan_running")
    # reschedule in 30 min
    return
```

Since scans run every 15 min and can take over an hour, there's essentially no window where
`scan_is_running()` returns False.

**Fix:** Allow compaction to run concurrently with scans. SQLite VACUUM requires an exclusive
lock, but if we're using WAL mode (Fix #3), we can run `PRAGMA optimize` and cleanup queries
safely alongside reads. If the compaction function uses VACUUM, change it to a lighter
alternative:

```python
async def run_db_compaction():
    """Run DB maintenance. Safe to run alongside scans in WAL mode."""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("PRAGMA busy_timeout=10000")
            # Optimize query planner stats
            await conn.execute("PRAGMA optimize")
            # Reclaim free pages without full VACUUM
            await conn.execute("PRAGMA incremental_vacuum(100)")
            # Analyze tables for query planner
            await conn.execute("PRAGMA analysis_limit=1000")
            await conn.execute("ANALYZE")
            await conn.commit()
        log.info("scheduler.compaction_complete")
    except Exception as e:
        log.warning("scheduler.compaction_failed", error=str(e))
```

Then **remove the `scan_is_running()` guard** that defers compaction. The above operations
are safe to run concurrently.

If the compaction function also purges old records (e.g., deleting old metrics rows or
expired trash), those DELETE queries are fine with WAL mode — just keep the busy_timeout.

**Verify:** After fix, wait for the next compaction window (or trigger manually). Confirm
`scheduler.compaction_complete` appears in logs instead of `scheduler.compaction_deferred`.

---

## 6. Fix: MCP server unreachable (ConnectError)

**Log evidence:**
```
{"event": "connect_tcp.failed exception=ConnectError(OSError('All connection attempts failed'))",
 "http_path": "/api/mcp/connection-info"}
```
Container `markflow-markflow-mcp-1` is running (confirmed via `docker ps`) but port 8001
connections fail inside the main app container.

**Diagnosis:** The MCP server container is up but the main app container can't reach it.
This is likely a Docker networking issue — the containers need to be on the same network
and the main app needs to reference the MCP service by its Docker Compose service name.

**Steps:**

### 6a. Verify Docker Compose networking

Check `docker-compose.yml` for the MCP service definition. It should look something like:

```yaml
services:
  markflow:
    # ... main app
    depends_on:
      - meilisearch
      - markflow-mcp    # should depend on MCP service

  markflow-mcp:
    # ... MCP server
    ports:
      - "8001:8001"
```

Both services must be in the same Docker network (they are by default if in the same
`docker-compose.yml`). The key question is: what hostname does the main app use to
connect to the MCP server?

### 6b. Check the MCP connection URL in the main app

Find where the main app connects to the MCP server. The diagnostic grep from Section 0.1
will show the file and line. The connection URL should use the Docker Compose service name,
NOT `localhost`:

```python
# WRONG — localhost is the markflow container itself, not the MCP container:
MCP_HOST = os.getenv("MCP_HOST", "localhost")

# RIGHT — use the Docker Compose service name:
MCP_HOST = os.getenv("MCP_HOST", "markflow-mcp")
```

### 6c. Check if the MCP container is actually healthy

If the container is running but the process inside has crashed, the container stays "up"
but the port won't respond. Check:

```bash
docker logs markflow-markflow-mcp-1 --tail 50
```

If the MCP server crashed (e.g., the `FastMCP.__init__()` description kwarg bug from
Session #1 that was fixed in the local repo but may not be deployed to the VM), the fix
is in `mcp_server/server.py` — remove the `description=` kwarg from `FastMCP()`.

### 6d. Set the correct environment variable

In `docker-compose.yml`, ensure the main app service has:

```yaml
environment:
  MCP_HOST: markflow-mcp  # Docker Compose service name
  MCP_PORT: 8001
```

Or whatever env vars the main app reads for MCP connection config.

**Verify:** After fix, restart all containers (`docker compose down && docker compose up -d`).
Visit a page that triggers the MCP connection check. Confirm no `ConnectError` in logs and
the MCP connection-info endpoint returns a healthy status.

---

## 7. Fix: Log download fails in browser (UI bug)

**Log evidence:** Repeated rapid-fire requests to `/api/logs/download/markflow.log` (6 requests
in 4 seconds) — the browser retries because the download never completes. Server returns 200
every time but browser shows "Couldn't download".

**Root cause:** The settings page JavaScript uses `fetch()` + `blob URL` + `createObjectURL()`
to trigger the download. This fails for large files when `Content-Length` is missing or when
the response is a streaming response that the blob API can't handle properly.

**Fix:** Two changes — backend and frontend.

### 7a. Backend: Switch to FileResponse

**File:** Find the download endpoint (likely in `api/routes/admin.py` or a dedicated log
route). The diagnostic grep from 0.1 will show the exact file.

Replace the current response with `FileResponse`:

```python
from fastapi.responses import FileResponse
import os

@router.get("/api/logs/download/{filename}")
async def download_log(filename: str):
    # Whitelist allowed filenames
    allowed = {"markflow.log", "markflow-debug.log"}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Log file not found")

    filepath = f"/app/logs/{filename}"
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Log file not found")

    file_size = os.path.getsize(filepath)
    if file_size > 500 * 1024 * 1024:  # 500MB guard
        raise HTTPException(status_code=413, detail="Log file too large for download")

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(file_size),
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
```

### 7b. Frontend: Switch to window.location.href

**File:** `static/settings.html` or `static/settings.js` (wherever the download button
click handler lives).

Replace the fetch+blob approach:

```javascript
// BEFORE (broken):
async function downloadLog(filename) {
    const response = await fetch(`/api/logs/download/${filename}`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

// AFTER (works):
function downloadLog(filename) {
    window.location.href = `/api/logs/download/${filename}`;
}
```

`window.location.href` lets the browser handle the download natively — it reads
`Content-Disposition: attachment` and triggers the save dialog. No blob, no fetch, no loop.

**Verify:** After fix, click both download buttons on the Settings page. Confirm:
- Each button triggers exactly ONE request (check in browser Network tab)
- The file saves to the Downloads folder
- No "Couldn't download" error

---

## 8. Fix: Startup orphan job recovery

**Problem:** When the Docker container restarts mid-job (OOM kill, deploy, crash), `bulk_jobs`
and `scan_runs` records stay in `scanning`/`running`/`pending` status permanently. This causes:
- The stop banner to appear on startup ("Stop requested — jobs are winding down")
- "1 job running" counter to be wrong
- New jobs may be blocked if the code checks for existing running jobs

The current workaround is manual SQL cleanup — this fix automates it.

**Files to modify:** `main.py`, `core/database.py`

### 8a. Add orphan cleanup function to `core/database.py`

Add a new async function:

```python
async def cleanup_orphaned_jobs():
    """Clean up jobs stuck in active states from a previous container run.

    Called once at startup. Any job in scanning/running/pending state when the
    container starts is by definition orphaned — the workers that owned them
    no longer exist.
    """
    log = structlog.get_logger(__name__)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA busy_timeout=10000")

        # Cancel stuck bulk jobs
        cursor = await conn.execute(
            """UPDATE bulk_jobs SET status='cancelled', finished_at=datetime('now')
               WHERE status IN ('scanning', 'running', 'pending')"""
        )
        cancelled_jobs = cursor.rowcount

        # Interrupt stuck scan runs
        cursor = await conn.execute(
            """UPDATE scan_runs SET status='interrupted', finished_at=datetime('now')
               WHERE status='running' AND finished_at IS NULL"""
        )
        interrupted_scans = cursor.rowcount

        await conn.commit()

    if cancelled_jobs or interrupted_scans:
        log.warning("startup.orphan_cleanup",
                    cancelled_jobs=cancelled_jobs,
                    interrupted_scans=interrupted_scans)
    else:
        log.info("startup.orphan_cleanup", msg="No orphaned jobs found")
```

### 8b. Call it from the lifespan function in `main.py`

Find the lifespan function (the `@asynccontextmanager` decorated function, or the `startup`
event handler). Add the cleanup call **before** the scheduler starts:

```python
from core.database import cleanup_orphaned_jobs

# In the lifespan/startup function, BEFORE scheduler.start():
await cleanup_orphaned_jobs()
```

This must run before the scheduler starts lifecycle scans, so the stop controller and
active-job counters see a clean state.

### 8c. Reset the stop flag on startup

Find `core/stop_controller.py`. In the startup path (or add a reset function), ensure
the in-memory stop flag is cleared:

```python
# In stop_controller.py — add or verify this function exists:
def reset_stop():
    """Clear the stop flag. Called at startup."""
    global _stop_requested
    _stop_requested = False
```

Call `reset_stop()` from the lifespan function right after `cleanup_orphaned_jobs()`.

**Verify:** Restart the container. Confirm:
- `startup.orphan_cleanup` appears in logs
- The stop banner does NOT appear on the Status page
- Active Jobs shows "0 jobs running" or "No active jobs"

---

## 9. Fix: Stop banner CSS/JS (Session #1 carry-over)

**Problem:** Even after orphan cleanup clears the DB, the stop banner can stick visible due
to a CSS specificity issue: `.stop-banner { display: flex }` in `markflow.css` overrides
the HTML `hidden` attribute.

**Files:** `static/markflow.css`, `static/status.html` or `static/status.js` (wherever the
banner toggle JS lives)

### 9a. CSS fix

Add to `static/markflow.css`:

```css
.stop-banner[hidden] {
    display: none !important;
}
```

### 9b. JS fix

Find the JavaScript that toggles the stop banner visibility (search for `stopBanner` or
`stop-banner` or `stop_requested`). Change from `hidden` attribute to explicit style toggle:

```javascript
// BEFORE (broken — CSS display:flex overrides hidden):
stopBanner.hidden = !data.stop_requested;

// AFTER (works):
stopBanner.style.display = data.stop_requested ? 'flex' : 'none';
```

Apply this to ALL places that toggle the banner — there may be multiple (the polling
function AND the initial page load).

**Verify:** After container restart (which triggers orphan cleanup), the stop banner should
NOT be visible. Click "Stop All Jobs" → banner appears. Click "Reset & allow new jobs" →
banner disappears.

---

## 10. Feature: Lifecycle scanner progress tracking + ETA

**Problem:** The Status page lifecycle scan card shows only "119,475 files scanned" with no
total count and no time estimate. The progress bar is indeterminate. Users can't tell if a
scan is 10% done or 90% done.

**New file:** `core/progress_tracker.py`
**Modified files:** `core/lifecycle_scanner.py`, `core/database.py`, `api/routes/scanner.py`
(or wherever the scanner progress endpoint lives), `static/status.html` or `static/status.js`

### 10a. Create `core/progress_tracker.py`

```python
"""Progress tracking with rolling-window ETA estimation."""
import time
import asyncio
import os
from collections import deque
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


class RollingWindowETA:
    """Estimates time remaining using a rolling window of recent processing rates.

    Tracks the last N items processed and calculates a smoothed rate to
    predict completion time. More accurate than simple total/elapsed because
    it adapts to changing processing speeds (e.g., faster for small files,
    slower for large ones).
    """

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._timestamps: deque = deque(maxlen=window_size)
        self._start_time: Optional[float] = None
        self._total_items: int = 0
        self._processed_items: int = 0

    def start(self, total_items: int):
        """Begin tracking with a known total."""
        self._total_items = total_items
        self._processed_items = 0
        self._start_time = time.monotonic()
        self._timestamps.clear()

    def tick(self):
        """Record one item processed."""
        self._processed_items += 1
        self._timestamps.append(time.monotonic())

    @property
    def total_items(self) -> int:
        return self._total_items

    @property
    def processed_items(self) -> int:
        return self._processed_items

    @property
    def progress_pct(self) -> float:
        """Progress as a percentage (0.0–100.0)."""
        if self._total_items == 0:
            return 0.0
        return min(100.0, (self._processed_items / self._total_items) * 100.0)

    @property
    def rate_per_second(self) -> float:
        """Items processed per second based on the rolling window."""
        if len(self._timestamps) < 2:
            return 0.0
        window_duration = self._timestamps[-1] - self._timestamps[0]
        if window_duration <= 0:
            return 0.0
        return (len(self._timestamps) - 1) / window_duration

    @property
    def eta_seconds(self) -> Optional[float]:
        """Estimated seconds until completion, or None if unable to estimate."""
        rate = self.rate_per_second
        if rate <= 0 or self._total_items == 0:
            return None
        remaining = self._total_items - self._processed_items
        if remaining <= 0:
            return 0.0
        return remaining / rate

    @property
    def elapsed_seconds(self) -> float:
        """Seconds since start() was called."""
        if self._start_time is None:
            return 0.0
        return time.monotonic() - self._start_time

    def snapshot(self) -> dict:
        """Return current state as a JSON-serializable dict."""
        eta = self.eta_seconds
        return {
            "total_items": self._total_items,
            "processed_items": self._processed_items,
            "progress_pct": round(self.progress_pct, 1),
            "rate_per_second": round(self.rate_per_second, 1),
            "eta_seconds": round(eta, 0) if eta is not None else None,
            "elapsed_seconds": round(self.elapsed_seconds, 0),
        }


async def count_files_fast(directory: str) -> int:
    """Count files in a directory tree using os.scandir for speed.

    Runs in a thread to avoid blocking the event loop. Uses os.scandir()
    instead of os.walk() for better performance on network shares (fewer
    stat calls).
    """
    def _count_sync():
        count = 0
        stack = [directory]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                count += 1
                            elif entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                continue
        return count

    return await asyncio.to_thread(_count_sync)
```

### 10b. Integrate into `core/lifecycle_scanner.py`

Find the main scan function (the one that iterates over files). The diagnostics will show
the exact function name.

**Changes:**

1. Import at the top:
   ```python
   from core.progress_tracker import RollingWindowETA, count_files_fast
   ```

2. Before the file iteration loop starts, count total files and initialize the tracker:
   ```python
   # Count files first (runs in thread, non-blocking)
   source_path = "/mnt/source"  # or however the source path is configured
   total_files = await count_files_fast(source_path)
   log.info("lifecycle_scan.counted", total_files=total_files)

   tracker = RollingWindowETA(window_size=100)
   tracker.start(total_files)
   ```

3. Inside the file iteration loop, after each file is processed, call `tracker.tick()`.

4. Store the tracker instance somewhere accessible to the progress API endpoint. Options:
   - Module-level variable: `_active_tracker: Optional[RollingWindowETA] = None`
   - Pass it to the scan run record in the DB
   - Attach to a shared state object

   The simplest approach is a module-level variable:
   ```python
   _active_tracker: Optional[RollingWindowETA] = None

   def get_active_tracker() -> Optional[RollingWindowETA]:
       return _active_tracker
   ```

   Set `_active_tracker = tracker` when the scan starts, and `_active_tracker = None`
   when it finishes.

### 10c. Update the scanner progress API endpoint

Find the endpoint that serves scanner progress (the diagnostics grep in 0.1 will find it).
It currently returns something like:
```json
{"status": "running", "files_scanned": 119475}
```

Update it to include the tracker snapshot:
```python
from core.lifecycle_scanner import get_active_tracker

@router.get("/api/scanner/progress")
async def scanner_progress():
    tracker = get_active_tracker()
    base_response = {... existing fields ...}

    if tracker:
        base_response.update(tracker.snapshot())
    else:
        # No active scan — return zeros
        base_response.update({
            "total_items": 0,
            "processed_items": 0,
            "progress_pct": 0,
            "rate_per_second": 0,
            "eta_seconds": None,
            "elapsed_seconds": 0,
        })

    return base_response
```

### 10d. Update the Status page frontend

Find the lifecycle scan card in the Status page HTML/JS. Currently it shows:
```
119,475 files scanned
```

Update the display to show:
```
119,475 / 280,749 files scanned (42.5%)
ETA: ~12 min remaining • 156 files/sec
```

**JavaScript changes:**

```javascript
// In the function that updates the lifecycle scan card:
function updateScanProgress(data) {
    const scanned = data.processed_items || data.files_scanned || 0;
    const total = data.total_items || 0;
    const pct = data.progress_pct || 0;
    const rate = data.rate_per_second || 0;
    const etaSec = data.eta_seconds;

    // Update the scanned count
    let text = `${scanned.toLocaleString()}`;
    if (total > 0) {
        text += ` / ${total.toLocaleString()}`;
    }
    text += ' files scanned';
    if (total > 0) {
        text += ` (${pct}%)`;
    }
    scanCountEl.textContent = text;

    // Update the progress bar (make it determinate if we have total)
    if (total > 0) {
        progressBar.style.width = `${pct}%`;
        progressBar.classList.remove('indeterminate');
    }

    // Show ETA line
    let etaText = '';
    if (rate > 0) {
        etaText += `${Math.round(rate)} files/sec`;
    }
    if (etaSec !== null && etaSec !== undefined && etaSec > 0) {
        const minutes = Math.ceil(etaSec / 60);
        if (minutes > 60) {
            const hours = Math.floor(minutes / 60);
            const mins = minutes % 60;
            etaText += ` • ~${hours}h ${mins}m remaining`;
        } else {
            etaText += ` • ~${minutes} min remaining`;
        }
    }
    if (etaText) {
        etaLine.textContent = etaText;
        etaLine.style.display = 'block';
    } else {
        etaLine.style.display = 'none';
    }
}
```

Adapt the element references (`scanCountEl`, `progressBar`, `etaLine`) to match the existing
DOM structure. If there's no ETA line element, add one:

```html
<!-- Inside the lifecycle scan card, after the files-scanned line -->
<p class="scan-eta" style="display:none; color: var(--text-secondary); font-size: 0.85em;"></p>
```

### 10e. Add CSS for determinate progress bar

If the progress bar currently uses an indeterminate animation (CSS shimmer/pulse), add a
class toggle so it becomes a real percentage bar when total is known:

```css
/* In markflow.css */
.scan-progress-bar {
    transition: width 0.5s ease;
}
.scan-progress-bar.indeterminate {
    width: 100% !important;
    animation: shimmer 2s infinite;
}
```

### 10f. DB schema update (optional but recommended)

Add `total_files` and `eta_seconds` columns to `scan_runs` so completed scans show their
final stats on the History page:

In `core/database.py`, in the migration/schema setup section, add:

```python
# Safe migration — these columns may not exist yet
for col, col_type in [("total_files", "INTEGER"), ("eta_seconds", "REAL")]:
    try:
        await conn.execute(f"ALTER TABLE scan_runs ADD COLUMN {col} {col_type}")
    except Exception:
        pass  # Column already exists
```

Update the scan completion code in `core/lifecycle_scanner.py` to write the final values:

```python
# When scan completes:
await conn.execute(
    "UPDATE scan_runs SET total_files=?, eta_seconds=0 WHERE id=?",
    (tracker.total_items, scan_run_id)
)
```

**Verify:** Start a lifecycle scan (or wait for the next scheduled one). Confirm:
- The Status page shows "X / Y files scanned (Z%)"
- A rate and ETA line appears below the count
- The progress bar moves as a percentage, not indeterminate shimmer
- When the scan completes, the card shows 100%

---

## 11. Post-Fix Verification Checklist

After all 10 fixes are applied:

1. `docker compose build && docker compose up -d`
2. Wait 3 minutes for scheduler jobs to run
3. Check logs for each fixed bug:

```bash
# Should return ZERO results for all of these:
docker logs markflow-markflow-1 --since 3m 2>&1 | grep 'no such column'
docker logs markflow-markflow-1 --since 3m 2>&1 | grep 'multiple values for argument'
docker logs markflow-markflow-1 --since 3m 2>&1 | grep 'database is locked'
docker logs markflow-markflow-1 --since 3m 2>&1 | grep 'skipped: maximum number'
docker logs markflow-markflow-1 --since 3m 2>&1 | grep 'compaction_deferred'
docker logs markflow-markflow-1 --since 3m 2>&1 | grep 'connection attempts failed'

# Should show the orphan cleanup ran:
docker logs markflow-markflow-1 --since 3m 2>&1 | grep 'orphan_cleanup'
```

4. Visit Status page:
   - Stop banner is NOT visible
   - Active Jobs shows "0 jobs running" or current actual jobs
   - Lifecycle scan card shows "X / Y files scanned (Z%)" with ETA
5. Visit Settings page → click both log download buttons → confirm files download
6. Visit Admin page → confirm stats load without errors
7. Test stop banner behavior: "Stop All Jobs" → banner appears → "Reset" → banner disappears

---

## 12. Tests

Create `tests/test_bugfix_patch.py`:

```python
"""Tests for v0.12.1 bugfix + stability patch."""
import pytest
import asyncio


class TestAdminStatsNoMissingColumns:
    """Bug 1: admin stats should not reference nonexistent columns."""

    @pytest.mark.asyncio
    async def test_admin_stats_returns_200(self, client):
        """GET /api/admin/stats should succeed without SQL errors."""
        response = await client.get("/api/admin/stats")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_stats_no_provider_type_error(self, client, caplog):
        """Stats endpoint should not log 'no such column: provider_type'."""
        await client.get("/api/admin/stats")
        assert "no such column: provider_type" not in caplog.text

    @pytest.mark.asyncio
    async def test_admin_stats_no_file_size_error(self, client, caplog):
        """Stats endpoint should not log 'no such column: file_size'."""
        await client.get("/api/admin/stats")
        assert "no such column: file_size" not in caplog.text


class TestStructlogEventArg:
    """Bug 2: structlog calls should not pass event as both positional and keyword."""

    def test_lifecycle_scanner_no_double_event(self):
        """Verify lifecycle_scanner.py has no double-event structlog calls."""
        import ast
        with open("core/lifecycle_scanner.py", "r") as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in (
                    "error", "info", "warning", "debug"
                ):
                    has_positional = len(node.args) > 0
                    has_event_kwarg = any(kw.arg == "event" for kw in node.keywords)
                    assert not (has_positional and has_event_kwarg), (
                        f"Line {node.lineno}: structlog call has both positional "
                        f"and event= keyword argument"
                    )

    def test_auto_metrics_aggregator_no_double_event(self):
        """Verify auto_metrics_aggregator.py has no double-event structlog calls."""
        import ast
        with open("core/auto_metrics_aggregator.py", "r") as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in (
                    "error", "info", "warning", "debug"
                ):
                    has_positional = len(node.args) > 0
                    has_event_kwarg = any(kw.arg == "event" for kw in node.keywords)
                    assert not (has_positional and has_event_kwarg), (
                        f"Line {node.lineno}: structlog call has both positional "
                        f"and event= keyword argument"
                    )


class TestSQLiteWALMode:
    """Bug 3: Database should use WAL mode for concurrent access."""

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self):
        """Verify WAL mode is active on the database."""
        import aiosqlite
        from core.database import DB_PATH
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute("PRAGMA journal_mode")
            row = await cursor.fetchone()
            assert row[0].lower() == "wal", f"Expected WAL mode, got {row[0]}"

    @pytest.mark.asyncio
    async def test_busy_timeout_set(self):
        """Verify busy_timeout is set to a reasonable value."""
        import aiosqlite
        from core.database import DB_PATH
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute("PRAGMA busy_timeout")
            row = await cursor.fetchone()
            assert row[0] >= 5000, f"Expected busy_timeout >= 5000, got {row[0]}"


class TestLogDownload:
    """Bug 7: Log download should use FileResponse, not streaming."""

    @pytest.mark.asyncio
    async def test_download_markflow_log(self, client):
        """Download endpoint should return with Content-Disposition header."""
        response = await client.get("/api/logs/download/markflow.log")
        if response.status_code == 200:
            assert "content-disposition" in response.headers
            assert "attachment" in response.headers["content-disposition"]

    @pytest.mark.asyncio
    async def test_download_invalid_filename_rejected(self, client):
        """Download endpoint should reject filenames not in whitelist."""
        response = await client.get("/api/logs/download/../../etc/passwd")
        assert response.status_code in (404, 400, 422)

    @pytest.mark.asyncio
    async def test_download_nonexistent_file(self, client):
        """Download endpoint should 404 for files that don't exist."""
        response = await client.get("/api/logs/download/nonexistent.log")
        assert response.status_code == 404


class TestOrphanCleanup:
    """Fix 8: Startup orphan job recovery."""

    @pytest.mark.asyncio
    async def test_cleanup_orphaned_jobs(self):
        """Verify cleanup_orphaned_jobs cancels stuck jobs."""
        import aiosqlite
        from core.database import DB_PATH, cleanup_orphaned_jobs

        # Insert a fake stuck job
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("PRAGMA busy_timeout=10000")
            await conn.execute(
                """INSERT OR IGNORE INTO bulk_jobs (id, status, source_path, created_at)
                   VALUES ('test_orphan_1', 'running', '/test', datetime('now'))"""
            )
            await conn.commit()

        # Run cleanup
        await cleanup_orphaned_jobs()

        # Verify it was cancelled
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT status FROM bulk_jobs WHERE id='test_orphan_1'"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "cancelled"

            # Clean up test data
            await conn.execute("DELETE FROM bulk_jobs WHERE id='test_orphan_1'")
            await conn.commit()

    @pytest.mark.asyncio
    async def test_cleanup_does_not_touch_completed_jobs(self):
        """Verify cleanup leaves completed/cancelled jobs alone."""
        import aiosqlite
        from core.database import DB_PATH, cleanup_orphaned_jobs

        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("PRAGMA busy_timeout=10000")
            await conn.execute(
                """INSERT OR IGNORE INTO bulk_jobs (id, status, source_path, created_at)
                   VALUES ('test_complete_1', 'completed', '/test', datetime('now'))"""
            )
            await conn.commit()

        await cleanup_orphaned_jobs()

        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT status FROM bulk_jobs WHERE id='test_complete_1'"
            )
            row = await cursor.fetchone()
            assert row[0] == "completed"

            await conn.execute("DELETE FROM bulk_jobs WHERE id='test_complete_1'")
            await conn.commit()


class TestProgressTracker:
    """Fix 10: Rolling window ETA estimation."""

    def test_progress_pct_basic(self):
        """Progress percentage should be accurate."""
        from core.progress_tracker import RollingWindowETA
        tracker = RollingWindowETA(window_size=10)
        tracker.start(100)
        for _ in range(50):
            tracker.tick()
        assert tracker.progress_pct == 50.0

    def test_progress_pct_zero_total(self):
        """Zero total should return 0% not divide-by-zero."""
        from core.progress_tracker import RollingWindowETA
        tracker = RollingWindowETA()
        tracker.start(0)
        assert tracker.progress_pct == 0.0

    def test_eta_returns_none_with_no_data(self):
        """ETA should be None when there's not enough data."""
        from core.progress_tracker import RollingWindowETA
        tracker = RollingWindowETA()
        tracker.start(100)
        assert tracker.eta_seconds is None

    def test_snapshot_returns_dict(self):
        """Snapshot should return a JSON-serializable dict."""
        from core.progress_tracker import RollingWindowETA
        tracker = RollingWindowETA()
        tracker.start(100)
        snap = tracker.snapshot()
        assert isinstance(snap, dict)
        assert "total_items" in snap
        assert "processed_items" in snap
        assert "progress_pct" in snap
        assert "eta_seconds" in snap
        assert snap["total_items"] == 100
        assert snap["processed_items"] == 0

    def test_rate_calculation(self):
        """Rate should be positive after multiple ticks."""
        import time
        from core.progress_tracker import RollingWindowETA
        tracker = RollingWindowETA(window_size=10)
        tracker.start(1000)
        # Simulate rapid ticks
        for _ in range(5):
            tracker.tick()
            time.sleep(0.01)
        assert tracker.rate_per_second > 0

    def test_progress_does_not_exceed_100(self):
        """Progress should cap at 100% even if ticks exceed total."""
        from core.progress_tracker import RollingWindowETA
        tracker = RollingWindowETA()
        tracker.start(10)
        for _ in range(20):
            tracker.tick()
        assert tracker.progress_pct == 100.0

    @pytest.mark.asyncio
    async def test_count_files_fast(self, tmp_path):
        """count_files_fast should count files in a directory tree."""
        from core.progress_tracker import count_files_fast
        # Create test directory structure
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "file1.txt").touch()
        (tmp_path / "a" / "file2.txt").touch()
        (tmp_path / "b").mkdir()
        (tmp_path / "b" / "file3.txt").touch()
        (tmp_path / "file4.txt").touch()

        count = await count_files_fast(str(tmp_path))
        assert count == 4

    @pytest.mark.asyncio
    async def test_count_files_fast_empty_dir(self, tmp_path):
        """count_files_fast should return 0 for empty directory."""
        from core.progress_tracker import count_files_fast
        count = await count_files_fast(str(tmp_path))
        assert count == 0
```

Adapt imports (`client` fixture, `DB_PATH`) to match the existing test infrastructure in
`tests/conftest.py`.

---

## 13. Update CLAUDE.md

After all fixes are verified:

1. Remove the entire "Known Bugs — from log analysis 2026-03-29" section from CLAUDE.md
2. Update the "Current Status" line to `v0.12.1`
3. Add `core/progress_tracker.py` to the Key Files table:
   ```
   | `core/progress_tracker.py` | Rolling-window ETA estimation for scans and bulk jobs |
   ```
4. Add to the Gotchas section in `docs/gotchas.md`:

```markdown
### Startup & Lifecycle
- **Orphan cleanup runs at startup**: `cleanup_orphaned_jobs()` in `core/database.py` cancels
  any bulk_jobs in scanning/running/pending and interrupts any scan_runs still in running state.
  Runs before the scheduler starts. This is why the stop banner doesn't stick after restarts.
- **Stop banner CSS**: `.stop-banner[hidden] { display: none !important; }` in markflow.css.
  JS uses `style.display` not `.hidden` attribute because CSS `display:flex` overrides `hidden`.

### Scanner & Progress
- **RollingWindowETA**: `core/progress_tracker.py`. Window size 100. Call `.tick()` per file.
  `count_files_fast()` uses `os.scandir()` in a thread for the initial count — do NOT use
  `os.walk()` on SMB shares (too many stat calls).
- **Active tracker is module-level**: `core/lifecycle_scanner._active_tracker`. Set to the
  tracker instance during scans, None when idle. The scanner progress API reads it directly.

### Scheduler & Metrics
- **SQLite WAL mode**: Always enabled at connection time. Every `aiosqlite.connect()` call
  must set `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=10000`.
- **collect_metrics interval**: 120s with `coalesce=True`. Do not reduce below 60s —
  causes massive skip storms under bulk load.
- **DB compaction runs concurrently**: No scan-running guard. Uses `PRAGMA optimize` +
  `incremental_vacuum`, not full VACUUM.
- **structlog event arg**: First positional arg IS the event. Never also pass `event=` as kwarg.
  Use `msg=` for human-readable descriptions.
- **Log download**: Uses `FileResponse` + `window.location.href`, NOT fetch+blob.
  The fetch+blob pattern causes download loops on large files.
```

5. Add to `docs/version-history.md`:

```markdown
### v0.12.1 — Bugfix + Stability Patch (2026-03-29)
**Bugfixes (from log analysis):**
- Fixed: admin stats queries referencing nonexistent `provider_type` and `file_size` columns
- Fixed: structlog double `event` argument in lifecycle_scanner and auto_metrics_aggregator
- Fixed: SQLite "database is locked" — enabled WAL mode + busy_timeout + retry on metrics INSERT
- Fixed: collect_metrics interval increased from 30/60s to 120s with coalesce + misfire grace
- Fixed: DB compaction always deferred — removed scan_running guard, switched to incremental vacuum
- Fixed: MCP server unreachable — corrected Docker service hostname + verified container health
- Fixed: Log download loop — switched to FileResponse + window.location.href

**Stability improvements:**
- Added: Startup orphan job recovery — auto-cancels stuck jobs on container start
- Fixed: Stop banner CSS/JS specificity bug — banner no longer sticks after restart
- Added: Lifecycle scanner progress tracking with rolling-window ETA (`core/progress_tracker.py`)
- Added: `count_files_fast()` using os.scandir for fast file counting on SMB shares
- Added: `total_files` and `eta_seconds` columns on `scan_runs` table
- Updated: Status page shows "X / Y files scanned (Z%)" with rate and ETA
```

---

## Done Criteria

- [ ] All 7 log-analysis bugs fixed (diagnostics confirm no regressions)
- [ ] Startup orphan cleanup runs on container start (log entry confirms)
- [ ] Stop banner does NOT appear after clean restart
- [ ] Stop banner correctly appears/disappears when Stop/Reset is clicked
- [ ] Lifecycle scan shows total files, percentage, rate, and ETA on Status page
- [ ] Progress bar is determinate (percentage-based) during active scan
- [ ] `docker compose build` succeeds
- [ ] All existing tests pass (`pytest`)
- [ ] New `tests/test_bugfix_patch.py` tests pass (~25 tests)
- [ ] 3-minute log check shows zero occurrences of all 7 error patterns
- [ ] Settings page log download works in browser
- [ ] Admin stats page loads without errors
- [ ] CLAUDE.md updated (known bugs removed, version bumped, gotchas + history updated)
- [ ] Git commit and tag `v0.12.1`
