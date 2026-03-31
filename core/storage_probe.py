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
import time
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
