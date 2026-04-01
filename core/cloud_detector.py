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
