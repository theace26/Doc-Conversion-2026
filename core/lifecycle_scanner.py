"""
Lifecycle scanner — walks the source share, detects new/modified/moved/deleted
files, and updates lifecycle state in source_files and bulk_files.

Called by the scheduler. One scan cycle:
1. Walk source share
2. Detect new, modified, moved, deleted files
3. Update DB state and create version records
4. Record scan run with counters

Deletion and move detection queries source_files (deduplicated) to avoid
overcounting from duplicate bulk_files rows across scan jobs.
"""

import asyncio
import hashlib
import json
import os
import queue
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import structlog

from core.stop_controller import should_stop
from core.db.analysis import enqueue_for_analysis as enqueue_image_for_analysis, _IMAGE_EXTENSIONS as _LIFECYCLE_IMAGE_EXTS
from core.scan_coordinator import (
    is_lifecycle_cancelled,
    register_lifecycle_scan,
    unregister_lifecycle_scan,
)
from core.storage_probe import ErrorRateMonitor, ScanThrottler, probe_storage_latency
from core.bulk_scanner import ALL_SUPPORTED, CONVERTIBLE_EXTENSIONS, ADOBE_EXTENSIONS, verify_source_mount
from core.metrics_collector import record_activity_event
from core.database import (
    create_scan_run,
    create_version_snapshot,
    db_fetch_all,
    get_source_file_by_path,
    get_next_version_number,
    get_scan_run,
    now_iso,
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


def _should_cancel() -> bool:
    """Combined check: global stop OR coordinator cancel."""
    return should_stop() or is_lifecycle_cancelled()


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

    # Resolve source paths — collect all configured source locations
    source_roots: list[Path] = []
    if source_path:
        source_roots = [Path(source_path)]
    else:
        env_path = os.getenv("BULK_SOURCE_PATH", "")
        if env_path:
            source_roots = [Path(env_path)]
        else:
            try:
                from core.database import list_locations
                locs = await list_locations(type_filter="source")
                source_roots = [Path(loc["path"]) for loc in locs]
            except Exception:
                pass

    if not source_roots:
        log.warning("lifecycle_scan.no_source_path")
        return scan_run_id

    # Validate each root — keep only accessible, mounted ones
    valid_roots: list[Path] = []
    init_errors: list[dict] = []
    for root in source_roots:
        if not root.exists() or not root.is_dir():
            init_errors.append({"path": str(root), "error": "Source share not accessible"})
            log.error("lifecycle_scan.source_unavailable", path=str(root))
        elif not verify_source_mount(str(root)):
            init_errors.append({"path": str(root), "error": "Source mount is empty — not mounted?"})
            log.error("lifecycle_scan.mount_not_ready", path=str(root))
        else:
            valid_roots.append(root)

    if not valid_roots:
        await create_scan_run(scan_run_id)
        await update_scan_run(scan_run_id, {
            "status": "failed",
            "finished_at": now_iso(),
            "error_log": json.dumps(init_errors),
        })
        return scan_run_id

    if len(valid_roots) > 1:
        log.info("lifecycle_scan.multi_source", count=len(valid_roots),
                 paths=[str(r) for r in valid_roots])

    await create_scan_run(scan_run_id)
    register_lifecycle_scan()

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

    # Pre-count files across all source roots for progress estimate
    try:
        count_tasks = [asyncio.to_thread(_count_files_sync, r) for r in valid_roots]
        counts = await asyncio.wait_for(asyncio.gather(*count_tasks), timeout=30.0)
        total_estimate = sum(counts)
        _scan_state["total"] = total_estimate
    except (asyncio.TimeoutError, Exception):
        _scan_state["total"] = 0
    _started_at_dt = datetime.now(timezone.utc)

    # ── Load exclusion paths (prefix-match) ────────────────────────────
    from core.database import get_exclusion_paths, get_preference as _get_pref
    exclusion_paths = await get_exclusion_paths()
    if exclusion_paths:
        log.info("lifecycle_scan.exclusions_loaded", count=len(exclusion_paths), paths=exclusion_paths)

    # ── Incremental scan decision ──────────────────────────────────
    from core.db.bulk import (
        load_dir_mtimes, save_dir_mtimes_batch,
        get_incremental_scan_count, increment_scan_count, reset_scan_count,
    )
    incremental_enabled = (await _get_pref("scan_incremental_enabled") or "true") == "true"
    full_walk_interval = int(await _get_pref("scan_full_walk_interval") or "5")
    scan_count = await get_incremental_scan_count()
    bh_start = int((await _get_pref("scanner_business_hours_start") or "06:00").split(":")[0])
    bh_end = int((await _get_pref("scanner_business_hours_end") or "22:00").split(":")[0])
    current_hour = datetime.now().hour
    outside_business_hours = current_hour < bh_start or current_hour >= bh_end
    force_full = (scan_count >= full_walk_interval) or outside_business_hours

    if incremental_enabled and not force_full:
        dir_mtime_cache = await load_dir_mtimes()
        incremental_mode = True
        log.info("lifecycle_scan.incremental_mode",
                 cached_dirs=len(dir_mtime_cache), scans_since_full=scan_count)
    else:
        dir_mtime_cache = {}
        incremental_mode = False
        reason = "outside_business_hours" if outside_business_hours else f"interval_reached ({scan_count}/{full_walk_interval})"
        log.info("lifecycle_scan.full_walk_mode", reason=reason)

    current_dir_mtimes: dict[str, float] = {}

    # Record activity event for scan start
    try:
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
                source_path=str(valid_roots[0]),
                output_path=os.getenv("BULK_OUTPUT_PATH", "/mnt/output-repo"),
            )
            log.info("lifecycle_scan.created_synthetic_job", job_id=job_id)

    # ── Walk each source root sequentially ─────────────────────────────
    max_threads_pref = await _get_pref("scan_max_threads") or "auto"
    if max_threads_pref == "auto":
        _max_override = None
    else:
        try:
            _max_override = int(max_threads_pref)
        except ValueError:
            _max_override = None

    cancelled = False
    for source_root in valid_roots:
        if _should_cancel():
            log.warning("lifecycle_scan.cancelled_between_roots",
                        completed_roots=valid_roots.index(source_root),
                        reason="coordinator_cancel" if is_lifecycle_cancelled() else "global_stop")
            cancelled = True
            break

        log.info("lifecycle_scan.walking_root", path=str(source_root),
                 root_index=valid_roots.index(source_root) + 1,
                 total_roots=len(valid_roots))

        # Storage probe per root — each mount may be different hardware
        storage_profile = await probe_storage_latency(
            source_root, max_threads_override=_max_override,
        )
        scan_threads = storage_profile.recommended_threads
        log.info("lifecycle_scan.storage_probe",
                 path=str(source_root),
                 storage_hint=storage_profile.storage_hint,
                 scan_threads=scan_threads,
                 ratio=storage_profile.ratio,
                 probe_ms=storage_profile.probe_duration_ms)

        try:
            if scan_threads > 1:
                await _parallel_lifecycle_walk(
                    source_root, scan_threads, seen_paths, counters,
                    error_entries, job_id, scan_run_id, _started_at_dt,
                    baseline_ms=storage_profile.sequential_median_ms,
                    exclusion_paths=exclusion_paths,
                    dir_mtime_cache=dir_mtime_cache,
                    current_dir_mtimes=current_dir_mtimes,
                    incremental_mode=incremental_mode,
                )
            else:
                await _serial_lifecycle_walk(
                    source_root, seen_paths, counters,
                    error_entries, job_id, scan_run_id, _started_at_dt,
                    exclusion_paths=exclusion_paths,
                    dir_mtime_cache=dir_mtime_cache,
                    current_dir_mtimes=current_dir_mtimes,
                    incremental_mode=incremental_mode,
                )
        except Exception as exc:
            # Log error for this root but continue to next root
            counters["errors"] += 1
            error_entries.append({"path": str(source_root), "error": str(exc)})
            log.error("lifecycle_scan.walk_failed", path=str(source_root), error=str(exc))

    # ── Check if scan was cancelled before heavy deletion detection ──────────
    if _should_cancel():
        cancelled = True

    # ── Detect deletions (files not seen but still active) ────────────────────
    # Query source_files (deduplicated) instead of bulk_files to avoid
    # overcounting from duplicate rows across scan jobs.
    # Skip deletion detection if cancelled — incomplete seen_paths would
    # incorrectly mark files as deleted.
    if cancelled:
        log.info("lifecycle_scan.skipping_deletion_detection_cancelled")
    else:
        try:
            active_files = await db_fetch_all(
                "SELECT * FROM source_files WHERE lifecycle_status='active' ORDER BY source_path",
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
                    match = await _find_hash_match_in_seen(content_hash, seen_paths)
                    if match:
                        # Look up all linked bulk_files rows and record the move
                        bf_rows = await db_fetch_all(
                            "SELECT id FROM bulk_files WHERE source_file_id = ? AND lifecycle_status = 'active'",
                            (f["id"],),
                        )
                        for bf in bf_rows:
                            await record_file_move(bf["id"], f["source_path"], match, scan_run_id)
                        counters["files_moved"] += 1  # count once per source file
                        continue

                # File is gone — mark all linked bulk_files rows for deletion
                bf_rows = await db_fetch_all(
                    "SELECT id FROM bulk_files WHERE source_file_id = ? AND lifecycle_status = 'active'",
                    (f["id"],),
                )
                for bf in bf_rows:
                    await mark_file_for_deletion(bf["id"], scan_run_id)
                counters["files_deleted"] += 1  # count once per source file, not per bulk_file row
        except Exception as exc:
            counters["errors"] += 1
            error_entries.append({"path": "deletion_detection", "error": str(exc)})
            log.error("lifecycle_scan.deletion_detection_error", error=str(exc))

    # ── Persist directory mtimes for next incremental scan ──────────
    if current_dir_mtimes:
        try:
            await save_dir_mtimes_batch(current_dir_mtimes, scan_run_id)
        except Exception:
            log.warning("lifecycle_scan.save_dir_mtimes_failed")
    if incremental_mode:
        await increment_scan_count()
    else:
        await reset_scan_count()

    # ── Finalize scan run ────────────────────────────────────────────────────
    final_status = "cancelled" if cancelled else "complete"
    await update_scan_run(scan_run_id, {
        "status": final_status,
        "finished_at": now_iso(),
        "files_scanned": counters["files_scanned"],
        "files_new": counters["files_new"],
        "files_modified": counters["files_modified"],
        "files_moved": counters["files_moved"],
        "files_deleted": counters["files_deleted"],
        "files_restored": counters["files_restored"],
        "errors": counters["errors"],
        "error_log": json.dumps(error_entries) if error_entries else None,
    })

    # Update scan state to idle and unregister from coordinator
    _scan_state["running"] = False
    _scan_state["scanned"] = counters["files_scanned"]
    _scan_state["pct"] = None
    _scan_state["current_file"] = None
    _scan_state["eta_seconds"] = None
    _scan_state["last_scan_at"] = now_iso()
    _scan_state["last_scan_run_id"] = scan_run_id
    unregister_lifecycle_scan()

    elapsed_s = round((datetime.now(timezone.utc) - _started_at_dt).total_seconds(), 1)
    log.info(
        f"lifecycle_scan.{final_status}",
        scan_run_id=scan_run_id,
        **counters,
    )

    # Record activity event for scan end
    try:
        event_detail = (
            f"Lifecycle scan cancelled after {counters['files_scanned']} files"
            if cancelled else
            f"Lifecycle scan: {counters['files_scanned']} files, {counters['files_new']} new, {counters['files_modified']} modified, {counters['files_deleted']} deleted"
        )
        await record_activity_event(
            "lifecycle_scan_end",
            event_detail,
            {
                "scanned": counters["files_scanned"],
                "new": counters["files_new"],
                "modified": counters["files_modified"],
                "deleted": counters["files_deleted"],
                "errors": counters["errors"],
                "duration": elapsed_s,
                "cancelled": cancelled,
            },
            duration_seconds=elapsed_s,
        )
    except Exception:
        pass

    # ── Auto-conversion trigger (skip if cancelled — incomplete scan) ────────
    if cancelled:
        log.info("lifecycle_scan.auto_convert_skipped_cancelled")
        return scan_run_id

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
    existing = await get_source_file_by_path(path_str)

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
        if ext.lower() in _LIFECYCLE_IMAGE_EXTS:
            try:
                await enqueue_image_for_analysis(
                    source_path=path_str,
                    content_hash=content_hash,
                    scan_run_id=scan_run_id,
                )
            except Exception as exc:
                log.warning("lifecycle_scanner.analysis_enqueue_failed",
                            path=path_str, error=str(exc))
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
        if ext.lower() in _LIFECYCLE_IMAGE_EXTS:
            try:
                await enqueue_image_for_analysis(
                    source_path=path_str,
                    content_hash=content_hash,
                    scan_run_id=scan_run_id,
                )
            except Exception as exc:
                log.warning("lifecycle_scanner.analysis_enqueue_failed",
                            path=path_str, error=str(exc))


async def _find_hash_match_in_seen(
    content_hash: str, seen_paths: set[str],
) -> str | None:
    """Check if any newly-seen file matches the content hash.

    Queries source_files (deduplicated) — no job_id filter needed.
    """
    rows = await db_fetch_all(
        "SELECT source_path FROM source_files WHERE content_hash=? AND lifecycle_status='active'",
        (content_hash,),
    )
    for row in rows:
        if row["source_path"] in seen_paths:
            return row["source_path"]
    return None


async def _serial_lifecycle_walk(
    source_root: Path,
    seen_paths: set[str],
    counters: dict,
    error_entries: list[dict],
    job_id: str,
    scan_run_id: str,
    started_at_dt: datetime,
    exclusion_paths: list[str] | None = None,
    dir_mtime_cache: dict[str, float] | None = None,
    current_dir_mtimes: dict[str, float] | None = None,
    incremental_mode: bool = False,
) -> None:
    """Serial walk for local SSD/HDD sources with error-rate abort."""
    error_monitor = ErrorRateMonitor()
    _excl = exclusion_paths or []
    _dir_mtime_cache = dir_mtime_cache or {}
    _current_dir_mtimes = current_dir_mtimes if current_dir_mtimes is not None else {}

    def _is_excluded(p: str) -> bool:
        return any(p.startswith(ep) for ep in _excl)

    def _lifecycle_walk_error(err: OSError) -> None:
        if isinstance(err, PermissionError):
            log.warning("lifecycle_permission_denied", path=str(err.filename or ""),
                        hint="folder may be gated by Active Directory")
        else:
            log.warning("lifecycle_walk_error", path=str(err.filename or ""), error=str(err))

    for dirpath, dirnames, filenames in os.walk(source_root, onerror=_lifecycle_walk_error):
        if _should_cancel() or error_monitor.should_abort():
            log.warning("lifecycle_scan_stopped", scan_run_id=scan_run_id,
                        cancelled=is_lifecycle_cancelled(),
                        aborted=error_monitor.aborted,
                        errors=error_monitor.total_errors)
            _scan_state["running"] = False
            _scan_state["current_file"] = None
            break

        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d != "_markflow"
            and not _is_excluded(str(Path(dirpath) / d))
        ]

        # Record dir mtime and skip if unchanged (incremental)
        try:
            _dir_mt = os.stat(dirpath).st_mtime
            _current_dir_mtimes[dirpath] = _dir_mt
        except OSError:
            _dir_mt = None
        if (incremental_mode and _dir_mt is not None
                and _dir_mtime_cache.get(dirpath) == _dir_mt):
            continue

        for filename in filenames:
            file_path = Path(dirpath) / filename
            if _is_excluded(str(file_path)):
                continue
            errors_before = counters["errors"]
            await _lifecycle_process_entry(
                file_path, source_root, seen_paths, counters,
                error_entries, job_id, scan_run_id, started_at_dt,
            )
            if counters["errors"] > errors_before:
                error_monitor.record_error(f"lifecycle entry: {file_path}")
            else:
                error_monitor.record_success()

            if error_monitor.should_abort():
                break


async def _parallel_lifecycle_walk(
    source_root: Path,
    thread_count: int,
    seen_paths: set[str],
    counters: dict,
    error_entries: list[dict],
    job_id: str,
    scan_run_id: str,
    started_at_dt: datetime,
    baseline_ms: float = 1.0,
    exclusion_paths: list[str] | None = None,
    dir_mtime_cache: dict[str, float] | None = None,
    current_dir_mtimes: dict[str, float] | None = None,
    incremental_mode: bool = False,
) -> None:
    """Parallel walk with feedback-loop throttling for NAS/SMB sources."""
    import time as _time

    _excl = exclusion_paths or []
    _dir_mtime_cache = dir_mtime_cache or {}
    _current_dir_mtimes = current_dir_mtimes if current_dir_mtimes is not None else {}

    def _is_excluded(p: str) -> bool:
        return any(p.startswith(ep) for ep in _excl)

    throttler = ScanThrottler(baseline_ms=baseline_ms, max_threads=thread_count)
    error_monitor = ErrorRateMonitor()

    log.info("lifecycle_parallel_walk_start",
             scan_run_id=scan_run_id, threads=thread_count,
             baseline_ms=round(baseline_ms, 2))

    file_queue: queue.Queue[tuple[Path, str, float, int] | None] = queue.Queue(maxsize=5000)

    # Discover top-level subdirs for distribution
    subdirs: list[Path] = []
    root_files: list[str] = []
    try:
        with os.scandir(source_root) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    name = entry.name
                    if not name.startswith(".") and name != "_markflow" and not _is_excluded(entry.path):
                        subdirs.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    if not _is_excluded(entry.path):
                        root_files.append(entry.name)
    except OSError as exc:
        log.warning("lifecycle_parallel_root_error", error=str(exc))

    def _walker_thread(
        worker_id: int,
        dirs_to_walk: list[Path],
        root_file_subset: list[str],
    ) -> None:
        """Thread worker: walks directories, stats files with latency tracking."""

        def _stat_and_enqueue(file_path: Path) -> None:
            if _is_excluded(str(file_path)):
                return
            t0 = _time.perf_counter()
            try:
                st = file_path.stat()
            except OSError as exc:
                error_monitor.record_error(str(exc))
                return
            latency_ms = (_time.perf_counter() - t0) * 1000
            throttler.record_latency(latency_ms)
            error_monitor.record_success()
            ext = file_path.suffix.lower()
            file_queue.put((file_path, ext, st.st_mtime, st.st_size))

        def _should_bail() -> bool:
            return _should_cancel() or error_monitor.should_abort()

        for filename in root_file_subset:
            if _should_bail():
                return
            while throttler.should_pause(worker_id):
                _time.sleep(0.1)
                if _should_bail():
                    return
            _stat_and_enqueue(source_root / filename)

        def _par_walk_error(err: OSError) -> None:
            if isinstance(err, PermissionError):
                log.warning("lifecycle_permission_denied", path=str(err.filename or ""),
                            hint="folder may be gated by Active Directory")
            else:
                log.warning("lifecycle_walk_error", path=str(err.filename or ""), error=str(err))

        for subdir in dirs_to_walk:
            if _should_bail():
                return
            for dirpath, dirnames, filenames in os.walk(subdir, onerror=_par_walk_error):
                if _should_bail():
                    return
                dirnames[:] = [
                    d for d in dirnames
                    if not d.startswith(".") and d != "_markflow"
                    and not _is_excluded(str(Path(dirpath) / d))
                ]
                # Record dir mtime and skip if unchanged (incremental)
                try:
                    _dir_mt = os.stat(dirpath).st_mtime
                    _current_dir_mtimes[dirpath] = _dir_mt
                except OSError:
                    _dir_mt = None
                if (incremental_mode and _dir_mt is not None
                        and _dir_mtime_cache.get(dirpath) == _dir_mt):
                    continue
                for filename in filenames:
                    if _should_bail():
                        return
                    while throttler.should_pause(worker_id):
                        _time.sleep(0.1)
                        if _should_bail():
                            return
                    _stat_and_enqueue(Path(dirpath) / filename)

    # Distribute subdirs across workers (round-robin)
    worker_dirs: list[list[Path]] = [[] for _ in range(thread_count)]
    for i, subdir in enumerate(subdirs):
        worker_dirs[i % thread_count].append(subdir)
    worker_root_files: list[list[str]] = [[] for _ in range(thread_count)]
    worker_root_files[0] = root_files

    executor = ThreadPoolExecutor(
        max_workers=thread_count,
        thread_name_prefix="lifecycle-walker",
    )
    futures = []
    for i in range(thread_count):
        fut = executor.submit(
            _walker_thread, i, worker_dirs[i], worker_root_files[i],
        )
        futures.append(fut)

    # Async consumer: drain queue, process files, periodically check throttle
    walkers_done = False
    last_throttle_check = 0

    while not walkers_done or not file_queue.empty():
        walkers_done = all(f.done() for f in futures)

        batch: list[tuple[Path, str, float, int]] = []
        try:
            while len(batch) < 100:
                item = file_queue.get_nowait()
                batch.append(item)
        except queue.Empty:
            pass

        if not batch:
            if not walkers_done:
                await asyncio.sleep(0.01)
            continue

        for file_path, ext, mtime, size in batch:
            path_str = str(file_path)
            seen_paths.add(path_str)
            counters["files_scanned"] += 1

            if ext not in ALL_SUPPORTED and ext not in CONVERTIBLE_EXTENSIONS and ext not in ADOBE_EXTENSIONS:
                existing = await get_source_file_by_path(path_str)
                if existing and existing.get("lifecycle_status") == "marked_for_deletion":
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

            if counters["files_scanned"] % 25 == 0:
                _update_scan_progress(
                    counters, file_path, source_root, started_at_dt,
                )

        # Periodically ask throttler to re-evaluate
        if counters["files_scanned"] - last_throttle_check >= 500:
            throttler.check_and_adjust()
            last_throttle_check = counters["files_scanned"]

    # Check for walker exceptions
    for i, fut in enumerate(futures):
        exc = fut.exception()
        if exc:
            log.error("lifecycle_walker_error", worker=i, error=str(exc))

    executor.shutdown(wait=False)

    if error_monitor.aborted:
        log.error("lifecycle_parallel_walk_aborted",
                  scan_run_id=scan_run_id,
                  error_rate=round(error_monitor.error_rate, 2),
                  total_errors=error_monitor.total_errors,
                  scanned=counters["files_scanned"])

    log.info("lifecycle_parallel_walk_complete",
             scan_run_id=scan_run_id,
             threads_initial=thread_count,
             threads_final=throttler.active_threads,
             throttle_adjustments=throttler.adjustment_count,
             stat_errors=error_monitor.total_errors,
             aborted=error_monitor.aborted,
             scanned=counters["files_scanned"])

    # Persist throttle events for resources dashboard
    try:
        from core.bulk_scanner import _persist_throttle_events
        await _persist_throttle_events(
            scan_run_id, "lifecycle_scan", throttler, error_monitor,
        )
    except Exception:
        pass


async def _lifecycle_process_entry(
    file_path: Path,
    source_root: Path,
    seen_paths: set[str],
    counters: dict,
    error_entries: list[dict],
    job_id: str,
    scan_run_id: str,
    started_at_dt: datetime,
) -> None:
    """Process a single discovered file in the lifecycle scan."""
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
        return

    if ext not in ALL_SUPPORTED and ext not in CONVERTIBLE_EXTENSIONS and ext not in ADOBE_EXTENSIONS:
        existing = await get_source_file_by_path(path_str)
        if existing and existing.get("lifecycle_status") == "marked_for_deletion":
            await restore_file(existing["id"], scan_run_id)
            counters["files_restored"] += 1
        return

    try:
        await _process_file(
            file_path, path_str, ext, mtime, size,
            job_id, scan_run_id, counters,
        )
    except Exception as exc:
        counters["errors"] += 1
        error_entries.append({"path": path_str, "error": str(exc)})
        log.error("lifecycle_scan.file_error", path=path_str, error=str(exc))

    if counters["files_scanned"] % 25 == 0:
        _update_scan_progress(
            counters, file_path, source_root, started_at_dt,
        )


def _update_scan_progress(
    counters: dict,
    file_path: Path,
    source_root: Path,
    started_at_dt: datetime,
) -> None:
    """Update the in-memory scan progress state."""
    _scan_state["scanned"] = counters["files_scanned"]
    try:
        _scan_state["current_file"] = str(file_path.relative_to(source_root))
    except ValueError:
        _scan_state["current_file"] = file_path.name
    total_est = _scan_state["total"]
    if total_est > 0:
        _scan_state["pct"] = min(99, int(counters["files_scanned"] / total_est * 100))
    else:
        _scan_state["pct"] = None
    elapsed = (datetime.now(timezone.utc) - started_at_dt).total_seconds()
    if elapsed > 5 and counters["files_scanned"] > 0:
        rate = counters["files_scanned"] / elapsed
        remaining = total_est - counters["files_scanned"] if total_est else 0
        _scan_state["eta_seconds"] = int(remaining / rate) if rate > 0 and remaining > 0 else None
    else:
        _scan_state["eta_seconds"] = None


def _count_files_sync(source_root: Path) -> int:
    """Count all files in source tree (synchronous, for use in a thread)."""
    def _count_walk_error(err: OSError) -> None:
        if isinstance(err, PermissionError):
            log.warning("lifecycle_count_permission_denied", path=str(err.filename or ""),
                        hint="folder may be gated by Active Directory")

    count = 0
    for _, dirnames, filenames in os.walk(source_root, onerror=_count_walk_error):
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
    from core.bulk_worker import BulkJob, get_all_active_jobs
    from core.database import create_bulk_job, get_db_path, get_preference

    try:
        # Guard: refuse to start if another bulk job is already active
        active = await get_all_active_jobs()
        if any(j["status"] in ("scanning", "running", "paused") for j in active):
            log.info("auto_convert_skipped_job_active",
                     active_count=len(active),
                     active_ids=[j["job_id"] for j in active if j["status"] in ("scanning", "running", "paused")])
            return

        output_path = os.getenv("BULK_OUTPUT_PATH", "/mnt/output-repo")

        # Apply pipeline_max_files_per_run cap if set
        pipeline_cap = int(await get_preference("pipeline_max_files_per_run") or "0")
        if pipeline_cap > 0:
            if decision.batch_size == 0:  # 0 = unlimited
                decision.batch_size = pipeline_cap
            else:
                decision.batch_size = min(decision.batch_size, pipeline_cap)

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
            source_paths=str(source_root),
            output_path=output_path,
            worker_count=decision.workers,
            max_files=decision.batch_size if decision.batch_size > 0 else None,
        )

        if decision.mode == "immediate":
            # Block scanner until batch completes
            await job.run()
        elif decision.mode in ("queued", "scheduled"):
            # Background task — scanner moves on
            asyncio.create_task(job.run())

    except Exception as exc:
        log.error(
            "auto_convert_execution_failed",
            error=str(exc),
            scan_run_id=scan_run_id,
        )


