"""
Bulk file scanner — walks a source directory tree, discovers convertible and
Adobe files, and records them into the bulk_files table with mtime tracking.

Supports incremental processing: unchanged files (same mtime) are skipped.

Adaptive parallelism: auto-probes storage latency at scan start and uses
parallel directory walkers for network storage (NAS/SMB/NFS) while staying
serial for local disks (HDD seek thrashing avoidance, SSD already fast).
"""

import asyncio
import os
import queue
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

from core.progress_tracker import RollingWindowETA, ETA_UPDATE_INTERVAL, format_eta
from core.stop_controller import should_stop
from core.storage_probe import ErrorRateMonitor, ScanThrottler, StorageProfile, probe_storage_latency
from core.database import db_fetch_one, get_preference, record_path_issue, update_bulk_file, update_bulk_job_status, update_source_file, upsert_bulk_file
from core.path_utils import PathSafetyResult, run_path_safety_pass

log = structlog.get_logger(__name__)

# All supported extensions — unified scanning (no separate Adobe/convertible split)
SUPPORTED_EXTENSIONS = {
    # Office documents
    ".docx", ".doc", ".docm", ".wpd",
    ".pdf",
    ".pptx", ".ppt",
    ".xlsx", ".xls",
    ".csv", ".tsv",
    ".rtf",
    # OpenDocument
    ".odt", ".ods", ".odp",
    # Markdown & text
    ".md", ".txt", ".log", ".text",
    # Web & data
    ".html", ".htm", ".xml", ".epub",
    # Data & config
    ".json", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".properties",
    # Email
    ".eml", ".msg",
    # Archives
    ".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
    ".tar.xz", ".txz", ".7z", ".rar", ".cab", ".iso",
    # Adobe creative suite
    ".psd", ".ai", ".indd", ".aep", ".prproj", ".xd", ".ait", ".indt",
    # Media (audio/video — indexed for metadata/scene detection)
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav", ".flac", ".ogg",
    ".webm", ".m4a", ".m4v", ".wmv", ".aac", ".wma",
    # Images
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".eps",
}

# Backwards-compat aliases (referenced by bulk_worker and other modules)
CONVERTIBLE_EXTENSIONS = SUPPORTED_EXTENSIONS
ADOBE_EXTENSIONS = {".ai", ".psd", ".indd", ".aep", ".prproj", ".xd", ".ait", ".indt"}
ALL_SUPPORTED = SUPPORTED_EXTENSIONS


def _get_effective_extension(file_path: Path) -> str:
    """Get effective extension, handling compound extensions like .tar.gz."""
    suffixes = file_path.suffixes
    if len(suffixes) >= 2:
        compound = "".join(suffixes[-2:]).lower()
        if compound in SUPPORTED_EXTENSIONS:
            return compound
    return file_path.suffix.lower()


@dataclass
class ScanResult:
    job_id: str
    total_discovered: int = 0
    convertible_count: int = 0
    adobe_count: int = 0
    unrecognized_count: int = 0
    skipped_count: int = 0
    new_count: int = 0
    changed_count: int = 0
    path_too_long_count: int = 0
    collision_count: int = 0
    case_collision_count: int = 0
    path_safety_result: "PathSafetyResult | None" = None
    storage_profile: "StorageProfile | None" = None
    scan_threads_used: int = 1
    scan_duration_ms: int = 0


@dataclass
class BulkFileRecord:
    file_id: str
    job_id: str
    source_path: Path
    file_ext: str
    file_size_bytes: int
    source_mtime: float
    status: str = "pending"


def _verify_source_mount(source_path: str) -> bool:
    """Verify the source path is mounted and accessible.

    Checks that the path exists, is a directory, and contains at least
    one entry (to distinguish a live mount from an empty mountpoint).
    """
    if not os.path.isdir(source_path):
        return False
    try:
        with os.scandir(source_path) as it:
            next(it)
            return True
    except (StopIteration, PermissionError, OSError):
        return False


class BulkScanner:
    """Walks a source directory and upserts discovered files into bulk_files."""

    def __init__(self, job_id: str, source_path: Path, output_path: Path | None = None, db_path: str = ""):
        self.job_id = job_id
        self.source_path = Path(source_path)
        self.output_path = Path(output_path) if output_path else None
        self._yield_interval = 1000  # yield control every N files

    async def scan(
        self,
        on_progress: Callable[[dict], Awaitable[None]] | None = None,
    ) -> ScanResult:
        """
        Walk source_path recursively. For each supported file:
          1. Check extension
          2. Get mtime and size
          3. Upsert into bulk_files table
          4. Yield control every _yield_interval files

        Adaptive parallelism: probes storage latency at scan start and uses
        parallel directory walkers for network storage (NAS/SMB/NFS) while
        staying serial for local disks.
        """
        t_start = time.perf_counter()
        result = ScanResult(job_id=self.job_id)
        file_count = 0
        self._convertible_paths: list[Path] = []

        if not _verify_source_mount(str(self.source_path)):
            log.error("bulk_scan_mount_not_ready",
                      job_id=self.job_id,
                      source_path=str(self.source_path),
                      msg="Source path is empty or not mounted. Aborting scan.")
            from core.database import get_db
            async with get_db() as conn:
                await conn.execute(
                    "UPDATE bulk_jobs SET status='failed' WHERE id=?",
                    (self.job_id,))
                await conn.commit()
            return result

        log.info("bulk_scan_start", job_id=self.job_id, source_path=str(self.source_path))

        # ── Storage probe — auto-detect optimal parallelism ──────────────
        max_threads_pref = await get_preference("scan_max_threads") or "auto"
        if max_threads_pref == "auto":
            max_override = None
        else:
            try:
                max_override = int(max_threads_pref)
            except ValueError:
                max_override = None

        storage_profile = await probe_storage_latency(
            self.source_path, max_threads_override=max_override,
        )
        result.storage_profile = storage_profile
        scan_threads = storage_profile.recommended_threads
        result.scan_threads_used = scan_threads

        # Emit storage probe result so UI can display it
        if on_progress:
            await on_progress({
                "event": "storage_probe_result",
                "job_id": self.job_id,
                "storage_hint": storage_profile.storage_hint,
                "scan_threads": scan_threads,
                "sequential_ms": storage_profile.sequential_median_ms,
                "random_ms": storage_profile.random_median_ms,
                "ratio": storage_profile.ratio,
                "probe_duration_ms": storage_profile.probe_duration_ms,
            })

        # Concurrent fast-walk counter — starts immediately, runs in parallel with scan
        tracker = RollingWindowETA(total=None)
        fast_walk_task = asyncio.create_task(
            self._fast_walk_counter(tracker)
        )

        # Emit first progress event
        if on_progress:
            await on_progress({
                "event": "scan_progress",
                "job_id": self.job_id,
                "scanned": 0,
                "total": None,
                "current_file": "",
                "pct": None,
                "eta_seconds": None,
                "eta_human": None,
                "files_per_second": None,
                "count_ready": False,
            })

        progress_interval = 50  # emit every N files
        last_eta_write = time.monotonic()

        # ── Choose scan strategy based on probe result ───────────────────
        if scan_threads > 1:
            file_count = await self._parallel_scan(
                scan_threads, tracker, result, on_progress,
                progress_interval,
            )
        else:
            file_count = await self._serial_scan(
                tracker, result, on_progress, progress_interval,
            )

        # Cancel fast-walk if still running
        if not fast_walk_task.done():
            fast_walk_task.cancel()
            try:
                await fast_walk_task
            except asyncio.CancelledError:
                pass

        # Emit final progress event
        snap = await tracker.snapshot()
        if on_progress:
            await on_progress({
                "event": "scan_progress",
                "job_id": self.job_id,
                "scanned": file_count,
                "total": file_count,
                "current_file": "",
                "pct": 99,
                "eta_seconds": 0,
                "eta_human": None,
                "files_per_second": round(snap.files_per_second, 1) if snap.files_per_second else None,
                "count_ready": True,
            })

        # Count skipped (already converted, unchanged)
        from core.database import get_bulk_file_count
        result.skipped_count = await get_bulk_file_count(self.job_id, status="skipped")
        pending = await get_bulk_file_count(self.job_id, status="pending")
        # new_count + changed_count = pending (we can't distinguish without more state,
        # but pending after upsert means either new or mtime-changed)
        result.new_count = pending  # approximate: all pending are "needs processing"

        # ── Path safety pass ──────────────────────────────────────────────
        if self.output_path and self._convertible_paths:
            result.path_safety_result = await self._run_path_safety_pass(result)

        result.scan_duration_ms = int((time.perf_counter() - t_start) * 1000)

        # Emit scan_complete event
        if on_progress:
            await on_progress({
                "event": "scan_complete",
                "job_id": self.job_id,
                "total_found": file_count,
            })

        log.info(
            "bulk_scan_complete",
            job_id=self.job_id,
            total_discovered=result.total_discovered,
            supported=result.convertible_count,
            unrecognized=result.unrecognized_count,
            skipped=result.skipped_count,
            pending=pending,
            too_long=result.path_too_long_count,
            collisions=result.collision_count,
            case_collisions=result.case_collision_count,
            scan_threads=result.scan_threads_used,
            storage_hint=storage_profile.storage_hint,
            duration_ms=result.scan_duration_ms,
        )

        return result

    # ── Serial scan (original path — SSD/HDD) ───────────────────────────

    async def _serial_scan(
        self,
        tracker: RollingWindowETA,
        result: ScanResult,
        on_progress: Callable[[dict], Awaitable[None]] | None,
        progress_interval: int,
    ) -> int:
        """Single-threaded scan — optimal for local SSD/HDD."""
        file_count = 0
        last_eta_write = time.monotonic()
        error_monitor = ErrorRateMonitor()

        def _serial_walk_error(err: OSError) -> None:
            if isinstance(err, PermissionError):
                log.warning(
                    "scan_permission_denied",
                    path=str(err.filename or ""),
                    error=str(err),
                    hint="folder may be gated by Active Directory",
                )
            else:
                log.warning("scan_walk_error", path=str(err.filename or ""), error=str(err))

        for dirpath, dirnames, filenames in os.walk(self.source_path, onerror=_serial_walk_error):
            if should_stop() or error_monitor.should_abort():
                reason = "high_error_rate" if error_monitor.aborted else "global_stop_requested"
                log.warning("scan_stopped_early", job_id=self.job_id,
                            scanned_so_far=file_count, reason=reason)
                if on_progress:
                    await on_progress({
                        "event": "scan_stopped" if not error_monitor.aborted else "scan_aborted",
                        "job_id": self.job_id,
                        "scanned": file_count,
                        "reason": reason,
                        "total_errors": error_monitor.total_errors,
                    })
                break

            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d != "_markflow"
            ]

            for filename in filenames:
                file_path = Path(dirpath) / filename
                old_count = file_count
                file_count = await self._process_discovered_file(
                    file_path, result, tracker, file_count,
                )
                # Track success/error (if count didn't change, stat failed)
                if file_count > old_count:
                    error_monitor.record_success()
                else:
                    error_monitor.record_error(f"stat failed: {file_path}")

                if error_monitor.should_abort():
                    break

                if on_progress and (file_count % progress_interval == 0):
                    await self._emit_progress(
                        on_progress, tracker, file_count, file_path,
                    )

                now = time.monotonic()
                if now - last_eta_write >= ETA_UPDATE_INTERVAL:
                    await self._log_eta(tracker, last_eta_write)
                    last_eta_write = now

                if file_count % self._yield_interval == 0:
                    await asyncio.sleep(0)

        return file_count

    # ── Parallel scan (network storage) ──────────────────────────────────

    async def _parallel_scan(
        self,
        thread_count: int,
        tracker: RollingWindowETA,
        result: ScanResult,
        on_progress: Callable[[dict], Awaitable[None]] | None,
        progress_interval: int,
    ) -> int:
        """Multi-threaded scan with feedback-loop throttling.

        Thread workers walk subdirectories and stat files concurrently,
        pushing (path, ext, size, mtime) tuples into a thread-safe queue.
        A single async consumer drains the queue and writes to SQLite.

        Workers report stat() latency to a ScanThrottler which monitors
        congestion and parks/unparks workers dynamically — like TCP
        congestion control for filesystem I/O.
        """
        # Use probe baseline for throttler (sequential median is the "calm" baseline)
        baseline_ms = result.storage_profile.sequential_median_ms if result.storage_profile else 1.0
        throttler = ScanThrottler(baseline_ms=baseline_ms, max_threads=thread_count)
        error_monitor = ErrorRateMonitor()

        log.info("parallel_scan_start",
                 job_id=self.job_id, threads=thread_count,
                 baseline_ms=round(baseline_ms, 2))

        # Thread-safe queue: walkers produce, async consumer consumes
        file_queue: queue.Queue[tuple[Path, str, int, float] | None] = queue.Queue(
            maxsize=5000
        )

        # Discover top-level subdirectories to distribute across workers
        root_files: list[str] = []
        subdirs: list[Path] = []
        try:
            with os.scandir(self.source_path) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        name = entry.name
                        if not name.startswith(".") and name != "_markflow":
                            subdirs.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        root_files.append(entry.name)
        except OSError as exc:
            log.warning("parallel_scan_root_error", error=str(exc))

        def _walker_thread(
            worker_id: int,
            dirs_to_walk: list[Path],
            root_files_subset: list[str],
        ) -> None:
            """Thread worker: walks directories, stats files with latency tracking."""
            import time as _time

            def _stat_and_enqueue(file_path: Path) -> None:
                # Skip NTFS Alternate Data Streams (ADS) — filenames with ':'
                if ":" in file_path.name:
                    return
                t0 = _time.perf_counter()
                try:
                    st = file_path.stat()
                except FileNotFoundError:
                    # File vanished between walk() and stat() — AV quarantine or deletion
                    log.debug("scan_file_vanished", path=str(file_path))
                    return
                except PermissionError:
                    log.debug("scan_file_permission_denied", path=str(file_path))
                    error_monitor.record_error(f"permission denied: {file_path}")
                    return
                except OSError as exc:
                    error_monitor.record_error(str(exc))
                    # Stale SMB connection or timeout — brief retry
                    if "reset" in str(exc).lower() or "timed out" in str(exc).lower():
                        _time.sleep(0.5)
                        try:
                            st = file_path.stat()
                        except OSError:
                            return
                    else:
                        return
                latency_ms = (_time.perf_counter() - t0) * 1000
                throttler.record_latency(latency_ms)
                error_monitor.record_success()
                ext = _get_effective_extension(file_path)
                file_queue.put((file_path, ext, st.st_size, st.st_mtime))

            def _should_bail() -> bool:
                return should_stop() or error_monitor.should_abort()

            # Process root-level files assigned to this worker
            for filename in root_files_subset:
                if _should_bail():
                    return
                while throttler.should_pause(worker_id):
                    _time.sleep(0.1)
                    if _should_bail():
                        return
                _stat_and_enqueue(self.source_path / filename)

            def _walk_error(err: OSError) -> None:
                """Handle os.walk errors (e.g. AD-credentialed folders)."""
                if isinstance(err, PermissionError):
                    log.warning(
                        "scan_permission_denied",
                        path=str(err.filename or ""),
                        error=str(err),
                        hint="folder may be gated by Active Directory",
                    )
                else:
                    log.warning("scan_walk_error", path=str(err.filename or ""), error=str(err))

            # Walk assigned subdirectories
            for subdir in dirs_to_walk:
                if _should_bail():
                    return
                try:
                    walker = os.walk(subdir, onerror=_walk_error)
                except PermissionError:
                    log.warning(
                        "scan_permission_denied",
                        path=str(subdir),
                        hint="folder may be gated by Active Directory",
                    )
                    continue
                for dirpath, dirnames, filenames in walker:
                    if _should_bail():
                        return
                    dirnames[:] = [
                        d for d in dirnames
                        if not d.startswith(".") and d != "_markflow"
                    ]
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

        # Distribute root files to worker 0
        worker_root_files: list[list[str]] = [[] for _ in range(thread_count)]
        worker_root_files[0] = root_files

        # Launch walker threads
        executor = ThreadPoolExecutor(
            max_workers=thread_count,
            thread_name_prefix="scan-walker",
        )
        futures = []
        for i in range(thread_count):
            fut = executor.submit(
                _walker_thread, i, worker_dirs[i], worker_root_files[i],
            )
            futures.append(fut)

        # Async consumer: drain queue, write to DB, periodically check throttle
        file_count = 0
        last_eta_write = time.monotonic()
        last_throttle_check = 0
        last_progress_file: Path | None = None
        walkers_done = False

        while not walkers_done or not file_queue.empty():
            walkers_done = all(f.done() for f in futures)

            batch: list[tuple[Path, str, int, float]] = []
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

            for file_path, ext, file_size, mtime in batch:
                result.total_discovered += 1

                if ext in SUPPORTED_EXTENSIONS:
                    result.convertible_count += 1
                    self._convertible_paths.append(file_path)
                    await upsert_bulk_file(
                        job_id=self.job_id,
                        source_path=str(file_path),
                        file_ext=ext,
                        file_size_bytes=file_size,
                        source_mtime=mtime,
                    )
                else:
                    result.unrecognized_count += 1
                    await self._record_unrecognized(file_path, ext, file_size, mtime)

                file_count += 1
                await tracker.record_completion()
                last_progress_file = file_path

            # Periodically ask throttler to re-evaluate
            if file_count - last_throttle_check >= 500:
                throttler.check_and_adjust()
                last_throttle_check = file_count

            if on_progress and last_progress_file and (file_count % progress_interval < len(batch)):
                await self._emit_progress(
                    on_progress, tracker, file_count, last_progress_file,
                )

            now = time.monotonic()
            if now - last_eta_write >= ETA_UPDATE_INTERVAL:
                await self._log_eta(tracker, last_eta_write)
                last_eta_write = now

        # Check for walker exceptions
        for i, fut in enumerate(futures):
            exc = fut.exception()
            if exc:
                log.error("parallel_scan_walker_error",
                          job_id=self.job_id, worker=i, error=str(exc))

        executor.shutdown(wait=False)

        # Emit abort event if error rate triggered early stop
        if error_monitor.aborted:
            if on_progress:
                await on_progress({
                    "event": "scan_aborted",
                    "job_id": self.job_id,
                    "reason": "high_error_rate",
                    "error_rate": round(error_monitor.error_rate, 2),
                    "total_errors": error_monitor.total_errors,
                    "scanned": file_count,
                })
            log.error("parallel_scan_aborted",
                      job_id=self.job_id,
                      error_rate=round(error_monitor.error_rate, 2),
                      total_errors=error_monitor.total_errors,
                      files_before_abort=file_count)

        log.info("parallel_scan_complete",
                 job_id=self.job_id,
                 threads_initial=thread_count,
                 threads_final=throttler.active_threads,
                 throttle_adjustments=throttler.adjustment_count,
                 stat_errors=error_monitor.total_errors,
                 aborted=error_monitor.aborted,
                 files=file_count)

        # Persist throttle events for resources dashboard
        await _persist_throttle_events(
            self.job_id, "bulk_scan", throttler, error_monitor,
        )

        return file_count

    # ── Shared helpers ───────────────────────────────────────────────────

    async def _process_discovered_file(
        self,
        file_path: Path,
        result: ScanResult,
        tracker: RollingWindowETA,
        file_count: int,
    ) -> int:
        """Process a single discovered file — stat, classify, upsert. Returns updated count."""
        # Skip NTFS Alternate Data Streams
        if ":" in file_path.name:
            return file_count

        ext = _get_effective_extension(file_path)

        try:
            stat = file_path.stat()
            file_size = stat.st_size
            mtime = stat.st_mtime
        except FileNotFoundError:
            log.debug("scan_file_vanished", path=str(file_path))
            return file_count
        except PermissionError:
            log.debug("scan_file_permission_denied", path=str(file_path))
            return file_count
        except OSError as exc:
            log.warning("bulk_scan_stat_error", path=str(file_path), error=str(exc))
            return file_count

        result.total_discovered += 1

        if ext in SUPPORTED_EXTENSIONS:
            result.convertible_count += 1
            self._convertible_paths.append(file_path)
            await upsert_bulk_file(
                job_id=self.job_id,
                source_path=str(file_path),
                file_ext=ext,
                file_size_bytes=file_size,
                source_mtime=mtime,
            )
        else:
            result.unrecognized_count += 1
            await self._record_unrecognized(file_path, ext, file_size, mtime)

        file_count += 1
        await tracker.record_completion()
        return file_count

    async def _emit_progress(
        self,
        on_progress: Callable[[dict], Awaitable[None]],
        tracker: RollingWindowETA,
        file_count: int,
        current_file: Path,
    ) -> None:
        """Emit a scan progress SSE event."""
        snap = await tracker.snapshot()
        try:
            rel_path = current_file.relative_to(self.source_path)
        except ValueError:
            rel_path = current_file
        pct = snap.to_dict()["percent"]
        await on_progress({
            "event": "scan_progress",
            "job_id": self.job_id,
            "scanned": file_count,
            "total": snap.total,
            "current_file": str(rel_path),
            "pct": pct,
            "eta_seconds": snap.eta_seconds,
            "eta_human": format_eta(snap.eta_seconds),
            "files_per_second": round(snap.files_per_second, 1) if snap.files_per_second else None,
            "count_ready": snap.count_ready,
        })

    async def _log_eta(self, tracker: RollingWindowETA, last_write: float) -> None:
        """Log ETA progress (throttled)."""
        snap = await tracker.snapshot()
        log.info("scan_progress",
                 job_id=self.job_id,
                 completed=snap.completed,
                 total=snap.total,
                 count_ready=snap.count_ready,
                 eta_seconds=snap.eta_seconds,
                 files_per_second=snap.files_per_second)

    async def _fast_walk_counter(self, tracker: RollingWindowETA) -> int:
        """Lightweight concurrent file counter — runs in parallel with the main scan.

        Walks the directory tree counting files only (no stat calls, no DB writes).
        Streams intermediate counts to the tracker so the UI can show "X of Y"
        before the walk finishes. Returns total when complete.
        """
        total = 0
        update_interval = 2000  # stream count to tracker every N files

        def _count_walk_error(err: OSError) -> None:
            if isinstance(err, PermissionError):
                log.warning(
                    "scan_count_permission_denied",
                    path=str(err.filename or ""),
                    hint="folder may be gated by Active Directory",
                )
            else:
                log.warning("scan_count_walk_error", path=str(err.filename or ""), error=str(err))

        def _walk_sync() -> int:
            nonlocal total
            for _, dirnames, filenames in os.walk(self.source_path, onerror=_count_walk_error):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "_markflow"]
                total += len(filenames)
            return total

        try:
            # Run the walk in a thread so we don't block the event loop
            final_total = await asyncio.to_thread(_walk_sync)
            await tracker.set_total(final_total)
            log.info("fast_walk_complete", job_id=self.job_id, total=final_total)
            return final_total
        except asyncio.CancelledError:
            # Scan finished before fast-walk — use whatever count we have
            await tracker.set_total(total)
            raise
        except Exception as exc:
            log.warning("fast_walk_error", job_id=self.job_id, error=str(exc))
            if total > 0:
                await tracker.set_total(total)
            return total

    async def _record_unrecognized(
        self, path: Path, ext: str, file_size: int, mtime: float
    ) -> None:
        """Record an unrecognized file with MIME detection."""
        try:
            from core.mime_classifier import classify
            mime_type, category = classify(path)
        except Exception:
            mime_type, category = "application/octet-stream", "unknown"

        file_id = await upsert_bulk_file(
            job_id=self.job_id,
            source_path=str(path),
            file_ext=ext or ".unknown",
            file_size_bytes=file_size,
            source_mtime=mtime,
        )
        # Update the status and MIME fields
        await update_bulk_file(
            file_id,
            status="unrecognized",
            mime_type=mime_type,
            file_category=category,
        )

        # Propagate MIME classification to source_files
        sf_row = await db_fetch_one(
            "SELECT source_file_id FROM bulk_files WHERE id = ?", (file_id,)
        )
        sf_id = sf_row.get("source_file_id") if sf_row else None
        if sf_id:
            await update_source_file(sf_id, mime_type=mime_type, file_category=category)

    async def _run_path_safety_pass(self, scan_result: ScanResult) -> PathSafetyResult:
        """Run path length and collision checks on all convertible files."""
        max_len_str = await get_preference("max_output_path_length") or "240"
        max_len = int(max_len_str)
        strategy_str = await get_preference("collision_strategy") or "rename"
        strategy = strategy_str if strategy_str in ("rename", "skip", "error") else "rename"

        safety = await run_path_safety_pass(
            all_files=self._convertible_paths,
            source_root=self.source_path,
            output_root=self.output_path,
            max_path_length=max_len,
            collision_strategy=strategy,
        )

        scan_result.path_too_long_count = safety.too_long_count
        scan_result.collision_count = safety.collision_count
        scan_result.case_collision_count = safety.case_collision_count

        # Record path issues in DB
        if safety.too_long_count or safety.collision_count or safety.case_collision_count:
            await self._record_path_issues(safety, strategy)

        log.info(
            "path_safety_pass_complete",
            job_id=self.job_id,
            total_checked=safety.total_checked,
            too_long=safety.too_long_count,
            collisions=safety.collision_count,
            case_collisions=safety.case_collision_count,
        )

        for output_path, files in safety.collision_groups.items():
            log.warning(
                "output_collision_detected",
                job_id=self.job_id,
                output_path=output_path,
                source_files=[str(f) for f in files],
                strategy=strategy,
            )

        return safety

    async def _record_path_issues(self, safety: PathSafetyResult, strategy: str) -> None:
        """Persist path issues to bulk_path_issues table and update bulk_files."""
        from core.path_utils import map_output_path

        # Too-long paths
        for f in safety.path_too_long:
            out = map_output_path(f, self.source_path, self.output_path)
            await record_path_issue(
                job_id=self.job_id,
                issue_type="path_too_long",
                source_path=str(f),
                output_path=str(out),
                resolution="skipped",
            )

        # Standard collisions
        for output_path_str, sources in safety.collision_groups.items():
            sorted_sources = sorted(sources, key=lambda p: str(p))
            for src in sorted_sources:
                resolved = safety.resolved_paths.get(str(src))
                resolved_path = resolved[0] if resolved else None
                resolution = resolved[1] if resolved else strategy
                peers = [str(s) for s in sorted_sources if s != src]
                await record_path_issue(
                    job_id=self.job_id,
                    issue_type="collision",
                    source_path=str(src),
                    output_path=output_path_str,
                    collision_group=output_path_str,
                    collision_peer=peers[0] if peers else None,
                    resolution=resolution,
                    resolved_path=resolved_path,
                )

        # Case collisions
        for lower_path, sources in safety.case_collision_groups.items():
            sorted_sources = sorted(sources, key=lambda p: str(p))
            for src in sorted_sources:
                resolved = safety.resolved_paths.get(str(src))
                resolved_path = resolved[0] if resolved else None
                resolution = resolved[1] if resolved else strategy
                peers = [str(s) for s in sorted_sources if s != src]
                await record_path_issue(
                    job_id=self.job_id,
                    issue_type="case_collision",
                    source_path=str(src),
                    output_path=lower_path,
                    collision_group=lower_path,
                    collision_peer=peers[0] if peers else None,
                    resolution=resolution,
                    resolved_path=resolved_path,
                )

        # Update job counters
        await update_bulk_job_status(
            self.job_id, "scanning",
            path_too_long_count=safety.too_long_count,
            collision_count=safety.collision_count,
            case_collision_count=safety.case_collision_count,
        )


# ── Module-level helpers ────────────────────────────────────────────────────

async def _persist_throttle_events(
    job_id: str,
    scan_type: str,
    throttler: ScanThrottler,
    error_monitor: ErrorRateMonitor,
) -> None:
    """Persist throttle adjustments and error-rate events to activity_events."""
    try:
        from core.metrics_collector import record_activity_event

        # Record each throttle adjustment
        for adj in throttler.adjustments:
            await record_activity_event(
                "scan_throttle",
                f"Scan throttle {adj['direction']}: {adj['from']} -> {adj['to']} threads "
                f"(latency ratio {adj['ratio']}x)",
                metadata={
                    "job_id": job_id,
                    "scan_type": scan_type,
                    "direction": adj.get("direction", "down" if adj["to"] < adj["from"] else "up"),
                    "from_threads": adj["from"],
                    "to_threads": adj["to"],
                    "latency_ratio": adj["ratio"],
                    "median_ms": adj["median_ms"],
                    "baseline_ms": adj["baseline_ms"],
                },
            )

        # Record summary if there were adjustments or errors
        if throttler.adjustment_count > 0 or error_monitor.total_errors > 0:
            await record_activity_event(
                "scan_throttle_summary",
                f"Scan {scan_type}: {throttler.adjustment_count} throttle adjustments, "
                f"{error_monitor.total_errors} errors, "
                f"final threads {throttler.active_threads}/{throttler.max_threads}",
                metadata={
                    "job_id": job_id,
                    "scan_type": scan_type,
                    "adjustments": throttler.adjustment_count,
                    "max_threads": throttler.max_threads,
                    "final_threads": throttler.active_threads,
                    "total_errors": error_monitor.total_errors,
                    "error_rate": round(error_monitor.error_rate, 3),
                    "aborted": error_monitor.aborted,
                },
            )
    except Exception:
        log.warning("persist_throttle_events_failed", job_id=job_id)
