"""
core/stop_controller.py

Global stop controller. Workers call should_stop() before each file.
A hard stop sets the global flag, cancels all async tasks that registered,
and records the stop event in SQLite.

This is intentionally simple -- one module-level flag, no locks needed because
asyncio is single-threaded. Worker tasks check the flag; they are responsible
for their own clean exit.
"""

import asyncio
import structlog
from datetime import datetime, timezone

log = structlog.get_logger(__name__)

# Module-level state -- lives for the lifetime of the process
_stop_requested: bool = False
_stop_requested_at: datetime | None = None
_stop_reason: str = ""
_registered_tasks: dict[str, asyncio.Task] = {}   # job_id -> asyncio.Task


def should_stop() -> bool:
    """Workers call this before processing each file. Cheap -- just reads a bool."""
    return _stop_requested


def request_stop(reason: str = "admin_requested") -> dict:
    """
    Sets the global stop flag and cancels all registered tasks.
    Returns a summary of what was stopped.
    """
    global _stop_requested, _stop_requested_at, _stop_reason
    _stop_requested = True
    _stop_requested_at = datetime.now(timezone.utc)
    _stop_reason = reason

    stopped = list(_registered_tasks.keys())
    for job_id, task in list(_registered_tasks.items()):
        if not task.done():
            task.cancel()
            log.info("job_cancelled_by_stop", job_id=job_id, reason=reason)

    _registered_tasks.clear()
    log.warning("global_stop_requested", reason=reason, jobs_cancelled=stopped)
    return {"stopped_jobs": stopped, "at": _stop_requested_at.isoformat()}


def reset_stop() -> None:
    """
    Clears the stop flag. Must be called before starting any new job after a stop.
    Called automatically when a new bulk job is created via the API.
    """
    global _stop_requested, _stop_requested_at, _stop_reason
    _stop_requested = False
    _stop_requested_at = None
    _stop_reason = ""
    log.info("stop_flag_reset")


def register_task(job_id: str, task: asyncio.Task) -> None:
    """Workers register their asyncio.Task here so stop_all can cancel them."""
    _registered_tasks[job_id] = task
    log.debug("task_registered", job_id=job_id)


def unregister_task(job_id: str) -> None:
    _registered_tasks.pop(job_id, None)


def get_stop_state() -> dict:
    return {
        "stop_requested":    _stop_requested,
        "stop_requested_at": _stop_requested_at.isoformat() if _stop_requested_at else None,
        "stop_reason":       _stop_reason,
        "registered_tasks":  list(_registered_tasks.keys()),
    }
