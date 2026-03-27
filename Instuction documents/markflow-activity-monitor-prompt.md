# MarkFlow — Resources Page & Resource History

> Target version: **v0.9.6**
> Scope: New metrics collector, new SQLite table, new Resources page, new API endpoints,
>   admin page disk usage section, nav changes
> Read `CLAUDE.md` before starting.
> This is a large feature — work through it section by section. All sections
> must be complete before tagging.

---

## Purpose

This feature builds a **resource monitoring and activity history system** that proves
MarkFlow is a well-behaved, low-impact program. The primary audience is an IT
administrator who needs evidence that MarkFlow won't disrupt other services on a
shared in-house server.

The deliverable is a new **Resources** page (visible in the top nav) that shows:
1. An **Executive Summary** card — the "elevator pitch" for IT
2. **Historical charts** — CPU, memory, disk over time with task correlation
3. **Live system metrics** — moved from Admin page (CPU bars, memory gauge)
4. **Repository overview** — copied from Admin page (file counts, format stats)
5. **Activity log** — what MarkFlow was doing at each point in time

---

## Architecture Overview

```
┌─────────────────────────────────┐
│  APScheduler                     │
│  ┌───────────────────────────┐  │
│  │ collect_metrics()         │  │  ← every 30 seconds
│  │  psutil → system_metrics  │  │
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │ collect_disk_snapshot()   │  │  ← every 6 hours
│  │  dir walks → disk_metrics │  │
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │ purge_old_metrics()       │  │  ← daily at 03:00
│  │  DELETE WHERE age > 90d   │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│  Activity Events (written by     │
│  bulk_worker, lifecycle_scanner, │
│  converter, scheduler)           │
│  ┌───────────────────────────┐  │
│  │ record_activity_event()   │  │  ← on task start/end/error
│  │  → activity_events table  │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

---

## Part 1: Database Schema

### New file: `core/metrics_collector.py`

This module owns the schema, the collection logic, and the query helpers.

### Table: `system_metrics`

```sql
CREATE TABLE IF NOT EXISTS system_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- CPU
    cpu_percent_total REAL NOT NULL,         -- process CPU % (all cores combined)
    cpu_percent_system REAL NOT NULL,        -- system-wide CPU %
    cpu_count INTEGER NOT NULL,              -- logical core count
    -- Memory
    mem_rss_bytes INTEGER NOT NULL,          -- MarkFlow process RSS
    mem_rss_percent REAL NOT NULL,           -- RSS as % of total system RAM
    mem_system_total_bytes INTEGER NOT NULL,  -- total system RAM
    mem_system_used_percent REAL NOT NULL,    -- system-wide memory %
    -- I/O (cumulative counters — delta computed at query time)
    io_read_bytes INTEGER,                   -- process cumulative disk reads
    io_write_bytes INTEGER,                  -- process cumulative disk writes
    -- Threads
    thread_count INTEGER NOT NULL,           -- MarkFlow process thread count
    -- Active tasks (snapshot at collection time)
    active_bulk_jobs INTEGER NOT NULL DEFAULT 0,
    active_lifecycle_scan INTEGER NOT NULL DEFAULT 0,  -- 0 or 1
    active_conversions INTEGER NOT NULL DEFAULT 0       -- single-file conversions in progress
);

CREATE INDEX IF NOT EXISTS idx_system_metrics_ts ON system_metrics(timestamp);
```

### Table: `disk_metrics`

Collected less frequently (every 6 hours) because directory walks are expensive.

```sql
CREATE TABLE IF NOT EXISTS disk_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- Per-directory sizes (bytes)
    output_repo_bytes INTEGER NOT NULL DEFAULT 0,
    output_repo_files INTEGER NOT NULL DEFAULT 0,
    trash_bytes INTEGER NOT NULL DEFAULT 0,
    trash_files INTEGER NOT NULL DEFAULT 0,
    conversion_output_bytes INTEGER NOT NULL DEFAULT 0,
    conversion_output_files INTEGER NOT NULL DEFAULT 0,
    database_bytes INTEGER NOT NULL DEFAULT 0,        -- .db + .wal + .shm
    logs_bytes INTEGER NOT NULL DEFAULT 0,
    meilisearch_bytes INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    -- Volume info
    volume_total_bytes INTEGER NOT NULL DEFAULT 0,
    volume_used_bytes INTEGER NOT NULL DEFAULT 0,
    volume_free_bytes INTEGER NOT NULL DEFAULT 0,
    volume_used_percent REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_disk_metrics_ts ON disk_metrics(timestamp);
```

### Table: `activity_events`

Records what MarkFlow was actually *doing* at notable moments. This is the
correlation layer — it ties resource usage to specific tasks.

```sql
CREATE TABLE IF NOT EXISTS activity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    event_type TEXT NOT NULL,         -- 'bulk_start', 'bulk_end', 'lifecycle_scan_start',
                                      -- 'lifecycle_scan_end', 'conversion_start',
                                      -- 'conversion_end', 'index_rebuild', 'db_maintenance',
                                      -- 'error', 'startup', 'shutdown'
    description TEXT NOT NULL,        -- human-readable: "Bulk job started: 12,450 files from Engineering Share"
    metadata TEXT,                    -- JSON blob: {"job_id": "...", "file_count": 12450, ...}
    duration_seconds REAL             -- filled on _end events, NULL on _start events
);

CREATE INDEX IF NOT EXISTS idx_activity_events_ts ON activity_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_activity_events_type ON activity_events(event_type);
```

Add all three tables in `core/database.py` → `_ensure_schema()`, following the
existing pattern (CREATE TABLE IF NOT EXISTS, then any ALTER TABLE additions).

---

## Part 2: Metrics Collector — `core/metrics_collector.py`

### Collection functions

```python
import psutil
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

import structlog
import aiosqlite

logger = structlog.get_logger(__name__)

_process = None  # cached psutil.Process — set on first call

def _get_process() -> psutil.Process:
    global _process
    if _process is None:
        _process = psutil.Process(os.getpid())
    return _process


def _human_bytes(n: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def _collect_system_snapshot() -> dict:
    """Collect a point-in-time system metrics snapshot. Runs in thread."""
    proc = _get_process()
    with proc.oneshot():
        cpu_proc = proc.cpu_percent(interval=None)  # non-blocking (primed at startup)
        mem_info = proc.memory_info()
        try:
            io_counters = proc.io_counters()
            io_read = io_counters.read_bytes
            io_write = io_counters.write_bytes
        except (psutil.AccessDenied, AttributeError):
            io_read = None
            io_write = None
        threads = proc.num_threads()

    cpu_system = psutil.cpu_percent(interval=None)
    cpu_count = psutil.cpu_count(logical=True)
    mem_sys = psutil.virtual_memory()

    return {
        "cpu_percent_total": cpu_proc,
        "cpu_percent_system": cpu_system,
        "cpu_count": cpu_count,
        "mem_rss_bytes": mem_info.rss,
        "mem_rss_percent": round(mem_info.rss / mem_sys.total * 100, 2),
        "mem_system_total_bytes": mem_sys.total,
        "mem_system_used_percent": mem_sys.percent,
        "io_read_bytes": io_read,
        "io_write_bytes": io_write,
        "thread_count": threads,
    }


def _collect_disk_snapshot() -> dict:
    """Walk MarkFlow directories and measure sizes. Runs in thread."""
    # Same logic as the disk-usage endpoint (Part 5), but returns a flat dict
    # for insertion into disk_metrics table.
    # ... (implementation follows same pattern as disk-usage prompt)
    # Key: Trash is subtracted from output-repo to avoid double-counting.
    pass  # Full implementation in the prompt below
```

### Active task counts

At snapshot time, query the in-memory state to determine what's running:

```python
async def _get_active_task_counts() -> dict:
    """Count currently active tasks from the running app."""
    from core.bulk_worker import get_all_jobs    # existing function
    from core.lifecycle_scanner import get_scan_state  # existing function
    from core.converter import _progress_queues  # existing module-level dict

    jobs = get_all_jobs()
    active_bulk = sum(1 for j in jobs.values() if j.status in ("running", "paused"))
    scan_state = get_scan_state()
    active_scan = 1 if scan_state.get("running", False) else 0
    active_conv = len(_progress_queues)

    return {
        "active_bulk_jobs": active_bulk,
        "active_lifecycle_scan": active_scan,
        "active_conversions": active_conv,
    }
```

### Scheduled collection

```python
async def collect_metrics():
    """Called by APScheduler every 30 seconds."""
    try:
        snapshot = await asyncio.to_thread(_collect_system_snapshot)
        tasks = await _get_active_task_counts()
        snapshot.update(tasks)
        await _insert_system_metrics(snapshot)
    except Exception:
        logger.warning("metrics_collection_failed", exc_info=True)


async def collect_disk_snapshot():
    """Called by APScheduler every 6 hours."""
    try:
        disk = await asyncio.to_thread(_collect_disk_snapshot)
        await _insert_disk_metrics(disk)
    except Exception:
        logger.warning("disk_metrics_collection_failed", exc_info=True)


async def purge_old_metrics():
    """Called by APScheduler daily. Delete metrics older than 90 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM system_metrics WHERE timestamp < ?", (cutoff,))
        await conn.execute("DELETE FROM disk_metrics WHERE timestamp < ?", (cutoff,))
        await conn.execute("DELETE FROM activity_events WHERE timestamp < ?", (cutoff,))
        await conn.commit()
    logger.info("metrics_purged", cutoff=cutoff)
```

### Activity event recording

A simple helper that any module can import:

```python
async def record_activity_event(
    event_type: str,
    description: str,
    metadata: dict | None = None,
    duration_seconds: float | None = None,
):
    """Record a notable activity event."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """INSERT INTO activity_events
               (event_type, description, metadata, duration_seconds)
               VALUES (?, ?, ?, ?)""",
            (event_type, description, json.dumps(metadata) if metadata else None, duration_seconds),
        )
        await conn.commit()
```

---

## Part 3: Scheduler Integration

In `core/scheduler.py`, add three new scheduled jobs alongside the existing ones:

```python
from core.metrics_collector import collect_metrics, collect_disk_snapshot, purge_old_metrics

# In start_scheduler():
scheduler.add_job(collect_metrics, "interval", seconds=30, id="collect_metrics",
                  max_instances=1, misfire_grace_time=10)
scheduler.add_job(collect_disk_snapshot, "interval", hours=6, id="collect_disk_snapshot",
                  max_instances=1, misfire_grace_time=300)
scheduler.add_job(purge_old_metrics, "cron", hour=3, id="purge_old_metrics",
                  max_instances=1)
```

In `main.py` lifespan, after the existing psutil prime call, fire an immediate
disk snapshot so the Resources page has data on first load:

```python
asyncio.create_task(collect_disk_snapshot())
```

Also record startup/shutdown activity events in lifespan:

```python
# In lifespan(), after scheduler starts:
await record_activity_event("startup", "MarkFlow started", {
    "version": "v0.9.6",
    "cpu_count": psutil.cpu_count(logical=True),
    "ram_total": psutil.virtual_memory().total,
})

# In lifespan() cleanup (after yield):
await record_activity_event("shutdown", "MarkFlow shutting down")
```

---

## Part 4: Activity Event Instrumentation

Add `record_activity_event()` calls to existing modules. These are one-line
additions — do not refactor the existing code.

### `core/bulk_worker.py`

At job start (in `BulkJob.run()` or equivalent, after the scan completes):
```python
await record_activity_event("bulk_start", f"Bulk job started: {total_files} files from {source_name}", {
    "job_id": self.job_id, "file_count": total_files, "source": str(self.source_path)
})
```

At job end (in the finally block or completion handler):
```python
await record_activity_event("bulk_end", f"Bulk job completed: {converted}/{total} files in {elapsed}s", {
    "job_id": self.job_id, "converted": converted, "failed": failed,
    "skipped": skipped, "duration": elapsed
}, duration_seconds=elapsed)
```

### `core/lifecycle_scanner.py`

At scan start (in `run_lifecycle_scan()` after `_scan_state` is set to running):
```python
await record_activity_event("lifecycle_scan_start", "Lifecycle scan started")
```

At scan end:
```python
await record_activity_event("lifecycle_scan_end", f"Lifecycle scan: {scanned} files, {new} new, {modified} modified, {deleted} deleted", {
    "scanned": scanned, "new": new, "modified": modified, "deleted": deleted,
    "errors": errors, "duration": elapsed
}, duration_seconds=elapsed)
```

### `core/scheduler.py`

At DB maintenance:
```python
await record_activity_event("db_maintenance", "Scheduled DB maintenance (VACUUM/integrity check)")
```

### `core/search_indexer.py`

At index rebuild:
```python
await record_activity_event("index_rebuild", f"Meilisearch index rebuild: {doc_count} documents")
```

---

## Part 5: API Endpoints

### New route file: `api/routes/resources.py`

Create a new router with prefix `/api/resources`. All endpoints require `MANAGER`
role minimum (not `ADMIN` — the IT admin may have manager access, not full admin).

**Endpoints:**

#### `GET /api/resources/metrics`

Historical system metrics with time range and downsampling.

Query params:
- `range`: `"1h"`, `"6h"`, `"24h"`, `"7d"`, `"30d"`, `"90d"` (default `"24h"`)
- `resolution`: `"raw"`, `"1m"`, `"5m"`, `"15m"`, `"1h"`, `"6h"` (default: auto based on range)

Auto-resolution mapping:
| Range  | Default Resolution | Approx Points |
|--------|--------------------|---------------|
| 1h     | raw (30s)          | 120           |
| 6h     | 1m                 | 360           |
| 24h    | 5m                 | 288           |
| 7d     | 15m                | 672           |
| 30d    | 1h                 | 720           |
| 90d    | 6h                 | 360           |

For downsampled resolutions, use SQL `GROUP BY` with `strftime` bucketing and
report `AVG()` for percent metrics and `MAX()` for byte/count metrics:

```sql
SELECT
    strftime('%Y-%m-%dT%H:%M:00Z', timestamp) AS bucket,
    AVG(cpu_percent_total) AS cpu_percent_total,
    MAX(cpu_percent_total) AS cpu_peak,
    AVG(cpu_percent_system) AS cpu_percent_system,
    AVG(mem_rss_bytes) AS mem_rss_bytes,
    MAX(mem_rss_bytes) AS mem_rss_peak,
    AVG(mem_rss_percent) AS mem_rss_percent,
    AVG(mem_system_used_percent) AS mem_system_used_percent,
    MAX(io_read_bytes) AS io_read_bytes,
    MAX(io_write_bytes) AS io_write_bytes,
    MAX(thread_count) AS thread_count,
    MAX(active_bulk_jobs) AS active_bulk_jobs,
    MAX(active_lifecycle_scan) AS active_lifecycle_scan,
    MAX(active_conversions) AS active_conversions
FROM system_metrics
WHERE timestamp >= ?
GROUP BY bucket
ORDER BY bucket
```

Response shape:
```json
{
  "range": "24h",
  "resolution": "5m",
  "points": [
    {
      "timestamp": "2026-03-25T14:00:00Z",
      "cpu_percent_total": 3.2,
      "cpu_peak": 12.5,
      "cpu_percent_system": 8.1,
      "mem_rss_bytes": 293601280,
      "mem_rss_peak": 310000000,
      "mem_rss_percent": 1.8,
      "mem_system_used_percent": 42.3,
      "io_read_bytes": 104857600,
      "io_write_bytes": 52428800,
      "thread_count": 12,
      "active_bulk_jobs": 1,
      "active_lifecycle_scan": 0,
      "active_conversions": 0
    }
  ]
}
```

#### `GET /api/resources/disk`

Historical disk metrics.

Query params:
- `range`: same as above (default `"30d"`)

Response: array of disk_metrics rows within range. No downsampling needed —
at 4 samples/day there are only ~120 points for 30 days.

```json
{
  "range": "30d",
  "points": [
    {
      "timestamp": "2026-03-25T12:00:00Z",
      "output_repo_bytes": 1073741824,
      "trash_bytes": 209715200,
      "database_bytes": 52428800,
      "logs_bytes": 10485760,
      "meilisearch_bytes": 31457280,
      "total_bytes": 1482735616,
      "volume_total_bytes": 107374182400,
      "volume_used_percent": 50.0
    }
  ]
}
```

#### `GET /api/resources/events`

Activity event log with filtering.

Query params:
- `range`: same (default `"7d"`)
- `type`: optional filter (e.g., `"bulk_start,bulk_end"`)
- `limit`: max results (default 100, max 500)

Response:
```json
{
  "events": [
    {
      "id": 42,
      "timestamp": "2026-03-25T14:30:00Z",
      "event_type": "bulk_end",
      "description": "Bulk job completed: 12,450/12,500 files in 3,420s",
      "metadata": {"job_id": "...", "converted": 12450, "failed": 50},
      "duration_seconds": 3420.5
    }
  ],
  "total": 156
}
```

#### `GET /api/resources/summary`

**The IT admin pitch card.** Computes aggregate statistics over a configurable
window (default 30 days). This is the single most important endpoint.

```json
{
  "period_days": 30,
  "period_start": "2026-02-24T00:00:00Z",
  "period_end": "2026-03-26T00:00:00Z",
  "uptime_hours": 718.5,
  "cpu": {
    "process_avg_percent": 2.1,
    "process_peak_percent": 47.3,
    "process_p95_percent": 8.4,
    "system_avg_percent": 12.5,
    "idle_baseline_percent": 0.4,
    "core_count": 8,
    "description": "MarkFlow averaged 2.1% CPU (0.4% idle, 47.3% peak during bulk conversion)"
  },
  "memory": {
    "rss_avg_bytes": 293601280,
    "rss_avg_human": "280.00 MB",
    "rss_peak_bytes": 524288000,
    "rss_peak_human": "500.00 MB",
    "rss_p95_bytes": 367001600,
    "rss_p95_human": "350.00 MB",
    "system_total_bytes": 17179869184,
    "system_total_human": "16.00 GB",
    "percent_of_system_avg": 1.7,
    "stable": true,
    "description": "Stable at ~280 MB (1.7% of 16 GB). No memory growth detected."
  },
  "disk": {
    "current_total_bytes": 1482735616,
    "current_total_human": "1.38 GB",
    "growth_bytes_per_day": 71303168,
    "growth_human_per_day": "68.00 MB",
    "projected_30d_bytes": 3621734400,
    "projected_30d_human": "3.37 GB",
    "volume_free_bytes": 53687091200,
    "volume_free_human": "50.00 GB",
    "description": "1.38 GB total, growing ~68 MB/day. 50 GB free on volume."
  },
  "io": {
    "read_avg_bytes_per_sec": 524288,
    "read_avg_human": "512.00 KB/s",
    "write_avg_bytes_per_sec": 262144,
    "write_avg_human": "256.00 KB/s",
    "description": "Average disk I/O: 512 KB/s read, 256 KB/s write"
  },
  "activity": {
    "total_events": 156,
    "bulk_jobs_completed": 3,
    "total_files_converted": 45230,
    "lifecycle_scans": 720,
    "errors": 12,
    "avg_bulk_duration_seconds": 2800,
    "description": "3 bulk jobs (45,230 files), 720 lifecycle scans, 12 errors"
  },
  "self_governance": {
    "worker_count": 4,
    "process_priority": "below_normal",
    "cpu_affinity": [0, 1, 2, 3],
    "business_hours_only": true,
    "description": "Configured: 4 workers, below-normal priority, pinned to cores 0-3, bulk runs during business hours only"
  }
}
```

The **description** fields are pre-written sentences designed for copy-paste into
an email to IT. They should read naturally and emphasize that MarkFlow is lightweight.

**Computing the summary:**

- `idle_baseline_percent`: Average CPU when `active_bulk_jobs = 0 AND active_conversions = 0 AND active_lifecycle_scan = 0`
- `stable` (memory): Compare average RSS of first 10% of samples to last 10%. If the difference is < 10%, mark as stable.
- `growth_bytes_per_day`: Linear regression on `total_bytes` from disk_metrics (or simple `(latest - earliest) / days`).
- `projected_30d_bytes`: `current + (growth_per_day * 30)`
- `p95_percent`: Use `PERCENTILE` approximation — sort values and pick the 95th percentile index. SQLite doesn't have built-in percentile, so fetch values and compute in Python.
- `read/write avg per second`: Delta between first and last `io_read_bytes` divided by time span.
- `self_governance`: Read from preferences table (worker_count, cpu_affinity_cores, process_priority) and scheduler config.
- `uptime_hours`: Count the number of 30-second samples × 30 / 3600. This is approximate but good enough — if the container was down, no samples were recorded.

#### `GET /api/resources/export`

Export raw metrics as CSV for the IT admin to import into their own monitoring tools.

Query params:
- `table`: `"system"`, `"disk"`, or `"events"` (required)
- `range`: same (default `"30d"`)

Response: `Content-Type: text/csv` with appropriate `Content-Disposition` header.
File named `markflow-{table}-{date}.csv`.

---

### Disk Usage endpoint — `GET /api/admin/disk-usage`

Add to `api/routes/admin.py`. Requires `ADMIN` role. This is the **live**
(non-historical) disk usage snapshot — also used by the Resources page as a
quick reference. Follows the same spec from the disk-usage prompt (response shape
with breakdown array and volume_info). The `collect_disk_snapshot()` function in
`metrics_collector.py` reuses this same walk logic.

Implementation details for the directory walk:

```python
_DISK_TARGETS = [
    ("Output Repository", Path("/mnt/output-repo"), "Bulk-converted Markdown knowledge base"),
    ("Trash", Path("/mnt/output-repo/.trash"), "Soft-deleted files awaiting purge"),
    ("Conversion Output", Path(os.environ.get("OUTPUT_DIR", "output")), "Single-file conversion results"),
    ("Logs", Path(os.environ.get("LOG_DIR", "logs")), "Operational and debug log files"),
    ("Meilisearch Data", Path(os.environ.get("MEILI_DATA_PATH", "/meili_data")), "Search index data"),
]
_DB_PATH = Path(os.environ.get("DB_PATH", "/app/data/markflow.db"))

def _walk_directory(path: Path, exclude_subdirs: set[str] | None = None) -> tuple[int, int]:
    """Return (total_bytes, file_count). Runs in thread."""
    total = 0
    count = 0
    if not path.exists():
        return 0, 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                if exclude_subdirs and any(part in exclude_subdirs for part in f.relative_to(path).parts):
                    continue
                try:
                    total += f.stat().st_size
                    count += 1
                except OSError:
                    pass
    except OSError:
        pass
    return total, count
```

For the output-repo walk, exclude `.trash`: `_walk_directory(repo_path, exclude_subdirs={".trash"})`

---

## Part 6: New Page — `static/resources.html`

### Nav placement

In `static/app.js`, add "Resources" to `NAV_ITEMS`:
```javascript
{ label: "Resources", href: "/resources.html", minRole: "manager" },
```

Place it between "Admin" and "Settings" in the nav order (or after Status —
use your judgment for what flows best, but it must be visible to `manager` role).

### Chart library

Include **Chart.js** from CDN for time-series charts. Add to `<head>`:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
```

If CDN is unavailable in the Docker network, fall back to bundling the minified
JS in `static/vendor/`. Check if the CDN domain is allowed first (it may not be —
see network config). **If CDN is blocked, download the files during `docker build`
and serve them from `/static/vendor/`.**

### Page layout

The page has five sections, stacked vertically. Use the existing `markflow.css`
design system (`.stat-card`, `.section`, CSS variables).

#### Section 1: Executive Summary

A prominent card at the top. This is what gets screenshot and emailed to IT.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  MarkFlow Resource Summary — Last 30 Days              [Export CSV ▾]  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │
│  │  CPU         │  │  Memory     │  │  Disk        │  │  Uptime     │   │
│  │  avg 2.1%   │  │  avg 280 MB │  │  1.38 GB     │  │  718 hrs    │   │
│  │  peak 47.3% │  │  peak 500MB │  │  +68 MB/day  │  │  (29.9 d)   │   │
│  │  idle 0.4%  │  │  1.7% of    │  │  50 GB free  │  │             │   │
│  │             │  │  system RAM │  │              │  │             │   │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘   │
│                                                                         │
│  "MarkFlow averaged 2.1% CPU and 280 MB RAM over the last 30 days.    │
│   It is configured to run at below-normal priority on 4 cores.         │
│   Disk usage is 1.38 GB with 50 GB free and growing at 68 MB/day."     │
│                                                                         │
│  Resource Controls: 4 workers • below-normal priority • cores 0-3      │
│                     bulk processing during business hours only          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

The natural-language paragraph is pulled from the summary endpoint's `description`
fields, concatenated. This is the "copy this into an email" text.

The **Export CSV** dropdown offers: System Metrics CSV, Disk Metrics CSV, Activity
Events CSV (calls `GET /api/resources/export?table=...`).

#### Section 2: Historical Charts — CPU & Memory

Two side-by-side Chart.js line charts. Time range selector: 1h | 6h | 24h | 7d | 30d | 90d.

**Left chart: CPU**
- Line 1: MarkFlow process CPU % (primary, colored `var(--accent)`)
- Line 2: System-wide CPU % (secondary, lighter color, dashed)
- Shaded regions (vertical spans) where `active_bulk_jobs > 0` — labeled "Bulk Job" in legend
- Y-axis: 0–100%

**Right chart: Memory**
- Line 1: MarkFlow RSS in MB (primary)
- Line 2: System memory used % (secondary, right Y-axis)
- Y-axis left: MB, Y-axis right: 0–100%

Both charts highlight periods where tasks were active using background shading,
so the IT admin can see that spikes correlate to actual work, not idle resource waste.

Chart.js config notes:
- Use `type: 'line'` with `fill: false`
- Time scale X-axis: `type: 'time'` (requires the date-fns adapter)
- `pointRadius: 0` for clean lines (too many points for visible dots)
- `tension: 0.3` for smooth curves
- Responsive, maintain aspect ratio
- Tooltip shows exact values + what task was active at that moment

#### Section 3: Historical Chart — Disk Usage

Single Chart.js stacked area chart showing disk growth over time.

- Stacked areas: Output Repo, Trash, Database, Logs, Meilisearch, Conversion Output
- Each in a different color from the design system
- Time range: 7d | 30d | 90d (disk snapshots are every 6h, so 1h/6h are too short)
- Secondary line (not stacked): volume free space (right Y-axis)

This shows the IT admin that disk growth is predictable and linear, not exponential.

#### Section 4: Live System Metrics (moved from Admin)

**Move** the Task Manager section from `static/admin.html` to here:
- Per-core CPU bars
- Memory gauge (RSS + system)
- Thread count
- 2-second polling via `GET /api/admin/system/metrics`

In `admin.html`, **replace** the Task Manager section with a link card:
```
"Live system metrics have moved to the Resources page. [Go to Resources →]"
```

This avoids breaking any existing admin workflows — the data is still accessible,
just in a more appropriate location.

#### Section 5: Activity Log

A table/list of recent activity events from `GET /api/resources/events`.

```
┌──────────────────────────────────────────────────────────────────┐
│  Activity Log                                   [Filter ▾] [7d] │
├──────────────────────────────────────────────────────────────────┤
│  Mar 25 14:30  bulk_end      Bulk job completed: 12,450 files   │
│                               in 57 min — 50 failed              │
│  Mar 25 13:33  bulk_start    Bulk job started: 12,500 files     │
│                               from Engineering Share             │
│  Mar 25 08:00  lifecycle     Lifecycle scan: 24,350 files,      │
│                _scan_end      3 new, 1 modified, 0 deleted       │
│  Mar 25 03:00  db_maint      Scheduled DB maintenance           │
│  Mar 24 20:00  lifecycle     Lifecycle scan: 24,347 files       │
│                _scan_end                                         │
│  ...                                                             │
└──────────────────────────────────────────────────────────────────┘
```

- Color-coded event type badges (green for completions, blue for starts, yellow for scans, red for errors)
- Filter dropdown: All, Bulk Jobs, Lifecycle, Maintenance, Errors
- Expandable rows — click to see the `metadata` JSON

#### Section 6: Repository Overview (copied from Admin)

**Copy** (not move) the Repository Overview stats section from `admin.html` to
the bottom of the Resources page. The data call is the same (`GET /api/admin/stats`).
This gives the IT admin file count context alongside the resource metrics.

Keep the original on the admin page too — admin users expect it there.

---

## Part 7: Admin Page — Disk Usage Section

Add a **Disk Usage** section to `static/admin.html` between Repository Overview
and the remaining admin sections. This calls `GET /api/admin/disk-usage` with a
manual Refresh button (no polling — walks are expensive).

Layout:

```
┌─────────────────────────────────────────────────────────────────┐
│  Disk Usage                                        [↻ Refresh]  │
├─────────────────────────────────────────────────────────────────┤
│  Total MarkFlow footprint: 1.38 GB                              │
│                                                                  │
│  Volume: / — 50.00 GB used of 100.00 GB (50.0%)                │
│  ████████████████████░░░░░░░░░░░░░░░░░░░░                       │
│  MarkFlow: 1.38 GB (1.4% of volume)                            │
│  ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                       │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ Output Repo  │  │ Trash        │  │ Conv. Output │           │
│  │ 1.00 GB      │  │ 200 MB       │  │ 100 MB       │           │
│  │ 24,350 files │  │ 1,200 files  │  │ 580 files    │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ Database     │  │ Logs         │  │ Meilisearch  │           │
│  │ 51 MB        │  │ 10 MB        │  │ 30 MB        │           │
│  │ DB + WAL     │  │ 4 files      │  │ Search index │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

Implementation:
- Use `.stat-card` class for breakdown cards
- Volume progress bars use `<div>` with percentage width
- Trash card gets warning border if > 1 GB
- DB card gets warning border if > 500 MB
- DB + WAL combined into one card in UI (separate in API response)
- Loading spinner during fetch
- File counts formatted with `toLocaleString()`

---

## Files to Create

| File | Purpose |
|------|---------|
| `core/metrics_collector.py` | Metrics collection, disk walking, activity event recording, purge |
| `api/routes/resources.py` | Resources API: metrics, disk history, events, summary, CSV export |
| `static/resources.html` | Resources page with charts, summary, live metrics, log, repo overview |

## Files to Modify

| File | Change |
|------|--------|
| `core/database.py` | Add `system_metrics`, `disk_metrics`, `activity_events` tables in `_ensure_schema()` |
| `core/scheduler.py` | Add 3 new scheduled jobs (collect_metrics, collect_disk_snapshot, purge_old_metrics) |
| `main.py` | Add `resources_router`, fire initial disk snapshot, record startup/shutdown events |
| `core/bulk_worker.py` | Add `record_activity_event()` calls at job start/end |
| `core/lifecycle_scanner.py` | Add `record_activity_event()` calls at scan start/end |
| `core/search_indexer.py` | Add `record_activity_event()` call at index rebuild |
| `api/routes/admin.py` | Add `GET /api/admin/disk-usage` endpoint |
| `static/admin.html` | Add Disk Usage section; replace Task Manager with link to Resources page |
| `static/app.js` | Add "Resources" to `NAV_ITEMS` with `minRole: "manager"` |

## No New Python Dependencies

`psutil` is already installed. `Chart.js` is client-side only (CDN or bundled).

---

## Gotchas for CLAUDE.md

Add these to the Gotchas section:

```
- **Metrics collector samples every 30 seconds**: `collect_metrics()` is a lightweight
  psutil call (~1ms). It runs via APScheduler with `max_instances=1` — if a sample takes
  longer than 30s (impossible in practice), the next is skipped, not stacked.

- **Disk snapshots every 6 hours, not 30 seconds**: Directory walks on large repos
  take 5-10 seconds. `collect_disk_snapshot()` runs every 6 hours. An immediate snapshot
  fires at startup so the Resources page has data on first load.

- **Metrics retention is 90 days**: `purge_old_metrics()` runs daily at 03:00 and
  deletes all three metrics tables' rows older than 90 days. At 2,880 samples/day
  (30s interval), this is ~260K rows for system_metrics — about 25 MB. Acceptable.

- **Disk usage endpoint is not auto-polled**: `GET /api/admin/disk-usage` walks
  directories in a thread. On large repos (100K+ files) this can take 5-10 seconds.
  The admin UI fetches once on load and has a manual Refresh button — no interval polling.

- **Trash is subtracted from output-repo total**: The `.trash/` directory lives inside
  `/mnt/output-repo`. Both the disk-usage endpoint and disk_metrics collector exclude
  `.trash/` from the output-repo walk to avoid double-counting.

- **Activity events are fire-and-forget**: `record_activity_event()` catches all
  exceptions internally. A failed event insert never disrupts the operation being recorded.
  This follows the same pattern as `POST /api/log/client-event`.

- **Summary endpoint computes p95 in Python, not SQL**: SQLite lacks PERCENTILE_CONT.
  The summary endpoint fetches the relevant column values and computes percentile in
  Python. For 90 days of 30s samples (~260K rows), fetching a single column is fast
  (~50ms). If this becomes a problem, add a precomputed daily_summary table.

- **`idle_baseline_percent`**: Computed from samples where ALL task counters are zero.
  If MarkFlow is always running something (unlikely), idle baseline falls back to the
  p5 (5th percentile) of CPU readings.

- **Chart.js loaded from CDN**: If cdn.jsdelivr.net is unreachable from the Docker
  container (check ALLOWED_DOMAINS in network config), bundle the minified JS files
  in `static/vendor/` during docker build. The HTML page should try CDN first with a
  fallback `<script>` tag for the local copy.

- **Resources page is MANAGER role, not ADMIN**: IT administrators may be given manager
  access to review resource usage without needing full admin (API key management,
  DB repair). The Resources API endpoints use `require_role(UserRole.MANAGER)`.

- **CPU percent can exceed 100%**: `psutil.Process.cpu_percent()` returns per-process
  CPU usage where 100% = one full core. On a 4-core system, max is 400%. The charts
  should account for this — Y-axis max should be `cpu_count * 100`, not hardcoded 100.

- **I/O counters are cumulative**: `io_read_bytes` and `io_write_bytes` in system_metrics
  are cumulative counters from process start. The Resources page computes deltas between
  adjacent samples for rate display. First sample of a session has no delta — show N/A.

- **Task Manager moved to Resources page**: The live CPU bars, memory gauge, and thread
  count previously on admin.html now live on resources.html. Admin page shows a link card
  pointing to Resources. The `GET /api/admin/system/metrics` endpoint is unchanged — both
  pages can call it.

- **Repository Overview is duplicated, not moved**: The stats cards appear on BOTH the
  admin page and the Resources page. Same `GET /api/admin/stats` call. This is intentional —
  admin users expect it on admin, IT reviewers need it on resources.
```

---

## Done Criteria

### Database & Collection
- [ ] Three new tables created in `_ensure_schema()`
- [ ] `collect_metrics()` writes to `system_metrics` every 30 seconds
- [ ] `collect_disk_snapshot()` writes to `disk_metrics` every 6 hours
- [ ] `purge_old_metrics()` deletes rows older than 90 days daily
- [ ] Activity events recorded at bulk start/end, lifecycle scan start/end, index rebuild, startup/shutdown, DB maintenance
- [ ] `record_activity_event()` is fire-and-forget (never throws)

### API Endpoints
- [ ] `GET /api/resources/metrics` returns time-range-filtered, downsampled metrics
- [ ] `GET /api/resources/disk` returns disk history
- [ ] `GET /api/resources/events` returns filtered activity events
- [ ] `GET /api/resources/summary` returns the executive summary with description sentences
- [ ] `GET /api/resources/export` returns CSV download for any table
- [ ] `GET /api/admin/disk-usage` returns live disk usage breakdown
- [ ] All resources endpoints require MANAGER role
- [ ] Disk-usage endpoint requires ADMIN role
- [ ] All endpoints never return 500 — partial results on error

### Resources Page
- [ ] "Resources" appears in nav for manager+ role
- [ ] Executive Summary card with 4 KPI sub-cards and natural-language paragraph
- [ ] CPU + Memory charts with time range selector (1h/6h/24h/7d/30d/90d)
- [ ] Task activity shading on charts (bulk job periods highlighted)
- [ ] Disk usage stacked area chart with 7d/30d/90d range
- [ ] Live system metrics section (moved from admin)
- [ ] Activity log table with type filter and expandable rows
- [ ] Repository overview cards (copied from admin)
- [ ] CSV export dropdown works for all three tables
- [ ] Charts handle empty data gracefully (show "No data yet" message)

### Admin Page
- [ ] Disk Usage section added with volume bar + breakdown cards
- [ ] Task Manager section replaced with link card to Resources page
- [ ] Repository Overview section unchanged

### Cleanup
- [ ] CLAUDE.md updated with version note and all gotchas above
- [ ] Tag `v0.9.6`
