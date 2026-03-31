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
    """Run lifecycle scan. Skips if outside business hours unless force=True.

    Also skips if any bulk job is currently active (scanning, running, or
    paused) — bulk jobs take priority over background lifecycle scans.
    """
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

        # Yield to active bulk jobs — they hold the DB heavily
        from core.bulk_worker import get_all_active_jobs
        active = await get_all_active_jobs()
        if any(j["status"] in ("scanning", "running", "paused") for j in active):
            log.info("scheduler.scan_skipped_bulk_job_active")
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
    """Run DB compaction. Safe to run alongside scans in WAL mode."""
    try:
        from core.db_maintenance import run_compaction
        await run_compaction()

        from core.metrics_collector import record_activity_event
        await record_activity_event("db_maintenance", "Scheduled DB maintenance (VACUUM/integrity check)")
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


async def _run_deferred_conversions() -> None:
    """Check for deferred auto-conversion jobs and start them if in-window.

    Only relevant in 'scheduled' mode. Checks if we're now inside a
    conversion window and picks up any pending deferred runs.
    """
    try:
        from core.database import get_preference
        mode = await get_preference("auto_convert_mode") or "off"
        if mode != "scheduled":
            return

        from core.auto_converter import get_auto_conversion_engine
        engine = get_auto_conversion_engine()
        hist = await engine._get_historical_context()

        if not await engine._is_in_conversion_window(hist):
            return

        # Find pending deferred runs
        from core.database import get_db

        async with get_db() as conn:
            rows = await conn.execute_fetchall(
                """SELECT * FROM auto_conversion_runs
                   WHERE status = 'deferred'
                   ORDER BY started_at ASC LIMIT 5"""
            )

        if not rows:
            return

        for run in rows:
            try:
                from core.lifecycle_scanner import run_lifecycle_scan
                log.info(
                    "deferred_conversion_triggered",
                    run_id=run["id"],
                    original_scan_run=run["scan_run_id"],
                )
                # Re-run the lifecycle scan which will trigger auto-conversion
                # (now in-window, so it will proceed)
                await run_lifecycle_scan()

                # Mark the deferred run as completed
                async with get_db() as conn:
                    await conn.execute(
                        "UPDATE auto_conversion_runs SET status = 'completed' WHERE id = ?",
                        (run["id"],),
                    )
                    await conn.commit()
            except Exception as exc:
                log.error(
                    "deferred_conversion_failed",
                    run_id=run["id"],
                    error=str(exc),
                )
    except Exception as exc:
        log.error("deferred_conversion_runner_failed", error=str(exc))


def start_scheduler() -> None:
    """Register all jobs and start the scheduler. Called from lifespan."""
    from core.metrics_collector import collect_metrics, collect_disk_snapshot, purge_old_metrics

    # Resource metrics — every 120 seconds
    scheduler.add_job(
        collect_metrics,
        trigger=IntervalTrigger(seconds=120),
        id="collect_metrics",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    # Disk metrics — every 6 hours
    scheduler.add_job(
        collect_disk_snapshot,
        trigger=IntervalTrigger(hours=6),
        id="collect_disk_snapshot",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Purge old metrics — daily at 03:00
    scheduler.add_job(
        purge_old_metrics,
        trigger=CronTrigger(hour=3, minute=0),
        id="purge_old_metrics",
        replace_existing=True,
        max_instances=1,
    )

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

    # v0.11.0: Hourly auto-metrics aggregation — :05 past every hour
    from core.auto_metrics_aggregator import aggregate_hourly_metrics
    scheduler.add_job(
        aggregate_hourly_metrics,
        trigger=CronTrigger(minute=5),
        id="auto_metrics_aggregation",
        replace_existing=True,
        max_instances=1,
    )

    # v0.11.0: Deferred conversion runner — every 15 minutes
    scheduler.add_job(
        _run_deferred_conversions,
        trigger=IntervalTrigger(minutes=15),
        id="deferred_conversion_runner",
        replace_existing=True,
        max_instances=1,
    )

    # v0.12.2: Log archive — compress rotated logs every 6 hours
    from core.log_archiver import archive_rotated_logs
    scheduler.add_job(
        archive_rotated_logs,
        trigger=IntervalTrigger(hours=6),
        id="log_archive",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    log.info("scheduler.started", jobs=11)


def get_scheduler_status() -> dict:
    """Return next run times for all scheduled jobs."""
    result = {}
    job_names = {
        "lifecycle_scan": "lifecycle_scan_next",
        "trash_expiry": "trash_expiry_next",
        "db_compaction": "db_compact_next",
        "collect_metrics": "metrics_collect_next",
        "collect_disk_snapshot": "disk_snapshot_next",
        "purge_old_metrics": "metrics_purge_next",
        "auto_metrics_aggregation": "auto_metrics_aggregation_next",
        "deferred_conversion_runner": "deferred_conversion_next",
        "log_archive": "log_archive_next",
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
