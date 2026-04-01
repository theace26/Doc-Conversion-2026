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
