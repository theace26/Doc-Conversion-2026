"""
APScheduler setup — registers lifecycle scan, trash expiry, and DB maintenance jobs.

Called from main.py lifespan.
"""

from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import structlog

from core.database import get_preference, set_preference
from core.metrics_collector import record_activity_event

log = structlog.get_logger(__name__)

scheduler = AsyncIOScheduler()

# ── Pipeline pause state (in-memory, resets on container restart) ─────────────
_pipeline_paused: bool = False


def is_pipeline_paused() -> bool:
    """Return whether the pipeline is currently paused."""
    return _pipeline_paused


def set_pipeline_paused(paused: bool) -> None:
    """Pause or resume the pipeline."""
    global _pipeline_paused
    _pipeline_paused = paused
    log.info("pipeline.pause_state_changed", paused=paused)


async def _is_business_hours_async() -> bool:
    """Check if current local time is within scan hours (Mon-Fri, reads DB preferences)."""
    now = datetime.now()
    if now.weekday() > 4:  # Saturday or Sunday
        return False

    try:
        start_str = await get_preference("scanner_business_hours_start") or "06:00"
        end_str = await get_preference("scanner_business_hours_end") or "22:00"
        start_hour, start_min = map(int, start_str.split(":"))
        end_hour, end_min = map(int, end_str.split(":"))
    except Exception:
        start_hour, start_min = 6, 0
        end_hour, end_min = 22, 0

    current_minutes = now.hour * 60 + now.minute
    start_minutes = start_hour * 60 + start_min
    end_minutes = end_hour * 60 + end_min
    return start_minutes <= current_minutes < end_minutes


async def run_lifecycle_scan(force: bool = False) -> None:
    """Run lifecycle scan. Skips if outside business hours unless force=True.

    Also skips if any bulk job is currently active (scanning, running, or
    paused) — bulk jobs take priority over background lifecycle scans.

    The scan coordinator handles mid-scan cancellation: if a bulk job or
    run-now starts while the lifecycle scan is walking files, the coordinator
    sets a cancel flag that the walker checks at each file. The scan exits
    cleanly and picks up at the next scheduled interval.
    """
    if not force:
        # Pipeline master gate — if disabled, skip all scheduled scans
        pipeline_enabled = await get_preference("pipeline_enabled")
        if pipeline_enabled == "false":
            log.debug("scheduler.scan_skipped_pipeline_disabled")
            return

        # Pipeline pause — temporary in-memory pause via API
        if _pipeline_paused:
            log.debug("scheduler.scan_skipped_pipeline_paused")
            return

        in_hours = await _is_business_hours_async()
        if not in_hours:
            log.debug("scheduler.scan_skipped_outside_business_hours")
            return

    try:
        # Check if scanner is enabled
        enabled = await get_preference("scanner_enabled")
        if enabled == "false" and not force:
            log.debug("scheduler.scan_disabled")
            return

        # Pre-check: skip if bulk job is already active (fast path avoids
        # starting a scan only to immediately cancel it)
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
        # Yield to active bulk jobs — they hold the DB heavily
        from core.bulk_worker import get_all_active_jobs
        active = await get_all_active_jobs()
        if any(j["status"] in ("scanning", "running", "paused") for j in active):
            log.info("scheduler.trash_expiry_skipped_bulk_job_active")
            return

        from core.database import get_source_files_pending_trash, get_source_files_pending_purge, db_fetch_all
        from core.lifecycle_manager import move_to_trash, purge_file

        # Get configurable periods
        grace_str = await get_preference("lifecycle_grace_period_hours")
        grace_hours = int(grace_str) if grace_str else 36
        retention_str = await get_preference("lifecycle_trash_retention_days")
        retention_days = int(retention_str) if retention_str else 60

        # Move to trash — look up linked bulk_files for each source_file
        pending_trash = await get_source_files_pending_trash(grace_period_hours=grace_hours)
        for sf in pending_trash:
            bf_rows = await db_fetch_all(
                "SELECT id FROM bulk_files WHERE source_file_id = ?", (sf["id"],),
            )
            for bf in bf_rows:
                try:
                    await move_to_trash(bf["id"])
                except Exception as exc:
                    log.error("scheduler.trash_move_failed", file_id=bf["id"], error=str(exc))

        # Purge expired trash — same pattern
        pending_purge = await get_source_files_pending_purge(trash_retention_days=retention_days)
        for sf in pending_purge:
            bf_rows = await db_fetch_all(
                "SELECT id FROM bulk_files WHERE source_file_id = ?", (sf["id"],),
            )
            for bf in bf_rows:
                try:
                    await purge_file(bf["id"])
                except Exception as exc:
                    log.error("scheduler.purge_failed", file_id=bf["id"], error=str(exc))

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
        # Yield to active bulk jobs — VACUUM can block writes
        from core.bulk_worker import get_all_active_jobs
        active = await get_all_active_jobs()
        if any(j["status"] in ("scanning", "running", "paused") for j in active):
            log.info("scheduler.compaction_skipped_bulk_job_active")
            return

        from core.db_maintenance import run_compaction
        await run_compaction()


        await record_activity_event("db_maintenance", "Scheduled DB maintenance (VACUUM/integrity check)")
    except Exception as exc:
        log.error("scheduler.compaction_failed", error=str(exc))


async def run_db_integrity_check() -> None:
    """Run DB integrity check."""
    try:
        # Yield to active bulk jobs — integrity check is read-heavy
        from core.bulk_worker import get_all_active_jobs
        active = await get_all_active_jobs()
        if any(j["status"] in ("scanning", "running", "paused") for j in active):
            log.info("scheduler.integrity_check_skipped_bulk_job_active")
            return

        from core.db_maintenance import run_integrity_check
        await run_integrity_check()
    except Exception as exc:
        log.error("scheduler.integrity_check_failed", error=str(exc))


async def run_stale_data_check() -> None:
    """Run stale data check."""
    try:
        # Yield to active bulk jobs — stale check queries bulk_files
        from core.bulk_worker import get_all_active_jobs
        active = await get_all_active_jobs()
        if any(j["status"] in ("scanning", "running", "paused") for j in active):
            log.info("scheduler.stale_check_skipped_bulk_job_active")
            return

        from core.db_maintenance import run_stale_data_check
        await run_stale_data_check()
    except Exception as exc:
        log.error("scheduler.stale_check_failed", error=str(exc))


async def _pipeline_watchdog() -> None:
    """Periodic check: warn loudly when pipeline is disabled, auto-reset after N days.

    This job runs every hour. When the pipeline is off:
    - Logs a WARNING every hour (visible in Grafana/Loki)
    - Logs an ERROR once per day (ensures alerting rules fire)
    - Tracks when it was disabled via `pipeline_disabled_at` preference
    - Auto-re-enables after `pipeline_auto_reset_days` (default 3)
    """
    try:
        pipeline_enabled = await get_preference("pipeline_enabled")
        if pipeline_enabled != "false":
            # Pipeline is on — clear any stale disabled_at timestamp
            disabled_at = await get_preference("pipeline_disabled_at")
            if disabled_at:
                await set_preference("pipeline_disabled_at", "")
            return

        # Pipeline is OFF — record when it was first disabled
        disabled_at_str = await get_preference("pipeline_disabled_at")
        now = datetime.now()

        if not disabled_at_str:
            # First detection — record timestamp
            await set_preference("pipeline_disabled_at", now.isoformat())
            disabled_at_str = now.isoformat()
            log.error(
                "pipeline.disabled",
                message=(
                    "PIPELINE IS DISABLED. MarkFlow is not scanning or converting files. "
                    "This is not the intended operating state. The pipeline will auto-reset "
                    "to enabled after the configured timeout. Check logs for the reason."
                ),
                disabled_at=disabled_at_str,
            )
            return

        # Parse when it was disabled
        try:
            disabled_at = datetime.fromisoformat(disabled_at_str)
        except ValueError:
            disabled_at = now
            await set_preference("pipeline_disabled_at", now.isoformat())

        elapsed_hours = (now - disabled_at).total_seconds() / 3600
        auto_reset_days = int(await get_preference("pipeline_auto_reset_days") or "3")
        auto_reset_hours = auto_reset_days * 24
        remaining_hours = max(0, auto_reset_hours - elapsed_hours)

        # Check if it's time to auto-reset
        if elapsed_hours >= auto_reset_hours:
            await set_preference("pipeline_enabled", "true")
            await set_preference("pipeline_disabled_at", "")
            log.warning(
                "pipeline.auto_reset",
                message=(
                    f"Pipeline was disabled for {auto_reset_days} days. "
                    "Auto-resetting to ENABLED. If a real problem exists, "
                    "it will surface in conversion logs."
                ),
                disabled_duration_hours=round(elapsed_hours, 1),
            )
            # Record activity event
            try:
        
                await record_activity_event(
                    "pipeline_auto_reset",
                    f"Pipeline auto-reset after {auto_reset_days} days disabled",
                )
            except Exception:
                pass
            return

        # Still disabled — log warnings
        # ERROR once per day (at hour boundaries divisible by 24)
        if int(elapsed_hours) > 0 and int(elapsed_hours) % 24 == 0:
            log.error(
                "pipeline.disabled_critical",
                message=(
                    f"PIPELINE HAS BEEN DISABLED FOR {int(elapsed_hours)} HOURS. "
                    f"Auto-reset in {int(remaining_hours)} hours. "
                    "MarkFlow is NOT scanning or converting files."
                ),
                disabled_at=disabled_at_str,
                elapsed_hours=round(elapsed_hours, 1),
                auto_reset_in_hours=round(remaining_hours, 1),
            )
        else:
            # WARNING every hour
            log.warning(
                "pipeline.disabled_reminder",
                message=(
                    f"Pipeline disabled for {int(elapsed_hours)}h. "
                    f"Auto-reset in {int(remaining_hours)}h. "
                    "No scanning or conversion is running."
                ),
                disabled_at=disabled_at_str,
                elapsed_hours=round(elapsed_hours, 1),
                auto_reset_in_hours=round(remaining_hours, 1),
            )
    except Exception as exc:
        log.error("pipeline.watchdog_failed", error=str(exc))


async def _run_deferred_conversions() -> None:
    """Backlog poller: start conversion batches for pending files.

    In 'immediate' or 'queued' mode, checks for pending files and starts
    a conversion batch if no bulk job is currently active — decoupled from
    scan completion so conversion doesn't wait for the scanner to finish.

    In 'scheduled' mode, also picks up deferred runs when in-window.
    """
    try:
        mode = await get_preference("auto_convert_mode") or "off"
        if mode == "off":
            return

        pipeline_enabled = (await get_preference("pipeline_enabled") or "true") == "true"
        if not pipeline_enabled:
            return

        # ── Backlog poller (immediate / queued / scheduled) ─────────
        from core.bulk_worker import get_all_active_jobs
        from core.database import db_fetch_one

        active = await get_all_active_jobs()
        if any(j["status"] in ("scanning", "running", "paused") for j in active):
            log.debug("backlog_poller.skipped_active_job")
            return
        # Double-check DB — in-memory state can miss jobs from other code paths
        db_active = await db_fetch_one(
            "SELECT COUNT(*) as cnt FROM bulk_jobs WHERE status IN ('scanning', 'running', 'pending')"
        )
        if db_active and db_active["cnt"] > 0:
            log.debug("backlog_poller.skipped_db_active_job", db_active_count=db_active["cnt"])
            return
        if not active:
            row = await db_fetch_one(
                "SELECT COUNT(*) as cnt FROM bulk_files WHERE status = 'pending'"
            )
            pending = row["cnt"] if row else 0

            if pending > 0:
                log.info(
                    "backlog_conversion_triggered",
                    pending_files=pending,
                    mode=mode,
                )
                # Reuse the auto-conversion execution path
                import asyncio
                import os
                from pathlib import Path
                from core.auto_converter import AutoConvertDecision
                from core.lifecycle_scanner import _execute_auto_conversion

                workers = int(await get_preference("auto_convert_workers") or "8")
                batch_raw = await get_preference("auto_convert_batch_size") or "auto"
                batch_size = 0 if batch_raw == "auto" else int(batch_raw)
                source_root = Path(os.getenv("SOURCE_DIR", "/mnt/source"))

                decision = AutoConvertDecision(
                    should_convert=True,
                    mode=mode if mode != "scheduled" else "queued",
                    workers=workers,
                    batch_size=batch_size,
                    reason=f"Backlog poller: {pending} pending files",
                )
                await _execute_auto_conversion(
                    decision,
                    scan_run_id="backlog-poller",
                    source_root=source_root,
                    job_id="backlog",
                )
                return  # Don't also process deferred runs this tick

        # ── Deferred run handler (scheduled mode only) ─────────────
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


async def _expire_flags() -> None:
    """Hourly job: expire flags past their expires_at."""
    try:
        from core.flag_manager import expire_flags
        expired = await expire_flags()
        if expired:
            log.info("flag_expiry_run", expired_count=expired)
    except Exception as exc:
        log.error("flag_expiry_failed", error=str(exc))


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

    # Stale scan watchdog — every 5 minutes
    from core.scan_coordinator import check_stale_scans
    scheduler.add_job(
        check_stale_scans,
        trigger=IntervalTrigger(minutes=5),
        id="check_stale_scans",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
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

    # Lifecycle scan — 45 min default (matches scanner_interval_minutes preference)
    scheduler.add_job(
        run_lifecycle_scan,
        trigger=IntervalTrigger(minutes=45),
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

    # v0.14.0: Pipeline watchdog — hourly check for disabled state + auto-reset
    scheduler.add_job(
        _pipeline_watchdog,
        trigger=IntervalTrigger(hours=1),
        id="pipeline_watchdog",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # v0.16.0: Flag expiry — hourly
    scheduler.add_job(
        _expire_flags,
        trigger=IntervalTrigger(hours=1),
        id="flag_expiry",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # v0.18.0: Image analysis queue drain — every 5 minutes
    from core.analysis_worker import run_analysis_drain
    scheduler.add_job(
        run_analysis_drain,
        trigger=IntervalTrigger(minutes=5),
        id="analysis_drain",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    scheduler.start()
    log.info("scheduler.started", jobs=14)


def get_pipeline_status() -> dict:
    """Return pipeline-specific status including next scan time."""
    scan_job = scheduler.get_job("lifecycle_scan") if scheduler.running else None
    next_scan = scan_job.next_run_time.isoformat() if scan_job and scan_job.next_run_time else None
    return {
        "paused": _pipeline_paused,
        "scheduler_running": scheduler.running,
        "next_scan": next_scan,
    }


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
        "pipeline_watchdog": "pipeline_watchdog_next",
        "log_archive": "log_archive_next",
        "analysis_drain": "analysis_drain_next",
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
