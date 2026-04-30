"""
Scan priority coordinator — manages mutual exclusion between scan types.

Priority hierarchy (highest to lowest):
    1. Bulk Job   — cancels lifecycle, pauses run-now
    2. Run Now    — cancels lifecycle
    3. Lifecycle   — lowest priority, never pauses (cancel only)

Lifecycle scans are the reliable background workhorse: if interrupted they
cleanly cancel and pick up at the next scheduled interval.  Run-now scans
pause when a bulk job starts and resume automatically when it finishes.
"""

import asyncio
import time

import structlog

log = structlog.get_logger(__name__)

# ── Cancel / pause signals ──────────────────────────────────────────────────
_lifecycle_cancel = asyncio.Event()      # set = lifecycle must stop
_run_now_cancel = asyncio.Event()        # set = run-now must stop
_run_now_pause = asyncio.Event()         # cleared = run-now should block; set = run
_run_now_pause.set()                     # not paused initially

# ── Tracking state ──────────────────────────────────────────────────────────
_lifecycle_running = False
_run_now_running = False
_run_now_paused = False
_active_bulk_count = 0                   # supports concurrent bulk jobs
_run_now_started_at: float | None = None # monotonic timestamp for watchdog
_lifecycle_started_at: float | None = None

# Stale scan timeout — if a scan has been "running" for longer than this
# without completing, the watchdog considers it dead. Default: 4 hours.
STALE_SCAN_TIMEOUT_S = 4 * 60 * 60


# ── Startup reset ──────────────────────────────────────────────────────────

def reset_coordinator() -> None:
    """Reset all in-memory coordinator state on container startup.

    Called after cleanup_orphaned_jobs() marks DB rows as interrupted.
    Without this, flags from a previous container lifecycle persist as
    ghost state (e.g. run_now_running=True with no actual async task).
    """
    global _lifecycle_running, _run_now_running, _run_now_paused, _active_bulk_count
    global _run_now_started_at, _lifecycle_started_at
    _lifecycle_cancel.clear()
    _run_now_cancel.clear()
    _run_now_pause.set()  # not paused
    _lifecycle_running = False
    _run_now_running = False
    _run_now_paused = False
    _active_bulk_count = 0
    _run_now_started_at = None
    _lifecycle_started_at = None
    log.info("scan_coordinator.reset", msg="All coordinator state cleared on startup")


# ── Lifecycle scan helpers ──────────────────────────────────────────────────

def register_lifecycle_scan() -> None:
    """Called when a lifecycle scan begins.

    Clears any stale cancel signal from a previous scan, but preserves a
    cancel that was set while this scan's setup was in progress (e.g. the
    active_ops cancel hook fired before register_lifecycle_scan() was called).
    """
    global _lifecycle_running, _lifecycle_started_at
    # Only clear if no cancel is already pending.  A pending cancel means the
    # operator clicked Cancel between the POST /run-now response and now —
    # preserving it lets the scan exit at its first _should_cancel() check.
    if not _lifecycle_cancel.is_set():
        _lifecycle_cancel.clear()
    _lifecycle_running = True
    _lifecycle_started_at = time.monotonic()
    log.debug("scan_coordinator.lifecycle_registered",
              cancel_pending=_lifecycle_cancel.is_set())


def unregister_lifecycle_scan() -> None:
    """Called when a lifecycle scan finishes (complete or cancelled)."""
    global _lifecycle_running, _lifecycle_started_at
    _lifecycle_running = False
    _lifecycle_started_at = None
    _lifecycle_cancel.clear()
    log.debug("scan_coordinator.lifecycle_unregistered")


def cancel_lifecycle_scan(reason: str = "") -> None:
    """Signal the lifecycle scan to cancel at its next check point."""
    if _lifecycle_running:
        _lifecycle_cancel.set()
        log.info("scan_coordinator.lifecycle_cancelled", reason=reason)


def is_lifecycle_cancelled() -> bool:
    """Checked by lifecycle walker loops — cheap bool read."""
    return _lifecycle_cancel.is_set()


# ── Run-now scan helpers ────────────────────────────────────────────────────

def register_run_now_scan() -> None:
    """Called when a run-now scan begins."""
    global _run_now_running, _run_now_started_at
    _run_now_cancel.clear()
    _run_now_pause.set()  # ensure not paused at start
    _run_now_running = True
    _run_now_started_at = time.monotonic()
    log.debug("scan_coordinator.run_now_registered")


def unregister_run_now_scan() -> None:
    """Called when a run-now scan finishes."""
    global _run_now_running, _run_now_paused, _run_now_started_at
    _run_now_running = False
    _run_now_paused = False
    _run_now_started_at = None
    _run_now_cancel.clear()
    _run_now_pause.set()
    log.debug("scan_coordinator.run_now_unregistered")


def cancel_run_now_scan(reason: str = "") -> None:
    """Signal the run-now scan to cancel."""
    if _run_now_running:
        _run_now_cancel.set()
        _run_now_pause.set()  # unblock if paused so it can exit
        log.info("scan_coordinator.run_now_cancelled", reason=reason)


def is_run_now_cancelled() -> bool:
    return _run_now_cancel.is_set()


def pause_run_now_scan(reason: str = "") -> None:
    """Pause run-now — it will block at the next checkpoint."""
    global _run_now_paused
    if _run_now_running and not _run_now_cancel.is_set():
        _run_now_pause.clear()  # clearing = blocked
        _run_now_paused = True
        log.info("scan_coordinator.run_now_paused", reason=reason)


def resume_run_now_scan(reason: str = "") -> None:
    """Resume a paused run-now scan."""
    global _run_now_paused
    _run_now_pause.set()  # setting = unblocked
    _run_now_paused = True if False else False  # always false after resume
    _run_now_paused = False
    log.info("scan_coordinator.run_now_resumed", reason=reason)


async def wait_if_run_now_paused() -> None:
    """Called by run-now at checkpoints. Blocks until resumed or cancelled."""
    if not _run_now_pause.is_set():
        log.info("scan_coordinator.run_now_waiting_for_bulk")
        await _run_now_pause.wait()
        log.info("scan_coordinator.run_now_wait_complete")


# ── Bulk job notifications ──────────────────────────────────────────────────

def notify_bulk_started(job_id: str = "") -> None:
    """Called when a bulk job starts. Cancels lifecycle, pauses run-now."""
    global _active_bulk_count
    _active_bulk_count += 1
    log.info("scan_coordinator.bulk_started",
             job_id=job_id, active_bulk_count=_active_bulk_count)

    # Cancel lifecycle — it will pick up at next scheduled time
    cancel_lifecycle_scan(reason=f"bulk_job_started:{job_id}")

    # Pause run-now — it will resume when bulk completes
    pause_run_now_scan(reason=f"bulk_job_started:{job_id}")

    try:
        from api.routes.pipeline import invalidate_stats_cache
        invalidate_stats_cache()
    except ImportError:
        pass


def notify_bulk_completed(job_id: str = "") -> None:
    """Called when a bulk job finishes. Resumes run-now if no other bulk active."""
    global _active_bulk_count
    _active_bulk_count = max(0, _active_bulk_count - 1)
    log.info("scan_coordinator.bulk_completed",
             job_id=job_id, active_bulk_count=_active_bulk_count)

    if _active_bulk_count == 0:
        resume_run_now_scan(reason="all_bulk_jobs_complete")

    try:
        from api.routes.pipeline import invalidate_stats_cache
        invalidate_stats_cache()
    except ImportError:
        pass


def notify_run_now_started() -> None:
    """Called when a run-now scan begins. Cancels lifecycle."""
    cancel_lifecycle_scan(reason="run_now_started")


def is_any_bulk_active() -> bool:
    """True if at least one bulk job is active."""
    return _active_bulk_count > 0


# ── Stale scan watchdog ────────────────────────────────────────────────────

def check_stale_scans() -> None:
    """Detect and reset scans that have been 'running' longer than the timeout.

    Called periodically by the scheduler (e.g. every 2 minutes via
    collect_metrics). If a scan's async task died without calling
    unregister, this resets the ghost flag so the coordinator doesn't
    block future scans indefinitely.
    """
    now = time.monotonic()

    if _run_now_running and _run_now_started_at is not None:
        elapsed = now - _run_now_started_at
        if elapsed > STALE_SCAN_TIMEOUT_S:
            log.warning("scan_coordinator.stale_run_now_detected",
                        elapsed_hours=round(elapsed / 3600, 1))
            unregister_run_now_scan()

    if _lifecycle_running and _lifecycle_started_at is not None:
        elapsed = now - _lifecycle_started_at
        if elapsed > STALE_SCAN_TIMEOUT_S:
            log.warning("scan_coordinator.stale_lifecycle_detected",
                        elapsed_hours=round(elapsed / 3600, 1))
            unregister_lifecycle_scan()


# ── Status for API / debugging ──────────────────────────────────────────────

def get_coordinator_status() -> dict:
    now = time.monotonic()
    run_now_elapsed = round(now - _run_now_started_at, 1) if _run_now_started_at else None
    lifecycle_elapsed = round(now - _lifecycle_started_at, 1) if _lifecycle_started_at else None
    return {
        "lifecycle_running": _lifecycle_running,
        "lifecycle_cancelled": _lifecycle_cancel.is_set(),
        "lifecycle_elapsed_s": lifecycle_elapsed,
        "run_now_running": _run_now_running,
        "run_now_cancelled": _run_now_cancel.is_set(),
        "run_now_paused": _run_now_paused,
        "run_now_elapsed_s": run_now_elapsed,
        "active_bulk_count": _active_bulk_count,
        "stale_timeout_s": STALE_SCAN_TIMEOUT_S,
    }


# Active Operations Registry — cancel hook for pipeline.run_now (v0.35.0).
# When operator clicks Cancel on the active-ops widget, registry calls
# this hook which translates to the existing scan cancel primitives.
#
# Bug fixed (v0.35.1): the original hook only called cancel_run_now_scan(),
# which sets _run_now_cancel.  But run_lifecycle_scan() (the actual scan
# loop) only polls _lifecycle_cancel via _should_cancel() / is_lifecycle_cancelled().
# _run_now_cancel is checked exactly once — before the scan starts — to bail
# out of a pause-for-bulk wait.  Once the scan loop is executing, setting
# _run_now_cancel has no effect on it.
#
# Fix: set _lifecycle_cancel directly (bypassing the _lifecycle_running guard
# in cancel_lifecycle_scan).  The guard exists to suppress spurious signals
# when no lifecycle scan is active; here we KNOW one is about to start or is
# already running because the active_ops registry only fires the hook when a
# live pipeline.run_now op exists.  Setting the event early is safe: if the
# scan hasn't started yet, register_lifecycle_scan() — which normally clears
# _lifecycle_cancel — must NOT clear it when a cancellation is already
# pending, so we also skip the clear in that path.  The simplest, safest
# change is: set the event unconditionally here; the scan checks
# _should_cancel() before its first expensive setup step and exits immediately.
from core.active_ops import register_cancel_hook  # noqa: E402


async def _cancel_run_now_via_active_ops(op_id: str) -> None:
    cancel_run_now_scan(reason="active_ops_registry")
    # Set _lifecycle_cancel directly — bypasses the _lifecycle_running guard
    # so the signal is honoured even if cancel arrives before register_lifecycle_scan().
    _lifecycle_cancel.set()
    log.info("scan_coordinator.lifecycle_cancelled_via_active_ops", op_id=op_id)


register_cancel_hook("pipeline.run_now", _cancel_run_now_via_active_ops)
