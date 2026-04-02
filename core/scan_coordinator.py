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


# ── Lifecycle scan helpers ──────────────────────────────────────────────────

def register_lifecycle_scan() -> None:
    """Called when a lifecycle scan begins. Clears any stale cancel signal."""
    global _lifecycle_running
    _lifecycle_cancel.clear()
    _lifecycle_running = True
    log.debug("scan_coordinator.lifecycle_registered")


def unregister_lifecycle_scan() -> None:
    """Called when a lifecycle scan finishes (complete or cancelled)."""
    global _lifecycle_running
    _lifecycle_running = False
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
    global _run_now_running
    _run_now_cancel.clear()
    _run_now_pause.set()  # ensure not paused at start
    _run_now_running = True
    log.debug("scan_coordinator.run_now_registered")


def unregister_run_now_scan() -> None:
    """Called when a run-now scan finishes."""
    global _run_now_running, _run_now_paused
    _run_now_running = False
    _run_now_paused = False
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


def notify_bulk_completed(job_id: str = "") -> None:
    """Called when a bulk job finishes. Resumes run-now if no other bulk active."""
    global _active_bulk_count
    _active_bulk_count = max(0, _active_bulk_count - 1)
    log.info("scan_coordinator.bulk_completed",
             job_id=job_id, active_bulk_count=_active_bulk_count)

    if _active_bulk_count == 0:
        resume_run_now_scan(reason="all_bulk_jobs_complete")


def notify_run_now_started() -> None:
    """Called when a run-now scan begins. Cancels lifecycle."""
    cancel_lifecycle_scan(reason="run_now_started")


def is_any_bulk_active() -> bool:
    """True if at least one bulk job is active."""
    return _active_bulk_count > 0


# ── Status for API / debugging ──────────────────────────────────────────────

def get_coordinator_status() -> dict:
    return {
        "lifecycle_running": _lifecycle_running,
        "lifecycle_cancelled": _lifecycle_cancel.is_set(),
        "run_now_running": _run_now_running,
        "run_now_cancelled": _run_now_cancel.is_set(),
        "run_now_paused": _run_now_paused,
        "active_bulk_count": _active_bulk_count,
    }
