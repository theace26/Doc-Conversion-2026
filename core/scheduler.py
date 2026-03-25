"""
APScheduler setup — registers lifecycle scan, trash expiry, and DB maintenance jobs.

Called from main.py lifespan.
"""

from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import structlog

log = structlog.get_logger(__name__)

scheduler = AsyncIOScheduler()


def _is_business_hours() -> bool:
    """Check if current local time is within business hours (Mon-Fri 06:00-18:00)."""
    try:
        from core.database import get_all_preferences
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Can't await in sync function — use defaults
            start_hour, start_min = 6, 0
            end_hour, end_min = 18, 0
        else:
            prefs = loop.run_until_complete(get_all_preferences())
            start = prefs.get("scanner_business_hours_start", "06:00")
            end = prefs.get("scanner_business_hours_end", "18:00")
            start_hour, start_min = map(int, start.split(":"))
            end_hour, end_min = map(int, end.split(":"))
    except Exception:
        start_hour, start_min = 6, 0
        end_hour, end_min = 18, 0

    now = datetime.now()
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    if weekday > 4:  # Saturday or Sunday
        return False

    current_minutes = now.hour * 60 + now.minute
    start_minutes = start_hour * 60 + start_min
    end_minutes = end_hour * 60 + end_min
    return start_minutes <= current_minutes < end_minutes


async def run_lifecycle_scan(force: bool = False) -> None:
    """Run lifecycle scan. Skips if outside business hours unless force=True."""
    if not force and not _is_business_hours():
        log.debug("scheduler.scan_skipped_outside_business_hours")
        return

    try:
        # Check if scanner is enabled
        from core.database import get_preference
        enabled = await get_preference("scanner_enabled")
        if enabled == "false" and not force:
            log.debug("scheduler.scan_disabled")
            return

        from core.lifecycle_scanner import run_lifecycle_scan as _scan
        scan_run_id = await _scan()
        log.info("scheduler.scan_complete", scan_run_id=scan_run_id)
    except Exception as exc:
        log.error("scheduler.scan_failed", error=str(exc))


async def run_trash_expiry() -> None:
    """Move expired marked_for_deletion to trash, purge expired trash."""
    try:
        from core.database import get_bulk_files_pending_trash, get_bulk_files_pending_purge, get_preference
        from core.lifecycle_manager import move_to_trash, purge_file

        # Get configurable periods
        grace_str = await get_preference("lifecycle_grace_period_hours")
        grace_hours = int(grace_str) if grace_str else 36
        retention_str = await get_preference("lifecycle_trash_retention_days")
        retention_days = int(retention_str) if retention_str else 60

        # Move to trash
        pending_trash = await get_bulk_files_pending_trash(grace_period_hours=grace_hours)
        for f in pending_trash:
            try:
                await move_to_trash(f["id"])
            except Exception as exc:
                log.error("scheduler.trash_move_failed", file_id=f["id"], error=str(exc))

        # Purge expired trash
        pending_purge = await get_bulk_files_pending_purge(trash_retention_days=retention_days)
        for f in pending_purge:
            try:
                await purge_file(f["id"])
            except Exception as exc:
                log.error("scheduler.purge_failed", file_id=f["id"], error=str(exc))

        if pending_trash or pending_purge:
            log.info(
                "scheduler.trash_expiry_complete",
                trashed=len(pending_trash),
                purged=len(pending_purge),
            )
    except Exception as exc:
        log.error("scheduler.trash_expiry_failed", error=str(exc))


async def run_db_compaction() -> None:
    """Run DB compaction, deferring if a scan is running."""
    try:
        from core.database import db_fetch_one
        running = await db_fetch_one(
            "SELECT id FROM scan_runs WHERE status='running' LIMIT 1"
        )
        if running:
            log.warning("scheduler.compaction_deferred", reason="scan_running")
            # Reschedule in 30 minutes
            scheduler.add_job(
                run_db_compaction,
                trigger=IntervalTrigger(minutes=30),
                id="db_compaction_retry",
                replace_existing=True,
                max_instances=1,
            )
            return

        from core.db_maintenance import run_compaction
        await run_compaction()
    except Exception as exc:
        log.error("scheduler.compaction_failed", error=str(exc))


async def run_db_integrity_check() -> None:
    """Run DB integrity check."""
    try:
        from core.db_maintenance import run_integrity_check
        await run_integrity_check()
    except Exception as exc:
        log.error("scheduler.integrity_check_failed", error=str(exc))


async def run_stale_data_check() -> None:
    """Run stale data check."""
    try:
        from core.db_maintenance import run_stale_data_check
        await run_stale_data_check()
    except Exception as exc:
        log.error("scheduler.stale_check_failed", error=str(exc))


def start_scheduler() -> None:
    """Register all jobs and start the scheduler. Called from lifespan."""
    # Lifecycle scan — every 15 minutes (business hours enforced in the job)
    scheduler.add_job(
        run_lifecycle_scan,
        trigger=IntervalTrigger(minutes=15),
        id="lifecycle_scan",
        replace_existing=True,
        max_instances=1,
    )

    # Trash expiry — every hour
    scheduler.add_job(
        run_trash_expiry,
        trigger=IntervalTrigger(hours=1),
        id="trash_expiry",
        replace_existing=True,
        max_instances=1,
    )

    # DB compaction — Sunday 02:00
    scheduler.add_job(
        run_db_compaction,
        trigger=CronTrigger(day_of_week="sun", hour=2, minute=0),
        id="db_compaction",
        replace_existing=True,
        max_instances=1,
    )

    # DB integrity check — Sunday 02:15
    scheduler.add_job(
        run_db_integrity_check,
        trigger=CronTrigger(day_of_week="sun", hour=2, minute=15),
        id="db_integrity",
        replace_existing=True,
        max_instances=1,
    )

    # Stale data check — Sunday 02:30
    scheduler.add_job(
        run_stale_data_check,
        trigger=CronTrigger(day_of_week="sun", hour=2, minute=30),
        id="stale_check",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    log.info("scheduler.started", jobs=5)


def get_scheduler_status() -> dict:
    """Return next run times for all scheduled jobs."""
    result = {}
    job_names = {
        "lifecycle_scan": "lifecycle_scan_next",
        "trash_expiry": "trash_expiry_next",
        "db_compaction": "db_compact_next",
    }
    for job_id, key in job_names.items():
        try:
            job = scheduler.get_job(job_id)
            if job and job.next_run_time:
                result[key] = job.next_run_time.isoformat()
            else:
                result[key] = None
        except Exception:
            result[key] = None
    return result


def stop_scheduler() -> None:
    """Gracefully shut down scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
