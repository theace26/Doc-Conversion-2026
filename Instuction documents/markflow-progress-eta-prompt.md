# MarkFlow — v[NEXT] Progress Tracking & ETA Feature
## Claude Code Instruction Document

---

## ⚠️ Pre-Flight — Do This First

1. **Read `CLAUDE.md`** in the project root. It is the authoritative source of truth for current version,
   completed phases, DB schema, table names, and file naming conventions. All implementation below must
   be consistent with what CLAUDE.md says is already built. Do not rebuild existing infrastructure.

2. **Confirm the current version number** from CLAUDE.md. The version tag for this changeset is
   `current_version + 1 patch` (e.g., if CLAUDE.md says v0.12.1, this ships as v0.12.2). Use that
   version number everywhere below where `[NEXT]` appears.

3. **Run the existing test suite** before touching any code:
   ```
   docker exec doc-conversion-2026-markflow-1 pytest tests/ -q
   ```
   Record the baseline pass count. All existing tests must still pass at the end.

4. **Grep for existing progress/ETA fields** so you don't duplicate:
   ```
   grep -r "eta\|total_files\|files_per_second\|rolling" app/ --include="*.py" -l
   grep -r "total_files\|eta" app/db/ --include="*.py"
   ```
   If any of these already exist, adapt rather than replace.

---

## Feature Overview

### What This Adds
1. **Concurrent fast-walk file counter** — when a scan starts, a lightweight background coroutine
   immediately begins counting files in the source tree (path-only, no stat calls). The UI shows
   "Counting…" briefly, then updates to show "1,300 of 245,000 files scanned" as the count arrives.
   The scan itself starts in parallel — there is zero delay to scan start.

2. **Rolling-window ETA** — all long-running jobs (scan, bulk conversion, single-file conversion)
   compute estimated time remaining using a rolling window of the last 100 completed items.
   ETA auto-adjusts continuously and is stored in the DB so it survives page refreshes.

3. **Unified progress model** — scan jobs, bulk conversion jobs, and single-file conversions all
   use the same `RollingWindowETA` engine and expose the same progress shape to the frontend.

### Industry pattern being implemented
- Concurrent fast-walk (not pre-scan blocking): scan begins immediately, count populates within
  seconds. This is the pattern used by rsync, robocopy, and modern file managers.
- Rolling window average over last N=100 items for ETA: adapts quickly to speed changes (e.g.,
  hitting a directory full of large PDFs after a run of tiny CSVs) without wild oscillation.

---

## Part 1 — New File: `core/progress_tracker.py`

Create this file. It is the single source of truth for ETA math across all job types.

```python
# core/progress_tracker.py
"""
Rolling-window ETA calculator for MarkFlow progress tracking.

Used by scan workers, bulk conversion workers, and single-file conversion
to provide consistent, auto-adjusting time remaining estimates.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


ROLLING_WINDOW_SIZE = 100   # number of recent completions to track
MIN_SAMPLES = 3             # minimum completions before ETA is meaningful
ETA_UPDATE_INTERVAL = 2.0   # seconds between DB writes for ETA (avoid write storms)


@dataclass
class ProgressSnapshot:
    """Immutable progress snapshot — safe to serialize and return to API."""
    completed: int
    total: Optional[int]          # None = count not yet known
    count_ready: bool             # True once fast-walk has finished counting
    eta_seconds: Optional[float]  # None = not enough data yet
    files_per_second: Optional[float]
    percent: Optional[float]      # None if total unknown

    def to_dict(self) -> dict:
        pct = None
        if self.total and self.total > 0:
            pct = round(min(100.0, self.completed / self.total * 100), 1)
        return {
            "completed": self.completed,
            "total": self.total,
            "count_ready": self.count_ready,
            "eta_seconds": round(self.eta_seconds, 1) if self.eta_seconds is not None else None,
            "files_per_second": round(self.files_per_second, 2) if self.files_per_second is not None else None,
            "percent": pct,
            "eta_human": _format_eta(self.eta_seconds),
        }


class RollingWindowETA:
    """
    Tracks completion events and computes rolling-window ETA.

    Thread-safe via asyncio. Not thread-safe across OS threads —
    call only from async context.

    Usage:
        tracker = RollingWindowETA(total=245000)
        tracker.record_completion()   # call after each file/item completes
        snapshot = tracker.snapshot() # read current state
    """

    def __init__(self, total: Optional[int] = None, window_size: int = ROLLING_WINDOW_SIZE):
        self._total: Optional[int] = total
        self._count_ready: bool = total is not None  # ready immediately if total passed at init
        self._completed: int = 0
        self._window: deque[tuple[float, int]] = deque(maxlen=window_size)
        # Each entry: (timestamp, cumulative_completed_at_that_point)
        self._lock = asyncio.Lock()

    async def set_total(self, total: int) -> None:
        """Call this when the concurrent fast-walk finishes counting."""
        async with self._lock:
            self._total = total
            self._count_ready = True

    async def update_total(self, total: int) -> None:
        """
        Call this periodically during fast-walk to stream an in-progress count.
        count_ready stays False until set_total() is called.
        """
        async with self._lock:
            self._total = total

    async def record_completion(self, count: int = 1) -> None:
        """Call after each file/item completes. count=N for batch completions."""
        async with self._lock:
            self._completed += count
            self._window.append((time.monotonic(), self._completed))

    async def snapshot(self) -> ProgressSnapshot:
        async with self._lock:
            return self._compute_snapshot()

    def snapshot_sync(self) -> ProgressSnapshot:
        """Synchronous snapshot — use only when not in async context."""
        return self._compute_snapshot()

    def _compute_snapshot(self) -> ProgressSnapshot:
        fps = None
        eta = None

        if len(self._window) >= MIN_SAMPLES:
            oldest_ts, oldest_count = self._window[0]
            newest_ts, newest_count = self._window[-1]
            elapsed = newest_ts - oldest_ts
            if elapsed > 0:
                fps = (newest_count - oldest_count) / elapsed
                if fps > 0 and self._total is not None:
                    remaining = self._total - self._completed
                    if remaining > 0:
                        eta = remaining / fps
                    else:
                        eta = 0.0

        return ProgressSnapshot(
            completed=self._completed,
            total=self._total,
            count_ready=self._count_ready,
            eta_seconds=eta,
            files_per_second=fps,
            percent=None,  # computed in to_dict()
        )


def _format_eta(seconds: Optional[float]) -> Optional[str]:
    """Human-readable ETA string. Returns None if ETA not yet available."""
    if seconds is None:
        return None
    if seconds < 0:
        return "finishing…"
    seconds = int(seconds)
    if seconds < 60:
        return f"~{seconds}s remaining"
    minutes = seconds // 60
    secs = seconds % 60
    if minutes < 60:
        return f"~{minutes}m {secs:02d}s remaining"
    hours = minutes // 60
    mins = minutes % 60
    return f"~{hours}h {mins:02d}m remaining"
```

---

## Part 2 — DB Schema Migrations

### 2a. Identify existing schema

Read `app/db/schema.sql` (or wherever the CREATE TABLE statements live — check CLAUDE.md for the
exact file). Find the `scan_runs` and `bulk_jobs` tables. Also find the `conversion_history` table
(or equivalent for single-file conversions).

### 2b. Add migration to `app/db/migrations.py` (or the equivalent migration runner)

Check CLAUDE.md for how schema migrations are applied. Add the following as a new migration.
**Do not ALTER existing columns** — only ADD new ones.

```sql
-- Migration: add progress tracking columns

-- scan_runs table
ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS total_files_counted INTEGER DEFAULT NULL;
ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS count_status TEXT NOT NULL DEFAULT 'counting'
    CHECK (count_status IN ('counting', 'ready'));
ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS eta_seconds REAL DEFAULT NULL;
ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS files_per_second REAL DEFAULT NULL;
ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS eta_updated_at TEXT DEFAULT NULL;

-- bulk_jobs table
ALTER TABLE bulk_jobs ADD COLUMN IF NOT EXISTS eta_seconds REAL DEFAULT NULL;
ALTER TABLE bulk_jobs ADD COLUMN IF NOT EXISTS files_per_second REAL DEFAULT NULL;
ALTER TABLE bulk_jobs ADD COLUMN IF NOT EXISTS eta_updated_at TEXT DEFAULT NULL;

-- conversion_history table (single-file conversions)
-- Only adds eta_seconds — single conversions are short but large files can take 30-120s
ALTER TABLE conversion_history ADD COLUMN IF NOT EXISTS eta_seconds REAL DEFAULT NULL;
```

**Important for SQLite:** SQLite does not support `IF NOT EXISTS` in ALTER TABLE.
Use the migration pattern already established in the codebase (check migrations.py for the existing
pattern — it likely wraps each ALTER in a try/except or checks `PRAGMA table_info` first).

The correct SQLite-safe pattern if not already in use:

```python
async def _add_column_if_missing(db, table: str, column: str, definition: str):
    """SQLite-safe column addition — no-ops if column already exists."""
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        cols = [row[1] async for row in cur]
    if column not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
```

Apply this for each column above.

---

## Part 3 — Concurrent Fast-Walk Counter

### 3a. Locate the scan worker

Find the file that handles scan jobs — likely `core/scan_worker.py`, `core/bulk_scanner.py`, or
similar. Check CLAUDE.md for the exact filename. All changes in Part 3 go in that file.

### 3b. Add `fast_walk_counter` coroutine

Add this function near the top of the scan worker (below imports):

```python
async def fast_walk_counter(
    root_path: str,
    tracker: "RollingWindowETA",
    db_job_id: int,
    db_pool,           # use the same db pool/connection pattern already in this file
    update_interval: int = 2000,  # write to DB every N files found
) -> int:
    """
    Lightweight concurrent file counter.

    Walks the directory tree counting files only — no stat calls, no format
    checking, no DB writes per file. Updates total on tracker and DB at
    intervals so the UI sees a streaming count before the walk finishes.

    Returns total file count when complete.
    """
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root_path):
            # Skip hidden directories (e.g. .git, .Trash-1000)
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            total += len(filenames)

            if total % update_interval == 0:
                # Stream intermediate count to tracker (count_ready stays False)
                await tracker.update_total(total)
                # Persist intermediate count to DB so UI poll can show it
                async with db_pool() as db:
                    await db.execute(
                        "UPDATE scan_runs SET total_files_counted = ? WHERE id = ?",
                        (total, db_job_id)
                    )
                    await db.commit()
                # Yield control so scan worker can make progress
                await asyncio.sleep(0)

    except Exception as e:
        # Fast-walk failure is non-fatal — scan continues without a total
        import structlog
        log = structlog.get_logger()
        log.warning("fast_walk_counter_error", error=str(e), job_id=db_job_id)
        return total

    # Walk complete — mark count as ready
    await tracker.set_total(total)
    async with db_pool() as db:
        await db.execute(
            """UPDATE scan_runs
               SET total_files_counted = ?,
                   count_status = 'ready'
               WHERE id = ?""",
            (total, db_job_id)
        )
        await db.commit()

    return total
```

### 3c. Integrate into the scan job entry point

In the existing scan job function (wherever `scan_runs` is created and files are walked), make these
changes:

```python
# 1. Import at top of file
from core.progress_tracker import RollingWindowETA, ETA_UPDATE_INTERVAL
import time

# 2. At scan job start — BEFORE the main scan loop:
tracker = RollingWindowETA(total=None)  # total unknown at start

# Launch fast-walk counter concurrently (fire and forget into the event loop)
fast_walk_task = asyncio.create_task(
    fast_walk_counter(source_root, tracker, scan_run_id, db_pool_or_connection)
)

# 3. Inside the main scan loop — after each file is recorded:
await tracker.record_completion()

# 4. Periodically write ETA to DB (throttled to avoid write storms):
#    Add a last_eta_write variable before the loop:
last_eta_write = time.monotonic()

#    Inside the loop, after record_completion():
now = time.monotonic()
if now - last_eta_write >= ETA_UPDATE_INTERVAL:
    snap = await tracker.snapshot()
    async with db as db_conn:   # use whatever db pattern is already in this file
        await db_conn.execute(
            """UPDATE scan_runs
               SET eta_seconds = ?,
                   files_per_second = ?,
                   eta_updated_at = datetime('now'),
                   total_files_counted = ?,
                   count_status = ?
               WHERE id = ?""",
            (
                snap.eta_seconds,
                snap.files_per_second,
                snap.total,
                'ready' if snap.count_ready else 'counting',
                scan_run_id,
            )
        )
        await db_conn.commit()
    last_eta_write = now

# 5. At scan job completion — cancel fast-walk if still running:
if not fast_walk_task.done():
    fast_walk_task.cancel()
    try:
        await fast_walk_task
    except asyncio.CancelledError:
        pass
```

---

## Part 4 — Bulk Conversion Worker ETA

### 4a. Locate bulk_worker.py

Find the file that processes bulk conversion jobs (likely `core/bulk_worker.py`). Check CLAUDE.md.

### 4b. Integrate RollingWindowETA

The bulk worker already knows `total_files` at job start (it was scanned in a prior phase). So
`count_ready=True` from the beginning.

```python
# At top of file
from core.progress_tracker import RollingWindowETA, ETA_UPDATE_INTERVAL
import time

# In the bulk job processing function, after loading total_files from the DB:
tracker = RollingWindowETA(total=total_files)  # total known immediately

last_eta_write = time.monotonic()

# After each file completes (success OR failure — both count as processed):
await tracker.record_completion()

now = time.monotonic()
if now - last_eta_write >= ETA_UPDATE_INTERVAL:
    snap = await tracker.snapshot()
    await db.execute(
        """UPDATE bulk_jobs
           SET eta_seconds = ?,
               files_per_second = ?,
               eta_updated_at = datetime('now')
           WHERE id = ?""",
        (snap.eta_seconds, snap.files_per_second, job_id)
    )
    await db.commit()
    last_eta_write = now
```

**Important:** The bulk worker likely uses concurrent workers (multiple asyncio tasks or a
ThreadPoolExecutor). The `RollingWindowETA` uses an asyncio Lock internally, so it is safe to call
`record_completion()` from multiple concurrent coroutines. If workers run in threads (not coroutines),
use `tracker.record_completion_threadsafe()` — add this method to `RollingWindowETA`:

```python
def record_completion_threadsafe(self, count: int = 1) -> None:
    """
    For use from ThreadPoolExecutor workers.
    Uses a threading.Lock instead of asyncio.Lock.
    """
    # Add threading.Lock as self._thread_lock in __init__
    # and use it here for the _completed and _window updates
    import threading
    with self._thread_lock:
        self._completed += count
        self._window.append((time.monotonic(), self._completed))
```

Check how bulk_worker.py dispatches tasks and add the threadsafe variant only if needed.

---

## Part 5 — Single-File Conversion ETA

Single-file conversions are short (seconds to minutes) but large PDFs/PPTX files can run 30–120s.
The ETA here is simpler: it's based on historical average for the same file type.

### 5a. Add a helper to query historical average

In `core/progress_tracker.py`, add:

```python
async def estimate_single_file_eta(db, file_extension: str, file_size_bytes: int) -> Optional[float]:
    """
    Estimate conversion time for a single file based on:
    - Historical average duration for same extension (last 50 conversions)
    - File size ratio adjustment if size data is available

    Returns estimated seconds, or None if no history available.
    """
    ext = file_extension.lower().lstrip('.')
    async with db.execute(
        """SELECT AVG(duration_seconds), AVG(file_size_bytes)
           FROM conversion_history
           WHERE file_extension = ?
             AND status = 'success'
             AND duration_seconds IS NOT NULL
           ORDER BY created_at DESC
           LIMIT 50""",
        (ext,)
    ) as cur:
        row = await cur.fetchone()

    if not row or row[0] is None:
        return None

    avg_duration, avg_size = row
    if avg_size and avg_size > 0 and file_size_bytes > 0:
        # Scale estimate by size ratio (linear approximation)
        size_ratio = file_size_bytes / avg_size
        return avg_duration * size_ratio
    return avg_duration
```

**Note:** This requires `duration_seconds` and `file_size_bytes` columns in `conversion_history`.
If they don't exist, check CLAUDE.md — if they're missing, add them to the migration in Part 2b.
If `file_size_bytes` doesn't exist, omit the size-ratio scaling and return `avg_duration` directly.

### 5b. Return ETA in single-file conversion API response

In the conversion API route (likely `api/routes/convert.py` or similar), before starting conversion:

```python
eta = await estimate_single_file_eta(db, file_extension, file_size_bytes)
# Store eta on the conversion_history record at creation time
# Return eta_seconds and eta_human in the initial API response so UI can show it immediately
```

Return shape (add to existing response dict):
```json
{
  "job_id": "...",
  "eta_seconds": 45.2,
  "eta_human": "~45s remaining"
}
```

---

## Part 6 — API Endpoint Updates

### 6a. Scan run status endpoint

Find the endpoint that returns scan run status (likely `GET /api/scans/{scan_id}` or
`GET /api/bulk/scan-status`). Add to its response:

```python
# Query these from the scan_runs row:
"progress": {
    "completed": row["files_scanned"],          # existing field
    "total": row["total_files_counted"],         # new field (None while counting)
    "count_ready": row["count_status"] == "ready",
    "eta_seconds": row["eta_seconds"],
    "files_per_second": row["files_per_second"],
    "eta_human": _format_eta(row["eta_seconds"]),
    "percent": _calc_percent(row["files_scanned"], row["total_files_counted"]),
}
```

Add `_format_eta` and `_calc_percent` as small module-level helpers in the route file, or import
from `core/progress_tracker.py` (preferred — import `_format_eta` directly).

### 6b. Bulk job status endpoint

Find `GET /api/bulk/jobs/{job_id}` or equivalent. Add the same `progress` block:

```python
"progress": {
    "completed": row["files_converted"],        # existing field
    "total": row["total_files"],                # existing field (already known at job start)
    "count_ready": True,                        # always true for bulk jobs
    "eta_seconds": row["eta_seconds"],
    "files_per_second": row["files_per_second"],
    "eta_human": _format_eta(row["eta_seconds"]),
    "percent": _calc_percent(row["files_converted"], row["total_files"]),
}
```

### 6c. Active jobs summary endpoint

If there is a `/api/bulk/active` or `/api/jobs/active` endpoint that the dashboard polls, add the
`progress` block to each job entry in that response as well.

---

## Part 7 — Frontend UI Updates

### 7a. Locate the relevant UI files

Check the `static/` directory. The files to update are most likely:
- The bulk jobs / scan progress page (check CLAUDE.md for filename — likely `bulk.html` or `jobs.html`)
- Possibly `admin.html` or `index.html` if job status is shown there

### 7b. Progress display component (vanilla JS)

Add a `renderProgress(progress)` function to the relevant JS file (or inline in the HTML `<script>`
block). This function renders the progress bar and ETA text.

```javascript
/**
 * Renders a progress block into a container element.
 * @param {object} progress - The progress object from the API response
 * @param {HTMLElement} container - The DOM element to render into
 */
function renderProgress(progress, container) {
    if (!progress) return;

    const { completed, total, count_ready, percent, eta_human, files_per_second } = progress;

    // Build count string
    let countStr;
    if (total === null || total === undefined) {
        countStr = `${completed.toLocaleString()} files processed — counting total…`;
    } else {
        const pct = percent !== null ? ` (${percent}%)` : '';
        countStr = `${completed.toLocaleString()} of ${total.toLocaleString()} files${pct}`;
    }

    // Build ETA string
    const etaStr = eta_human || (completed > 0 ? 'Calculating…' : '');

    // Build speed string
    const speedStr = files_per_second ? `${files_per_second.toFixed(1)} files/sec` : '';

    container.innerHTML = `
        <div class="progress-wrapper">
            <div class="progress-count">${countStr}</div>
            ${percent !== null ? `
            <div class="progress-bar-track">
                <div class="progress-bar-fill" style="width: ${Math.min(100, percent)}%"></div>
            </div>` : ''}
            <div class="progress-meta">
                <span class="progress-eta">${etaStr}</span>
                ${speedStr ? `<span class="progress-speed">${speedStr}</span>` : ''}
            </div>
        </div>
    `;
}
```

### 7c. Wire into existing poll loop

The existing UI likely has a `setInterval` or polling loop that fetches job status. In that loop,
after receiving the response, call:

```javascript
const progressContainer = document.getElementById('job-progress-' + jobId);
// or whatever the container's ID pattern is — inspect the existing HTML
if (progressContainer && data.progress) {
    renderProgress(data.progress, progressContainer);
}
```

### 7d. Add progress container to job cards/rows

In the existing HTML template for job cards (wherever job status is displayed), add:

```html
<!-- Inside each job card or row, add this container: -->
<div id="job-progress-{{JOB_ID}}" class="job-progress-container"></div>
```

Since this is vanilla JS (no templating engine), the job card is likely built via JS string
interpolation. Add the container div in that string.

### 7e. Add CSS to `static/markflow.css`

```css
/* ── Progress Tracking ─────────────────────────────────────────────── */
.progress-wrapper {
    margin: 8px 0;
    font-size: 0.875rem;
}

.progress-count {
    color: var(--text-secondary, #6b7280);
    margin-bottom: 4px;
    font-variant-numeric: tabular-nums;
}

.progress-bar-track {
    height: 6px;
    background: var(--surface-2, #e5e7eb);
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 4px;
}

.progress-bar-fill {
    height: 100%;
    background: var(--accent, #3b82f6);
    border-radius: 3px;
    transition: width 0.8s ease;
}

.progress-meta {
    display: flex;
    justify-content: space-between;
    color: var(--text-tertiary, #9ca3af);
    font-size: 0.8rem;
}

.progress-eta {
    font-weight: 500;
    color: var(--text-secondary, #6b7280);
}

.progress-speed {
    font-variant-numeric: tabular-nums;
}
```

---

## Part 8 — Tests

Add the following test file: `tests/test_progress_tracker.py`

```python
"""Tests for core/progress_tracker.py"""
import asyncio
import time
import pytest
from core.progress_tracker import RollingWindowETA, _format_eta, ProgressSnapshot


class TestRollingWindowETA:

    @pytest.mark.asyncio
    async def test_initial_state_no_total(self):
        tracker = RollingWindowETA()
        snap = await tracker.snapshot()
        assert snap.completed == 0
        assert snap.total is None
        assert snap.eta_seconds is None
        assert snap.count_ready is False

    @pytest.mark.asyncio
    async def test_initial_state_with_total(self):
        tracker = RollingWindowETA(total=1000)
        snap = await tracker.snapshot()
        assert snap.total == 1000
        assert snap.count_ready is True

    @pytest.mark.asyncio
    async def test_set_total_marks_ready(self):
        tracker = RollingWindowETA()
        await tracker.set_total(5000)
        snap = await tracker.snapshot()
        assert snap.total == 5000
        assert snap.count_ready is True

    @pytest.mark.asyncio
    async def test_update_total_does_not_mark_ready(self):
        tracker = RollingWindowETA()
        await tracker.update_total(2500)
        snap = await tracker.snapshot()
        assert snap.total == 2500
        assert snap.count_ready is False  # still counting

    @pytest.mark.asyncio
    async def test_no_eta_before_min_samples(self):
        tracker = RollingWindowETA(total=100)
        await tracker.record_completion()
        await tracker.record_completion()
        snap = await tracker.snapshot()
        # Only 2 samples, below MIN_SAMPLES=3
        assert snap.eta_seconds is None

    @pytest.mark.asyncio
    async def test_eta_computed_after_min_samples(self):
        tracker = RollingWindowETA(total=1000)
        for _ in range(10):
            await tracker.record_completion()
            await asyncio.sleep(0.01)  # simulate ~10ms per file
        snap = await tracker.snapshot()
        assert snap.eta_seconds is not None
        assert snap.eta_seconds > 0
        assert snap.files_per_second is not None
        assert snap.files_per_second > 0

    @pytest.mark.asyncio
    async def test_eta_zero_when_complete(self):
        tracker = RollingWindowETA(total=5)
        for _ in range(5):
            await tracker.record_completion()
            await asyncio.sleep(0.01)
        snap = await tracker.snapshot()
        assert snap.eta_seconds == 0.0

    @pytest.mark.asyncio
    async def test_percent_computed_in_to_dict(self):
        tracker = RollingWindowETA(total=200)
        for _ in range(50):
            await tracker.record_completion()
        snap = await tracker.snapshot()
        d = snap.to_dict()
        assert d["percent"] == 25.0

    @pytest.mark.asyncio
    async def test_percent_none_when_total_unknown(self):
        tracker = RollingWindowETA()
        await tracker.record_completion()
        snap = await tracker.snapshot()
        d = snap.to_dict()
        assert d["percent"] is None

    @pytest.mark.asyncio
    async def test_rolling_window_evicts_old_samples(self):
        """Window of 5 should evict oldest entries."""
        tracker = RollingWindowETA(total=1000, window_size=5)
        for i in range(10):
            await tracker.record_completion()
            await asyncio.sleep(0.005)
        assert len(tracker._window) == 5


class TestFormatEta:

    def test_none_returns_none(self):
        assert _format_eta(None) is None

    def test_seconds(self):
        result = _format_eta(45)
        assert "45s" in result

    def test_minutes(self):
        result = _format_eta(150)
        assert "2m" in result

    def test_hours(self):
        result = _format_eta(7384)  # ~2h 3m
        assert "2h" in result

    def test_negative_finishing(self):
        result = _format_eta(-1)
        assert "finishing" in result

    def test_zero(self):
        result = _format_eta(0)
        assert "0s" in result
```

Also add integration tests for the DB migration and API progress field shape:

```python
# In tests/test_api_progress.py

async def test_scan_status_includes_progress_block(client, db):
    """GET /api/scans/{id} should return a progress object."""
    # Create a scan_run record
    # ... setup ...
    resp = await client.get(f"/api/scans/{scan_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "progress" in data
    progress = data["progress"]
    assert "completed" in progress
    assert "total" in progress
    assert "eta_seconds" in progress
    assert "eta_human" in progress
    assert "count_ready" in progress

async def test_bulk_job_status_includes_progress_block(client, db):
    """GET /api/bulk/jobs/{id} should return a progress object."""
    # ... similar pattern ...
```

Add at minimum the two API shape tests even if they require fixture setup.

---

## Part 9 — Structured Logging

All ETA updates should emit structured log events for Grafana/Loki monitoring.

In the scan worker, add to the periodic ETA write block:

```python
log.info(
    "scan_progress",
    job_id=scan_run_id,
    completed=snap.completed,
    total=snap.total,
    count_ready=snap.count_ready,
    eta_seconds=snap.eta_seconds,
    files_per_second=snap.files_per_second,
)
```

In the bulk worker, add to the periodic ETA write block:

```python
log.info(
    "bulk_progress",
    job_id=job_id,
    completed=snap.completed,
    total=snap.total,
    eta_seconds=snap.eta_seconds,
    files_per_second=snap.files_per_second,
)
```

Use `structlog.get_logger()` with the same logger binding pattern already in use in those files.
Do not introduce a new logging pattern — match what's already there.

---

## Part 10 — Done Criteria

Before marking this changeset complete, verify all of the following:

- [ ] `core/progress_tracker.py` exists and all unit tests in `test_progress_tracker.py` pass
- [ ] DB migrations applied cleanly — verify with `PRAGMA table_info(scan_runs)` and
      `PRAGMA table_info(bulk_jobs)` — new columns present
- [ ] Concurrent fast-walk launches in parallel with scan start — scan does NOT wait for count
- [ ] `total_files_counted` and `count_status` update in DB during a live scan
      (verify: start a scan, poll the DB every 5s, watch values change)
- [ ] Bulk worker writes `eta_seconds` and `files_per_second` to `bulk_jobs` during conversion
- [ ] `GET /api/scans/{id}` response includes `progress.total`, `progress.eta_human`,
      `progress.count_ready`
- [ ] `GET /api/bulk/jobs/{id}` response includes `progress.total`, `progress.eta_human`
- [ ] UI shows "X of Y files" (or "X files — counting total…" before count is ready)
- [ ] UI progress bar animates as files complete
- [ ] ETA string appears (e.g., "~14m 32s remaining") and updates on each poll
- [ ] All pre-existing tests still pass (baseline count preserved)
- [ ] No new `Exception` swallowed silently — all error paths log with structlog

---

## Part 11 — CLAUDE.md Update

After all done criteria are checked, update CLAUDE.md:

1. Bump version to `[NEXT]`
2. Add entry under **Completed Patches**:
   ```
   ### v[NEXT] — Progress Tracking & ETA
   - New: core/progress_tracker.py — RollingWindowETA, ProgressSnapshot, _format_eta
   - DB: scan_runs + bulk_jobs + conversion_history — added eta_seconds, files_per_second,
         total_files_counted, count_status, eta_updated_at columns
   - Concurrent fast-walk counter in scan worker (asyncio.create_task — non-blocking)
   - Rolling window ETA (last 100 items) in scan worker and bulk worker
   - Single-file conversion ETA via historical average from conversion_history
   - API: all job status endpoints now return progress block with eta_human, percent, count_ready
   - UI: progress bar, count display, ETA string, speed display on all job cards
   - Tests: test_progress_tracker.py (14 tests), test_api_progress.py (2 integration tests)
   ```
3. Update any phase status entries that this patch affects.
4. Add to **Known Gotchas** if anything unusual was discovered during implementation.
