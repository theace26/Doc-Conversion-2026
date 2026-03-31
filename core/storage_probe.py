"""
Storage latency probe — auto-detects storage type (SSD, HDD, NAS) by measuring
sequential vs random stat() latency patterns and recommends scan thread count.

The key insight: spinning disks show a large gap between sequential and random
access times (seek penalty), while network storage and SSDs show roughly equal
latency for both patterns. This ratio is stable even under background I/O load.

Usage:
    profile = await probe_storage_latency(Path("/mnt/source-share"))
    print(f"Detected: {profile.storage_hint}, threads: {profile.recommended_threads}")
"""

import os
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import asyncio
import structlog

log = structlog.get_logger(__name__)

# ── Classification thresholds ───────────────────────────────────────────────

# If random/sequential ratio exceeds this, it's a spinning disk (seek penalty)
HDD_RATIO_THRESHOLD = 3.0

# Below this median latency (ms), storage is fast enough that parallelism won't help
SSD_LATENCY_CEILING_MS = 0.1

# Thread count lookup based on detected storage type and latency
_THREAD_TABLE = {
    "ssd":       1,   # Already fast — parallelism adds overhead, not speed
    "hdd":       1,   # Seek thrashing makes parallel worse
    "hdd_busy":  1,   # Busy HDD — definitely stay serial
    "nas":       6,   # Typical NAS over gigabit — good parallelism target
    "nas_slow":  10,  # Slow NAS (WiFi, VPN, WAN) — aggressive overlap
}

MAX_PROBE_THREADS = 12
MIN_SAMPLE_FILES = 5


@dataclass
class StorageProfile:
    """Result of the storage latency probe."""
    storage_hint: str          # "ssd", "hdd", "nas", "nas_slow", "unknown"
    recommended_threads: int   # 1 for local, 4-12 for network
    sequential_median_ms: float
    random_median_ms: float
    ratio: float               # random_median / sequential_median
    variance_coefficient: float  # stddev / median (0-1+, higher = more jitter)
    sample_count: int
    probe_duration_ms: float


# ── Feedback-loop throttler ──────────────────────────────────────────────

# How often (in stat calls) the throttler re-evaluates
THROTTLE_CHECK_INTERVAL = 500

# Latency ratio thresholds for throttle decisions
THROTTLE_CONGESTION_SEVERE = 3.0   # current / baseline → shed 2 threads
THROTTLE_CONGESTION_MILD = 2.0     # current / baseline → shed 1 thread
THROTTLE_RECOVERY = 1.5            # current / baseline → restore 1 thread

# Minimum time between adjustments (seconds) to avoid oscillation
THROTTLE_COOLDOWN_SECONDS = 5.0


class ScanThrottler:
    """Thread-safe backpressure controller for parallel scan workers.

    Workers report stat() latencies as they go. The throttler periodically
    compares rolling median latency to the initial probe baseline and adjusts
    the active thread count up or down.

    Workers call `should_pause(worker_id)` before each directory — workers
    whose ID >= active_threads sleep until the throttler restores them.
    """

    def __init__(self, baseline_ms: float, max_threads: int):
        self.baseline_ms = max(baseline_ms, 0.01)  # avoid div-by-zero
        self.max_threads = max_threads
        self.active_threads = max_threads
        self._lock = threading.Lock()
        self._recent: deque[float] = deque(maxlen=100)
        self._stat_count = 0
        self._last_adjust_time = time.monotonic()
        self._adjustments: list[dict] = []  # log of throttle events

    def record_latency(self, latency_ms: float) -> None:
        """Called by walker threads after each stat() call."""
        with self._lock:
            self._recent.append(latency_ms)
            self._stat_count += 1

    def should_pause(self, worker_id: int) -> bool:
        """Check if this worker should be parked (thread-safe, lock-free read)."""
        return worker_id >= self.active_threads

    def check_and_adjust(self) -> int:
        """Evaluate latency and adjust active thread count. Called by consumer.

        Returns current active_threads after any adjustment.
        """
        with self._lock:
            if len(self._recent) < 20:
                return self.active_threads

            now = time.monotonic()
            if now - self._last_adjust_time < THROTTLE_COOLDOWN_SECONDS:
                return self.active_threads

            current_median = statistics.median(self._recent)
            ratio = current_median / self.baseline_ms

            old_threads = self.active_threads

            if ratio >= THROTTLE_CONGESTION_SEVERE and self.active_threads > 1:
                # Heavy congestion — shed 2 threads
                self.active_threads = max(1, self.active_threads - 2)
            elif ratio >= THROTTLE_CONGESTION_MILD and self.active_threads > 2:
                # Mild congestion — shed 1 thread
                self.active_threads = max(2, self.active_threads - 1)
            elif ratio < THROTTLE_RECOVERY and self.active_threads < self.max_threads:
                # Latency recovered — restore 1 thread
                self.active_threads = min(self.max_threads, self.active_threads + 1)

            if self.active_threads != old_threads:
                self._last_adjust_time = now
                event = {
                    "from": old_threads,
                    "to": self.active_threads,
                    "ratio": round(ratio, 2),
                    "median_ms": round(current_median, 2),
                    "baseline_ms": round(self.baseline_ms, 2),
                    "time": now,
                }
                self._adjustments.append(event)
                log.info(
                    "scan_throttle_adjust",
                    direction="down" if self.active_threads < old_threads else "up",
                    from_threads=old_threads,
                    to_threads=self.active_threads,
                    latency_ratio=round(ratio, 2),
                    current_median_ms=round(current_median, 2),
                    baseline_ms=round(self.baseline_ms, 2),
                )

            return self.active_threads

    @property
    def adjustment_count(self) -> int:
        return len(self._adjustments)

    @property
    def stat_count(self) -> int:
        return self._stat_count


# ── Error-rate monitor ───────────────────────────────────────────────────

# Default: abort if >50% of the last 100 operations failed
ERROR_RATE_WINDOW = 100
ERROR_RATE_ABORT_THRESHOLD = 0.5

# Minimum operations before error rate is evaluated (avoid false positives on startup)
ERROR_RATE_MIN_OPS = 20


class ErrorRateMonitor:
    """Thread-safe rolling-window error rate tracker.

    Tracks success/failure of recent operations. If the error rate in the
    rolling window exceeds a threshold, signals abort. Usable by scanners
    (stat failures) and conversion workers (I/O failures).

    Usage:
        monitor = ErrorRateMonitor()
        monitor.record_success()
        monitor.record_error("Connection reset")
        if monitor.should_abort():
            # stop the scan/conversion
    """

    def __init__(
        self,
        window_size: int = ERROR_RATE_WINDOW,
        abort_threshold: float = ERROR_RATE_ABORT_THRESHOLD,
        min_ops: int = ERROR_RATE_MIN_OPS,
    ):
        self.window_size = window_size
        self.abort_threshold = abort_threshold
        self.min_ops = min_ops
        self._lock = threading.Lock()
        # Rolling window: True = success, False = error
        self._window: deque[bool] = deque(maxlen=window_size)
        self._total_errors = 0
        self._total_ops = 0
        self._consecutive_errors = 0
        self._last_error_msg: str = ""
        self._abort_triggered = False

    def record_success(self) -> None:
        """Record a successful operation."""
        with self._lock:
            self._window.append(True)
            self._total_ops += 1
            self._consecutive_errors = 0

    def record_error(self, error_msg: str = "") -> None:
        """Record a failed operation."""
        with self._lock:
            self._window.append(False)
            self._total_ops += 1
            self._total_errors += 1
            self._consecutive_errors += 1
            if error_msg:
                self._last_error_msg = error_msg

    def should_abort(self) -> bool:
        """Check if error rate exceeds threshold. Thread-safe."""
        if self._abort_triggered:
            return True  # once triggered, stays triggered

        with self._lock:
            if self._total_ops < self.min_ops:
                return False  # not enough data yet

            # Check consecutive errors (fast path — 20 in a row is almost certainly a mount failure)
            if self._consecutive_errors >= 20:
                self._abort_triggered = True
                log.error(
                    "error_rate_abort",
                    reason="consecutive_errors",
                    consecutive=self._consecutive_errors,
                    last_error=self._last_error_msg,
                )
                return True

            # Check rolling window rate
            errors_in_window = sum(1 for ok in self._window if not ok)
            rate = errors_in_window / len(self._window) if self._window else 0.0

            if rate >= self.abort_threshold:
                self._abort_triggered = True
                log.error(
                    "error_rate_abort",
                    reason="high_error_rate",
                    error_rate=round(rate, 2),
                    threshold=self.abort_threshold,
                    window_size=len(self._window),
                    errors_in_window=errors_in_window,
                    last_error=self._last_error_msg,
                )
                return True

            return False

    @property
    def error_rate(self) -> float:
        """Current error rate in rolling window."""
        with self._lock:
            if not self._window:
                return 0.0
            return sum(1 for ok in self._window if not ok) / len(self._window)

    @property
    def total_errors(self) -> int:
        return self._total_errors

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    @property
    def aborted(self) -> bool:
        return self._abort_triggered


def _collect_sample_files(source_path: Path, max_files: int = 20) -> tuple[list[Path], list[Path]]:
    """Collect files for sequential (same-dir) and random (cross-dir) stat tests.

    Returns (sequential_files, random_files).
    Sequential: files from the first directory with enough entries.
    Random: files spread across different subdirectories.
    """
    sequential: list[Path] = []
    random_files: list[Path] = []
    seen_dirs: set[str] = set()

    try:
        # First pass: find a directory with enough files for sequential test
        for dirpath, dirnames, filenames in os.walk(source_path):
            # Skip hidden dirs and _markflow
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "_markflow"]

            if not sequential and len(filenames) >= max_files // 2:
                sequential = [Path(dirpath) / f for f in filenames[:max_files // 2]]

            # Collect one file per directory for random test
            if filenames and dirpath not in seen_dirs:
                random_files.append(Path(dirpath) / filenames[0])
                seen_dirs.add(dirpath)

            # Stop once we have enough samples
            if len(sequential) >= max_files // 2 and len(random_files) >= max_files // 2:
                break

            # Don't walk too deep looking for samples
            if len(seen_dirs) > 50:
                break

        # Fallback: if no single dir had enough files, use what we found
        if len(sequential) < MIN_SAMPLE_FILES:
            # Use root-level files as sequential samples
            try:
                with os.scandir(source_path) as it:
                    for entry in it:
                        if entry.is_file() and len(sequential) < max_files // 2:
                            sequential.append(Path(entry.path))
            except OSError:
                pass

    except OSError as exc:
        log.warning("storage_probe_walk_error", error=str(exc))

    return sequential, random_files


def _time_stat_calls(files: list[Path]) -> list[float]:
    """Stat each file individually and return per-file latency in milliseconds."""
    latencies: list[float] = []
    for f in files:
        try:
            t0 = time.perf_counter()
            f.stat()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed_ms)
        except OSError:
            continue  # skip inaccessible files
    return latencies


def _classify(
    seq_latencies: list[float],
    rand_latencies: list[float],
) -> StorageProfile:
    """Classify storage type from sequential and random stat latency measurements."""

    seq_median = statistics.median(seq_latencies) if seq_latencies else 0.0
    rand_median = statistics.median(rand_latencies) if rand_latencies else seq_median

    # Combine all latencies for variance calculation
    all_latencies = seq_latencies + rand_latencies
    if len(all_latencies) >= 2:
        overall_median = statistics.median(all_latencies)
        overall_stddev = statistics.stdev(all_latencies)
        variance_coeff = overall_stddev / overall_median if overall_median > 0 else 0.0
    else:
        overall_median = seq_median
        variance_coeff = 0.0

    # Compute the key discriminator: random/sequential ratio
    ratio = rand_median / seq_median if seq_median > 0 else 1.0

    # Classification logic
    if seq_median < SSD_LATENCY_CEILING_MS and ratio < 2.0:
        # Very fast + no seek penalty = SSD
        hint = "ssd"
    elif ratio >= HDD_RATIO_THRESHOLD:
        # Large seek penalty = spinning disk
        if seq_median > 1.0:
            hint = "hdd_busy"  # HDD under load (elevated sequential too)
        else:
            hint = "hdd"
    elif seq_median > 10.0:
        # High latency + low ratio = slow network
        hint = "nas_slow"
    elif seq_median > 0.5:
        # Moderate latency + low ratio = network storage
        hint = "nas"
    else:
        # Fast-ish, low ratio, but above SSD threshold — likely fast NAS or NVMe
        hint = "ssd"

    threads = _THREAD_TABLE.get(hint, 1)

    return StorageProfile(
        storage_hint=hint,
        recommended_threads=threads,
        sequential_median_ms=round(seq_median, 3),
        random_median_ms=round(rand_median, 3),
        ratio=round(ratio, 2),
        variance_coefficient=round(variance_coeff, 3),
        sample_count=len(all_latencies),
        probe_duration_ms=0.0,  # filled by caller
    )


def _probe_sync(source_path: Path) -> StorageProfile:
    """Synchronous probe — runs in a thread to avoid blocking the event loop."""
    t_start = time.perf_counter()

    sequential, random_files = _collect_sample_files(source_path)

    if len(sequential) < MIN_SAMPLE_FILES and len(random_files) < MIN_SAMPLE_FILES:
        # Not enough files to probe — return safe default
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        return StorageProfile(
            storage_hint="unknown",
            recommended_threads=1,
            sequential_median_ms=0.0,
            random_median_ms=0.0,
            ratio=1.0,
            variance_coefficient=0.0,
            sample_count=0,
            probe_duration_ms=round(elapsed_ms, 1),
        )

    # Warm the OS file cache with one throwaway stat (avoids cold-start outlier)
    if sequential:
        try:
            sequential[0].stat()
        except OSError:
            pass

    seq_latencies = _time_stat_calls(sequential)
    rand_latencies = _time_stat_calls(random_files)

    profile = _classify(seq_latencies, rand_latencies)
    profile.probe_duration_ms = round((time.perf_counter() - t_start) * 1000, 1)

    return profile


async def probe_storage_latency(
    source_path: Path,
    max_threads_override: Optional[int] = None,
) -> StorageProfile:
    """Probe storage latency and return a classification with recommended thread count.

    Args:
        source_path: Root directory to probe.
        max_threads_override: If set, caps recommended_threads to this value.
            Pass None or 0 to use auto-detection. Pass 1 to force serial.

    Returns:
        StorageProfile with classification and recommended thread count.
    """
    try:
        profile = await asyncio.to_thread(_probe_sync, source_path)
    except Exception as exc:
        log.warning("storage_probe_failed", error=str(exc), source_path=str(source_path))
        return StorageProfile(
            storage_hint="unknown",
            recommended_threads=1,
            sequential_median_ms=0.0,
            random_median_ms=0.0,
            ratio=1.0,
            variance_coefficient=0.0,
            sample_count=0,
            probe_duration_ms=0.0,
        )

    # Apply user override (cap)
    if max_threads_override is not None and max_threads_override > 0:
        profile.recommended_threads = min(profile.recommended_threads, max_threads_override)

    # Hard cap
    profile.recommended_threads = min(profile.recommended_threads, MAX_PROBE_THREADS)

    log.info(
        "storage_probe_complete",
        source_path=str(source_path),
        storage_hint=profile.storage_hint,
        recommended_threads=profile.recommended_threads,
        sequential_median_ms=profile.sequential_median_ms,
        random_median_ms=profile.random_median_ms,
        ratio=profile.ratio,
        variance_coefficient=profile.variance_coefficient,
        sample_count=profile.sample_count,
        probe_duration_ms=profile.probe_duration_ms,
    )

    return profile
