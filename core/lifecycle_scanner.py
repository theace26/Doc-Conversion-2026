"""
Lifecycle scanner — walks the source share, detects new/modified/moved/deleted
files, and updates lifecycle state in bulk_files.

Called by the scheduler. One scan cycle:
1. Walk source share
2. Detect new, modified, moved, deleted files
3. Update DB state and create version records
4. Record scan run with counters
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog

from core.stop_controller import should_stop
from core.bulk_scanner import ALL_SUPPORTED, CONVERTIBLE_EXTENSIONS, ADOBE_EXTENSIONS
from core.database import (
    create_scan_run,
    create_version_snapshot,
    db_fetch_all,
    get_bulk_file_by_path,
    get_next_version_number,
    get_scan_run,
    update_bulk_file,
    update_scan_run,
    upsert_bulk_file,
)
from core.lifecycle_manager import (
    mark_file_for_deletion,
    record_content_change,
    record_file_move,
    restore_file,
)

log = structlog.get_logger(__name__)

# ── In-memory scan state (resets on container restart) ────────────────────────
_scan_state: dict = {
    "running": False,
    "run_id": None,
    "started_at": None,
    "scanned": 0,
    "total": 0,
    "pct": None,
    "current_file": None,
    "eta_seconds": None,
    "last_scan_at": None,
    "last_scan_run_id": None,
}


def get_scan_state() -> dict:
    """Return a snapshot of the current lifecycle scan state."""
    return dict(_scan_state)


def compute_file_hash(file_path: Path) -> str | None:
    """SHA-256 of file contents. Returns None on read error."""
    try:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


async def run_lifecycle_scan(
    source_path: str | None = None,
    job_id: str | None = None,
) -> str:
    """Run a full lifecycle scan. Returns scan_run_id."""
    scan_run_id = uuid.uuid4().hex

    # Resolve source path
    if not source_path:
        source_path = os.getenv("BULK_SOURCE_PATH", "")
    if not source_path:
        # Try to get from locations
        try:
            from core.database import list_locations
            locs = await list_locations(type_filter="source")
            if locs:
                source_path = locs[0]["path"]
        except Exception:
            pass

    if not source_path:
        log.warning("lifecycle_scan.no_source_path")
        return scan_run_id

    source_root = Path(source_path)
    if not source_root.exists() or not source_root.is_dir():
        await create_scan_run(scan_run_id)
        await update_scan_run(scan_run_id, {
            "status": "failed",
            "finished_at": _now_iso(),
            "error_log": json.dumps([{"path": str(source_root), "error": "Source share not accessible"}]),
        })
        log.error("lifecycle_scan.source_unavailable", path=str(source_root))
        return scan_run_id

    # Verify the mount is actually populated (empty mountpoint = SMB not connected)
    try:
        with os.scandir(source_root) as it:
            next(it)
    except (StopIteration, PermissionError, OSError):
        await create_scan_run(scan_run_id)
        await update_scan_run(scan_run_id, {
            "status": "failed",
            "finished_at": _now_iso(),
            "error_log": json.dumps([{"path": str(source_root), "error": "Source mount is empty — not mounted?"}]),
        })
        log.error("lifecycle_scan.mount_not_ready", path=str(source_root),
                  msg="Source path is empty or not mounted. Skipping scan cycle.")
        return scan_run_id

    await create_scan_run(scan_run_id)

    counters = {
        "files_scanned": 0,
        "files_new": 0,
        "files_modified": 0,
        "files_moved": 0,
        "files_deleted": 0,
        "files_restored": 0,
        "errors": 0,
    }
    error_entries: list[dict] = []
    seen_paths: set[str] = set()

    # Update scan state for progress tracking
    _scan_state["running"] = True
    _scan_state["run_id"] = scan_run_id
    _scan_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _scan_state["scanned"] = 0
    _scan_state["total"] = 0
    _scan_state["pct"] = None
    _scan_state["current_file"] = None
    _scan_state["eta_seconds"] = None

    # Pre-count files for progress estimate
    import asyncio
    try:
        total_estimate = await asyncio.wait_for(
            asyncio.to_thread(_count_files_sync, source_root),
            timeout=10.0,
        )
        _scan_state["total"] = total_estimate
    except (asyncio.TimeoutError, Exception):
        _scan_state["total"] = 0
    _started_at_dt = datetime.now(timezone.utc)

    # Record activity event for scan start
    try:
        from core.metrics_collector import record_activity_event
        await record_activity_event("lifecycle_scan_start", "Lifecycle scan started")
    except Exception:
        pass

    # Resolve the job_id to use for upserts — use most recent job if not specified
    if not job_id:
        from core.database import list_bulk_jobs, create_bulk_job
        jobs = await list_bulk_jobs(limit=1)
        if jobs:
            job_id = jobs[0]["id"]
        else:
            # No bulk jobs exist yet — create a synthetic lifecycle job so FK is satisfied
            job_id = await create_bulk_job(
                source_path=str(source_root),
                output_path=os.getenv("BULK_OUTPUT_PATH", "/mnt/output-repo"),
            )
            log.info("lifecycle_scan.created_synthetic_job", job_id=job_id)

    # ── Walk source share ────────────────────────────────────────────────────
    try:
        for dirpath, dirnames, filenames in os.walk(source_root):
            # Check global stop
            if should_stop():
                log.warning("lifecycle_scan_stopped", scan_run_id=scan_run_id)
                _scan_state["running"] = False
                _scan_state["current_file"] = None
                break

            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "_markflow"]

            for filename in filenames:
                file_path = Path(dirpath) / filename
                ext = file_path.suffix.lower()
                path_str = str(file_path)
                seen_paths.add(path_str)
                counters["files_scanned"] += 1

                try:
                    stat = file_path.stat()
                    mtime = stat.st_mtime
                    size = stat.st_size
                except OSError as exc:
                    counters["errors"] += 1
                    error_entries.append({"path": path_str, "error": str(exc)})
                    continue

                # Only track files that the bulk pipeline would process
                if ext not in ALL_SUPPORTED and ext not in CONVERTIBLE_EXTENSIONS and ext not in ADOBE_EXTENSIONS:
                    # Check if this was previously tracked (e.g. unrecognized)
                    existing = await get_bulk_file_by_path(path_str)
                    if existing and existing.get("lifecycle_status") == "marked_for_deletion":
                        # Reappeared during grace period
                        await restore_file(existing["id"], scan_run_id)
                        counters["files_restored"] += 1
                    continue

                try:
                    await _process_file(
                        file_path, path_str, ext, mtime, size,
                        job_id, scan_run_id, counters,
                    )
                except Exception as exc:
                    counters["errors"] += 1
                    error_entries.append({"path": path_str, "error": str(exc)})
                    log.error("lifecycle_scan.file_error", path=path_str, error=str(exc))

                # Update scan state every 25 files
                if counters["files_scanned"] % 25 == 0:
                    _scan_state["scanned"] = counters["files_scanned"]
                    try:
                        _scan_state["current_file"] = str(file_path.relative_to(source_root))
                    except ValueError:
                        _scan_state["current_file"] = filename
                    total_est = _scan_state["total"]
                    if total_est > 0:
                        _scan_state["pct"] = min(99, int(counters["files_scanned"] / total_est * 100))
                    else:
                        _scan_state["pct"] = None
                    elapsed = (datetime.now(timezone.utc) - _started_at_dt).total_seconds()
                    if elapsed > 5 and counters["files_scanned"] > 0:
                        rate = counters["files_scanned"] / elapsed
                        remaining = total_est - counters["files_scanned"] if total_est else 0
                        _scan_state["eta_seconds"] = int(remaining / rate) if rate > 0 and remaining > 0 else None
                    else:
                        _scan_state["eta_seconds"] = None
    except Exception as exc:
        await update_scan_run(scan_run_id, {
            "status": "failed",
            "finished_at": _now_iso(),
            "errors": counters["errors"] + 1,
            "error_log": json.dumps(error_entries + [{"path": str(source_root), "error": str(exc)}]),
        })
        _scan_state["running"] = False
        _scan_state["current_file"] = None
        _scan_state["eta_seconds"] = None
        _scan_state["last_scan_at"] = _now_iso()
        _scan_state["last_scan_run_id"] = scan_run_id
        log.error("lifecycle_scan.walk_failed", error=str(exc))
        return scan_run_id

    # ── Detect deletions (files not seen but still active) ────────────────────
    try:
        active_files = await db_fetch_all(
            """SELECT * FROM bulk_files
               WHERE lifecycle_status='active'
               AND job_id=?""",
            (job_id,),
        )

        # Build set of newly seen paths that don't have DB records yet
        # for move detection via content hash
        disappeared: list[dict] = []
        for f in active_files:
            if f["source_path"] not in seen_paths:
                disappeared.append(f)

        # Move detection: check if disappeared file's content_hash matches a new file
        for f in disappeared:
            content_hash = f.get("content_hash")
            if content_hash:
                # Look for a newly created file with the same hash
                match = await _find_hash_match_in_seen(content_hash, seen_paths, job_id)
                if match:
                    await record_file_move(f["id"], f["source_path"], match, scan_run_id)
                    counters["files_moved"] += 1
                    continue

            await mark_file_for_deletion(f["id"], scan_run_id)
            counters["files_deleted"] += 1
    except Exception as exc:
        counters["errors"] += 1
        error_entries.append({"path": "deletion_detection", "error": str(exc)})
        log.error("lifecycle_scan.deletion_detection_error", error=str(exc))

    # ── Finalize scan run ────────────────────────────────────────────────────
    await update_scan_run(scan_run_id, {
        "status": "complete",
        "finished_at": _now_iso(),
        "files_scanned": counters["files_scanned"],
        "files_new": counters["files_new"],
        "files_modified": counters["files_modified"],
        "files_moved": counters["files_moved"],
        "files_deleted": counters["files_deleted"],
        "files_restored": counters["files_restored"],
        "errors": counters["errors"],
        "error_log": json.dumps(error_entries) if error_entries else None,
    })

    # Update scan state to idle
    _scan_state["running"] = False
    _scan_state["scanned"] = counters["files_scanned"]
    _scan_state["pct"] = None
    _scan_state["current_file"] = None
    _scan_state["eta_seconds"] = None
    _scan_state["last_scan_at"] = _now_iso()
    _scan_state["last_scan_run_id"] = scan_run_id

    elapsed_s = round((datetime.now(timezone.utc) - _started_at_dt).total_seconds(), 1)
    log.info(
        "lifecycle_scan.complete",
        scan_run_id=scan_run_id,
        **counters,
    )

    # Record activity event for scan end
    try:
        from core.metrics_collector import record_activity_event
        await record_activity_event(
            "lifecycle_scan_end",
            f"Lifecycle scan: {counters['files_scanned']} files, {counters['files_new']} new, {counters['files_modified']} modified, {counters['files_deleted']} deleted",
            {
                "scanned": counters["files_scanned"],
                "new": counters["files_new"],
                "modified": counters["files_modified"],
                "deleted": counters["files_deleted"],
                "errors": counters["errors"],
                "duration": elapsed_s,
            },
            duration_seconds=elapsed_s,
        )
    except Exception:
        pass

    # ── Auto-conversion trigger ──────────────────────────────────────────────
    try:
        from core.auto_converter import get_auto_conversion_engine

        engine = get_auto_conversion_engine()
        decision = await engine.on_scan_complete(
            scan_run_id=scan_run_id,
            new_files=counters["files_new"],
            modified_files=counters["files_modified"],
        )

        if decision.should_convert:
            await _execute_auto_conversion(
                decision, scan_run_id, source_root, job_id
            )
    except Exception as exc:
        log.error("lifecycle_scan.auto_convert_trigger_failed", error=str(exc))

    return scan_run_id


async def _process_file(
    file_path: Path,
    path_str: str,
    ext: str,
    mtime: float,
    size: int,
    job_id: str,
    scan_run_id: str,
    counters: dict,
) -> None:
    """Process a single file discovered during scan."""
    existing = await get_bulk_file_by_path(path_str)

    if existing is None:
        # New file — upsert and create initial version
        file_id = await upsert_bulk_file(
            job_id=job_id,
            source_path=path_str,
            file_ext=ext,
            file_size_bytes=size,
            source_mtime=mtime,
        )

        # Compute and store content hash
        content_hash = compute_file_hash(file_path)
        if content_hash:
            await update_bulk_file(file_id, content_hash=content_hash)

        # Create initial version record
        version_num = await get_next_version_number(file_id)
        await create_version_snapshot(file_id, {
            "version_number": version_num,
            "change_type": "initial",
            "path_at_version": path_str,
            "mtime_at_version": mtime,
            "size_at_version": size,
            "content_hash": content_hash,
            "scan_run_id": scan_run_id,
        })
        counters["files_new"] += 1
        return

    # File exists in DB
    file_id = existing["id"]

    # Check if marked_for_deletion — restore if grace period hasn't expired
    if existing.get("lifecycle_status") == "marked_for_deletion":
        await restore_file(file_id, scan_run_id)
        counters["files_restored"] += 1
        return

    # Skip files that aren't active
    if existing.get("lifecycle_status") not in ("active", None):
        return

    # Check for modification (mtime or size changed)
    stored_mtime = existing.get("source_mtime") or existing.get("stored_mtime")
    stored_size = existing.get("file_size_bytes")

    if stored_mtime != mtime or stored_size != size:
        # Compute new content hash
        content_hash = compute_file_hash(file_path)

        # Get the old .md path before we reset status
        old_md_path = Path(existing["output_path"]) if existing.get("output_path") else None

        # Reset to pending so bulk worker re-converts on next run
        await update_bulk_file(
            file_id,
            status="pending",
            source_mtime=mtime,
            file_size_bytes=size,
            content_hash=content_hash,
        )

        # Record content change (diff will be computed if old .md exists)
        await record_content_change(file_id, old_md_path, old_md_path, scan_run_id)
        counters["files_modified"] += 1


async def _find_hash_match_in_seen(
    content_hash: str, seen_paths: set[str], job_id: str
) -> str | None:
    """Check if any newly-seen file matches the content hash."""
    # Look for files recently added with matching hash
    rows = await db_fetch_all(
        "SELECT source_path FROM bulk_files WHERE content_hash=? AND job_id=? AND lifecycle_status='active'",
        (content_hash, job_id),
    )
    for row in rows:
        if row["source_path"] in seen_paths:
            return row["source_path"]
    return None


def _count_files_sync(source_root: Path) -> int:
    """Count all files in source tree (synchronous, for use in a thread)."""
    count = 0
    for _, dirnames, filenames in os.walk(source_root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "_markflow"]
        count += len(filenames)
    return count


async def _execute_auto_conversion(
    decision,
    scan_run_id: str,
    source_root: Path,
    job_id: str,
) -> None:
    """Create and start a bulk job based on the auto-conversion decision.

    Uses the existing BulkJob infrastructure — auto-conversion is just
    a programmatically-created bulk job with specific worker/batch settings.
    """
    import asyncio as _asyncio

    from core.bulk_worker import BulkJob
    from core.database import create_bulk_job, get_db_path

    try:
        output_path = os.getenv("BULK_OUTPUT_PATH", "/mnt/output-repo")

        # Create a bulk job marked as auto-conversion
        import aiosqlite
        new_job_id = await create_bulk_job(
            source_path=str(source_root),
            output_path=output_path,
            worker_count=decision.workers,
        )

        # Mark it as auto-triggered
        from core.database import get_db
        async with get_db() as conn:
            await conn.execute(
                "UPDATE bulk_jobs SET auto_triggered = 1 WHERE id = ?",
                (new_job_id,),
            )
            await conn.commit()

        log.info(
            "auto_convert_job_created",
            job_id=new_job_id,
            mode=decision.mode,
            workers=decision.workers,
            batch_size=decision.batch_size,
            scan_run_id=scan_run_id,
        )

        # Update the auto_conversion_runs record with the bulk_job_id
        try:
            async with get_db() as conn:
                await conn.execute(
                    """
                    UPDATE auto_conversion_runs
                    SET bulk_job_id = ?, status = 'running'
                    WHERE scan_run_id = ? AND status = 'pending'
                    """,
                    (new_job_id, scan_run_id),
                )
                await conn.commit()
        except Exception:
            pass  # Fire-and-forget

        job = BulkJob(
            job_id=new_job_id,
            source_path=str(source_root),
            output_path=output_path,
            worker_count=decision.workers,
            max_files=decision.batch_size if decision.batch_size > 0 else None,
        )

        if decision.mode == "immediate":
            # Block scanner until batch completes
            await job.run()
        elif decision.mode in ("queued", "scheduled"):
            # Background task — scanner moves on
            _asyncio.create_task(job.run())

    except Exception as exc:
        log.error(
            "auto_convert_execution_failed",
            error=str(exc),
            scan_run_id=scan_run_id,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
