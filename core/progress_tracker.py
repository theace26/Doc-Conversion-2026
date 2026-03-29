"""
Rolling-window ETA calculator for MarkFlow progress tracking.

Used by scan workers, bulk conversion workers, and single-file conversion
to provide consistent, auto-adjusting time remaining estimates.

The rolling window (default last 100 completions) adapts quickly to speed
changes — e.g., hitting a directory of large PDFs after a run of tiny CSVs —
without the wild oscillation of a global average.
"""

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass
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
            "eta_human": format_eta(self.eta_seconds),
        }


class RollingWindowETA:
    """
    Tracks completion events and computes rolling-window ETA.

    Safe for both async and threaded use:
    - Async callers: use record_completion(), snapshot(), set_total(), update_total()
    - Thread callers: use record_completion_sync() and snapshot_sync()
    """

    def __init__(self, total: Optional[int] = None, window_size: int = ROLLING_WINDOW_SIZE):
        self._total: Optional[int] = total
        self._count_ready: bool = total is not None
        self._completed: int = 0
        self._window: deque[tuple[float, int]] = deque(maxlen=window_size)
        self._async_lock = asyncio.Lock()
        self._thread_lock = threading.Lock()

    async def set_total(self, total: int) -> None:
        """Call when the concurrent fast-walk finishes counting."""
        async with self._async_lock:
            self._total = total
            self._count_ready = True

    async def update_total(self, total: int) -> None:
        """Call periodically during fast-walk to stream an in-progress count."""
        async with self._async_lock:
            self._total = total

    async def record_completion(self, count: int = 1) -> None:
        """Call after each file/item completes (async context)."""
        async with self._async_lock:
            self._completed += count
            self._window.append((time.monotonic(), self._completed))

    def record_completion_sync(self, count: int = 1) -> None:
        """Call after each file/item completes (threaded context)."""
        with self._thread_lock:
            self._completed += count
            self._window.append((time.monotonic(), self._completed))

    async def snapshot(self) -> ProgressSnapshot:
        """Read current state (async context)."""
        async with self._async_lock:
            return self._compute_snapshot()

    def snapshot_sync(self) -> ProgressSnapshot:
        """Read current state (threaded context)."""
        with self._thread_lock:
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


def format_eta(seconds: Optional[float]) -> Optional[str]:
    """Human-readable ETA string. Returns None if ETA not yet available."""
    if seconds is None:
        return None
    if seconds < 0:
        return "finishing\u2026"
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


async def estimate_single_file_eta(
    file_extension: str, file_size_bytes: int
) -> Optional[float]:
    """
    Estimate conversion time for a single file based on historical average
    duration for the same extension (last 50 conversions), scaled by file size.

    Returns estimated seconds, or None if no history available.
    """
    from core.database import db_fetch_one
    ext = file_extension.lower().lstrip(".")
    row = await db_fetch_one(
        """SELECT AVG(duration_ms) as avg_ms, AVG(file_size_bytes) as avg_size
           FROM conversion_history
           WHERE source_format = ?
             AND status = 'success'
             AND duration_ms IS NOT NULL
           ORDER BY created_at DESC
           LIMIT 50""",
        (ext,),
    )
    if not row or row["avg_ms"] is None:
        return None

    avg_duration_s = row["avg_ms"] / 1000.0
    avg_size = row["avg_size"]
    if avg_size and avg_size > 0 and file_size_bytes > 0:
        size_ratio = file_size_bytes / avg_size
        return avg_duration_s * size_ratio
    return avg_duration_s
