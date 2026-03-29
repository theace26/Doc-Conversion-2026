# MarkFlow Patch — Log Issue Resolution
**Session type:** Bug fixes from log analysis
**Source files:** `markflow-error-extract.md`, `markflow-warning-extract.md`
**Log window:** 2026-03-29 00:00–02:20 (~2.3 hours, 20.5M lines)
**Estimated scope:** 5 fixes across 4 files — all small, no architectural changes

---

## Overview of Issues

| # | Issue | Severity | Root Cause |
|---|-------|----------|------------|
| 1 | SQLite DB locked during bulk jobs | ERROR | 4 concurrent workers competing for 1 writer |
| 2 | `auto_metrics_aggregation_failed` | ERROR | structlog `event=` passed as both positional and kwarg |
| 3 | Admin stats missing columns | WARNING | `provider_type` and `file_size` not in schema |
| 4 | `collect_metrics` stalls under bulk load | WARNING | 30s interval too tight; cascades from issue #1 |
| 5 | Corrupt PNG images not attributed | WARNING | Source document path not logged on failure |

Issue #6 (`scheduler.compaction_deferred`) is **working as designed** — no fix needed.

---

## Fix 1 — SQLite Write Contention (Root Cause)

**File:** `core/database.py` and/or `core/bulk_worker.py`

### Step 1 — Read current DB connection setup

```bash
grep -n "connect\|busy_timeout\|timeout\|WAL\|journal" core/database.py
```

### Step 2 — Add busy timeout and WAL mode

In `core/database.py`, find where the aiosqlite connection is created or configured.
Add these two PRAGMAs immediately after the connection is established:

```python
await db.execute("PRAGMA journal_mode = WAL")
await db.execute("PRAGMA busy_timeout = 10000")  # 10 seconds
```

WAL mode (Write-Ahead Logging) allows one writer and multiple concurrent readers
without blocking. This is the single most impactful fix — it eliminates most lock
contention for the async workload pattern.

`busy_timeout = 10000` means SQLite will retry for up to 10 seconds before raising
`OperationalError: database is locked` instead of failing immediately.

### Step 3 — Add retry wrapper in `core/bulk_worker.py`

Find the DB write calls inside the worker loop (wherever `bulk_files` status is
updated after conversion). Wrap them with a retry helper:

```python
import asyncio
from sqlite3 import OperationalError

async def _db_write_with_retry(fn, retries=3, base_delay=0.5):
    """Retry a DB write on lock contention with exponential backoff."""
    for attempt in range(retries):
        try:
            return await fn()
        except OperationalError as e:
            if "database is locked" in str(e) and attempt < retries - 1:
                delay = base_delay * (2 ** attempt)
                log.warning("db_write_retry",
                            attempt=attempt + 1,
                            delay=delay,
                            error=str(e))
                await asyncio.sleep(delay)
            else:
                raise
```

Replace bare DB writes in the worker with:
```python
await _db_write_with_retry(lambda: update_file_status(db, file_id, "converted"))
```

### Step 4 — Verify

After applying, start a bulk job and check logs:
```powershell
docker logs doc-conversion-2026-markflow-1 --follow | findstr "locked\|retry"
```
Should see zero `database is locked` errors. Retries may appear briefly under load
but should succeed within 1–2 attempts.

---

## Fix 2 — `auto_metrics_aggregation_failed` (structlog double event)

**File:** `core/auto_metrics_aggregator.py`

### Step 1 — Find the bad call

```bash
grep -n "\.info\|\.warning\|\.error\|\.debug" core/auto_metrics_aggregator.py
```

Look for any call that passes `event=` as a keyword argument. Structlog uses `event`
as its first positional parameter — passing it again as a keyword causes:
`BoundLogger.info() got multiple values for argument 'event'`

The pattern will look like this:

```python
# BAD — event is both the positional arg AND a keyword
log.info("auto_metrics_aggregation_failed", event=some_variable)

# Also bad:
log.info("some_label", event="auto_metrics_aggregation_failed")
```

### Step 2 — Fix the call

Rename the conflicting kwarg to something non-reserved:

```python
# GOOD — use a different key for the data you were passing
log.info("auto_metrics_aggregation_failed", metric_event=some_variable)

# Or if the first arg was supposed to be the event name, just remove the kwarg:
log.info("auto_metrics_aggregation_failed", result=some_variable)
```

The structlog convention is: first positional arg = the event name (string label),
all subsequent kwargs = structured fields. Never use `event=` as a kwarg.

### Step 3 — Verify

```powershell
docker logs doc-conversion-2026-markflow-1 --follow | findstr "auto_metrics_aggregation_failed"
```

The error fires every hour at :05. After fixing, the next :05 mark should show
`auto_metrics_aggregation_complete` (or similar success event) instead.

---

## Fix 3 — Admin Stats Missing Columns

**Files:** `api/routes/admin.py` and `core/database.py`

### Step 1 — Find the broken queries

```bash
grep -n "provider_type\|file_size" api/routes/admin.py core/database.py
```

### Step 2 — Check actual schema

```powershell
$check = @'
import sqlite3
conn = sqlite3.connect('/app/data/markflow.db')
cur = conn.cursor()
cur.execute("PRAGMA table_info(bulk_files)")
print("bulk_files columns:")
for r in cur.fetchall():
    print(f"  {r[1]} ({r[2]})")
cur.execute("PRAGMA table_info(llm_providers)")
print("\nllm_providers columns:")
for r in cur.fetchall():
    print(f"  {r[1]} ({r[2]})")
'@
$check | docker exec -i doc-conversion-2026-markflow-1 python -
```

### Step 3 — Decide: fix query or add columns

**Option A — Fix the query** (if columns were renamed):
Update the stats query in `api/routes/admin.py` to use whatever column name
actually exists in the schema.

**Option B — Add missing columns via migration** (if columns should exist):
In `core/database.py`, find the `CREATE TABLE` or migration section and add:

For `bulk_files`:
```sql
ALTER TABLE bulk_files ADD COLUMN file_size INTEGER;
```

For `llm_providers` (or wherever `provider_type` should live):
```sql
ALTER TABLE llm_providers ADD COLUMN provider_type TEXT;
```

Add these as conditional migrations that run at startup:
```python
async def run_migrations(db):
    # Add file_size to bulk_files if missing
    try:
        await db.execute("ALTER TABLE bulk_files ADD COLUMN file_size INTEGER")
        await db.commit()
        log.info("migration.added_column", table="bulk_files", column="file_size")
    except Exception:
        pass  # Column already exists

    # Add provider_type to llm_providers if missing
    try:
        await db.execute("ALTER TABLE llm_providers ADD COLUMN provider_type TEXT")
        await db.commit()
        log.info("migration.added_column", table="llm_providers", column="provider_type")
    except Exception:
        pass  # Column already exists
```

Call `run_migrations(db)` in the app lifespan startup.

### Step 4 — Verify

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/admin/stats" | ConvertTo-Json -Depth 5
```

Should return a valid response with no `stats_query_failed` in logs.

---

## Fix 4 — `collect_metrics` Stalling Under Bulk Load

**File:** Wherever APScheduler jobs are registered (likely `core/scheduler.py`)

### Step 1 — Find the metrics job registration

```bash
grep -n "collect_metrics\|add_job\|interval" core/scheduler.py
```

### Step 2 — Increase interval and add coalesce

Find the `collect_metrics` job registration. Change the interval and add coalesce:

```python
# BEFORE
scheduler.add_job(collect_metrics, 'interval', seconds=30, id='collect_metrics')

# AFTER
scheduler.add_job(
    collect_metrics,
    'interval',
    seconds=60,           # Double the interval — gives headroom under load
    id='collect_metrics',
    max_instances=1,      # Already default, make it explicit
    coalesce=True,        # If multiple fires missed, run once on recovery
    misfire_grace_time=30 # Allow up to 30s late before considering it a skip
)
```

### Step 3 — Optimize the metrics query (if possible)

```bash
grep -n "def collect_metrics" core/scheduler.py core/auto_metrics_aggregator.py
```

If the query does a full table scan on `bulk_files` (large table during bulk jobs),
add a limit or restrict to recent records:

```python
# Instead of scanning all bulk_files, only look at last 24h
WHERE converted_at > datetime('now', '-24 hours')
```

### Step 4 — Verify

Under a running bulk job, confirm metrics no longer stall:
```powershell
docker logs doc-conversion-2026-markflow-1 --follow | findstr "collect_metrics"
```

Should see `collect_metrics` firing at ~60s intervals with no `skipped` warnings.

---

## Fix 5 — Corrupt PNG Logging (Attribution)

**File:** `core/image_handler.py`

### Step 1 — Find the current error handler

```bash
grep -n "cannot identify\|UnidentifiedImageError\|Image.open\|BytesIO" core/image_handler.py
```

### Step 2 — Add source attribution to the log call

The current warning logs the BytesIO address (useless). Update to log the source
document path and image index so corrupt images can be traced back to their origin:

```python
# BEFORE
log.warning("image_handler.convert_failed",
            format=fmt,
            error=str(e))

# AFTER
from PIL import UnidentifiedImageError

try:
    img = Image.open(image_bytes)
    # ... rest of handling
except (UnidentifiedImageError, Exception) as e:
    log.warning("image_handler.convert_failed",
                format=fmt,
                source_document=source_path,   # Pass this in from caller
                image_index=image_index,        # Pass this in from caller
                error=str(e))
    return None  # or however the function signals failure
```

The caller that extracts images from documents needs to pass `source_path` and
`image_index` into the image handler. Find the call site:

```bash
grep -rn "image_handler\|convert_image\|process_image" core/ --include="*.py"
```

Update the call to pass the document path through.

---

## Done Criteria

- [ ] Bulk jobs run without any `database is locked` errors in logs
- [ ] `auto_metrics_aggregation_failed` no longer appears in hourly logs
- [ ] `GET /api/admin/stats` returns 200 with no `stats_query_failed` warnings
- [ ] `collect_metrics` fires on 60s interval with no skipped warnings during bulk jobs
- [ ] PNG failures log the source document path instead of a BytesIO address

## Do NOT change in this session

- Bulk job scan/conversion logic
- Meilisearch indexing
- Lifecycle scanner
- MCP server
- Any Phase 8 files
- CLAUDE.md (update only after all 5 fixes verified)
