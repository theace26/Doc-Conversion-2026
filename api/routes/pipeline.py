"""
Pipeline status and control API endpoints.

GET  /api/pipeline/status   -- Pipeline status (enabled, paused, last scan, next scan)
POST /api/pipeline/pause    -- Pause the pipeline (in-memory)
POST /api/pipeline/resume   -- Resume the pipeline
POST /api/pipeline/run-now  -- Trigger immediate scan+convert cycle
GET  /api/pipeline/stats    -- Pipeline funnel statistics
GET  /api/pipeline/files    -- Paginated file list by pipeline status category
"""

import asyncio
from datetime import datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Query

from core.auth import AuthenticatedUser, UserRole, require_role
from core.database import (
    db_fetch_all,
    db_fetch_one,
    get_latest_scan_run,
    get_preference,
)
from core.db.analysis import get_analysis_stats
from core.search_client import get_meili_client
from core.scan_coordinator import (
    get_coordinator_status,
    is_any_bulk_active,
    is_run_now_cancelled,
    notify_run_now_started,
    register_run_now_scan,
    unregister_run_now_scan,
    wait_if_run_now_paused,
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

    # Pending files count
    pending_row = await db_fetch_one(
        "SELECT COUNT(*) as cnt FROM source_files WHERE lifecycle_status = 'active'"
    )
    # True pending conversion count: distinct source files that are still
    # active in source_files AND have NEVER successfully converted in ANY job.
    # The naive `COUNT(*) FROM bulk_files WHERE status='pending'` over-counts
    # by ~2-3x because each new scan job inserts its own pending rows for
    # files that were already converted in older jobs (cross-job duplication).
    # Fixed in v0.22.9 — see docs/gotchas.md > Database & aiosqlite.
    pending_conversion = await db_fetch_one(
        """SELECT COUNT(*) AS cnt FROM source_files sf
           WHERE sf.lifecycle_status = 'active'
             AND NOT EXISTS (
                 SELECT 1 FROM bulk_files bf
                 WHERE bf.source_path = sf.source_path
                   AND bf.status = 'converted'
             )"""
    )

    # Last auto-conversion run
    last_auto_run = await db_fetch_one(
        "SELECT * FROM auto_conversion_runs ORDER BY started_at DESC LIMIT 1"
    )

    # Disabled-state info (for alerting UI)
    disabled_info = None
    if pipeline_enabled == "false":
        disabled_at_str = await get_preference("pipeline_disabled_at") or ""
        auto_reset_days = int(await get_preference("pipeline_auto_reset_days") or "3")
        if disabled_at_str:
            try:
                disabled_at = datetime.fromisoformat(disabled_at_str)
                elapsed_hours = (datetime.now() - disabled_at).total_seconds() / 3600
                remaining_hours = max(0, auto_reset_days * 24 - elapsed_hours)
                disabled_info = {
                    "disabled_at": disabled_at_str,
                    "elapsed_hours": round(elapsed_hours, 1),
                    "auto_reset_in_hours": round(remaining_hours, 1),
                    "auto_reset_days": auto_reset_days,
                    "message": (
                        f"Pipeline disabled {int(elapsed_hours)}h ago. "
                        f"Will auto-reset in {int(remaining_hours)}h. "
                        "No scanning or conversion is running."
                    ),
                }
            except ValueError:
                disabled_info = {
                    "disabled_at": None,
                    "message": "Pipeline is disabled. Auto-reset timer not started.",
                }
        else:
            disabled_info = {
                "disabled_at": None,
                "message": "Pipeline is disabled. Watchdog will start tracking shortly.",
            }

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
        "disabled_info": disabled_info,
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
    """Trigger an immediate scan+convert cycle (bypasses pause and business hours).

    Run-now has higher priority than lifecycle scans (cancels them) but lower
    priority than bulk jobs. If a bulk job is active, run-now will pause and
    automatically resume once all bulk jobs complete.
    """

    async def _run():
        register_run_now_scan()
        try:
            # Signal coordinator — cancels any active lifecycle scan
            notify_run_now_started()

            # If a bulk job is active, wait for it to finish before scanning
            if is_any_bulk_active():
                log.info("pipeline.run_now_waiting_for_bulk")
                await wait_if_run_now_paused()
                if is_run_now_cancelled():
                    log.info("pipeline.run_now_cancelled_while_waiting")
                    return

            await run_lifecycle_scan(force=True)
        finally:
            unregister_run_now_scan()

    background_tasks.add_task(_run)
    log.info("pipeline.run_now_triggered")

    if is_any_bulk_active():
        return {
            "message": "Run-now queued. A bulk job is active — scan will start automatically when it finishes.",
            "paused_for_bulk": True,
        }
    return {"message": "Pipeline cycle triggered. Scan will start shortly."}


@router.get("/coordinator")
async def coordinator_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return scan coordinator state for debugging."""
    return get_coordinator_status()


@router.get("/stats")
async def pipeline_stats(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Pipeline funnel statistics across all processing stages."""

    async def _safe(coro):
        try:
            return await coro
        except Exception:
            return None

    async def _count(query: str) -> int:
        row = await db_fetch_one(query)
        return row["cnt"] if row else 0

    async def _count_search_index() -> int | None:
        client = get_meili_client()
        if not client:
            return None
        total = 0
        for index in ("documents", "adobe-files", "transcripts"):
            stats = await client.get_index_stats(index)
            total += stats.get("numberOfDocuments", 0)
        return total

    # See pipeline_status() above for why pending_conversion uses a NOT EXISTS
    # join against bulk_files instead of `COUNT(*) WHERE status='pending'`.
    scanned, pending_conv, failed, unrecognized, analysis, search_count = await asyncio.gather(
        _safe(_count("SELECT COUNT(*) AS cnt FROM source_files WHERE lifecycle_status = 'active'")),
        _safe(_count(
            """SELECT COUNT(*) AS cnt FROM source_files sf
               WHERE sf.lifecycle_status = 'active'
                 AND NOT EXISTS (
                     SELECT 1 FROM bulk_files bf
                     WHERE bf.source_path = sf.source_path
                       AND bf.status = 'converted'
                 )"""
        )),
        _safe(_count(
            """SELECT COUNT(DISTINCT bf.source_path) AS cnt FROM bulk_files bf
               WHERE bf.status = 'failed'
                 AND NOT EXISTS (
                     SELECT 1 FROM bulk_files bf2
                     WHERE bf2.source_path = bf.source_path
                       AND bf2.status = 'converted'
                 )"""
        )),
        _safe(_count(
            """SELECT COUNT(DISTINCT bf.source_path) AS cnt FROM bulk_files bf
               WHERE bf.status = 'unrecognized'
                 AND NOT EXISTS (
                     SELECT 1 FROM bulk_files bf2
                     WHERE bf2.source_path = bf.source_path
                       AND bf2.status = 'converted'
                 )"""
        )),
        _safe(get_analysis_stats()),
        _safe(_count_search_index()),
    )

    analysis = analysis or {}

    return {
        "scanned": scanned or 0,
        "pending_conversion": pending_conv or 0,
        "failed": failed or 0,
        "unrecognized": unrecognized or 0,
        "pending_analysis": analysis.get("pending", 0),
        "batched_for_analysis": analysis.get("batched", 0),
        "analysis_failed": analysis.get("failed", 0),
        "in_search_index": search_count,
    }


@router.get("/files")
async def pipeline_files(
    status: str = Query(..., description="Comma-separated: scanned,pending,failed,unrecognized,pending_analysis,batched,analysis_failed,indexed"),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    sort: str = Query("source_path"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Paginated file list filtered by one or more pipeline status categories."""
    from core.db.bulk import get_pipeline_files

    statuses = [s.strip() for s in status.split(",") if s.strip()]
    valid = {"scanned", "pending", "failed", "unrecognized",
             "pending_analysis", "batched", "analysis_failed", "indexed"}
    statuses = [s for s in statuses if s in valid]

    if not statuses:
        return {"files": [], "total": 0, "page": 1, "per_page": per_page, "pages": 1}

    has_indexed = "indexed" in statuses
    db_statuses = [s for s in statuses if s != "indexed"]

    offset = (max(1, page) - 1) * per_page
    files: list[dict] = []
    total = 0

    if db_statuses:
        rows, db_total = await get_pipeline_files(
            statuses=db_statuses, search=search,
            limit=per_page, offset=offset,
            sort=sort, sort_dir=sort_dir,
        )
        files.extend(rows)
        total += db_total

    if has_indexed:
        try:
            indexed_files, indexed_total = await _browse_search_index(
                search=search, limit=per_page, offset=offset,
            )
            files.extend(indexed_files)
            total += indexed_total
        except Exception:
            pass

    return {
        "files": files,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


async def _browse_search_index(
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Browse Meilisearch indexes and return files in pipeline-files format."""
    client = get_meili_client()
    if not client:
        return [], 0

    files = []
    total = 0

    for index_name in ("documents", "adobe-files", "transcripts"):
        try:
            if search:
                result = await client.search(index_name, search, limit=limit, offset=offset)
            else:
                result = await client.get_documents(index_name, limit=limit, offset=offset)

            hits = result.get("hits") or result.get("results") or []
            total += result.get("estimatedTotalHits") or result.get("total") or len(hits)

            for doc in hits:
                files.append({
                    "id": doc.get("id", ""),
                    "source_path": doc.get("source_path") or doc.get("source_filename", ""),
                    "file_ext": doc.get("source_format", ""),
                    "file_size_bytes": doc.get("file_size_bytes"),
                    "source_mtime": None,
                    "status": "indexed",
                    "error_msg": None,
                    "skip_reason": None,
                    "converted_at": doc.get("converted_at"),
                    "job_id": None,
                    "content_hash": doc.get("content_hash"),
                })
        except Exception:
            continue

    return files, total
