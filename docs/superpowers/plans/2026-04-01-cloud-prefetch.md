# Cloud File Prefetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a platform-agnostic cloud file prefetch system that reads files ahead of conversion, forcing any cloud provider to download them.

**Architecture:** Three components — `CloudDetector` (probes if file is a cloud placeholder), `PrefetchManager` (background worker pool that reads files to trigger hydration), and integration hooks in scanner/converter/health/settings. All state is ephemeral (in-memory), no DB writes.

**Tech Stack:** Python asyncio, ThreadPoolExecutor for blocking I/O, structlog, existing MarkFlow preferences system.

---

### Task 1: Add Default Preferences

**Files:**
- Modify: `core/database.py:95-106` (add to DEFAULT_PREFERENCES before closing brace)

- [ ] **Step 1: Add cloud prefetch preferences**

In `core/database.py`, add after the `"pipeline_auto_reset_days": "3",` line (line 96), before `# Scan parallelism`:

```python
    # Cloud file prefetch (v0.15.1)
    "cloud_prefetch_enabled": "false",
    "cloud_prefetch_concurrency": "5",
    "cloud_prefetch_rate_limit": "30",
    "cloud_prefetch_timeout_seconds": "120",
    "cloud_prefetch_min_size_bytes": "0",
    "cloud_prefetch_probe_all": "false",
```

- [ ] **Step 2: Verify app starts**

Run: `docker-compose build markflow && docker-compose up -d markflow`
Wait 10s, then: `curl -s http://localhost:8000/api/health | python -m json.tool | head -3`
Expected: `{"status": "ok", ...}`

- [ ] **Step 3: Commit**

```bash
git add core/database.py
git commit -m "feat(prefetch): add cloud_prefetch_* default preferences"
```

---

### Task 2: Cloud File Detector

**Files:**
- Create: `core/cloud_detector.py`

- [ ] **Step 1: Create cloud_detector.py**

```python
"""
Platform-agnostic cloud file placeholder detector.

Determines whether a file needs prefetching by checking disk allocation
and read latency. Works with any cloud provider (OneDrive, Google Drive,
Nextcloud, Dropbox, iCloud, NAS tiered storage, AWS Storage Gateway).
"""

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# Shared thread pool for blocking I/O probes
_probe_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cloud-probe")

# Thresholds
_BLOCK_RATIO_THRESHOLD = 0.5   # allocated < 50% of size = likely placeholder
_READ_LATENCY_THRESHOLD = 0.2  # 200ms = likely cloud-backed
_PROBE_TIMEOUT = 0.5           # 500ms max for a 1-byte read probe


def _check_disk_blocks(path: Path, file_size: int) -> bool | None:
    """Check if file's allocated disk space is much less than reported size.

    Returns True if placeholder detected, False if local, None if check
    is unavailable (e.g. st_blocks not supported).
    """
    if file_size <= 0:
        return False
    try:
        st = os.stat(path)
        if not hasattr(st, "st_blocks"):
            return None
        allocated = st.st_blocks * 512
        if allocated == 0 and file_size > 4096:
            return True
        ratio = allocated / file_size
        return ratio < _BLOCK_RATIO_THRESHOLD
    except OSError:
        return None


def _timed_read_probe(path: Path) -> float:
    """Read 1 byte from the file and return the time it took in seconds.

    Returns -1.0 on error.
    """
    try:
        t0 = time.perf_counter()
        with open(path, "rb") as f:
            f.read(1)
        return time.perf_counter() - t0
    except OSError:
        return -1.0


class CloudDetector:
    """Detects cloud placeholder files using platform-agnostic heuristics."""

    def __init__(self, min_size_bytes: int = 0, probe_all: bool = False):
        self.min_size_bytes = min_size_bytes
        self.probe_all = probe_all

    async def needs_prefetch(self, path: Path, file_size: int) -> bool:
        """Returns True if the file appears to be a cloud placeholder."""
        # Size filter: skip small files unless probe_all
        if not self.probe_all and self.min_size_bytes > 0 and file_size < self.min_size_bytes:
            return False

        # Step 1: disk block check (fast, no I/O)
        block_result = _check_disk_blocks(path, file_size)
        if block_result is True:
            log.debug("cloud_detect_placeholder_blocks", path=str(path))
            return True
        if block_result is False:
            return False

        # Step 2: timed read probe (requires I/O, run in thread)
        try:
            latency = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(_probe_pool, _timed_read_probe, path),
                timeout=_PROBE_TIMEOUT + 0.1,
            )
        except (asyncio.TimeoutError, Exception):
            # Timeout on a 1-byte read strongly suggests cloud placeholder
            log.debug("cloud_detect_probe_timeout", path=str(path))
            return True

        if latency < 0:
            # Read error — assume local, let conversion handle the error
            return False

        if latency > _READ_LATENCY_THRESHOLD:
            log.debug("cloud_detect_placeholder_latency", path=str(path), latency_ms=int(latency * 1000))
            return True

        return False

    async def probe_batch(self, paths: list[tuple[Path, int]]) -> dict[Path, bool]:
        """Probe multiple files concurrently. Returns {path: needs_prefetch}."""
        tasks = [self.needs_prefetch(p, sz) for p, sz in paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[Path, bool] = {}
        for (p, _), result in zip(paths, results):
            out[p] = result if isinstance(result, bool) else False
        return out
```

- [ ] **Step 2: Verify import works**

Run: `docker-compose build markflow && docker-compose up -d markflow`
Wait 10s, then:
```bash
docker exec doc-conversion-2026-markflow-1 python -c "from core.cloud_detector import CloudDetector; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add core/cloud_detector.py
git commit -m "feat(prefetch): add CloudDetector for placeholder detection"
```

---

### Task 3: Prefetch Manager

**Files:**
- Create: `core/cloud_prefetch.py`

- [ ] **Step 1: Create cloud_prefetch.py**

```python
"""
Background cloud file prefetch worker pool.

Reads files ahead of conversion to trigger cloud provider hydration.
Platform-agnostic: works with OneDrive, Google Drive, Nextcloud, Dropbox,
iCloud, NAS tiered storage, or any cloud-synced filesystem.
"""

import asyncio
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path

import structlog

from core.cloud_detector import CloudDetector

log = structlog.get_logger(__name__)

_CHUNK_SIZE = 65536  # 64KB read chunks
_MAX_RETRIES = 3
_RETRY_BACKOFF = [5, 15, 45]  # seconds
_DEFAULT_BANDWIDTH = 2 * 1024 * 1024  # 2 MB/s conservative start
_BANDWIDTH_WINDOW = 20  # rolling average over last N successful reads
_MIN_TIMEOUT = 10.0
_BACKPRESSURE_THRESHOLD = 5  # consecutive failures before reducing concurrency


class PrefetchStatus(Enum):
    PENDING = "pending"
    PREFETCHING = "prefetching"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"


class _PrefetchItem:
    __slots__ = ("path", "file_size", "priority", "status", "retries", "event")

    def __init__(self, path: Path, file_size: int, priority: int = 0):
        self.path = path
        self.file_size = file_size
        self.priority = priority
        self.status = PrefetchStatus.PENDING
        self.retries = 0
        self.event = asyncio.Event()


def _read_file_sync(path: Path) -> tuple[int, float]:
    """Read entire file in chunks (blocking). Returns (bytes_read, duration_seconds)."""
    t0 = time.perf_counter()
    bytes_read = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            bytes_read += len(chunk)
    duration = time.perf_counter() - t0
    return bytes_read, duration


class PrefetchManager:
    """Background worker pool that prefetches cloud files by reading them."""

    def __init__(
        self,
        concurrency: int = 5,
        rate_limit: int = 30,
        timeout: int = 120,
        min_size_bytes: int = 0,
        probe_all: bool = False,
    ):
        self._concurrency = concurrency
        self._rate_limit = rate_limit
        self._max_timeout = float(timeout)
        self._detector = CloudDetector(min_size_bytes=min_size_bytes, probe_all=probe_all)

        # State
        self._items: dict[str, _PrefetchItem] = {}  # path_str -> item
        self._queue: asyncio.PriorityQueue[tuple[int, str]] = asyncio.PriorityQueue()
        self._pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="prefetch")
        self._workers: list[asyncio.Task] = []
        self._running = False

        # Rate limiting: token bucket
        self._tokens = float(rate_limit)
        self._max_tokens = float(rate_limit)
        self._last_refill = time.monotonic()

        # Bandwidth calibration
        self._bandwidth = float(_DEFAULT_BANDWIDTH)
        self._bw_samples: deque[float] = deque(maxlen=_BANDWIDTH_WINDOW)

        # Stats
        self._total_prefetched = 0
        self._total_failed = 0
        self._total_skipped = 0
        self._total_bytes = 0
        self._consecutive_failures = 0
        self._active_concurrency = concurrency

    async def start(self) -> None:
        """Start background worker tasks."""
        if self._running:
            return
        self._running = True
        for i in range(self._concurrency):
            task = asyncio.create_task(self._worker(i))
            self._workers.append(task)
        log.info("cloud_prefetch_started", concurrency=self._concurrency,
                 rate_limit=self._rate_limit, max_timeout=self._max_timeout)

    async def shutdown(self) -> None:
        """Drain queue and stop workers gracefully."""
        self._running = False
        # Inject poison pills
        for _ in self._workers:
            await self._queue.put((-1, ""))
        for task in self._workers:
            task.cancel()
        self._workers.clear()
        self._pool.shutdown(wait=False)
        log.info("cloud_prefetch_shutdown", prefetched=self._total_prefetched,
                 failed=self._total_failed, skipped=self._total_skipped)

    async def enqueue(self, path: Path, file_size: int, priority: int = 0) -> None:
        """Add a file to the prefetch queue."""
        path_str = str(path)
        if path_str in self._items:
            return  # already tracked

        item = _PrefetchItem(path, file_size, priority)
        self._items[path_str] = item

        # Quick check: does this file need prefetching?
        needs = await self._detector.needs_prefetch(path, file_size)
        if not needs:
            item.status = PrefetchStatus.SKIPPED
            item.event.set()
            self._total_skipped += 1
            log.debug("cloud_prefetch_skipped", path=path_str)
            return

        log.debug("cloud_prefetch_enqueued", path=path_str, size=file_size, priority=priority)
        await self._queue.put((priority, path_str))

    async def enqueue_batch(self, files: list[tuple[Path, int]]) -> int:
        """Enqueue multiple files. Returns count of files that need prefetching."""
        count = 0
        for path, size in files:
            path_str = str(path)
            if path_str in self._items:
                continue
            item = _PrefetchItem(path, size, priority=count)
            self._items[path_str] = item

            needs = await self._detector.needs_prefetch(path, size)
            if not needs:
                item.status = PrefetchStatus.SKIPPED
                item.event.set()
                self._total_skipped += 1
                continue

            await self._queue.put((count, path_str))
            count += 1
        log.info("cloud_prefetch_batch_enqueued", total=len(files), need_prefetch=count)
        return count

    async def wait_for(self, path: Path, timeout: float | None = None) -> PrefetchStatus:
        """Block until the file is ready or timeout."""
        path_str = str(path)
        item = self._items.get(path_str)

        if item is None:
            # Not tracked — do inline prefetch
            return await self._inline_prefetch(path)

        if item.status in (PrefetchStatus.READY, PrefetchStatus.SKIPPED, PrefetchStatus.FAILED):
            return item.status

        # Wait for completion
        effective_timeout = timeout or self._calc_timeout(item.file_size)
        try:
            await asyncio.wait_for(item.event.wait(), timeout=effective_timeout)
        except asyncio.TimeoutError:
            log.warning("cloud_prefetch_wait_timeout", path=path_str, timeout=effective_timeout)
        return item.status

    async def status(self, path: Path) -> PrefetchStatus:
        """Check current status without blocking."""
        item = self._items.get(str(path))
        if item is None:
            return PrefetchStatus.PENDING
        return item.status

    async def stats(self) -> dict:
        """Return queue depth, active count, completed, failed, avg speed."""
        return {
            "enabled": True,
            "queue_depth": self._queue.qsize(),
            "active_concurrency": self._active_concurrency,
            "max_concurrency": self._concurrency,
            "total_prefetched": self._total_prefetched,
            "total_failed": self._total_failed,
            "total_skipped": self._total_skipped,
            "total_bytes_read": self._total_bytes,
            "bandwidth_bytes_per_sec": int(self._bandwidth),
            "tracked_files": len(self._items),
        }

    # ── Internal ─────────────────────────────────────────────────────────

    def _calc_timeout(self, file_size: int) -> float:
        """Calculate adaptive timeout for a file based on calibrated bandwidth."""
        base = 30.0
        size_time = file_size / self._bandwidth if self._bandwidth > 0 else 60.0
        return min(max(base + size_time, _MIN_TIMEOUT), self._max_timeout)

    def _refill_tokens(self) -> None:
        """Refill rate-limit tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._max_tokens, self._tokens + elapsed * (self._max_tokens / 60.0))
        self._last_refill = now

    async def _acquire_token(self) -> None:
        """Wait until a rate-limit token is available."""
        while True:
            self._refill_tokens()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            # Sleep until approximately 1 token is available
            wait = (1.0 - self._tokens) / (self._max_tokens / 60.0)
            log.debug("cloud_prefetch_rate_limited", wait_seconds=round(wait, 1))
            await asyncio.sleep(min(wait, 2.0))

    async def _worker(self, worker_id: int) -> None:
        """Background worker: dequeue files and read them."""
        while self._running:
            try:
                priority, path_str = await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

            if not path_str:  # poison pill
                break

            # Backpressure: skip if this worker exceeds reduced concurrency
            if worker_id >= self._active_concurrency:
                await self._queue.put((priority, path_str))
                await asyncio.sleep(2.0)
                continue

            item = self._items.get(path_str)
            if item is None or item.status in (PrefetchStatus.READY, PrefetchStatus.SKIPPED):
                continue

            await self._acquire_token()
            await self._prefetch_one(item)

    async def _prefetch_one(self, item: _PrefetchItem) -> None:
        """Prefetch a single file with retries."""
        path_str = str(item.path)
        item.status = PrefetchStatus.PREFETCHING
        log.debug("cloud_prefetch_started", path=path_str, size=item.file_size)

        for attempt in range(1, _MAX_RETRIES + 1):
            timeout = self._calc_timeout(item.file_size)
            try:
                bytes_read, duration = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(self._pool, _read_file_sync, item.path),
                    timeout=timeout,
                )

                # Success
                item.status = PrefetchStatus.READY
                item.event.set()
                self._total_prefetched += 1
                self._total_bytes += bytes_read
                self._consecutive_failures = 0

                # Calibrate bandwidth
                if duration > 0 and bytes_read > 0:
                    bw = bytes_read / duration
                    self._bw_samples.append(bw)
                    self._bandwidth = sum(self._bw_samples) / len(self._bw_samples)
                    if len(self._bw_samples) % 5 == 0:
                        log.info("cloud_prefetch_bandwidth_calibrated",
                                 bandwidth_mbps=round(self._bandwidth / (1024 * 1024), 1))

                # Restore concurrency after success
                if self._active_concurrency < self._concurrency:
                    self._active_concurrency = min(self._active_concurrency + 1, self._concurrency)

                log.debug("cloud_prefetch_complete", path=path_str,
                          bytes=bytes_read, duration_ms=int(duration * 1000),
                          bandwidth_mbps=round((bytes_read / duration / 1048576) if duration > 0 else 0, 1))
                return

            except asyncio.TimeoutError:
                log.warning("cloud_prefetch_timeout", path=path_str, attempt=attempt, timeout=timeout)
            except OSError as exc:
                log.warning("cloud_prefetch_error", path=path_str, attempt=attempt, error=str(exc))
            except Exception as exc:
                log.warning("cloud_prefetch_error", path=path_str, attempt=attempt, error=str(exc))

            # Retry backoff
            item.retries = attempt
            if attempt < _MAX_RETRIES:
                backoff = _RETRY_BACKOFF[attempt - 1]
                await asyncio.sleep(backoff)

        # All retries exhausted
        item.status = PrefetchStatus.FAILED
        item.event.set()
        self._total_failed += 1
        self._consecutive_failures += 1

        # Backpressure: reduce concurrency on consecutive failures
        if self._consecutive_failures >= _BACKPRESSURE_THRESHOLD and self._active_concurrency > 1:
            self._active_concurrency = max(1, self._active_concurrency - 1)
            log.warning("cloud_prefetch_backpressure",
                        active_concurrency=self._active_concurrency,
                        consecutive_failures=self._consecutive_failures)

        log.warning("cloud_prefetch_failed", path=str(item.path), retries=_MAX_RETRIES)

    async def _inline_prefetch(self, path: Path) -> PrefetchStatus:
        """Prefetch a single file inline (not queued). Used when converter needs a file now."""
        needs = await self._detector.needs_prefetch(path, path.stat().st_size if path.exists() else 0)
        if not needs:
            return PrefetchStatus.SKIPPED

        timeout = self._calc_timeout(path.stat().st_size if path.exists() else 0)
        try:
            bytes_read, duration = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(self._pool, _read_file_sync, path),
                timeout=timeout,
            )
            self._total_prefetched += 1
            self._total_bytes += bytes_read
            log.debug("cloud_prefetch_inline_complete", path=str(path), bytes=bytes_read)
            return PrefetchStatus.READY
        except (asyncio.TimeoutError, OSError) as exc:
            log.warning("cloud_prefetch_inline_failed", path=str(path), error=str(exc))
            self._total_failed += 1
            return PrefetchStatus.FAILED


# ── Module-level singleton ───────────────────────────────────────────────────

_manager: PrefetchManager | None = None


def get_prefetch_manager() -> PrefetchManager | None:
    """Return the global PrefetchManager, or None if prefetch is disabled."""
    return _manager


async def init_prefetch_manager(
    concurrency: int = 5,
    rate_limit: int = 30,
    timeout: int = 120,
    min_size_bytes: int = 0,
    probe_all: bool = False,
) -> PrefetchManager:
    """Initialize and start the global PrefetchManager singleton."""
    global _manager
    if _manager is not None:
        return _manager
    _manager = PrefetchManager(
        concurrency=concurrency,
        rate_limit=rate_limit,
        timeout=timeout,
        min_size_bytes=min_size_bytes,
        probe_all=probe_all,
    )
    await _manager.start()
    return _manager


async def shutdown_prefetch_manager() -> None:
    """Shutdown the global PrefetchManager if running."""
    global _manager
    if _manager is not None:
        await _manager.shutdown()
        _manager = None
```

- [ ] **Step 2: Verify import works**

```bash
docker-compose build markflow && docker-compose up -d markflow
```
Wait 10s, then:
```bash
docker exec doc-conversion-2026-markflow-1 python -c "from core.cloud_prefetch import PrefetchManager, PrefetchStatus; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add core/cloud_prefetch.py
git commit -m "feat(prefetch): add PrefetchManager with rate limiting and adaptive timeouts"
```

---

### Task 4: App Lifespan Integration

**Files:**
- Modify: `main.py:133-165` (lifespan startup and shutdown)

- [ ] **Step 1: Add prefetch init to lifespan startup**

In `main.py`, after the pipeline startup block (after line 144 `asyncio.create_task(wait_for_health_and_start_pipeline())`), add:

```python
        # Initialize cloud file prefetch if enabled
        from core.database import get_preference
        prefetch_enabled = (await get_preference("cloud_prefetch_enabled") or "false").lower() == "true"
        if prefetch_enabled:
            from core.cloud_prefetch import init_prefetch_manager
            pfx_concurrency = int(await get_preference("cloud_prefetch_concurrency") or "5")
            pfx_rate = int(await get_preference("cloud_prefetch_rate_limit") or "30")
            pfx_timeout = int(await get_preference("cloud_prefetch_timeout_seconds") or "120")
            pfx_min_size = int(await get_preference("cloud_prefetch_min_size_bytes") or "0")
            pfx_probe_all = (await get_preference("cloud_prefetch_probe_all") or "false").lower() == "true"
            await init_prefetch_manager(pfx_concurrency, pfx_rate, pfx_timeout, pfx_min_size, pfx_probe_all)
            log.info("markflow.cloud_prefetch_enabled", concurrency=pfx_concurrency, rate_limit=pfx_rate)
```

- [ ] **Step 2: Add prefetch shutdown to lifespan teardown**

In `main.py`, in the yield/shutdown section, after `stop_scheduler()` (around line 162), add:

```python
    try:
        from core.cloud_prefetch import shutdown_prefetch_manager
        await shutdown_prefetch_manager()
    except Exception as exc:
        log.warning("markflow.prefetch_shutdown_error", error=str(exc))
```

- [ ] **Step 3: Verify app starts clean**

```bash
docker-compose build markflow && docker-compose up -d markflow
```
Wait 10s: `curl -s http://localhost:8000/api/health | python -m json.tool | head -3`
Expected: `{"status": "ok", ...}` (prefetch is disabled by default, so no change)

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(prefetch): initialize PrefetchManager in app lifespan"
```

---

### Task 5: Scanner Integration

**Files:**
- Modify: `core/bulk_scanner.py:670-679` (after upsert_bulk_file in _process_discovered_file)

- [ ] **Step 1: Add prefetch enqueue after file discovery**

In `core/bulk_scanner.py`, in the `_process_discovered_file` method, after the `upsert_bulk_file()` call (line 679), add:

```python
            # Enqueue for cloud prefetch if enabled
            from core.cloud_prefetch import get_prefetch_manager
            pfx = get_prefetch_manager()
            if pfx is not None:
                try:
                    await pfx.enqueue(file_path, file_size, priority=file_count)
                except Exception:
                    pass  # non-critical — conversion will handle it
```

- [ ] **Step 2: Verify scan still works**

```bash
docker-compose build markflow && docker-compose up -d markflow
```
Wait 10s: `curl -s http://localhost:8000/api/health | python -m json.tool | head -3`
Expected: `{"status": "ok", ...}`

- [ ] **Step 3: Commit**

```bash
git add core/bulk_scanner.py
git commit -m "feat(prefetch): enqueue discovered files for cloud prefetch during scan"
```

---

### Task 6: Converter Integration

**Files:**
- Modify: `core/bulk_worker.py:628-656` (in _process_convertible, before asyncio.to_thread)

- [ ] **Step 1: Add prefetch wait before conversion**

In `core/bulk_worker.py`, in the `_process_convertible` method, before the `result = await asyncio.to_thread(` call (line 649), add:

```python
        # Wait for cloud prefetch if enabled
        from core.cloud_prefetch import get_prefetch_manager
        pfx = get_prefetch_manager()
        if pfx is not None:
            pfx_status = await pfx.wait_for(source_path)
            if pfx_status.value == "failed":
                log.warning("cloud_prefetch_wait_failed", path=str(source_path),
                            hint="attempting conversion anyway")
```

- [ ] **Step 2: Verify conversion still works**

```bash
docker-compose build markflow && docker-compose up -d markflow
```
Wait 10s: `curl -s http://localhost:8000/api/health | python -m json.tool | head -3`
Expected: `{"status": "ok", ...}`

- [ ] **Step 3: Commit**

```bash
git add core/bulk_worker.py
git commit -m "feat(prefetch): wait for cloud prefetch before conversion"
```

---

### Task 7: Health Check Integration

**Files:**
- Modify: `core/health.py:272-274` (after GPU component, before all_ok check)

- [ ] **Step 1: Add cloud_prefetch health component**

In `core/health.py`, after the GPU health component block (after line 273 `components["gpu"] = ...`), add:

```python
    # Cloud prefetch status
    try:
        from core.cloud_prefetch import get_prefetch_manager
        pfx = get_prefetch_manager()
        if pfx is not None:
            pfx_stats = await pfx.stats()
            components["cloud_prefetch"] = {
                "ok": True,
                "version": f"{pfx_stats['total_prefetched']} prefetched, {pfx_stats['queue_depth']} queued",
                **pfx_stats,
            }
        else:
            components["cloud_prefetch"] = {"ok": True, "version": "disabled"}
    except Exception:
        components["cloud_prefetch"] = {"ok": True, "version": "disabled"}
```

- [ ] **Step 2: Verify health endpoint shows new component**

```bash
docker-compose build markflow && docker-compose up -d markflow
```
Wait 10s:
```bash
curl -s http://localhost:8000/api/health | python -m json.tool | grep -A 2 cloud_prefetch
```
Expected: `"cloud_prefetch": {"ok": true, "version": "disabled"}`

- [ ] **Step 3: Commit**

```bash
git add core/health.py
git commit -m "feat(prefetch): add cloud_prefetch component to health check"
```

---

### Task 8: Settings Page Integration

**Files:**
- Modify: `static/settings.html` (add Cloud Prefetch section after Pipeline section)

- [ ] **Step 1: Find Pipeline section end and add Cloud Prefetch section**

In `static/settings.html`, find the Pipeline settings section and add after it a new "Cloud Prefetch" section following the exact same HTML pattern used by the Pipeline section. The section should include:

- Toggle for `cloud_prefetch_enabled` (checkbox)
- Number input for `cloud_prefetch_concurrency` (1-20)
- Number input for `cloud_prefetch_rate_limit` (1-100)
- Number input for `cloud_prefetch_timeout_seconds` (10-600)
- Number input for `cloud_prefetch_min_size_bytes` (0 = all)
- Toggle for `cloud_prefetch_probe_all` (checkbox)

Follow the existing pattern from the Pipeline section for save buttons, preference loading, and API calls.

- [ ] **Step 2: Verify settings page loads**

```bash
docker-compose build markflow && docker-compose up -d markflow
```
Open `http://localhost:8000/settings.html` and verify the Cloud Prefetch section appears.

- [ ] **Step 3: Commit**

```bash
git add static/settings.html
git commit -m "feat(prefetch): add Cloud Prefetch settings section to settings page"
```

---

### Task 9: Update Docs and Version

**Files:**
- Modify: `CLAUDE.md` (current status, key files, gotchas)
- Modify: `docs/version-history.md` (add v0.15.1 entry)
- Modify: `docs/key-files.md` (add cloud_detector.py, cloud_prefetch.py)
- Modify: `docs/gotchas.md` (add cloud prefetch gotchas)

- [ ] **Step 1: Update all project docs**

Update CLAUDE.md current status to v0.15.1 with cloud prefetch description. Add new files to key-files.md. Add gotchas:
- Cloud prefetch is purely additive — disabling it changes nothing about existing behavior
- Prefetch state is ephemeral — resets on container restart
- Rate limit tokens refill per-minute, not per-second — bursty traffic is expected on startup
- `st_blocks` check may not detect all placeholders on all mount types — timed read probe is the fallback
- Inline prefetch in converter runs when file wasn't in the queue — still works, just slower than pre-queued

Add v0.15.1 entry to version-history.md.

- [ ] **Step 2: Final build and smoke test**

```bash
docker-compose build markflow && docker-compose up -d markflow
```
Wait 10s:
```bash
curl -s http://localhost:8000/api/health | python -m json.tool | head -5
curl -s http://localhost:8000/api/search/all?q=electrical&per_page=5 | python -m json.tool | head -5
```
Both should return OK.

- [ ] **Step 3: Commit and push**

```bash
git add -A
git commit -m "feat: v0.15.1 — cloud file prefetch system for cloud-synced sources"
git push origin main
```
