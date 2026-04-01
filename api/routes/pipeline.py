"""
Pipeline status and control API endpoints.

GET  /api/pipeline/status   -- Pipeline status (enabled, paused, last scan, next scan)
POST /api/pipeline/pause    -- Pause the pipeline (in-memory)
POST /api/pipeline/resume   -- Resume the pipeline
POST /api/pipeline/run-now  -- Trigger immediate scan+convert cycle
"""

import asyncio

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends

from core.auth import AuthenticatedUser, UserRole, require_role
from core.database import (
    db_fetch_all,
    db_fetch_one,
    get_latest_scan_run,
    get_preference,
)
from core.scheduler import (
    get_pipeline_status,
    is_pipeline_paused,
    run_lifecycle_scan,
    set_pipeline_paused,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/status")
async def pipeline_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Full pipeline status: enabled, paused, running, last/next scan, pending files."""
    pipeline_enabled = await get_preference("pipeline_enabled") or "true"
    auto_convert_mode = await get_preference("auto_convert_mode") or "off"
    pipeline_max_files = int(await get_preference("pipeline_max_files_per_run") or "0")
    scanner_interval = int(await get_preference("scanner_interval_minutes") or "15")

    # Scheduler info
    sched = get_pipeline_status()

    # Last scan
    last_run = await get_latest_scan_run()

    # Is a scan currently running?
    running_row = await db_fetch_all(
        "SELECT id FROM scan_runs WHERE status='running' LIMIT 1"
    )
    is_scan_running = bool(running_row)

    # Pending files count (files discovered but not yet converted)
    pending_row = await db_fetch_one(
        "SELECT COUNT(*) as cnt FROM source_files WHERE lifecycle_status = 'active'"
    )
    pending_conversion = await db_fetch_one(
        "SELECT COUNT(*) as cnt FROM bulk_files WHERE status = 'pending'"
    )

    # Last auto-conversion run
    last_auto_run = await db_fetch_one(
        "SELECT * FROM auto_conversion_runs ORDER BY started_at DESC LIMIT 1"
    )

    return {
        "pipeline_enabled": pipeline_enabled == "true",
        "paused": sched["paused"],
        "auto_convert_mode": auto_convert_mode,
        "scanner_interval_minutes": scanner_interval,
        "pipeline_max_files_per_run": pipeline_max_files,
        "is_scan_running": is_scan_running,
        "scheduler_running": sched["scheduler_running"],
        "next_scan": sched["next_scan"],
        "last_scan": {
            "id": last_run["id"],
            "started_at": last_run.get("started_at"),
            "finished_at": last_run.get("finished_at"),
            "status": last_run.get("status"),
            "files_scanned": last_run.get("files_scanned", 0),
            "files_new": last_run.get("files_new", 0),
            "files_modified": last_run.get("files_modified", 0),
        } if last_run else None,
        "total_source_files": pending_row["cnt"] if pending_row else 0,
        "pending_conversion": pending_conversion["cnt"] if pending_conversion else 0,
        "last_auto_conversion": {
            "scan_run_id": last_auto_run["scan_run_id"],
            "mode": last_auto_run.get("mode"),
            "status": last_auto_run.get("status"),
            "files_discovered": last_auto_run.get("files_discovered", 0),
            "workers_chosen": last_auto_run.get("workers_chosen"),
            "batch_size_chosen": last_auto_run.get("batch_size_chosen"),
            "reason": last_auto_run.get("reason"),
        } if last_auto_run else None,
    }


@router.post("/pause")
async def pause_pipeline(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Pause the pipeline (skips scheduled scans until resumed)."""
    set_pipeline_paused(True)
    return {"paused": True, "message": "Pipeline paused. Scheduled scans will be skipped."}


@router.post("/resume")
async def resume_pipeline(
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Resume a paused pipeline."""
    set_pipeline_paused(False)
    return {"paused": False, "message": "Pipeline resumed. Scans will run on schedule."}


@router.post("/run-now")
async def run_pipeline_now(
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER)),
) -> dict:
    """Trigger an immediate scan+convert cycle (bypasses pause and business hours)."""

    async def _run():
        await run_lifecycle_scan(force=True)

    background_tasks.add_task(_run)
    log.info("pipeline.run_now_triggered")
    return {"message": "Pipeline cycle triggered. Scan will start shortly."}
