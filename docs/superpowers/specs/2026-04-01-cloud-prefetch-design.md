# Cloud File Prefetch System — Design Spec

**Date:** 2026-04-01
**Version target:** v0.15.1
**Status:** Approved

## Problem

Cloud-synced source directories (OneDrive, Google Drive, Nextcloud, Dropbox, iCloud, NAS tiered storage, AWS Storage Gateway) use placeholder files that appear in directory listings but aren't immediately readable. When the converter tries to open these files, reads stall or fail, causing conversion errors and wasted time.

The scanner discovers 36K+ files but many may be cloud-only placeholders. Conversion fails or hangs when it tries to read them.

## Solution

A platform-agnostic background prefetch system that reads files ahead of conversion, forcing any cloud provider to download them. No vendor-specific APIs — uses the universal mechanism that reading file bytes triggers hydration on any platform.

## Architecture

Three components:

### 1. Cloud File Detector (`core/cloud_detector.py`)

Determines whether a file needs prefetching using platform-agnostic heuristics.

**Detection methods (in order):**

1. **Disk block check** — Compare `os.stat().st_blocks * 512` against `st_size`. Cloud placeholders report full size but occupy near-zero disk. If allocated < 50% of reported size, file is likely cloud-only. Falls back gracefully on platforms where `st_blocks` is unavailable (Windows via Docker mount may not expose this).

2. **Timed read probe** — Open the file, attempt to read 1 byte with a 500ms timeout. If the read takes > 200ms, the file is likely cloud-backed and needs prefetching. If the read completes instantly, the file is already local.

3. **Size-based fallback** — When `cloud_prefetch_probe_all` is false (default), only probe files above `cloud_prefetch_min_size_bytes`. When true, probe all files.

**Public interface:**

```python
class CloudDetector:
    async def needs_prefetch(self, path: Path, file_size: int) -> bool:
        """Returns True if the file appears to be a cloud placeholder."""

    async def probe_batch(self, paths: list[Path]) -> dict[Path, bool]:
        """Probe multiple files concurrently. Returns {path: needs_prefetch}."""
```

### 2. Prefetch Worker Pool (`core/cloud_prefetch.py`)

Background queue that downloads files ahead of conversion by reading them.

**Core class: `PrefetchManager`**

```python
class PrefetchStatus(Enum):
    PENDING = "pending"
    PREFETCHING = "prefetching"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"  # file was already local

class PrefetchManager:
    def __init__(self, concurrency: int, rate_limit: int, timeout: int): ...

    async def enqueue(self, path: Path, file_size: int, priority: int = 0) -> None:
        """Add a file to the prefetch queue. Lower priority = processed first."""

    async def enqueue_batch(self, files: list[tuple[Path, int]]) -> int:
        """Enqueue multiple files. Returns count of files that need prefetching."""

    async def wait_for(self, path: Path, timeout: float | None = None) -> PrefetchStatus:
        """Block until the file is ready or timeout. Used by converter."""

    async def status(self, path: Path) -> PrefetchStatus:
        """Check current status without blocking."""

    async def stats(self) -> dict:
        """Return queue depth, active count, completed, failed, avg speed."""

    async def shutdown(self) -> None:
        """Drain queue and stop workers gracefully."""
```

**Prefetch action:**
- Open file in binary read mode
- Read in 64KB chunks until EOF (forces cloud provider to download)
- Close the file — we don't need the content, just the side effect of reading it
- Track bytes read and duration for bandwidth calibration

**Adaptive timeout:**
- Base timeout: 30 seconds
- Per-file timeout: `base + (file_size / calibrated_bandwidth)`
- `calibrated_bandwidth` starts at a conservative 2 MB/s, recalculates as rolling average of last 20 successful prefetches
- Minimum timeout: 10 seconds (even for tiny files on slow connections)
- Maximum timeout: `cloud_prefetch_timeout_seconds` preference (default 120s)

**Rate limiting:**
- Token bucket: max `cloud_prefetch_rate_limit` prefetches per minute (default 30)
- Prevents tripping cloud provider throttles (OneDrive: 10K requests/10min, Google Drive: varies)
- When rate limited, workers sleep until tokens replenish

**Retry with backoff:**
- 3 retries per file
- Backoff: 5s, 15s, 45s
- After final failure: mark as FAILED, log warning, conversion will try anyway (may succeed if file hydrated by then)

**Concurrency:**
- `cloud_prefetch_concurrency` workers (default 5)
- Workers are asyncio tasks running in a ThreadPoolExecutor (file I/O is blocking)
- Concurrency auto-reduces if consecutive failures exceed threshold (backpressure)

**Memory footprint:**
- Status tracking: in-memory dict[str, PrefetchStatus] — ephemeral, resets on restart
- No DB writes — this is a session-level optimization, not persistent state
- Bandwidth stats: rolling window of last 20 measurements

### 3. Integration Points

**Scanner integration (`core/bulk_scanner.py`):**
- After `_process_discovered_file()` upserts a file to `bulk_files`, also enqueue it to PrefetchManager if `cloud_prefetch_enabled`
- Scanner does NOT wait for prefetch — fire-and-forget enqueue
- Files enqueued in discovery order (which approximates directory walk order = the order converter will process them)

**Converter integration (`core/bulk_worker.py`):**
- Before `_process_convertible()` opens a file, call `prefetch_manager.wait_for(path, timeout=per_file_timeout)`
- If status is READY: proceed immediately
- If status is PREFETCHING: wait for completion (bounded by timeout)
- If status is PENDING: prefetch inline — read the file directly, then convert
- If status is FAILED: attempt conversion anyway (might work, might fail gracefully)
- If prefetch is disabled: no change to existing behavior

**Pipeline startup (`core/pipeline_startup.py`):**
- Initialize PrefetchManager singleton during app lifespan if `cloud_prefetch_enabled`
- Shutdown gracefully on app shutdown

**Health check (`core/health.py`):**
- Add `cloud_prefetch` component showing: enabled, queue depth, active workers, bandwidth estimate, total prefetched/failed

**Settings page:**
- New "Cloud Prefetch" section with toggle and concurrency/rate/timeout controls

### 4. Preferences

| Key | Default | Description |
|-----|---------|-------------|
| `cloud_prefetch_enabled` | `"false"` | Master toggle |
| `cloud_prefetch_concurrency` | `"5"` | Concurrent prefetch workers |
| `cloud_prefetch_rate_limit` | `"30"` | Max prefetches per minute |
| `cloud_prefetch_timeout_seconds` | `"120"` | Max wait per file |
| `cloud_prefetch_min_size_bytes` | `"0"` | Min file size to prefetch (0 = all) |
| `cloud_prefetch_probe_all` | `"false"` | Probe every file vs. size-based |

### 5. Data Flow

```
Scanner discovers file via os.walk()
    |
    v
File upserted to bulk_files table (existing behavior)
    |
    v  (if cloud_prefetch_enabled)
PrefetchManager.enqueue(path, size)
    |
    v
CloudDetector.needs_prefetch(path, size)
    |
    +-- Already local --> status = SKIPPED
    |
    +-- Needs download --> Prefetch worker reads file in chunks
        |
        +-- Success --> status = READY
        |
        +-- Timeout/error --> retry (up to 3x) --> FAILED
    
    ...later...

BulkJob worker picks up file for conversion
    |
    v
prefetch_manager.wait_for(path)
    |
    +-- READY/SKIPPED --> convert immediately
    +-- PREFETCHING --> wait (bounded)
    +-- PENDING --> inline prefetch, then convert
    +-- FAILED --> try conversion anyway
```

### 6. Logging

All prefetch events use structlog with these event names:
- `cloud_prefetch_enqueued` — file added to queue
- `cloud_prefetch_started` — worker begins reading file
- `cloud_prefetch_complete` — file fully read (includes duration, bandwidth)
- `cloud_prefetch_failed` — read failed after retries
- `cloud_prefetch_skipped` — file already local
- `cloud_prefetch_timeout` — read exceeded timeout
- `cloud_prefetch_rate_limited` — worker sleeping due to rate limit
- `cloud_prefetch_bandwidth_calibrated` — rolling average updated
- `cloud_prefetch_backpressure` — concurrency reduced due to consecutive failures

### 7. What This Does NOT Do

- No vendor-specific APIs or SDKs
- No file modification — read-only prefetch, source mount stays read-only
- No persistent state — prefetch status resets on restart
- No interference with existing scan/convert logic — purely additive
- No downloading files to a separate location — just triggers the cloud provider to hydrate in place

### 8. Testing Approach

- Unit tests with mock files (simulated slow reads via `asyncio.sleep`)
- Integration test: create a temp dir with files, verify prefetch reads them
- Manual test: point at a real OneDrive folder with cloud-only files, verify hydration
