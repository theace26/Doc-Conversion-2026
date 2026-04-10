# MarkFlow Audit Remediation & Spec Implementation — Design Spec

**Date:** 2026-04-09
**Version:** 0.22.19 → 0.23.0
**Branch:** vector
**Scope:** 17 implementation items from the combined Health Audit + Specification Review

---

## Table of Contents

1. [Overview](#1-overview)
2. [Database Layer (Items G, M, N, O, P)](#2-database-layer)
3. [Pipeline Stats & Frontend (Items A, E)](#3-pipeline-stats--frontend)
4. [Vision Adapter (Item B + Batch Redesign)](#4-vision-adapter)
5. [bulk_files Deduplication & Cleanup (Items D, F)](#5-bulk_files-deduplication--cleanup)
6. [Lifecycle & Trash (Lifecycle Churn Fix, Trash Expiry Force)](#6-lifecycle--trash)
7. [Scanning & Worker Pool (Scanner Incremental, Worker Config, Semaphore)](#7-scanning--worker-pool)
8. [PDF Engine & Logging (C6, httpx Suppression, Unused Deps)](#8-pdf-engine--logging)
9. [Testing & Validation (S4, S2)](#9-testing--validation)
10. [Vector Indexing (Item Q)](#10-vector-indexing)
11. [File Inventory](#11-file-inventory)
12. [Migration & Rollback](#12-migration--rollback)

---

## 1. Overview

### Problem Statement

Live-system log analysis (14 hours, 3.6M log lines) and DB inspection revealed:

- Pipeline stats endpoint blocking for up to 431 seconds (7 minutes)
- Frontend polling generating 49,000+ requests/day with zero users
- Vision adapter failing 100% (MIME type mismatch)
- bulk_files table inflated 3.1x (276K rows for 88K unique files)
- 35K lifecycle trash events in 14 hours (test timer values)
- 2.4M lines of DB contention logging
- Per-file DB writes in worker loop (800K+ writes for a full scan)
- Conversion semaphore starving 5 of 8 workers

### Design Principles

1. **Reads never block writes** — Read-only connection pool for analytics
2. **Batch over individual** — Counter updates, image API calls, DB inserts
3. **Cache over re-query** — TTL caches for slow-changing data
4. **Housekeeping is non-negotiable** — Cleanup jobs supersede normal work
5. **User-configurable, sensible defaults** — Worker count, semaphore, timers from Settings

---

## 2. Database Layer

### 2.1 Connection Pool (`core/db/connection.py`)

**Replace** per-call `aiosqlite.connect()` with a module-level `ConnectionPool` class.

```
Pool composition (scales with host hardware):
  - N general-purpose connections (read/write): max(2, cpu_count // 4), capped at 4
  - 2 read-only connections (PRAGMA query_only=ON): fixed at 2
  - Total: 4-6 connections depending on host

  Examples:
    i7-10750H (12 logical) → 3 rw + 2 ro = 5
    i5-8250U  (8 logical)  → 2 rw + 2 ro = 4
    Threadripper (32 logical) → 4 rw + 2 ro = 6 (capped)
    Dual-core (4 logical) → 2 rw + 2 ro = 4 (floor)
```

**Pool lifecycle:**
- Initialized once during `main.py:lifespan` startup
- Each connection runs PRAGMAs once at creation:
  - `PRAGMA journal_mode=WAL`
  - `PRAGMA busy_timeout=30000` (raised from 5000)
  - `PRAGMA foreign_keys=ON`
  - Read-only connections additionally: `PRAGMA query_only=ON`
- Pool exposes:
  - `async get_connection() -> AsyncContextManager` — returns a general-purpose connection
  - `async get_read_connection() -> AsyncContextManager` — returns a read-only connection
- Connections are reused via asyncio.Queue (FIFO)
- On pool shutdown: close all connections

**Backward compatibility:**
- Existing `db_fetch_one()`, `db_fetch_all()`, `db_execute()` functions updated to use pool internally
- Analytics endpoints (`/pipeline/stats`, `/pipeline/status`, `/scanner/progress`) use `get_read_connection()`
- All other code continues using existing helper functions (transparent migration)

### 2.2 busy_timeout Increase

Changed from `PRAGMA busy_timeout=5000` to `PRAGMA busy_timeout=30000` in pool init.
Single-location change since PRAGMAs now only run at pool creation.

### 2.3 Preferences Caching (`core/preferences_cache.py` — new file)

```python
# Module-level cache
_cache: dict[str, tuple[Any, float]] = {}  # key -> (value, expiry_time)
TTL = 300  # 5 minutes

async def get_cached_preference(key: str, default=None):
    now = time.time()
    if key in _cache and _cache[key][1] > now:
        return _cache[key][0]
    value = await get_preference(key, default)  # DB call
    _cache[key] = (value, now + TTL)
    return value

def invalidate_preference(key: str):
    _cache.pop(key, None)

def invalidate_all():
    _cache.clear()
```

**Integration points:**
- All `get_preference()` calls in `scheduler.py`, `bulk_worker.py`, `converter.py` → `get_cached_preference()`
- `PUT /api/preferences/<key>` handler calls `invalidate_preference(key)` after DB write
- Settings page "Save" action invalidates all

### 2.4 Stale Job Detection

**Schema change** (`core/db/schema.py`):
- Add column: `ALTER TABLE bulk_jobs ADD COLUMN last_heartbeat DATETIME`

**Heartbeat updates** (`core/bulk_worker.py`):
- During scan/conversion loop, update `last_heartbeat = datetime('now')` every 60 seconds
- Use a simple time check: `if time.time() - last_hb_time > 60: update_heartbeat(job_id)`

**Startup cleanup** (`main.py:lifespan`):
```sql
UPDATE bulk_jobs
SET status = 'interrupted'
WHERE status = 'running'
  AND last_heartbeat < datetime('now', '-30 minutes')
```
- Runs once on startup, after pool init, before scheduler starts
- Gated by a check: only runs if there are actually stale jobs

### 2.5 File I/O Outside Transactions (`core/lifecycle_manager.py`)

**Current pattern (broken):**
```
BEGIN TRANSACTION
  read metadata
  shutil.move(src, dst)  ← holds write lock during I/O
  update status
COMMIT
```

**New pattern:**
```
TRANSACTION 1 (fast):
  read metadata
  update status = 'moving'
COMMIT

FILE I/O (no lock held):
  shutil.move(src, dst)

TRANSACTION 2 (fast):
  update status = 'in_trash'
  update trash_path
COMMIT
```

If the file move fails, Transaction 2 sets status back to 'marked_for_deletion' with error logged.
If the process crashes between T1 and T2, startup detects 'moving' status and retries.

Apply same pattern to `purge_file()`.

---

## 3. Pipeline Stats & Frontend

### 3.1 Pipeline Stats Caching (`api/routes/pipeline.py`)

```python
_stats_lock = asyncio.Lock()
_stats_cache: dict = {"result": None, "time": 0}
_STATS_TTL = 20  # seconds

async def pipeline_stats(...):
    now = time.time()
    if _stats_cache["result"] and now - _stats_cache["time"] < _STATS_TTL:
        return _stats_cache["result"]

    async with _stats_lock:
        # Double-check after acquiring lock (another request may have refreshed)
        if _stats_cache["result"] and time.time() - _stats_cache["time"] < _STATS_TTL:
            return _stats_cache["result"]

        # Run queries using read-only connection
        result = await _compute_stats()
        _stats_cache["result"] = result
        _stats_cache["time"] = time.time()
        return result
```

Apply identical pattern to `pipeline_status()`.

**Cache invalidation:**
- `invalidate_stats_cache()` function sets `_stats_cache["time"] = 0`
- Called from `scan_coordinator.notify_bulk_started()` and `notify_bulk_completed()`

### 3.2 Frontend Polling (`static/js/global-status-bar.js`)

```javascript
var POLL_VISIBLE = 20000;     // 20 seconds when tab visible
var POLL_HIDDEN = 30000;      // 30 seconds when tab hidden
var MAX_HIDDEN_MS = 1800000;  // 30 minutes max hidden polling
var hiddenSince = null;

document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
        hiddenSince = Date.now();
        clearInterval(pollTimer);
        pollTimer = setInterval(function() {
            if (Date.now() - hiddenSince > MAX_HIDDEN_MS) {
                clearInterval(pollTimer);  // stop polling after 30 min
                return;
            }
            poll();
        }, POLL_HIDDEN);
    } else {
        hiddenSince = null;
        clearInterval(pollTimer);
        location.reload();  // full page refresh on tab re-activation
    }
});

// Initial poll at visible interval
pollTimer = setInterval(poll, POLL_VISIBLE);
```

**Additional page-specific audits:**
- `pipeline-files.html` — align to 20s
- `bulk.html` — align to 15-20s (SSE already handles live updates during active jobs)

---

## 4. Vision Adapter

### 4.1 MIME Detection (`core/vision_adapter.py`)

New helper function:

```python
_MAGIC_BYTES = {
    b'\xff\xd8\xff': 'image/jpeg',
    b'\x89PNG': 'image/png',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF': '_check_webp',  # need to also check bytes 8-12 for WEBP
    b'BM': 'image/bmp',
}

def detect_mime(file_path: Path) -> str:
    """Detect actual MIME from file magic bytes, fall back to extension."""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(32)
        for magic, mime in _MAGIC_BYTES.items():
            if header.startswith(magic):
                if mime == '_check_webp':
                    return 'image/webp' if header[8:12] == b'WEBP' else 'image/bmp'
                return mime
    except OSError:
        pass
    # Fallback to extension
    return mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream'
```

Replace all `mimetypes.guess_type()` calls in the image batching path with `detect_mime()`.

### 4.2 Collect-Then-Dispatch Batch Redesign

**Phase 1: Catalog (during scan)**
- As the lifecycle/bulk scanner encounters image files, enqueue them to `analysis_queue` with status `pending_catalog`
- Record: file path, file size, detected MIME type
- Do NOT submit to API during scan

**Phase 2: Batch Planning (post-scan)**
- Triggered by `scan_coordinator.notify_bulk_completed()` or lifecycle scan completion
- Query all `pending_catalog` entries
- Resolve the active vision provider via `get_active_provider()`
- Look up provider-specific limits from `_PROVIDER_LIMITS` (see below)
- Group images by MIME type, then bin-pack into batches sized per provider limits
- Update status to `batched`, store `batch_id`

**Provider-Aware Batch Limits:**

The vision adapter already supports anthropic, openai, gemini, and ollama.
Each provider has different request size limits and per-image caps. A new
module-level dict centralizes these:

```python
_PROVIDER_LIMITS = {
    "anthropic": {
        "max_request_bytes": 24 * 1024 * 1024,  # 32MB limit - 33% base64 overhead
        "max_image_raw_bytes": 3_500_000,         # 5MB encoded cap → 3.5MB raw
        "max_images_per_batch": 20,
        "max_edge_px": 1568,
    },
    "openai": {
        "max_request_bytes": 18 * 1024 * 1024,   # 20MB limit - overhead
        "max_image_raw_bytes": 18 * 1024 * 1024,  # no per-image cap, just total
        "max_images_per_batch": 10,               # GPT-4o handles 10 well
        "max_edge_px": 2048,
    },
    "gemini": {
        "max_request_bytes": 18 * 1024 * 1024,   # 20MB limit - overhead
        "max_image_raw_bytes": 18 * 1024 * 1024,  # generous per-image
        "max_images_per_batch": 16,
        "max_edge_px": 3072,
    },
    "ollama": {
        "max_request_bytes": 50 * 1024 * 1024,   # local, generous
        "max_image_raw_bytes": 50 * 1024 * 1024,  # local, no real cap
        "max_images_per_batch": 5,                # local models are slower
        "max_edge_px": 1568,                      # model-dependent, safe default
    },
}
_DEFAULT_LIMITS = _PROVIDER_LIMITS["anthropic"]  # fallback for unknown providers
```

**Batch sizing algorithm:**
1. Resolve active provider → look up limits (fall back to `_DEFAULT_LIMITS`)
2. Sort images by file size descending (largest first for better bin-packing)
3. Start a new batch; for each image:
   - If adding this image would exceed `max_request_bytes` or `max_images_per_batch`, close batch, start new
   - If single image exceeds `max_image_raw_bytes`, resize/compress to fit (existing `_compress_image_for_vision` logic)
4. Each batch records its target provider so that if the provider changes mid-queue, remaining batches are re-planned

**Phase 3: Submit (async, post-scan)**
- Process batches sequentially (respect rate limits)
- On success: status → `completed`
- On failure: increment `retry_count`, status → `pending_catalog` if retries < 3, else `failed`
- On MIME error (400): log, skip that image (bad file), status → `failed`
- If active provider changes between batch planning and submission, re-plan remaining batches with new provider limits

**Re-queue existing failures:**
- One-time migration in `main.py:lifespan`: reset `analysis_queue` entries with status `failed` AND `error LIKE '%media type%'` back to `pending_catalog`

---

## 5. bulk_files Deduplication & Cleanup

### 5.1 Scanner Key Change (`core/bulk_scanner.py`)

**Current:** `ON CONFLICT(job_id, source_path) DO UPDATE ...`
**New:** `ON CONFLICT(source_path) DO UPDATE SET job_id=?, mtime=?, size=?, updated_at=?`

This requires schema change:
- SQLite does not support DROP CONSTRAINT. Migration approach: create new table with `(source_path)` unique constraint, copy data (latest row per source_path), drop old table, rename new table.
- Keep `job_id` as a non-unique column (tracks which job last touched the file)
- The dedup cleanup (Section 5.2) naturally feeds into this — dedup first, then migrate table structure.

**Migration:** The one-time dedup cleanup (Section 5.2) must run BEFORE the constraint change.

### 5.2 Cross-Job Deduplication Query

Run after each scan as a post-scan cleanup step:

```sql
DELETE FROM bulk_files
WHERE rowid NOT IN (
    SELECT MAX(rowid) FROM bulk_files GROUP BY source_path
)
```

This keeps only the latest row per `source_path`.

**One-time historical cleanup:**
- Run in `main.py:lifespan`, gated by preference `bulk_dedup_v0_23_done`
- Expected to delete ~187,784 rows
- Follow with `PRAGMA optimize` and `ANALYZE`

### 5.3 Scheduled Housekeeping (`core/scheduler.py`)

New APScheduler job: `run_housekeeping`, interval: 2 hours.

**This job does NOT check `get_all_active_jobs()`.** It runs regardless of active bulk jobs.

Steps:
1. Cross-job dedup query (safety net — should be near-zero rows after scanner fix)
2. `PRAGMA optimize` (lets SQLite update query planner stats)
3. Check `PRAGMA freelist_count` — if free pages > 10% of `page_count`, run `VACUUM`
4. Log results: rows deduped, pages freed, vacuum ran y/n

---

## 6. Lifecycle & Trash

### 6.1 Restore Production Timers

On startup in `main.py:lifespan`, after existing migrations:

```python
# Warn if lifecycle timers are at testing values
grace = await get_preference('lifecycle_grace_period_hours', 36)
retention = await get_preference('lifecycle_trash_retention_days', 60)
if grace < 24:
    log.warning("lifecycle_grace_period_hours is below production threshold",
                current=grace, recommended=36)
if retention < 30:
    log.warning("lifecycle_trash_retention_days is below production threshold",
                current=retention, recommended=60)
```

Set the actual values via the existing preferences update mechanism:
- `lifecycle_grace_period_hours`: 36
- `lifecycle_trash_retention_days`: 60

### 6.2 Forced Trash Expiry

In `core/scheduler.py`:

```python
_trash_expiry_count = 0

async def run_trash_expiry():
    global _trash_expiry_count
    _trash_expiry_count += 1

    # Every 4th run: force execution regardless of active bulk jobs
    force = (_trash_expiry_count % 4 == 0)

    if not force:
        active = await get_all_active_jobs()
        if active:
            log.info("trash_expiry.skipped_bulk_active")
            return

    # ... existing trash expiry logic ...
```

---

## 7. Scanning & Worker Pool

### 7.1 Incremental Scanning (`core/bulk_scanner.py`)

Add to the per-file processing loop:

```python
# Skip files already successfully processed
existing = await get_bulk_file_by_source_path(path_str)
if existing and existing['status'] == 'converted' and existing['mtime'] == mtime:
    counters['skipped_unchanged'] += 1
    continue
```

This prevents re-queuing files that are already converted and haven't changed.

### 7.2 Worker Count from Settings (`core/bulk_worker.py`)

**Settings integration:**
- New preference: `bulk_worker_count` (default: 8, range: 1-16)
- Read via `get_cached_preference('bulk_worker_count', 8)` at job start
- Settings UI: add slider/input in the Pipeline section

**Dynamic throttling:**
- Track rolling average conversion time (last 50 conversions)
- If current conversion takes > 2x rolling average, decrement active worker count by 1
- If 10 consecutive conversions are below average, increment by 1 (up to configured max)
- Never drop below 2 workers

### 7.3 Conversion Semaphore (`core/converter.py`)

```python
# Module-level semaphore, rebuilt when preference changes
_semaphore = asyncio.Semaphore(6)  # default
_semaphore_limit = 6

async def refresh_semaphore():
    """Called on startup and when max_concurrent_conversions preference changes."""
    global _semaphore, _semaphore_limit
    limit = int(await get_cached_preference('max_concurrent_conversions', 6))
    if limit != _semaphore_limit:
        _semaphore = asyncio.Semaphore(limit)
        _semaphore_limit = limit
```

Default is now **auto-detected from host hardware**, not hardcoded:

```python
import os

def _detect_default_concurrency() -> int:
    """Auto-detect optimal concurrent conversions based on host hardware."""
    cpu_count = os.cpu_count() or 4
    # Use physical core count (logical / 2 for hyperthreaded CPUs)
    # Cap at 8 — diminishing returns beyond that due to I/O contention
    # Floor at 2 — always allow some parallelism
    physical = max(2, min(cpu_count // 2, 8))
    return physical

# Example results:
#   i7-10750H (6c/12t)  → 6
#   i5-8250U  (4c/8t)   → 4
#   Ryzen 5600X (6c/12t) → 6
#   Dual-core NUC (2c/4t) → 2
#   16-core Threadripper  → 8 (capped)
```

The auto-detected value is the **startup default**. Users can override via
`max_concurrent_conversions` in Settings. The dynamic throttling system
(Section 7.2) adjusts downward from whatever the configured value is
when conversions are running slow (I/O-bound, mechanical drive, etc.).

### 7.4 Counter Batching (`core/bulk_worker.py`)

```python
class CounterAccumulator:
    def __init__(self, job_id: str, flush_interval: int = 50, flush_timeout: float = 5.0):
        self.job_id = job_id
        self.counts = {'converted': 0, 'failed': 0, 'skipped': 0}
        self.since_flush = 0
        self.last_flush = time.time()
        self.flush_interval = flush_interval
        self.flush_timeout = flush_timeout

    def increment(self, field: str):
        self.counts[field] += 1
        self.since_flush += 1

    async def maybe_flush(self):
        if self.since_flush >= self.flush_interval or \
           time.time() - self.last_flush > self.flush_timeout:
            await self._flush()

    async def _flush(self):
        if self.since_flush == 0:
            return
        for field, count in self.counts.items():
            if count > 0:
                await increment_bulk_job_counter(self.job_id, field, count)
                self.counts[field] = 0
        self.since_flush = 0
        self.last_flush = time.time()

    async def flush_final(self):
        """Call on job completion to flush remaining counts."""
        await self._flush()
```

SSE progress events continue to fire per-file from in-memory state (not from DB counters).

---

## 8. PDF Engine & Logging

### 8.1 PyMuPDF Default with Auto-Switch (`formats/pdf_handler.py`)

```python
import fitz  # PyMuPDF

async def ingest(self, file_path: Path) -> DocumentModel:
    doc = fitz.open(str(file_path))
    model = DocumentModel()

    for page_num in range(len(doc)):
        page = doc[page_num]

        # Check for tables: look for line objects forming grid patterns
        has_tables = self._detect_tables_pymupdf(page)

        if has_tables:
            # Switch to pdfplumber for this page
            elements = self._extract_with_pdfplumber(file_path, page_num)
        else:
            # Use PyMuPDF (faster)
            elements = self._extract_with_pymupdf(page)

        model.elements.extend(elements)

    doc.close()
    return model

def _detect_tables_pymupdf(self, page) -> bool:
    """Detect table presence via line/rect analysis."""
    drawings = page.get_drawings()
    # Count horizontal and vertical lines
    h_lines = sum(1 for d in drawings for item in d['items']
                  if item[0] == 'l' and abs(item[1].y - item[2].y) < 2)
    v_lines = sum(1 for d in drawings for item in d['items']
                  if item[0] == 'l' and abs(item[1].x - item[2].x) < 2)
    # Table heuristic: 3+ horizontal AND 3+ vertical lines = table
    return h_lines >= 3 and v_lines >= 3
```

**Wire preference:** Check `pdf_engine` preference. If set to `pdfplumber`, skip PyMuPDF entirely. Default: `pymupdf`.

### 8.2 httpx/httpcore Log Suppression (`core/logging_config.py`)

Add to `configure_logging()`:

```python
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
```

Same pattern as existing pdfminer suppression. Eliminates ~40,000 log lines/day.

### 8.3 Remove Unused Dependencies (`requirements.txt`)

Remove:
- `mammoth` — never imported
- `markdownify` — never imported (Note: markitdown stays — used for validation per Section 9.2)

Verify with: `grep -r "import mammoth\|from mammoth\|import markdownify\|from markdownify" --include="*.py"`

---

## 9. Testing & Validation

### 9.1 Structural Hash (`core/document_model.py`)

```python
import hashlib

def structural_hash(self) -> str:
    """Generate a single hash representing document structure for round-trip comparison."""
    parts = []

    # Headings: count + text
    headings = [e for e in self.elements if e.element_type == ElementType.HEADING]
    parts.append(f"h:{len(headings)}")
    for h in headings:
        parts.append(f"ht:{h.content[:100]}")

    # Tables: count + dimensions + cell content
    tables = [e for e in self.elements if e.element_type == ElementType.TABLE]
    parts.append(f"t:{len(tables)}")
    for t in tables:
        if t.table_data:
            parts.append(f"td:{len(t.table_data)}x{len(t.table_data[0]) if t.table_data else 0}")
            for row in t.table_data:
                for cell in row:
                    parts.append(f"tc:{str(cell)[:50]}")

    # Images: count + dimensions
    images = [e for e in self.elements if e.element_type == ElementType.IMAGE]
    parts.append(f"i:{len(images)}")
    for img in images:
        w = img.metadata.get('width', 0) if img.metadata else 0
        h = img.metadata.get('height', 0) if img.metadata else 0
        parts.append(f"id:{w}x{h}")

    # Lists: count + nesting depth
    lists = [e for e in self.elements if e.element_type == ElementType.LIST]
    parts.append(f"l:{len(lists)}")
    for li in lists:
        depth = li.metadata.get('depth', 0) if li.metadata else 0
        parts.append(f"ld:{depth}")

    combined = "|".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()
```

**Tests** (`tests/test_roundtrip.py`):
- `test_structural_hash_consistency()` — same document produces same hash
- `test_structural_hash_detects_heading_change()` — adding a heading changes hash
- `test_structural_hash_detects_table_change()` — modifying table dimensions changes hash
- `test_roundtrip_structural_hash_preserved()` — docx → md → docx preserves structural hash

### 9.2 markitdown Validation Reference (`core/validation/markitdown_compare.py`)

```python
from markitdown import MarkItDown

async def compare_with_markitdown(file_path: Path) -> dict:
    """Run markitdown conversion and compare against MarkFlow output."""
    md = MarkItDown()
    result = md.convert(str(file_path))
    markitdown_text = result.text_content

    # Compare structural metrics
    markflow_model = await convert_to_model(file_path)

    return {
        "markflow_headings": count_headings(markflow_model),
        "markitdown_headings": count_markdown_headings(markitdown_text),
        "markflow_tables": count_tables(markflow_model),
        "markitdown_tables": count_markdown_tables(markitdown_text),
        "heading_match": ...,
        "table_match": ...,
    }
```

**NOT in the hot path.** Available as:
- CLI utility: `python -m core.validation.markitdown_compare <file>`
- Background validation job (optional, triggered manually)

---

## 10. Vector Indexing

### Backpressure (`core/bulk_worker.py`)

```python
_vector_semaphore = asyncio.Semaphore(20)

async def _index_in_background(file_path, content):
    acquired = _vector_semaphore.acquire_nowait()  # non-blocking
    if not acquired:
        log.info("vector_indexing.backpressure_skip", file=str(file_path))
        return  # picked up on next lifecycle scan

    try:
        await index_to_qdrant(file_path, content)
    finally:
        _vector_semaphore.release()
```

Replace existing `asyncio.create_task(index_to_qdrant(...))` calls with `asyncio.create_task(_index_in_background(...))`.

---

## 11. File Inventory

Files created or modified, organized by subsystem:

### New Files
| File | Purpose |
|------|---------|
| `core/preferences_cache.py` | TTL-cached preference reads |
| `core/validation/__init__.py` | Validation package |
| `core/validation/markitdown_compare.py` | markitdown comparison utility |

### Modified Files
| File | Changes |
|------|---------|
| `core/db/connection.py` | Connection pool (5 connections, read/write separation) |
| `core/db/schema.py` | Add `last_heartbeat` column to bulk_jobs |
| `core/db/preferences.py` | Wire cache invalidation |
| `core/preferences_cache.py` | New: TTL cache module |
| `core/lifecycle_manager.py` | I/O outside transactions pattern |
| `core/bulk_scanner.py` | Incremental mode, key change to (source_path), post-scan dedup |
| `core/bulk_worker.py` | CounterAccumulator, worker count from settings, dynamic throttle, vector backpressure, heartbeat |
| `core/converter.py` | Semaphore from preferences (default 6), read-only pool for stats |
| `core/vision_adapter.py` | Magic-byte MIME detection, collect-then-dispatch batching |
| `core/scheduler.py` | Housekeeping job (2h), forced trash expiry (every 4th), preferences cache usage |
| `core/scan_coordinator.py` | Trigger vision batch planning on scan complete, stats cache invalidation |
| `core/document_model.py` | structural_hash() method |
| `core/logging_config.py` | Suppress httpx/httpcore to WARNING |
| `core/version.py` | Bump to 0.23.0 |
| `main.py` | Pool init, stale job cleanup, bulk dedup migration, lifecycle timer warnings |
| `api/routes/pipeline.py` | Stats/status TTL caching with read-only connections |
| `api/routes/preferences.py` | Cache invalidation on PUT |
| `formats/pdf_handler.py` | PyMuPDF primary with auto-switch to pdfplumber on tables |
| `static/js/global-status-bar.js` | Polling: 20s visible, 30s hidden (30min max), reload on activate |
| `requirements.txt` | Remove mammoth, markdownify |
| `tests/test_roundtrip.py` | structural_hash tests |

---

## 12. Migration & Rollback

### Startup Migrations (in `main.py:lifespan`, sequential)

1. **Stale job cleanup** — mark interrupted jobs (no gate needed, idempotent)
2. **bulk_files dedup** — one-time, gated by `bulk_dedup_v0_23_done` preference
3. **Schema: last_heartbeat column** — `ALTER TABLE bulk_jobs ADD COLUMN last_heartbeat DATETIME` (SQLite ignores if exists)
4. **Schema: bulk_files unique constraint** — create new table with `(source_path)` unique, migrate data, swap tables (SQLite has no ALTER CONSTRAINT)
5. **Vision re-queue** — reset MIME-error failures to `pending_catalog`
6. **Lifecycle timer check** — log warnings if below production thresholds
7. **Set production lifecycle timers** — update preferences to 36h grace, 60d retention

### Rollback

All changes are forward-compatible. If a rollback to 0.22.19 is needed:
- The connection pool gracefully degrades — old code opens new connections (slower but works)
- bulk_files with `(source_path)` unique constraint still works with old scanner (which uses ON CONFLICT)
- Preferences cache is transparent — removing the module falls back to direct DB reads
- The `last_heartbeat` column is ignored by old code (nullable, no NOT NULL constraint)

No destructive migrations. VACUUM is the only irreversible operation and is gated by free page threshold.
