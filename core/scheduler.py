"""Scheduler job registry.

When adding a new job, FIRST update docs/scheduler-time-slots.md
to claim a time slot and document conflict checks (spec §17 P7).

The `log.info("scheduler.started", jobs=...)` literal is
self-counting via `len(scheduler.get_jobs())` as of v0.35.0 — no
manual count to maintain.
"""

import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import structlog

from core.active_ops import purge_old_active_ops
from core.database import get_preference, set_preference
from core.metrics_collector import record_activity_event

log = structlog.get_logger(__name__)

scheduler = AsyncIOScheduler()

_trash_expiry_run_count = 0

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
    except asyncio.CancelledError:
        # Container shutdown cancelled the scan mid-DB-await. CancelledError
        # is a BaseException, so it slips past `except Exception` and surfaces
        # as an apscheduler unhandled-exception traceback. Swallow at this
        # boundary — the scan run will be picked up at the next interval.
        log.info("scheduler.scan_cancelled_on_shutdown")
        return
    except Exception as exc:
        log.error("scheduler.scan_failed", error=str(exc))


async def run_trash_expiry() -> None:
    """Move expired marked_for_deletion to trash, purge expired trash."""
    global _trash_expiry_run_count
    _trash_expiry_run_count += 1

    try:
        force = (_trash_expiry_run_count % 4 == 0)

        if not force:
            # Yield to active bulk jobs — they hold the DB heavily
            from core.bulk_worker import get_all_active_jobs
            active = await get_all_active_jobs()
            if any(j["status"] in ("scanning", "running", "paused") for j in active):
                log.info("scheduler.trash_expiry_skipped_bulk_job_active")
                return

        if force:
            log.info("trash_expiry.forced_housekeeping_run", run_count=_trash_expiry_run_count)

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

        # v0.23.6 M4: the purge branch has moved to the dedicated daily
        # _purge_aged_trash job. This hourly job now only moves expired
        # marked_for_deletion rows into trash.
        if pending_trash:
            log.info(
                "scheduler.trash_expiry_complete",
                trashed=len(pending_trash),
            )
    except Exception as exc:
        log.error("scheduler.trash_expiry_failed", error=str(exc))


async def _purge_aged_trash() -> None:
    """v0.23.6 M4: daily 04:00 job — permanently delete trashed files older
    than `lifecycle_trash_retention_days` (default 60). Gated on the new
    `trash_auto_purge_enabled` preference, and yields to active bulk jobs
    like every other scheduled job.
    """
    try:
        enabled = await get_preference("trash_auto_purge_enabled")
        if enabled == "false":
            log.info("scheduler.purge_aged_trash_skipped_disabled")
            return

        # Yield to active bulk jobs
        from core.bulk_worker import get_all_active_jobs
        active = await get_all_active_jobs()
        if any(j["status"] in ("scanning", "running", "paused") for j in active):
            log.info("scheduler.purge_aged_trash_skipped_bulk_job_active")
            return

        from core.database import get_source_files_pending_purge, db_fetch_all
        from core.lifecycle_manager import purge_file

        retention_str = await get_preference("lifecycle_trash_retention_days")
        retention_days = int(retention_str) if retention_str else 60

        pending_purge = await get_source_files_pending_purge(trash_retention_days=retention_days)
        bytes_freed = 0
        purged_count = 0
        for sf in pending_purge:
            size = sf.get("file_size_bytes") or 0
            try:
                bytes_freed += int(size)
            except (TypeError, ValueError):
                pass
            bf_rows = await db_fetch_all(
                "SELECT id FROM bulk_files WHERE source_file_id = ?", (sf["id"],),
            )
            for bf in bf_rows:
                try:
                    await purge_file(bf["id"])
                    purged_count += 1
                except Exception as exc:
                    log.error("scheduler.purge_aged_trash_failed", file_id=bf["id"], error=str(exc))

        log.info(
            "scheduler.purge_aged_trash_complete",
            retention_days=retention_days,
            purged=purged_count,
            bytes_freed=bytes_freed,
        )

        if purged_count > 0:
            try:
                await record_activity_event(
                    "trash_auto_purge",
                    f"Auto-purged {purged_count} trashed files ({bytes_freed / (1024*1024):.0f} MB)",
                )
            except Exception:
                pass
    except Exception as exc:
        log.error("scheduler.purge_aged_trash_error", error=str(exc))


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


async def _bulk_files_self_correction() -> None:
    """
    Periodic self-correction for the bulk_files table.

    Removes phantom rows (source file gone from disk), purged rows
    (source_files.lifecycle_status='purged'), and cross-job duplicates
    (older copies of the same source_path from finished jobs). Skips work
    while any bulk job is active to avoid touching in-flight rows.

    Why: bulk_files is keyed by (job_id, source_path), so each scan creates
    a fresh copy of every file. Without periodic cleanup the table balloons
    to 10x+ the unique file count and the pipeline status badge reports
    nonsensical pending counts.
    """
    try:
        # Skip if any bulk job is currently scanning/running/paused.
        from core.bulk_worker import get_all_active_jobs
        if await get_all_active_jobs():
            log.info("bulk_files_self_correction_skipped",
                     reason="active_bulk_job")
            return

        from core.db import cleanup_stale_bulk_files
        result = await cleanup_stale_bulk_files()
        if result["total_deleted"] > 0:
            log.info(
                "bulk_files_self_correction_run",
                phantom_deleted=result["phantom_deleted"],
                purged_deleted=result["purged_deleted"],
                dedup_deleted=result["dedup_deleted"],
                total_deleted=result["total_deleted"],
            )
        else:
            log.debug("bulk_files_self_correction_run", total_deleted=0)
    except Exception as exc:
        log.error("bulk_files_self_correction_failed", error=str(exc))


async def run_housekeeping():
    """Periodic housekeeping — supersedes all other tasks.

    Does NOT check get_all_active_jobs(). Runs regardless of active bulk jobs.
    """
    log.info("housekeeping.start")

    # 1. Cross-job dedup (safety net)
    try:
        from core.db.connection import db_execute
        await db_execute("""
            DELETE FROM bulk_files
            WHERE rowid NOT IN (
                SELECT MAX(rowid) FROM bulk_files GROUP BY source_path
            )
        """)
        log.info("housekeeping.dedup_complete")
    except Exception as e:
        log.warning("housekeeping.dedup_failed", error=str(e))

    # 2. PRAGMA optimize
    try:
        from core.db.connection import db_execute as _db_execute
        await _db_execute("PRAGMA optimize")
    except Exception:
        pass

    # 3. Check free pages — VACUUM if > 10%
    try:
        from core.db.connection import db_fetch_one, db_execute as _db_exec
        free = await db_fetch_one("PRAGMA freelist_count")
        total = await db_fetch_one("PRAGMA page_count")
        if free and total:
            free_count = list(free.values())[0]
            total_count = list(total.values())[0]
            if total_count > 0 and free_count / total_count > 0.10:
                log.info("housekeeping.vacuum_starting",
                         free_pages=free_count, total_pages=total_count)
                await _db_exec("VACUUM")
                log.info("housekeeping.vacuum_complete")
    except Exception as e:
        log.warning("housekeeping.vacuum_failed", error=str(e))

    log.info("housekeeping.complete")


async def run_mount_health_check() -> None:
    """v0.25.0: Probe each mounted share's reachability. Yields to active bulk jobs.

    A failed probe doesn't auto-remount — the operator sees the red dot on
    the Storage page and decides what to do. Auto-remediation hides root
    causes (matches the overnight-rebuild design philosophy).
    """
    try:
        from core.bulk_worker import get_all_active_jobs
        active = await get_all_active_jobs()
        if active:
            log.debug("mount_health.skipped_bulk_job_active")
            return
        from core.mount_manager import check_mount_health, get_mount_manager
        await check_mount_health(get_mount_manager())
    except Exception as exc:
        log.error("mount_health.failed", error=str(exc))


async def check_llm_costs_staleness() -> None:
    """v0.33.3: daily check that the LLM rate table on disk is fresh.

    Emits a `llm_costs.stale` warning event if `llm_costs.json:updated_at`
    is older than 90 days, so admins can grep the log for the warning
    and refresh the file from the providers' published pricing pages.
    Doesn't auto-update — the file is operator-curated by design.
    """
    try:
        from core.llm_costs import get_costs, is_data_stale
        threshold_days = 90
        table = get_costs()
        if not table.updated_at:
            log.warning(
                "llm_costs.stale",
                reason="updated_at field empty in llm_costs.json",
                source_url=table.source_url,
            )
            return
        if is_data_stale(threshold_days=threshold_days):
            log.warning(
                "llm_costs.stale",
                updated_at=table.updated_at,
                threshold_days=threshold_days,
                source_url=table.source_url,
                hint="edit core/data/llm_costs.json against current provider pricing, then POST /api/admin/llm-costs/reload",
            )
    except Exception as exc:
        log.error("llm_costs.staleness_check_failed", error=str(exc))


async def _drift_check() -> None:
    """Compare active_ops in-memory counters against the DB for running ops.

    bulk.job ops: active_ops.done vs bulk_jobs.converted + skipped + failed
    pipeline.scan ops: active_ops.done vs scan_runs.files_scanned

    Does NOT yield to active bulk jobs — this check is most meaningful
    while a job is in flight. Read-only; never mutates state.
    """
    try:
        from core.active_ops import list_ops
        from core.database import db_fetch_one

        running = await list_ops(include_finished=False)

        for op in running:
            if op.op_type == "bulk.job":
                job_id = (op.extra or {}).get("job_id")
                if not job_id:
                    continue
                row = await db_fetch_one(
                    "SELECT COALESCE(converted,0) + COALESCE(skipped,0)"
                    " + COALESCE(failed,0) AS db_done"
                    " FROM bulk_jobs WHERE id = ?",
                    (job_id,),
                )
                if row is None:
                    continue
                drift = op.done - row["db_done"]
                if abs(drift) > 10:
                    log.warning(
                        "active_ops.drift_detected",
                        op_id=op.op_id,
                        op_type=op.op_type,
                        active_ops_done=op.done,
                        db_done=row["db_done"],
                        drift=drift,
                    )

            elif op.op_type == "pipeline.scan":
                scan_run_id = (op.extra or {}).get("scan_run_id")
                if not scan_run_id:
                    continue
                row = await db_fetch_one(
                    "SELECT COALESCE(files_scanned, 0) AS db_done"
                    " FROM scan_runs WHERE id = ?",
                    (scan_run_id,),
                )
                if row is None:
                    continue
                drift = op.done - row["db_done"]
                if abs(drift) > 10:
                    log.warning(
                        "active_ops.drift_detected",
                        op_id=op.op_id,
                        op_type=op.op_type,
                        active_ops_done=op.done,
                        db_done=row["db_done"],
                        drift=drift,
                    )

    except Exception as exc:
        log.error("scheduler.drift_check_failed", error=str(exc))


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

    # Trash expiry — every hour (only moves expired marks → trash)
    scheduler.add_job(
        run_trash_expiry,
        trigger=IntervalTrigger(hours=1),
        id="trash_expiry",
        replace_existing=True,
        max_instances=1,
    )

    # v0.23.6 M4: Aged-trash auto-purge — daily at 04:00 local
    scheduler.add_job(
        _purge_aged_trash,
        trigger=CronTrigger(hour=4, minute=0),
        id="purge_aged_trash",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
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

    # v0.31.0: Unified log management job. Replaces the v0.12.2
    # `core.log_manager.archive_rotated_logs` (the old core.log_archiver
    # module was consolidated into core/log_manager.py) with a thin
    # wrapper around `core.log_manager` so the Settings-page
    # preferences (compression format, retention days) actually
    # govern the automated cycle. Previously the cron ignored those
    # prefs — only manual "Compress Rotated Now" / "Apply Retention
    # Now" admin clicks honored them, which surprised operators.
    async def _log_manage_cycle():
        from core.log_manager import compress_rotated_logs, apply_retention
        try:
            await compress_rotated_logs()
        except Exception as exc:
            log.warning("scheduler.log_compress_failed",
                        error=f"{type(exc).__name__}: {exc}")
        try:
            await apply_retention()
        except Exception as exc:
            log.warning("scheduler.log_retention_failed",
                        error=f"{type(exc).__name__}: {exc}")

    scheduler.add_job(
        _log_manage_cycle,
        trigger=IntervalTrigger(hours=6),
        id="log_archive",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # v0.31.5: ETA framework system-spec snapshot — daily.
    # Records a bounded history (last 90 entries) of host CPU /
    # RAM / load to `preferences['eta_system_spec_history']`. The
    # ETA estimator uses recent throughput + this spec history to
    # forecast operation durations on the operator's actual
    # hardware. Best-effort: failures are logged, never raised.
    from core.eta_estimator import record_system_spec_snapshot
    scheduler.add_job(
        record_system_spec_snapshot,
        trigger=IntervalTrigger(hours=24),
        id="eta_system_spec_snapshot",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
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

    # v0.22.7: bulk_files self-correction (phantom prune + cross-job dedup)
    # Runs every 6 hours; skips automatically if a bulk job is in flight.
    scheduler.add_job(
        _bulk_files_self_correction,
        trigger=IntervalTrigger(hours=6),
        id="bulk_files_self_correction",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # v0.23.0: Housekeeping — every 2 hours (dedup + optimize + conditional VACUUM)
    scheduler.add_job(
        run_housekeeping,
        trigger=IntervalTrigger(hours=2),
        id="run_housekeeping",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # v0.25.0: Mount health probe — every 5 minutes (yields to active bulk jobs)
    scheduler.add_job(
        run_mount_health_check,
        trigger=IntervalTrigger(minutes=5),
        id="mount_health",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )

    # v0.33.3: LLM rate-table staleness check — daily at 03:30 (quiet
    # window before the 04:00 trash auto-purge). Emits a warning event
    # if llm_costs.json:updated_at is older than 90 days.
    scheduler.add_job(
        check_llm_costs_staleness,
        trigger=CronTrigger(hour=3, minute=30),
        id="check_llm_costs_staleness",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # v0.35.0: Active Operations Registry — daily auto-purge of finished
    # rows older than 7 days (spec §10). Slot 03:50 is 10 min after the
    # 03:30 llm_costs check and 10 min before 04:00 trash purge —
    # avoids contention with both (spec P7). Deliberately does NOT yield
    # to bulk jobs (cf. CLAUDE.md "Top Gotchas") because the DELETE is
    # on a small bounded table (~1000 rows max by design); yielding
    # would risk deferring cleanup indefinitely if a bulk job overlaps.
    scheduler.add_job(
        purge_old_active_ops,
        trigger=CronTrigger(hour=3, minute=50),
        id="purge_old_active_ops",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # v0.41.0: Active-ops drift detection — daily at 03:55
    # Compares in-memory counters against DB ground truth for all running ops.
    # Slot 03:55 is 5 min after purge_old_active_ops (03:50) and 5 min
    # before purge_aged_trash (04:00). Read-only; never yields to bulk jobs.
    scheduler.add_job(
        _drift_check,
        trigger=CronTrigger(hour=3, minute=55),
        id="active_ops_drift_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    # Self-counting so add_job calls don't need to bump a literal here.
    log.info("scheduler.started", jobs=len(scheduler.get_jobs()))


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
        "eta_system_spec_snapshot": "eta_system_spec_snapshot_next",
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
