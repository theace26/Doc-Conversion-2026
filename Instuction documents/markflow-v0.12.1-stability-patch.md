# MarkFlow v0.12.1 — Stability & Bugfix Patch
# Full Log Analysis Fixes — 2026-03-29 (Supersedes prior draft)

**Version:** Current → v0.12.1  
**Prerequisite:** Current codebase with CLAUDE.md loaded  
**Execution:** Single Claude Code session. Fix in order listed — some fixes depend on earlier ones.  
**Estimated scope:** ~12 targeted fixes across existing files, 1 new file, 1 DB migration, ~30 new tests

---

## ⚠️ READ FIRST — Critical Context

This patch was generated from analysis of **two full log files** covering 19 hours of runtime
(39,276 main log lines + 6,691 debug log lines, March 29 00:00–19:02 UTC). It fixes **every
bug found** across three troubleshooting sessions.

**Ground rules:**
- Load `CLAUDE.md` before writing any code
- Read `docs/gotchas.md` if it exists — especially aiosqlite, structlog, and scheduler sections
- Run the diagnostic in Section 0 FIRST to confirm each bug exists before patching
- Fix in the order listed — later fixes depend on earlier ones
- Do NOT create new files except where explicitly specified
- After all fixes: run full test suite, then update CLAUDE.md

---

## 0. DIAGNOSTIC PASS — Run Before Any Code Changes

Run every command below. Paste the output as a block. Do NOT start fixing until the
diagnostic confirms the bugs. If a diagnostic shows the bug is already fixed (e.g., from
a prior session), skip that fix and move on.

```bash
echo "=== DIAGNOSTIC 1: structlog double event= in auto_metrics_aggregator.py ==="
grep -n 'event=' core/auto_metrics_aggregator.py | head -20

echo ""
echo "=== DIAGNOSTIC 2: structlog double event= in lifecycle_scanner.py ==="
grep -n 'event=' core/lifecycle_scanner.py | head -30

echo ""
echo "=== DIAGNOSTIC 3: SQLite WAL mode check ==="
grep -rn 'journal_mode\|wal\|WAL\|busy_timeout' core/database.py

echo ""
echo "=== DIAGNOSTIC 4: collect_metrics interval ==="
grep -n 'collect_metrics\|interval.*30\|interval.*seconds' core/scheduler.py core/metrics_collector.py 2>/dev/null | head -20

echo ""
echo "=== DIAGNOSTIC 5: Admin stats — missing columns ==="
grep -n 'provider_type\|file_size' api/routes/admin.py | head -10

echo ""
echo "=== DIAGNOSTIC 6: MCP server description kwarg ==="
grep -n 'FastMCP\|description' mcp_server/server.py | head -10

echo ""
echo "=== DIAGNOSTIC 7: Stop banner CSS ==="
grep -n 'stop-banner\|\.stop-banner' static/markflow.css static/styles.css 2>/dev/null | head -10

echo ""
echo "=== DIAGNOSTIC 8: Log file handlers — RotatingFileHandler? ==="
grep -rn 'FileHandler\|RotatingFileHandler' core/logging_config.py | head -10

echo ""
echo "=== DIAGNOSTIC 9: Log download endpoint ==="
grep -n 'download\|FileResponse\|StreamingResponse\|blob\|createObjectURL' api/routes/admin.py api/routes/settings.py static/settings.html 2>/dev/null | head -20

echo ""
echo "=== DIAGNOSTIC 10: Startup lifespan / orphan recovery ==="
grep -n 'lifespan\|startup\|on_startup\|orphan\|cleanup' main.py | head -10

echo ""
echo "=== DIAGNOSTIC 11: Mount readiness check in bulk scanner ==="
grep -n 'mnt/source\|source_path\|os.path.exists\|os.path.isdir\|os.listdir' core/bulk_scanner.py | head -10

echo ""
echo "=== DIAGNOSTIC 12: DB compaction guard ==="
grep -n 'scan_running\|compaction\|vacuum\|VACUUM' core/scheduler.py core/database.py 2>/dev/null | head -15

echo ""
echo "=== DIAGNOSTIC 13: Static file cache headers ==="
grep -rn 'StaticFiles\|cache\|Cache-Control\|no-cache' main.py api/ static/ --include='*.py' 2>/dev/null | head -10

echo ""
echo "=== DIAGNOSTIC 14: Image handler context logging ==="
grep -n 'image_handler.convert_failed\|convert_failed' core/image_handler.py | head -5
```

**STOP HERE.** Paste the diagnostic output. Then proceed fix-by-fix based on what was found.

---

## Fix 1: structlog double `event=` kwarg — auto_metrics_aggregator.py

**Bug:** `BoundLogger.info() got multiple values for argument 'event'`  
**Impact:** Hourly metrics aggregation silently fails (4 occurrences per day)  
**Root cause:** structlog's first positional arg IS the event. Code is also passing `event=` as a keyword argument.

**Log evidence:**
```json
{"error": "BoundLogger.info() got multiple values for argument 'event'", "event": "auto_metrics_aggregation_failed", "level": "error", "logger": "core.auto_metrics_aggregator"}
```

**Pattern to find:** Any call like:
```python
log.info("some_event_name", event="some description", ...)
# or
log.error("some_event_name", event="some description", ...)
```

**Fix:** Rename the `event=` kwarg to `msg=` or `detail=` or remove it entirely:
```python
# BEFORE (broken):
log.info("aggregation_complete", event="Hourly metrics aggregated", rows=count)

# AFTER (fixed):
log.info("aggregation_complete", msg="Hourly metrics aggregated", rows=count)
```

**Search the ENTIRE file** for every `log.info(`, `log.error(`, `log.warning(`, `log.debug(` call
and verify none of them pass `event=` as a kwarg. Fix ALL occurrences, not just the one that
triggered the error.

**Test:**
```python
# In tests/test_bugfix_v0121.py
async def test_structlog_no_double_event_aggregator():
    """Verify auto_metrics_aggregator has no structlog double-event calls."""
    import ast, inspect
    from core import auto_metrics_aggregator
    source = inspect.getsource(auto_metrics_aggregator)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                assert kw.arg != "event", (
                    f"Line {node.lineno}: structlog call uses event= kwarg. "
                    "Use msg= or detail= instead."
                )
```

---

## Fix 2: structlog double `event=` kwarg — lifecycle_scanner.py

**Bug:** `BoundLogger.error() got multiple values for argument 'event'`  
**Impact:** HIGH — This is in the exception handler for auto-convert trigger. It masks the
REAL error that caused auto-convert to fail. Two lifecycle scans found 60,959 and 3,613
new files respectively, decided to convert them, and then crashed — with the real exception
swallowed by the broken error handler.

**Log evidence:**
```json
{"scan_run_id": "c8a20175...", "files_new": 60959, "event": "lifecycle_scan.complete"}
{"decision_mode": "queued", "should_convert": true, "workers": 5, "batch_size": 187, "event": "auto_convert_decision"}
{"error": "BoundLogger.error() got multiple values for argument 'event'", "event": "lifecycle_scan.auto_convert_trigger_failed"}
```

**Fix:** Same pattern as Fix 1 — find every `log.info(`, `log.error(`, `log.warning(`,
`log.debug(` call in `lifecycle_scanner.py` and rename any `event=` kwargs to `msg=` or
`detail=`.

**CRITICAL:** Pay extra attention to the `except` block that handles auto-convert failures.
It likely looks like:
```python
except Exception as e:
    log.error("lifecycle_scan.auto_convert_trigger_failed", event=str(e))
```
Fix to:
```python
except Exception as e:
    log.error("lifecycle_scan.auto_convert_trigger_failed", error=str(e), exc_info=True)
```

Adding `exc_info=True` ensures the full traceback is captured, so next time the auto-convert
trigger fails we'll see the REAL cause.

**Also search these files for the same bug pattern** (they use structlog too):
```bash
grep -rn 'log\.\(info\|error\|warning\|debug\)(.*event=' core/ api/ --include='*.py'
```
Fix ALL occurrences project-wide while you're at it.

**Test:**
```python
async def test_structlog_no_double_event_lifecycle():
    """Verify lifecycle_scanner has no structlog double-event calls."""
    import ast, inspect
    from core import lifecycle_scanner
    source = inspect.getsource(lifecycle_scanner)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                assert kw.arg != "event", (
                    f"Line {node.lineno}: structlog call uses event= kwarg. "
                    "Use msg= or detail= or error= instead."
                )
```

---

## Fix 3: SQLite `database is locked` — WAL mode + busy_timeout + retry

**Bug:** `sqlite3.OperationalError: database is locked`  
**Impact:** 5 bulk worker file conversions failed, 4 metrics collections failed, plus a 45-minute
cascade of 88 skipped `collect_metrics` jobs (the lock caused one instance to hang, and every
subsequent 30s trigger found the previous instance still running).

**Log evidence:**
```json
{"file_id": "3b3d99aa...", "error": "database is locked", "event": "bulk_worker_unhandled"}
{"event": "metrics_collection_failed", "exception": "...sqlite3.OperationalError: database is locked"}
```

### 3a. Enable WAL mode + busy_timeout in database.py

Find the database connection/initialization function in `core/database.py`. It likely has a
function that opens the SQLite connection. Add WAL mode and busy_timeout:

```python
async def get_db():
    """Get database connection with WAL mode and busy timeout."""
    db = await aiosqlite.connect(DB_PATH)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=10000")  # 10 second wait before 'locked' error
    await db.execute("PRAGMA synchronous=NORMAL")   # Safe with WAL, better performance
    db.row_factory = aiosqlite.Row
    return db
```

If there's already a connection function, add the three PRAGMA lines to it. If the app uses
a connection pool or context manager, add the PRAGMAs to the connection factory.

**Important:** Search for ALL places that call `aiosqlite.connect()` in the codebase:
```bash
grep -rn 'aiosqlite.connect' core/ api/ --include='*.py'
```
Every connection point needs the same PRAGMAs.

### 3b. Add retry wrapper for DB writes in bulk_worker.py

Find `core/bulk_worker.py`. Add a retry helper and wrap database writes:

```python
import asyncio

async def _db_write_with_retry(coro_func, *args, max_retries=3, base_delay=0.5, **kwargs):
    """Retry a database write operation on 'database is locked' errors."""
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # exponential backoff
                log.warning("db_write_retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay_seconds=delay,
                    error=str(e))
                await asyncio.sleep(delay)
            else:
                raise
```

Then wrap the critical DB update calls in the bulk worker's per-file processing loop.
Look for calls that update file status (e.g., `UPDATE bulk_files SET status=...`).

### 3c. Add retry to metrics_collector.py

Find the `_insert_system_metrics` function in `core/metrics_collector.py` and wrap the
INSERT in a similar retry:

```python
async def _insert_system_metrics(snapshot, max_retries=3):
    for attempt in range(max_retries):
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute("PRAGMA busy_timeout=10000")
                await conn.execute(
                    "INSERT INTO system_metrics ...",
                    (...)
                )
                await conn.commit()
                return
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                await asyncio.sleep(0.5 * (2 ** attempt))
            else:
                raise
```

**Tests:**
```python
async def test_wal_mode_enabled():
    """Verify WAL journal mode is set on database connections."""
    from core.database import get_db
    db = await get_db()
    cursor = await db.execute("PRAGMA journal_mode")
    row = await cursor.fetchone()
    assert row[0].lower() == "wal"
    await db.close()

async def test_busy_timeout_set():
    """Verify busy_timeout is configured."""
    from core.database import get_db
    db = await get_db()
    cursor = await db.execute("PRAGMA busy_timeout")
    row = await cursor.fetchone()
    assert row[0] >= 5000  # at least 5 seconds
    await db.close()
```

---

## Fix 4: collect_metrics interval — increase to 120s + coalesce

**Bug:** 30s interval causes a skip cascade under load. One stuck instance blocks all
subsequent triggers. 88 consecutive skips observed over 45 minutes.

**Log evidence:** 88 warnings of `maximum number of running instances reached (1)` from
00:43 through 01:28 UTC, then more skips later in the day after the interval was manually
changed to 60s.

**Fix:** Find the scheduler setup in `core/scheduler.py` (or wherever `collect_metrics` is
registered with APScheduler). Change:

```python
# BEFORE:
scheduler.add_job(collect_metrics, 'interval', seconds=30, ...)

# AFTER:
scheduler.add_job(
    collect_metrics,
    'interval',
    seconds=120,
    coalesce=True,
    max_instances=1,
    misfire_grace_time=60,
    id='collect_metrics',
    replace_existing=True,
)
```

- `seconds=120` — 2 minutes between collections (was 30s)
- `coalesce=True` — if multiple runs were missed, only run once when caught up
- `max_instances=1` — already set, but be explicit
- `misfire_grace_time=60` — skip if more than 60s late instead of running anyway

**Test:**
```python
def test_metrics_interval_not_too_tight():
    """Verify collect_metrics runs no more frequently than every 60 seconds."""
    import ast, inspect
    from core import scheduler
    source = inspect.getsource(scheduler)
    # Verify no interval below 60 for collect_metrics
    assert "seconds=30" not in source or "collect_metrics" not in source, \
        "collect_metrics interval must be >= 60 seconds"
```

---

## Fix 5: Admin stats — missing columns migration

**Bug:** Admin stats page queries reference `provider_type` and `file_size` columns that
don't exist in the current SQLite schema.

**Log evidence:**
```json
{"error": "no such column: provider_type", "event": "admin.stats_query_failed"}
{"error": "no such column: file_size", "event": "admin.stats_query_failed"}
```

**Fix — two options (pick based on diagnostic):**

### Option A: The columns should exist — add migration

If the admin stats queries are intentional (the code expects these columns for LLM provider
stats and file size analytics), add the columns to the schema.

Find the database initialization / migration code in `core/database.py`. Add:

```python
# In the migration or table creation section:
try:
    await db.execute("ALTER TABLE conversion_history ADD COLUMN provider_type TEXT DEFAULT NULL")
except Exception:
    pass  # Column already exists

try:
    await db.execute("ALTER TABLE conversion_history ADD COLUMN file_size INTEGER DEFAULT NULL")
except Exception:
    pass  # Column already exists
```

The `try/except` pattern handles both fresh installs (column created by CREATE TABLE) and
existing databases (ALTER TABLE adds it).

### Option B: The queries are premature — guard them

If these columns are planned for a future version and the queries were added prematurely,
wrap them in try/except in `api/routes/admin.py`:

```python
# Find the admin stats queries that reference these columns
# Wrap each in try/except:
try:
    cursor = await db.execute("SELECT provider_type, COUNT(*) ...")
    provider_stats = await cursor.fetchall()
except Exception as e:
    log.debug("admin.stats_column_missing", column="provider_type", error=str(e))
    provider_stats = []
```

**Check which option:** Look at the admin stats code. If the queries are using the data
meaningfully (charts, tables), go with Option A. If they're just COUNT queries that feed
into optional dashboard widgets, Option B is fine.

---

## Fix 6: MCP server crash-loop — remove `description` kwarg

**Bug:** `FastMCP.__init__()` got an unexpected keyword argument 'description'`  
**Impact:** MCP server container restarts every ~30 seconds.

**Fix:** Open `mcp_server/server.py`. Find the `FastMCP(...)` constructor call and remove
the `description` parameter:

```python
# BEFORE:
mcp = FastMCP(
    name="MarkFlow",
    description="MarkFlow document conversion MCP server",
)

# AFTER:
mcp = FastMCP(
    name="MarkFlow",
)
```

**Verify the fix:**
```bash
docker compose up -d --build markflow-mcp
sleep 5
docker ps | grep mcp  # Should show running, not restarting
docker logs doc-conversion-2026-markflow-mcp-1 --tail 10  # Should show clean startup
```

---

## Fix 7: Stop banner CSS/JS specificity bug

**Bug:** The `.stop-banner` has `display: flex` in CSS which overrides the `hidden` HTML
attribute, causing the banner to remain visible even after the stop condition is cleared.

**Fix — CSS:** Find the `.stop-banner` rule in the CSS file (check `static/markflow.css`
or `static/styles.css`). Add:

```css
.stop-banner[hidden] {
    display: none !important;
}
```

**Fix — JS:** Find the JavaScript that shows/hides the stop banner (likely in
`static/status.html` or `static/markflow.js`). Change from using the `hidden` attribute to
using `style.display`:

```javascript
// BEFORE (broken — CSS display:flex overrides hidden attribute):
banner.hidden = false;
banner.hidden = true;

// AFTER (works — direct style override):
banner.style.display = 'flex';   // show
banner.style.display = 'none';   // hide
```

Find ALL places that toggle the banner and update them.

---

## Fix 8: Startup orphan job recovery

**Bug:** When the container restarts mid-job, `bulk_jobs` and `scan_runs` records stay in
`scanning`/`running` status permanently. This causes: (a) the stop banner to appear
incorrectly on fresh starts, (b) DB compaction to be permanently deferred because it sees
`scan_running=true`, and (c) stale progress data in the UI.

**Log evidence:** 5 compaction deferrals from 02:00–04:00 UTC due to `scan_running` from
an orphaned job. The last bulk job (`a9bbc656`) was mid-scan at 19:02 when the container
was killed — now orphaned.

**Fix:** Create a new function in `core/database.py`:

```python
async def cleanup_orphaned_jobs(db=None):
    """Cancel stuck jobs left over from a prior container lifecycle.
    
    Called once during startup, before the scheduler starts.
    """
    close_after = False
    if db is None:
        db = await get_db()
        close_after = True
    
    try:
        # Cancel stuck bulk jobs
        cursor = await db.execute(
            """UPDATE bulk_jobs 
               SET status = 'cancelled', 
                   finished_at = COALESCE(finished_at, datetime('now'))
               WHERE status IN ('scanning', 'running', 'pending')"""
        )
        cancelled_jobs = cursor.rowcount
        
        # Interrupt stuck scan runs
        cursor = await db.execute(
            """UPDATE scan_runs
               SET status = 'interrupted',
                   finished_at = COALESCE(finished_at, datetime('now'))
               WHERE status = 'running' AND finished_at IS NULL"""
        )
        interrupted_scans = cursor.rowcount
        
        await db.commit()
        
        if cancelled_jobs or interrupted_scans:
            log.info("startup_orphan_cleanup",
                cancelled_jobs=cancelled_jobs,
                interrupted_scans=interrupted_scans)
        else:
            log.info("startup_orphan_cleanup", msg="No orphaned jobs found")
            
    finally:
        if close_after:
            await db.close()
```

Then wire it into the app startup. Find `main.py` and the lifespan function:

```python
# In main.py, inside the lifespan function, BEFORE the scheduler starts:
from core.database import cleanup_orphaned_jobs

async def lifespan(app):
    # ... existing startup code ...
    
    # Clean up orphaned jobs from prior container lifecycle
    await cleanup_orphaned_jobs()
    
    # ... then start scheduler ...
    # ... rest of lifespan ...
```

**Test:**
```python
async def test_orphan_cleanup_cancels_stuck_jobs():
    """Startup orphan cleanup should cancel scanning/running/pending jobs."""
    from core.database import get_db, cleanup_orphaned_jobs
    db = await get_db()
    # Insert a fake stuck job
    await db.execute(
        "INSERT INTO bulk_jobs (id, status, source_path, created_at) VALUES (?, ?, ?, datetime('now'))",
        ("test-orphan-1", "running", "/mnt/source")
    )
    await db.commit()
    
    await cleanup_orphaned_jobs(db)
    
    cursor = await db.execute("SELECT status FROM bulk_jobs WHERE id = 'test-orphan-1'")
    row = await cursor.fetchone()
    assert row[0] == "cancelled"
    
    # Clean up
    await db.execute("DELETE FROM bulk_jobs WHERE id = 'test-orphan-1'")
    await db.commit()
    await db.close()

async def test_orphan_cleanup_interrupts_stuck_scans():
    """Startup orphan cleanup should interrupt running scans."""
    from core.database import get_db, cleanup_orphaned_jobs
    db = await get_db()
    await db.execute(
        "INSERT INTO scan_runs (id, status, started_at) VALUES (?, ?, datetime('now'))",
        ("test-scan-orphan-1", "running")
    )
    await db.commit()
    
    await cleanup_orphaned_jobs(db)
    
    cursor = await db.execute("SELECT status, finished_at FROM scan_runs WHERE id = 'test-scan-orphan-1'")
    row = await cursor.fetchone()
    assert row[0] == "interrupted"
    assert row[1] is not None  # finished_at should be set
    
    await db.execute("DELETE FROM scan_runs WHERE id = 'test-scan-orphan-1'")
    await db.commit()
    await db.close()
```

---

## Fix 9: Log file rotation — RotatingFileHandler

**Bug:** Debug log grew to 4GB+ (reported in prior sessions). Using plain `FileHandler`
with no size limit.

**Fix:** Find `core/logging_config.py`. Replace `FileHandler` instances with
`RotatingFileHandler`:

```python
from logging.handlers import RotatingFileHandler

# BEFORE:
handler = logging.FileHandler("/app/logs/markflow.log")
debug_handler = logging.FileHandler("/app/logs/markflow-debug.log")

# AFTER:
handler = RotatingFileHandler(
    "/app/logs/markflow.log",
    maxBytes=50 * 1024 * 1024,   # 50 MB
    backupCount=3,
)
debug_handler = RotatingFileHandler(
    "/app/logs/markflow-debug.log",
    maxBytes=100 * 1024 * 1024,  # 100 MB
    backupCount=2,
)
```

Find ALL `FileHandler` instances in the file and replace them. There may also be handlers
in the structlog configuration.

---

## Fix 10: Mount-readiness guard for bulk scanner

**Bug:** Bulk scan at 17:02 UTC found 0 files in 2ms on `/mnt/source` — the SMB mount was
not ready. Compare to the 19:01 scan which found 29,842 files at the same path. A 0-file
scan completes instantly, reports success, and the user has no idea nothing happened.

**Log evidence:**
```json
{"job_id": "3e5d1686...", "total_discovered": 0, "supported": 0, "duration_ms": 2, "event": "bulk_scan_complete"}
```

**Fix:** In `core/bulk_scanner.py`, add a mount-readiness check before scanning starts:

```python
import os

def _verify_source_mount(source_path: str) -> bool:
    """Verify the source path is mounted and accessible.
    
    Checks that the path exists, is a directory, and contains at least
    one entry (to distinguish a live mount from an empty mountpoint).
    """
    if not os.path.isdir(source_path):
        return False
    try:
        # os.scandir is fast — just check for at least one entry
        with os.scandir(source_path) as it:
            next(it)
            return True
    except (StopIteration, PermissionError, OSError):
        return False
```

Then call it at the top of the scan function:

```python
async def scan_source(job_id: str, source_path: str, ...):
    if not _verify_source_mount(source_path):
        log.error("bulk_scan_mount_not_ready",
            job_id=job_id,
            source_path=source_path,
            msg="Source path is empty or not mounted. Aborting scan.")
        # Update job status to failed
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE bulk_jobs SET status='failed', error='Source mount not ready' WHERE id=?",
                (job_id,))
            await db.commit()
        return
    
    # ... existing scan logic ...
```

**Also add the same guard to the lifecycle scanner** — find `core/lifecycle_scanner.py` and
add the check before it walks the source tree. The lifecycle scanner scans every 15 minutes;
if the mount drops temporarily, it should skip that cycle rather than reporting 0 changes.

**Test:**
```python
def test_mount_readiness_rejects_empty_dir(tmp_path):
    """Mount readiness check should fail for empty directories."""
    from core.bulk_scanner import _verify_source_mount
    empty_dir = tmp_path / "empty_mount"
    empty_dir.mkdir()
    assert _verify_source_mount(str(empty_dir)) is False

def test_mount_readiness_accepts_populated_dir(tmp_path):
    """Mount readiness check should pass for directories with content."""
    from core.bulk_scanner import _verify_source_mount
    populated_dir = tmp_path / "real_mount"
    populated_dir.mkdir()
    (populated_dir / "test_file.txt").write_text("hello")
    assert _verify_source_mount(str(populated_dir)) is True

def test_mount_readiness_rejects_nonexistent():
    """Mount readiness check should fail for nonexistent paths."""
    from core.bulk_scanner import _verify_source_mount
    assert _verify_source_mount("/nonexistent/path/abc123") is False
```

---

## Fix 11: DB compaction — remove scan_running guard

**Bug:** DB compaction was deferred 5 consecutive times (02:00–04:00 UTC) because it checks
for `scan_running` before proceeding. An orphaned job made `scan_running` permanently true.

**Log evidence:**
```json
{"reason": "scan_running", "event": "scheduler.compaction_deferred"}
```

**Fix:** With Fix 8 (orphan recovery) in place, the orphaned-job problem won't persist
across restarts. But the compaction guard is still too aggressive — it blocks on ANY running
scan, even a lightweight lifecycle scan that doesn't write heavily.

In `core/scheduler.py`, find the compaction function. Replace the `scan_running` check with
a lighter guard:

```python
# BEFORE:
if scan_running:
    log.warning("scheduler.compaction_deferred", reason="scan_running")
    return

# AFTER — only defer during active bulk CONVERSION (not scanning/lifecycle):
async def _is_bulk_conversion_active():
    """Check if bulk conversion workers are actively writing."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM bulk_jobs WHERE status = 'running'"
        )
        row = await cursor.fetchone()
        return row[0] > 0

if await _is_bulk_conversion_active():
    log.debug("scheduler.compaction_deferred", reason="bulk_conversion_active")
    return
```

Also switch from full VACUUM to incremental:
```python
# BEFORE:
await db.execute("VACUUM")

# AFTER:
await db.execute("PRAGMA optimize")
await db.execute("PRAGMA incremental_vacuum(1000)")  # Reclaim up to 1000 pages
```

Full VACUUM rewrites the entire DB file and takes an exclusive lock. Incremental vacuum
reclaims free pages without locking out concurrent readers.

---

## Fix 12: Static file cache-control headers

**Bug:** Static files (JS, CSS) are served without cache-control headers. After deploys,
browsers serve stale JavaScript from cache, causing UI bugs.

**Fix:** In `main.py`, find where `StaticFiles` is mounted. Add cache headers via middleware
or by subclassing:

```python
from starlette.staticfiles import StaticFiles
from starlette.middleware import Middleware

# Option A: Custom StaticFiles with no-cache in dev
class NoCacheStaticFiles(StaticFiles):
    async def __call__(self, scope, receive, send):
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                # Add cache-busting headers
                new_headers = list(message.get("headers", []))
                new_headers.append((b"cache-control", b"no-cache, must-revalidate"))
                message["headers"] = new_headers
            await send(message)
        await super().__call__(scope, receive, send_with_headers)

# Replace:
app.mount("/static", StaticFiles(directory="static"), name="static")
# With:
app.mount("/static", NoCacheStaticFiles(directory="static"), name="static")
```

**Alternative (simpler):** Add a global middleware:
```python
@app.middleware("http")
async def add_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response
```

Pick whichever approach fits the existing middleware stack better.

---

## Fix 13: Log download endpoint fix

**Bug:** Settings page log download uses `fetch()` + blob URL pattern which fails without
proper `Content-Length` headers, causing download loops on large files.

**Fix — Backend:** Find the log download endpoint in the API routes. Replace with `FileResponse`:

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
    
    # Size guard — don't serve files > 500MB
    size = os.path.getsize(filepath)
    if size > 500 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Log file too large for download")
    
    return FileResponse(
        filepath,
        media_type="application/octet-stream",
        filename=filename,
    )
```

**Fix — Frontend:** Find the download button handler in `static/settings.html` (or wherever
the settings UI lives). Replace fetch+blob with a simple redirect:

```javascript
// BEFORE (broken):
async function downloadLog(filename) {
    const resp = await fetch(`/api/logs/download/${filename}`);
    const blob = await resp.blob();
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

---

## Fix 14: Image handler — add source document context to log

**Bug:** When an embedded image can't be identified, the log entry doesn't say which source
document contained it. Makes it impossible to track down corrupt files.

**Log evidence:**
```json
{"format": "png", "error": "cannot identify image file <_io.BytesIO object at 0x762bc20aa5c0>", "event": "image_handler.convert_failed"}
```

**Fix:** Find the image conversion error handler in `core/image_handler.py`. Add
`source_path` (or `source_file` or whatever context variable is available) to the log call:

```python
# BEFORE:
log.warning("image_handler.convert_failed", format=fmt, error=str(e))

# AFTER:
log.warning("image_handler.convert_failed",
    format=fmt,
    error=str(e),
    source_path=getattr(self, 'source_path', 'unknown'),
    image_index=idx if 'idx' in dir() else None)
```

The exact variable names depend on what's in scope. Look at the function signature and
local variables to determine what context is available.

---

## 15. New Test File

Create `tests/test_bugfix_v0121.py` with all the tests from the fixes above, plus these
integration tests:

```python
"""Tests for v0.12.1 stability patch."""
import pytest
import ast
import inspect
import os
import glob


class TestStructlogNoDoubleEvent:
    """Verify no structlog calls in the project use event= as a kwarg."""
    
    def _check_file_for_double_event(self, filepath):
        """Check a single Python file for structlog double-event pattern."""
        with open(filepath) as f:
            try:
                tree = ast.parse(f.read())
            except SyntaxError:
                return []  # Skip unparseable files
        
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check if it's a log.xxx() call
                if isinstance(node.func, ast.Attribute) and node.func.attr in (
                    'info', 'error', 'warning', 'debug', 'critical', 'exception'
                ):
                    for kw in node.keywords:
                        if kw.arg == "event":
                            violations.append(
                                f"{filepath}:{node.lineno}: "
                                f"log.{node.func.attr}() uses event= kwarg"
                            )
        return violations
    
    def test_no_double_event_anywhere(self):
        """Scan entire codebase for structlog double-event pattern."""
        violations = []
        for pattern in ["core/*.py", "api/**/*.py", "mcp_server/*.py"]:
            for filepath in glob.glob(pattern, recursive=True):
                violations.extend(self._check_file_for_double_event(filepath))
        
        assert not violations, (
            f"Found {len(violations)} structlog double-event violations:\n"
            + "\n".join(violations)
        )


class TestDatabaseResilience:
    """Test WAL mode, busy_timeout, and orphan cleanup."""
    
    @pytest.mark.asyncio
    async def test_wal_mode(self):
        from core.database import get_db
        db = await get_db()
        cursor = await db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        assert row[0].lower() == "wal"
        await db.close()
    
    @pytest.mark.asyncio
    async def test_busy_timeout(self):
        from core.database import get_db
        db = await get_db()
        cursor = await db.execute("PRAGMA busy_timeout")
        row = await cursor.fetchone()
        assert row[0] >= 5000
        await db.close()


class TestMountReadiness:
    """Test source mount verification."""
    
    def test_empty_dir_rejected(self, tmp_path):
        from core.bulk_scanner import _verify_source_mount
        empty = tmp_path / "empty"
        empty.mkdir()
        assert _verify_source_mount(str(empty)) is False
    
    def test_populated_dir_accepted(self, tmp_path):
        from core.bulk_scanner import _verify_source_mount
        pop = tmp_path / "populated"
        pop.mkdir()
        (pop / "file.txt").write_text("x")
        assert _verify_source_mount(str(pop)) is True
    
    def test_nonexistent_rejected(self):
        from core.bulk_scanner import _verify_source_mount
        assert _verify_source_mount("/no/such/path/xyz") is False


class TestLogRotation:
    """Verify log handlers use rotation."""
    
    def test_no_plain_filehandler(self):
        """logging_config should use RotatingFileHandler, not FileHandler."""
        source = inspect.getsource(__import__('core.logging_config', fromlist=['']))
        # Should have RotatingFileHandler
        assert "RotatingFileHandler" in source, \
            "logging_config must use RotatingFileHandler"
        # FileHandler should only appear as part of RotatingFileHandler
        import re
        plain_fh = re.findall(r'[^a-zA-Z]FileHandler\(', source)
        assert not plain_fh, \
            f"Found plain FileHandler (should be RotatingFileHandler): {plain_fh}"
```

---

## 16. Update CLAUDE.md

After all fixes are verified, update CLAUDE.md:

### Remove from Known Bugs section:
- Bug #2 (MCP crash-loop) → Fixed
- Bug #3 (Static files cache-control) → Fixed
- Bug #4 (Debug log unbounded growth) → Fixed
- Bug #5 (Settings page download loop) → Fixed
- Bug #6 (SQLite database is locked) → Fixed
- Bug #7 (structlog double event=) → Fixed
- Bug #8 (Admin stats missing columns) → Fixed
- Bug #9 (collect_metrics interval too tight) → Fixed

### Remove from Backlog section:
- Startup orphan job recovery → Implemented
- Cache-control headers → Implemented

### Add to Gotchas / docs/gotchas.md:
```markdown
### structlog event argument
The first positional argument to structlog's `log.info()`, `log.error()`, etc. IS the event
name. Never also pass `event=` as a keyword argument — it causes "got multiple values for
argument 'event'" and silently drops the log entry.
- Use `msg=` for human-readable descriptions
- Use `error=` for error messages
- Use `detail=` for additional context

### collect_metrics interval
Minimum interval: 120s with `coalesce=True`. Intervals below 60s cause massive skip storms
under bulk load (88 consecutive skips observed at 30s interval).

### DB compaction
Uses `PRAGMA optimize` + `incremental_vacuum`, NOT full VACUUM. Only deferred during active
bulk conversion (status='running'), not during scanning or lifecycle scans.

### Log download
Uses `FileResponse` + `window.location.href`, NOT fetch+blob. The fetch+blob pattern causes
download loops on large files (>50MB).

### SQLite concurrency
WAL mode + busy_timeout=10000 + PRAGMA synchronous=NORMAL. All connection points must set
these PRAGMAs. Bulk worker DB writes have retry with exponential backoff.

### Source mount verification
Both bulk scanner and lifecycle scanner verify mount readiness before scanning. An empty
mountpoint (SMB not yet connected) is treated as a failed scan, not a 0-file success.
```

### Update version:
```
**Version:** v0.12.1
```

### Add to version history:
```markdown
### v0.12.1 — Stability & Bugfix Patch (2026-03-29)
**Bugfixes (from log analysis — 3 troubleshooting sessions):**
- Fixed: structlog double `event=` kwarg in auto_metrics_aggregator.py AND lifecycle_scanner.py
  (the lifecycle_scanner bug was masking auto-convert trigger failures — 64K files silently skipped)
- Fixed: SQLite "database is locked" — WAL mode + busy_timeout=10000 + retry wrapper
- Fixed: collect_metrics interval increased from 30s to 120s with coalesce + misfire grace
- Fixed: Admin stats queries referencing nonexistent provider_type and file_size columns
- Fixed: MCP server crash-loop — removed unsupported description kwarg from FastMCP init
- Fixed: Stop banner CSS/JS specificity — banner no longer sticks after container restart
- Fixed: Log file unbounded growth — switched to RotatingFileHandler (50MB main, 100MB debug)
- Fixed: Settings page log download loop — FileResponse + window.location.href
- Fixed: DB compaction permanently deferred by orphaned jobs — relaxed guard + incremental vacuum
- Fixed: Static files served without cache-control headers
- Fixed: Image handler error log missing source document context

**Stability improvements:**
- Added: Startup orphan job recovery — auto-cancels stuck jobs on container start
- Added: Mount-readiness guard — bulk scanner and lifecycle scanner verify source mount before scanning
- Added: 30 new tests in test_bugfix_v0121.py
```

---

## Done Criteria

- [ ] Diagnostic pass completed — all bugs confirmed before fixing
- [ ] Fix 1: No structlog double `event=` in auto_metrics_aggregator.py
- [ ] Fix 2: No structlog double `event=` in lifecycle_scanner.py (or anywhere else project-wide)
- [ ] Fix 3: WAL mode + busy_timeout enabled on all DB connections; retry wrapper on bulk worker + metrics
- [ ] Fix 4: collect_metrics interval = 120s with coalesce=True
- [ ] Fix 5: Admin stats page loads without column errors
- [ ] Fix 6: MCP server starts clean (no crash-loop)
- [ ] Fix 7: Stop banner hidden correctly on clean start, shows/hides on stop/reset
- [ ] Fix 8: Startup orphan cleanup runs — log shows `startup_orphan_cleanup` on boot
- [ ] Fix 9: Log handlers are RotatingFileHandler (verify with diagnostic grep)
- [ ] Fix 10: Bulk scan on empty mount fails gracefully with `bulk_scan_mount_not_ready`
- [ ] Fix 11: DB compaction only defers during active bulk conversion, uses incremental vacuum
- [ ] Fix 12: Static files have `Cache-Control: no-cache` headers
- [ ] Fix 13: Log download works in browser (verify manually)
- [ ] Fix 14: Image handler errors include source document path
- [ ] All existing tests pass (`pytest`)
- [ ] New `tests/test_bugfix_v0121.py` tests pass (~30 tests)
- [ ] 3-minute runtime log check shows zero occurrences of all error patterns
- [ ] CLAUDE.md updated — bugs removed, gotchas added, version bumped, history updated
- [ ] Git commit and tag `v0.12.1`
