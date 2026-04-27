"""
Pipeline status and control API endpoints.

GET  /api/pipeline/status            -- Pipeline status (enabled, paused, last scan, next scan)
POST /api/pipeline/pause             -- Pause the pipeline (in-memory)
POST /api/pipeline/resume            -- Resume the pipeline
POST /api/pipeline/run-now           -- Trigger immediate scan+convert cycle
POST /api/pipeline/convert-selected  -- Convert a hand-picked subset of pending files (v0.31.6)
GET  /api/pipeline/stats             -- Pipeline funnel statistics
GET  /api/pipeline/files             -- Paginated file list by pipeline status category
"""

import asyncio
from datetime import datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

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

import time as _time

_stats_lock = asyncio.Lock()
_stats_cache: dict = {"result": None, "time": 0.0}
_CACHE_TTL = 20  # seconds


def invalidate_stats_cache():
    """Called from scan_coordinator on bulk job start/complete."""
    _stats_cache["time"] = 0.0


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


# ── POST /api/pipeline/convert-selected (v0.31.6) ──────────────────────────────
#
# Targeted conversion of a hand-picked subset of pending bulk_files rows.
# Replaces the "all-or-nothing" choice between letting the pipeline pick up
# everything (Force Transcribe) vs. doing nothing — operators can now check
# the boxes for the 3 files they want to test and trigger conversion just
# for those.
#
# Hard cap of 100 files per call. Above that, "Force Transcribe / Convert
# Pending" is the right tool. This endpoint is for SELECTIVE testing.

# Bounded so an operator can't accidentally trigger 100k file conversions.
_CONVERT_SELECTED_MAX = 100

# Statuses we can re-process. "pending" = never tried; "failed" / "adobe_failed"
# = retry. Other statuses (converted, skipped, …) refuse with 400 — operators
# should use re-convert on the file detail page for those.
_CONVERT_SELECTED_ELIGIBLE = {"pending", "failed", "adobe_failed"}


class ConvertSelectedRequest(BaseModel):
    file_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=_CONVERT_SELECTED_MAX,
        description="bulk_files.id values to schedule for conversion",
    )


async def _convert_one_pending_file(file_dict: dict, user_email: str) -> None:
    """Background task: convert a single pending bulk_files row.

    Mirrors the inner work of `BulkJob._process_convertible` but
    standalone — no full BulkJob lifecycle. Uses:
      - `core.storage_manager.get_output_path()` for the output root
        (Universal Storage Manager since v0.25.0)
      - `_map_output_path` to compute the per-file destination
      - `core.converter._convert_file_sync` for the heavy lifting
        (run in a worker thread)
      - `update_bulk_file` to record success / failure

    Best-effort: per-file exceptions are logged + recorded on the row,
    they never abort the surrounding asyncio.gather (callers run all
    selected files concurrently).
    """
    import hashlib
    import time
    from datetime import timezone

    from core.converter import _convert_file_sync
    from core.db.bulk import _map_output_path, update_bulk_file
    from core.db.connection import db_write_with_retry
    from core.storage_manager import get_output_path, is_write_allowed

    file_id = file_dict["id"]
    source_path = Path(file_dict["source_path"])
    job_id = file_dict.get("job_id") or "convert_selected"
    source_mtime = file_dict.get("source_mtime")

    # Resolve output root from Storage Manager (the same root the
    # Force Transcribe / pipeline scans use). If the operator hasn't
    # configured one yet, fall back to /mnt/output-repo (legacy default).
    output_root_str = get_output_path() or "/mnt/output-repo"
    output_root = Path(output_root_str)

    # The bulk_files row stores the source root that was active when
    # the file was scanned, but it's not on the row itself. Reconstruct
    # by walking up: the deepest ancestor of source_path that exists
    # under one of /mnt/source, /host/c, /host/d, /host/rw is the
    # source root for output mapping. Defensive fallback to source_path
    # parent if no match (the converter still works; the output just
    # lands directly under output_root rather than mirroring the tree).
    candidates = [Path(p) for p in (
        "/mnt/source", "/host/c", "/host/d", "/host/rw", "/host/root"
    )]
    source_root = source_path.parent  # fallback
    for c in candidates:
        try:
            source_path.relative_to(c)
            source_root = c
            break
        except ValueError:
            continue

    output_md = _map_output_path(source_path, source_root, output_root)

    if not is_write_allowed(str(output_md.parent)):
        log.warning(
            "convert_selected.write_denied",
            file_id=file_id,
            output_dir=str(output_md.parent),
            user=user_email,
        )
        await db_write_with_retry(lambda: update_bulk_file(
            file_id,
            status="failed",
            error_msg="write denied — output dir outside Storage Manager allow-list",
        ))
        return

    try:
        output_md.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("convert_selected.mkdir_failed",
                    file_id=file_id, error=str(exc))
        await db_write_with_retry(lambda: update_bulk_file(
            file_id, status="failed",
            error_msg=f"output dir mkdir failed: {exc}",
        ))
        return

    log.info(
        "convert_selected.start",
        file_id=file_id, source=str(source_path),
        output=str(output_md), user=user_email,
    )
    t_start = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            _convert_file_sync,
            source_path,
            "to_md",
            job_id,
            output_md.parent,
            {},  # no per-job overrides — uses global settings
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.error(
            "convert_selected.exception",
            file_id=file_id, source=str(source_path),
            duration_ms=duration_ms,
            error=f"{type(exc).__name__}: {exc}",
        )
        await db_write_with_retry(lambda: update_bulk_file(
            file_id, status="failed",
            error_msg=f"{type(exc).__name__}: {exc}",
        ))
        return

    duration_ms = int((time.perf_counter() - t_start) * 1000)

    if result.status == "success":
        content_hash = None
        actual = Path(result.output_path) if result.output_path else None
        if actual and actual.exists():
            try:
                content_hash = hashlib.sha256(actual.read_bytes()).hexdigest()
            except OSError:
                pass
        await db_write_with_retry(lambda: update_bulk_file(
            file_id,
            status="converted",
            output_path=result.output_path,
            stored_mtime=source_mtime,
            content_hash=content_hash,
            converted_at=datetime.now(timezone.utc).isoformat(),
            error_msg=None,
        ))
        log.info(
            "convert_selected.success",
            file_id=file_id, duration_ms=duration_ms,
            output=result.output_path,
        )
    else:
        await db_write_with_retry(lambda: update_bulk_file(
            file_id,
            status="failed",
            error_msg=getattr(result, "error", "conversion returned non-success"),
        ))
        log.warning(
            "convert_selected.failed",
            file_id=file_id, duration_ms=duration_ms,
            status=result.status,
            error=getattr(result, "error", None),
        )


async def _run_convert_selected_batch(files: list[dict], user_email: str) -> None:
    """Spawn per-file conversion tasks with a concurrency cap so a
    100-file selection doesn't melt the worker pool. Caps at 4
    concurrent conversions to match the default BULK_WORKER_COUNT."""
    sem = asyncio.Semaphore(4)

    async def _bound(f: dict) -> None:
        async with sem:
            await _convert_one_pending_file(f, user_email)

    await asyncio.gather(*(_bound(f) for f in files), return_exceptions=False)
    log.info(
        "convert_selected.batch_complete",
        count=len(files), user=user_email,
    )


@router.post("/convert-selected")
async def convert_selected_files(
    body: ConvertSelectedRequest,
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Schedule a hand-picked subset of pending bulk_files rows for
    immediate conversion (v0.31.6).

    Every selected row must be in `pending`, `failed`, or `adobe_failed`
    status. Already-converted rows are rejected with 400 — use the
    file-detail page's Re-convert action for those.

    Behavior:
      - Looks up the bulk_files row for each id (skips any not found,
        with the count of skipped surfaced in the response).
      - Spawns a background batch that runs the conversions in
        parallel (up to 4 concurrent — matches BULK_WORKER_COUNT
        default).
      - Returns immediately. Frontend polls /api/bulk/pending to see
        files transition out of pending.
    """
    selected: list[dict] = []
    not_found: list[str] = []
    ineligible: list[dict] = []

    for fid in body.file_ids:
        row = await db_fetch_one(
            "SELECT id, source_path, source_mtime, status, job_id, file_ext "
            "FROM bulk_files WHERE id = ?",
            (fid,),
        )
        if not row:
            not_found.append(fid)
            continue
        d = dict(row)
        if d["status"] not in _CONVERT_SELECTED_ELIGIBLE:
            ineligible.append({"id": fid, "status": d["status"]})
            continue
        selected.append(d)

    if not selected:
        raise HTTPException(
            status_code=400,
            detail={
                "msg": "No eligible files in the selection.",
                "not_found": not_found,
                "ineligible": ineligible,
                "eligible_statuses": sorted(_CONVERT_SELECTED_ELIGIBLE),
            },
        )

    background_tasks.add_task(
        _run_convert_selected_batch, selected, user.email,
    )

    log.info(
        "convert_selected.scheduled",
        count=len(selected),
        not_found=len(not_found),
        ineligible=len(ineligible),
        user=user.email,
    )
    return {
        "queued": len(selected),
        "not_found": not_found,
        "ineligible": ineligible,
        "message": (
            f"Scheduled {len(selected)} file"
            f"{'' if len(selected) == 1 else 's'} for conversion. "
            "Status will update as each completes."
        ),
    }


@router.get("/coordinator")
async def coordinator_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return scan coordinator state for debugging."""
    return get_coordinator_status()


@router.get("/stats")
async def pipeline_stats(
    include_trashed: bool = Query(
        False,
        description="If true, include trashed/marked-for-deletion files "
                    "in the failed/unrecognized counters. Default false — "
                    "matches the file-list view's default.",
    ),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Pipeline funnel statistics across all processing stages.

    By default (`include_trashed=False`) the failed and unrecognized
    counters apply a `source_files.lifecycle_status = 'active'` filter
    so they reflect what's actually present on disk. Operators were
    seeing the failed counter inflated by 100K+ rows for files the
    lifecycle scanner had already moved through marked_for_deletion ->
    in_trash. The `scanned` and `pending_conversion` counters already
    filtered on `lifecycle_status = 'active'`; this commit makes the
    failed/unrecognized pair consistent."""

    # The default (active-only) view uses the existing flat cache.
    # The trashed-included view bypasses cache — it's rare (operator
    # toggles it on demand) so the freshness win outweighs caching.
    now = _time.time()
    if not include_trashed and _stats_cache["result"] and now - _stats_cache["time"] < _CACHE_TTL:
        return _stats_cache["result"]

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

    # Build the JOIN-on-source_files lifecycle clause once; reuse for
    # all three lifecycle-gated counters (pending_conversion, failed,
    # unrecognized). When include_trashed=False we filter to active +
    # NULL (NULL covers orphaned bulk_files rows from older data sets
    # where source_file_id wasn't backfilled).
    if include_trashed:
        scanned_sql = "SELECT COUNT(*) AS cnt FROM source_files"
        sf_active_clause = ""
        bf_lifecycle_join = ""
        bf_lifecycle_clause = ""
    else:
        scanned_sql = "SELECT COUNT(*) AS cnt FROM source_files WHERE lifecycle_status = 'active'"
        sf_active_clause = "AND sf.lifecycle_status = 'active'"
        bf_lifecycle_join = "LEFT JOIN source_files sf ON bf.source_file_id = sf.id"
        bf_lifecycle_clause = "AND (sf.lifecycle_status = 'active' OR sf.lifecycle_status IS NULL)"

    # See pipeline_status() above for why pending_conversion uses a NOT EXISTS
    # join against bulk_files instead of `COUNT(*) WHERE status='pending'`.
    scanned, pending_conv, failed, unrecognized, analysis, search_count = await asyncio.gather(
        _safe(_count(scanned_sql)),
        _safe(_count(
            f"""SELECT COUNT(*) AS cnt FROM source_files sf
               WHERE 1=1 {sf_active_clause}
                 AND NOT EXISTS (
                     SELECT 1 FROM bulk_files bf
                     WHERE bf.source_path = sf.source_path
                       AND bf.status = 'converted'
                 )"""
        )),
        _safe(_count(
            f"""SELECT COUNT(DISTINCT bf.source_path) AS cnt FROM bulk_files bf
               {bf_lifecycle_join}
               WHERE bf.status = 'failed'
                 {bf_lifecycle_clause}
                 AND NOT EXISTS (
                     SELECT 1 FROM bulk_files bf2
                     WHERE bf2.source_path = bf.source_path
                       AND bf2.status = 'converted'
                 )"""
        )),
        _safe(_count(
            f"""SELECT COUNT(DISTINCT bf.source_path) AS cnt FROM bulk_files bf
               {bf_lifecycle_join}
               WHERE bf.status = 'unrecognized'
                 {bf_lifecycle_clause}
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

    result = {
        "scanned": scanned or 0,
        "pending_conversion": pending_conv or 0,
        "failed": failed or 0,
        "unrecognized": unrecognized or 0,
        "pending_analysis": analysis.get("pending", 0),
        "batched_for_analysis": analysis.get("batched", 0),
        "analysis_failed": analysis.get("failed", 0),
        "in_search_index": search_count,
    }
    # Only cache the active-only view; see comment at the top of the
    # function. Trashed-included results are computed fresh each call.
    if not include_trashed:
        _stats_cache["result"] = result
        _stats_cache["time"] = _time.time()
    return result


@router.get("/files")
async def pipeline_files(
    status: str = Query(..., description="Comma-separated: scanned,pending,failed,unrecognized,pending_analysis,batched,analysis_failed,indexed"),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    sort: str = Query("source_path"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    include_trashed: bool = Query(
        False,
        description="If true, include rows whose linked source_files row "
                    "is in marked_for_deletion / in_trash / purged. "
                    "Default false — most operators want only files that "
                    "actually exist on disk.",
    ),
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
            include_trashed=include_trashed,
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
