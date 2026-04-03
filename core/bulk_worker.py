"""
Bulk conversion worker pool — processes files from the scanner queue.

Reuses ConversionOrchestrator for convertible files and AdobeIndexer for
Adobe files. Supports pause, resume, and cancel operations.
"""

import asyncio
import hashlib
import json
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from core.progress_tracker import RollingWindowETA, ETA_UPDATE_INTERVAL, format_eta
from core.scan_coordinator import notify_bulk_started, notify_bulk_completed
from core.stop_controller import should_stop, register_task, unregister_task
from core.metrics_collector import record_activity_event
from core.storage_probe import ErrorRateMonitor
from core.bulk_scanner import (
    ADOBE_EXTENSIONS,
    CONVERTIBLE_EXTENSIONS,
    BulkFileRecord,
    BulkScanner,
    ScanResult,
)
from core.database import (
    add_to_review_queue,
    db_write_with_retry,
    get_ocr_gap_fill_candidates,
    get_preference,
    get_review_queue_count,
    get_unprocessed_bulk_files,
    increment_bulk_job_counter,
    update_bulk_file,
    update_bulk_file_confidence,
    update_bulk_job_status,
    update_history_ocr_stats,
    get_bulk_file_count,
    update_source_file,
)

log = structlog.get_logger(__name__)


_IMAGE_EXTENSIONS_BW = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".eps"}


def _should_enqueue_for_analysis(source_path) -> bool:
    """Return True if source_path is an image file eligible for LLM vision analysis."""
    from pathlib import Path
    return Path(source_path).suffix.lower() in _IMAGE_EXTENSIONS_BW


# ── SSE progress queues (per bulk job_id) ────────────────────────────────────
_bulk_progress_queues: dict[str, asyncio.Queue] = {}


def get_bulk_progress_queue(job_id: str) -> asyncio.Queue | None:
    return _bulk_progress_queues.get(job_id)


def _emit_bulk_event(job_id: str, event: str, data: dict) -> None:
    q = _bulk_progress_queues.get(job_id)
    if q is not None:
        try:
            q.put_nowait({"event": event, "data": data})
        except asyncio.QueueFull:
            pass


# ── Job registry ─────────────────────────────────────────────────────────────
_active_jobs: dict[str, "BulkJob"] = {}


def get_active_job(job_id: str) -> "BulkJob | None":
    return _active_jobs.get(job_id)


def register_job(job: "BulkJob") -> None:
    _active_jobs[job.job_id] = job


def deregister_job(job_id: str) -> None:
    _active_jobs.pop(job_id, None)


# ── Path mapping helpers ─────────────────────────────────────────────────────

def _map_output_path(source_file: Path, source_root: Path, output_root: Path) -> Path:
    """Map source path to mirrored output path with .md extension."""
    relative = source_file.relative_to(source_root)
    return output_root / relative.with_suffix(".md")


def _map_sidecar_dir(output_md_path: Path) -> Path:
    """Sidecar dir is _markflow/ alongside the .md file."""
    return output_md_path.parent / "_markflow"


# ── OCR confidence pre-scan ──────────────────────────────────────────────────

async def _estimate_ocr_confidence(source_path: Path) -> float | None:
    """
    Quick pre-scan estimate for PDF files.

    Uses pdfplumber to check text density on the first 3 pages.
    Returns estimated confidence 0.0-100.0, or None if not a PDF or cannot read.

    - Text-native PDF (chars per page > threshold): return 95.0
    - Image-only PDF: run Tesseract OSD on first page for rough confidence
    - Non-PDF or unreadable: return None
    """
    if source_path.suffix.lower() != ".pdf":
        return None

    try:
        result = await asyncio.to_thread(_prescan_pdf_sync, source_path)
        return result
    except Exception as exc:
        log.warning("prescan_failed", source_path=str(source_path), error=str(exc))
        return None


def _prescan_pdf_sync(source_path: Path) -> float | None:
    """Synchronous pre-scan logic for PDF files."""
    import pdfplumber

    try:
        with pdfplumber.open(source_path) as pdf:
            pages_to_check = min(3, len(pdf.pages))
            if pages_to_check == 0:
                return None

            total_chars = 0
            for i in range(pages_to_check):
                page = pdf.pages[i]
                text = page.extract_text() or ""
                total_chars += len(text.strip())

            chars_per_page = total_chars / pages_to_check

            # If there's meaningful text, it's a text-native PDF
            if chars_per_page > 50:
                return 95.0

            # Image-only PDF — try Tesseract OSD for rough confidence
            try:
                return _osd_confidence(source_path)
            except Exception:
                return 30.0

    except Exception:
        return None


def _osd_confidence(source_path: Path) -> float:
    """Run Tesseract OSD on first page for orientation/script confidence."""
    import subprocess
    import tempfile

    try:
        from pdf2image import convert_from_path
    except ImportError:
        return 30.0

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            images = convert_from_path(
                str(source_path), first_page=1, last_page=1,
                output_folder=tmpdir, fmt="png", dpi=150,
            )
            if not images:
                return 30.0

            img_path = Path(tmpdir) / "osd_input.png"
            images[0].save(str(img_path))

            result = subprocess.run(
                ["tesseract", str(img_path), "stdout", "--psm", "0"],
                capture_output=True, text=True, timeout=15,
            )
            for line in result.stdout.splitlines():
                if "Script confidence" in line:
                    try:
                        return float(line.split(":")[-1].strip())
                    except ValueError:
                        pass
            return 50.0
    except Exception:
        return 30.0


# ── BulkJob ──────────────────────────────────────────────────────────────────

class BulkJob:
    def __init__(
        self,
        job_id: str,
        source_paths: list[Path] | Path,
        output_path: Path,
        worker_count: int = 4,
        fidelity_tier: int = 2,
        ocr_mode: str = "auto",
        include_adobe: bool = True,
        max_files: int | None = None,
        overrides: dict | None = None,
    ):
        self.job_id = job_id
        # Accept single path or list for backward compatibility
        if isinstance(source_paths, (str, Path)):
            self.source_paths = [Path(source_paths)]
        else:
            self.source_paths = [Path(p) for p in source_paths]
        self.source_path = self.source_paths[0]  # primary, for backward compat
        self.output_path = Path(output_path)
        self.worker_count = min(max(worker_count, 1), 16)
        self.fidelity_tier = fidelity_tier
        self.ocr_mode = ocr_mode
        self.include_adobe = include_adobe
        self.max_files = max_files  # Auto-conversion batch limit
        self.overrides = overrides or {}  # Per-job setting overrides

        self._queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._pause_event = asyncio.Event()
        self._cancel_event = asyncio.Event()
        self._pause_event.set()  # not paused initially

        # Error rate monitoring — abort early if source becomes unreachable
        self._error_monitor = ErrorRateMonitor()

        # Counters for SSE events
        self._converted = 0
        self._skipped = 0
        self._failed = 0
        self._adobe_indexed = 0
        self._total_pending = 0
        self._scanning = True  # True until scan phase completes
        self._skip_batch_count = 0
        self._review_queue_count = 0
        self._files_completed = 0  # Track total completed for max_files

        # Job metadata for active-jobs panel
        self.started_at: datetime | None = None
        self.options: dict = {
            "fidelity_tier": fidelity_tier,
            "ocr_enabled": ocr_mode != "skip",
            "ocr_mode": ocr_mode,
            "worker_count": self.worker_count,
            "include_adobe": include_adobe,
        }
        self.current_files: list[dict] = []   # [{worker_id, filename}]
        self.dir_stats: dict[str, dict] = {}  # top_dir -> {converted, failed, pending}

    async def run(self) -> None:
        """Full job lifecycle."""
        t_start = time.perf_counter()
        self.started_at = datetime.now(timezone.utc)

        register_job(self)
        register_task(self.job_id, asyncio.current_task())
        _bulk_progress_queues[self.job_id] = asyncio.Queue(maxsize=500)

        # Signal coordinator — cancels lifecycle scan, pauses run-now
        notify_bulk_started(job_id=self.job_id)

        try:
            # 1. Scanning phase — scan each source root sequentially
            await update_bulk_job_status(self.job_id, "scanning")

            async def _scan_progress_cb(event: dict):
                event_type = event.pop("event", "scan_progress")
                _emit_bulk_event(self.job_id, event_type, event)

            # Accumulate results across all source roots
            combined_result = ScanResult(job_id=self.job_id)
            self._resolved_paths: dict[str, tuple[str | None, str]] = {}

            for i, src_path in enumerate(self.source_paths):
                if self._cancel_event.is_set() or should_stop():
                    break

                if len(self.source_paths) > 1:
                    log.info("bulk_scan_root", job_id=self.job_id,
                             root_index=i + 1, total_roots=len(self.source_paths),
                             path=str(src_path))

                scanner = BulkScanner(self.job_id, src_path, self.output_path)
                scan_result = await scanner.scan(on_progress=_scan_progress_cb)

                # Merge results
                combined_result.total_discovered += scan_result.total_discovered
                combined_result.convertible_count += scan_result.convertible_count
                combined_result.adobe_count += scan_result.adobe_count
                combined_result.unrecognized_count += scan_result.unrecognized_count
                combined_result.skipped_count += scan_result.skipped_count
                combined_result.new_count += scan_result.new_count
                combined_result.changed_count += scan_result.changed_count
                combined_result.path_too_long_count += scan_result.path_too_long_count
                combined_result.collision_count += scan_result.collision_count
                combined_result.case_collision_count += scan_result.case_collision_count

                if scan_result.path_safety_result:
                    self._resolved_paths.update(scan_result.path_safety_result.resolved_paths)

            scan_result = combined_result

            # Emit scan_complete event
            _emit_bulk_event(self.job_id, "scan_complete", {
                "job_id": self.job_id,
                "total": scan_result.total_discovered,
                "convertible": scan_result.convertible_count,
                "adobe": scan_result.adobe_count,
                "skipped": scan_result.skipped_count,
                "new": scan_result.new_count,
                "changed": scan_result.changed_count,
                "path_too_long": scan_result.path_too_long_count,
                "collisions": scan_result.collision_count,
                "case_collisions": scan_result.case_collision_count,
                "unrecognized": scan_result.unrecognized_count,
            })

            # Emit path issues event if any
            total_issues = scan_result.path_too_long_count + scan_result.collision_count + scan_result.case_collision_count
            if total_issues > 0:
                strategy = await get_preference("collision_strategy") or "rename"
                _emit_bulk_event(self.job_id, "path_issues_found", {
                    "job_id": self.job_id,
                    "too_long": scan_result.path_too_long_count,
                    "collisions": scan_result.collision_count,
                    "case_collisions": scan_result.case_collision_count,
                    "total_affected": total_issues,
                    "strategy_applied": strategy,
                })

            # Update job totals
            self._scanning = False
            self._skipped = scan_result.skipped_count
            await update_bulk_job_status(
                self.job_id, "running",
                total_files=scan_result.total_discovered,
                skipped=scan_result.skipped_count,
            )

            # Record activity event for job start
            try:

                source_name = self.source_path.name if hasattr(self.source_path, 'name') else str(self.source_path)
                await record_activity_event("bulk_start", f"Bulk job started: {scan_result.total_discovered} files from {source_name}", {
                    "job_id": self.job_id, "file_count": scan_result.total_discovered, "source": str(self.source_path),
                })
            except Exception:
                pass

            # Initialize shared PasswordHandler for found-password reuse across files
            try:
                from core.password_handler import PasswordHandler
                from core.database import get_all_preferences
                pw_prefs = await get_all_preferences()
                self._password_handler = PasswordHandler(pw_prefs)
            except Exception:
                self._password_handler = None

            # 2. Enqueue pending files
            pending_files = await get_unprocessed_bulk_files(self.job_id)
            self._total_pending = len(pending_files)

            # Initialize ETA tracker (total known at this point)
            self._eta_tracker = RollingWindowETA(total=self._total_pending)
            self._last_eta_write = time.monotonic()

            for file_dict in pending_files:
                ext = file_dict["file_ext"]
                is_adobe = ext in ADOBE_EXTENSIONS
                if is_adobe and not self.include_adobe:
                    continue
                await self._queue.put(file_dict)

            # Sentinel values to signal workers to stop
            for _ in range(self.worker_count):
                await self._queue.put(None)

            # 3. Start workers
            workers = [
                asyncio.create_task(self._worker(i))
                for i in range(self.worker_count)
            ]
            await asyncio.gather(*workers)

            # 4. Final status
            if self._cancel_event.is_set():
                final_status = "cancelled"
                cancel_reason = getattr(self, '_cancel_reason', 'Cancelled by user')
            else:
                final_status = "completed"
                cancel_reason = None

            duration_ms = int((time.perf_counter() - t_start) * 1000)
            extra_fields = dict(completed_at=datetime.now(timezone.utc).isoformat())
            if cancel_reason:
                extra_fields["cancellation_reason"] = cancel_reason
            await update_bulk_job_status(self.job_id, final_status, **extra_fields)

            _emit_bulk_event(self.job_id, "job_complete", {
                "job_id": self.job_id,
                "converted": self._converted,
                "skipped": self._skipped,
                "failed": self._failed,
                "adobe_indexed": self._adobe_indexed,
                "review_queue_count": self._review_queue_count,
                "duration_ms": duration_ms,
            })
            _emit_bulk_event(self.job_id, "done", {})

            # Record activity event for job end
            try:

                elapsed_s = round(duration_ms / 1000, 1)
                await record_activity_event("bulk_end", f"Bulk job {final_status}: {self._converted}/{scan_result.total_discovered} files in {elapsed_s}s", {
                    "job_id": self.job_id, "converted": self._converted, "failed": self._failed,
                    "skipped": self._skipped, "duration": elapsed_s,
                }, duration_seconds=elapsed_s)
            except Exception:
                pass

        except Exception as exc:
            log.error("bulk_job_fatal", job_id=self.job_id, error=str(exc))
            await update_bulk_job_status(
                self.job_id, "failed",
                error_msg=str(exc),
                cancellation_reason=f"Fatal error: {str(exc)[:200]}",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            _emit_bulk_event(self.job_id, "done", {})
        finally:
            notify_bulk_completed(job_id=self.job_id)
            unregister_task(self.job_id)
            deregister_job(self.job_id)

    async def _worker(self, worker_id: int) -> None:
        """Pull from queue and process files until sentinel received."""
        log.debug("bulk_worker_start", job_id=self.job_id, worker_id=worker_id)

        while True:
            item = await self._queue.get()
            if item is None:
                break

            # Check global stop
            if should_stop():
                log.warning("bulk_worker_stopped", job_id=self.job_id, worker_id=worker_id)
                _emit_bulk_event(self.job_id, "job_stopped", {
                    "job_id": self.job_id, "reason": "global_stop_requested"})
                continue  # drain queue

            # Check error rate — abort if source is unreachable
            if self._error_monitor.should_abort():
                log.error("bulk_worker_error_rate_abort",
                          job_id=self.job_id, worker_id=worker_id,
                          error_rate=round(self._error_monitor.error_rate, 2),
                          total_errors=self._error_monitor.total_errors)
                _emit_bulk_event(self.job_id, "job_error_rate_abort", {
                    "job_id": self.job_id,
                    "error_rate": round(self._error_monitor.error_rate, 2),
                    "total_errors": self._error_monitor.total_errors,
                })
                self._cancel_reason = f"Aborted: error rate {round(self._error_monitor.error_rate * 100)}% exceeded threshold ({self._error_monitor.total_errors} errors)"
                self._cancel_event.set()
                self._pause_event.set()
                continue  # drain queue

            # Check cancel
            if self._cancel_event.is_set():
                continue  # drain queue

            # Wait on pause
            await self._pause_event.wait()

            # Check cancel again after resume
            if self._cancel_event.is_set():
                continue

            # Check global stop again after pause
            if should_stop():
                continue

            file_dict = item
            ext = file_dict["file_ext"]
            file_id = file_dict["id"]
            source_path = Path(file_dict["source_path"])

            # Track current worker_id for use in sub-methods
            self._current_worker_id = worker_id + 1

            # Track current file for active-jobs panel
            worker_entry = {"worker_id": worker_id + 1, "filename": source_path.name}
            self.current_files = [e for e in self.current_files if e["worker_id"] != worker_id + 1]
            self.current_files.append(worker_entry)

            # Emit file_start event so the UI can show what each worker is doing
            _emit_bulk_event(self.job_id, "file_start", {
                "job_id": self.job_id,
                "file_id": file_id,
                "filename": source_path.name,
                "relative_path": str(source_path),
                "worker_id": worker_id + 1,
            })

            try:
                # Pre-scan confidence check for PDFs in bulk mode
                if ext == ".pdf" and self.ocr_mode != "force":
                    skip_for_review = await self._check_confidence_prescan(file_dict)
                    if skip_for_review:
                        continue

                # Unified dispatch — all formats go through conversion pipeline
                # Check resolved_paths — skip files flagged by path safety
                resolved = self._resolved_paths.get(str(source_path))
                if resolved and resolved[0] is None:
                    skip_reason = resolved[1]
                    log.debug("bulk_worker_path_skip", file_id=file_id,
                              reason=skip_reason)
                    await db_write_with_retry(lambda fid=file_id, sr=skip_reason: update_bulk_file(
                        fid, status="skipped", skip_reason=sr,
                    ))
                    self._skipped += 1
                    await db_write_with_retry(lambda: increment_bulk_job_counter(self.job_id, "skipped"))
                    continue
                await self._process_convertible(file_dict, worker_id)
                self._error_monitor.record_success()
            except Exception as exc:
                self._error_monitor.record_error(str(exc))
                log.error(
                    "bulk_worker_unhandled",
                    job_id=self.job_id,
                    file_id=file_id,
                    error=str(exc),
                )
                await db_write_with_retry(lambda: update_bulk_file(
                    file_id,
                    status="failed",
                    error_msg=str(exc),
                ))
                self._failed += 1
                await db_write_with_retry(lambda: increment_bulk_job_counter(self.job_id, "failed"))

                _emit_bulk_event(self.job_id, "file_failed", {
                    "job_id": self.job_id,
                    "file_id": file_id,
                    "source_path": str(source_path),
                    "error": str(exc),
                    "failed": self._failed,
                    "worker_id": worker_id + 1,
                })
            finally:
                # Clear worker from current_files
                self.current_files = [e for e in self.current_files if e["worker_id"] != worker_id + 1]

                # Record completion for ETA tracking
                await self._eta_tracker.record_completion()
                now = time.monotonic()
                if now - self._last_eta_write >= ETA_UPDATE_INTERVAL:
                    snap = await self._eta_tracker.snapshot()
                    _emit_bulk_event(self.job_id, "progress_update", {
                        "job_id": self.job_id,
                        "completed": snap.completed,
                        "total": snap.total,
                        "eta_seconds": round(snap.eta_seconds, 1) if snap.eta_seconds is not None else None,
                        "eta_human": format_eta(snap.eta_seconds),
                        "files_per_second": round(snap.files_per_second, 2) if snap.files_per_second else None,
                        "percent": snap.to_dict()["percent"],
                    })
                    try:
                        await db_write_with_retry(lambda: update_bulk_job_status(
                            self.job_id, "running",
                            eta_seconds=snap.eta_seconds,
                            files_per_second=snap.files_per_second,
                            eta_updated_at=datetime.now(timezone.utc).isoformat(),
                        ))
                    except Exception:
                        pass  # ETA DB write is non-critical
                    log.info("bulk_progress",
                             job_id=self.job_id,
                             completed=snap.completed,
                             total=snap.total,
                             eta_seconds=snap.eta_seconds,
                             files_per_second=snap.files_per_second)
                    self._last_eta_write = now

                # Check max_files limit (auto-conversion batch cap)
                self._files_completed += 1
                if self.max_files and self._files_completed >= self.max_files:
                    log.info(
                        "bulk_worker_max_files_reached",
                        job_id=self.job_id,
                        max_files=self.max_files,
                        completed=self._files_completed,
                    )
                    self._cancel_event.set()
                    self._pause_event.set()
                    break

        log.debug("bulk_worker_stop", job_id=self.job_id, worker_id=worker_id)

    async def _check_confidence_prescan(self, file_dict: dict) -> bool:
        """
        Pre-scan a PDF's estimated OCR confidence.
        Returns True if the file was skipped for review, False to proceed.
        """
        file_id = file_dict["id"]
        source_path = Path(file_dict["source_path"])

        estimated_conf = await _estimate_ocr_confidence(source_path)
        if estimated_conf is None:
            return False  # Can't estimate — proceed normally

        threshold_str = await get_preference("ocr_confidence_threshold") or "70"
        threshold = float(threshold_str)

        if estimated_conf >= threshold:
            return False  # Above threshold — proceed normally

        # Below threshold — skip and queue for review
        await add_to_review_queue(
            job_id=self.job_id,
            bulk_file_id=file_id,
            source_path=str(source_path),
            file_ext=file_dict["file_ext"],
            estimated_confidence=estimated_conf,
            skip_reason="below_threshold",
        )
        await update_bulk_file(
            file_id,
            status="skipped",
            ocr_skipped_reason="below_threshold",
            ocr_confidence_mean=estimated_conf,
            skip_reason=f"OCR confidence {estimated_conf:.0f}% below threshold {threshold:.0f}%",
        )
        # Propagate OCR confidence to source_files
        sf_id = file_dict.get("source_file_id")
        if sf_id:
            await update_source_file(sf_id, ocr_confidence_mean=estimated_conf)

        await increment_bulk_job_counter(self.job_id, "skipped")
        await increment_bulk_job_counter(self.job_id, "review_queue_count")
        self._skipped += 1
        self._review_queue_count += 1

        pending_review = await get_review_queue_count(self.job_id, status="pending")
        _emit_bulk_event(self.job_id, "file_skipped_for_review", {
            "job_id": self.job_id,
            "file_id": file_id,
            "source_path": str(source_path),
            "estimated_confidence": estimated_conf,
            "threshold": threshold,
            "review_queue_total": pending_review,
            "worker_id": self._current_worker_id,
        })

        log.info(
            "bulk_file_skipped_for_review",
            job_id=self.job_id, file_id=file_id,
            estimated_confidence=estimated_conf, threshold=threshold,
        )
        return True

    async def _process_convertible(self, file_dict: dict, worker_id: int = 0) -> None:
        """Convert a single file using ConversionOrchestrator internals."""
        from core.converter import _convert_file_sync

        file_id = file_dict["id"]
        source_path = Path(file_dict["source_path"])
        source_mtime = file_dict["source_mtime"]

        output_md = _map_output_path(source_path, self.source_path, self.output_path)
        sidecar_dir = _map_sidecar_dir(output_md)

        # Create output dirs
        output_md.parent.mkdir(parents=True, exist_ok=True)
        sidecar_dir.mkdir(parents=True, exist_ok=True)

        t_start = time.perf_counter()

        # Run sync conversion in thread (with shared PasswordHandler for batch reuse)
        convert_opts = {"fidelity_tier": self.fidelity_tier, "ocr_mode": self.ocr_mode}
        if self._password_handler:
            convert_opts["_password_handler"] = self._password_handler
        # Wait for cloud prefetch if enabled
        from core.cloud_prefetch import get_prefetch_manager
        pfx = get_prefetch_manager()
        if pfx is not None:
            pfx_status = await pfx.wait_for(source_path)
            if pfx_status.value == "failed":
                log.warning("cloud_prefetch_wait_failed", path=str(source_path),
                            hint="attempting conversion anyway")

        result = await asyncio.to_thread(
            _convert_file_sync,
            source_path,
            "to_md",
            self.job_id,
            output_md.parent,  # output_dir — the converter creates batch_id subdir
            convert_opts,
        )

        duration_ms = int((time.perf_counter() - t_start) * 1000)

        # Track dir_stats for top-level subdirectory
        try:
            rel_parts = source_path.relative_to(self.source_path).parts
            top_dir = rel_parts[0] if len(rel_parts) > 1 else "(root)"
        except ValueError:
            top_dir = "(root)"
        self.dir_stats.setdefault(top_dir, {"converted": 0, "failed": 0, "pending": 0})

        if result.status == "success":
            # Compute content hash of output
            content_hash = None
            actual_output = Path(result.output_path) if result.output_path else None
            if actual_output and actual_output.exists():
                content_hash = hashlib.sha256(
                    actual_output.read_bytes()
                ).hexdigest()

            await db_write_with_retry(lambda: update_bulk_file(
                file_id,
                status="converted",
                output_path=result.output_path,
                stored_mtime=source_mtime,
                content_hash=content_hash,
                converted_at=datetime.now(timezone.utc).isoformat(),
            ))

            # Propagate file-intrinsic data to source_files
            sf_id = file_dict.get("source_file_id")
            if sf_id:
                sf_fields: dict[str, Any] = {}
                if result.output_path:
                    sf_fields["output_path"] = result.output_path
                if content_hash:
                    sf_fields["content_hash"] = content_hash
                if source_mtime:
                    sf_fields["stored_mtime"] = source_mtime
                if sf_fields:
                    await db_write_with_retry(lambda: update_source_file(sf_id, **sf_fields))

            self._converted += 1
            self.dir_stats[top_dir]["converted"] += 1
            await db_write_with_retry(lambda: increment_bulk_job_counter(self.job_id, "converted"))

            _emit_bulk_event(self.job_id, "file_converted", {
                "job_id": self.job_id,
                "file_id": file_id,
                "source_path": str(source_path),
                "status": "converted",
                "duration_ms": duration_ms,
                "tier": result.fidelity_tier,
                "converted": self._converted,
                "total": self._total_pending,
                "worker_id": worker_id + 1,
            })

            # Index in Meilisearch (best-effort)
            try:
                from core.search_indexer import get_search_indexer
                indexer = get_search_indexer()
                if indexer and actual_output and actual_output.exists():
                    await indexer.index_document(actual_output, self.job_id)

                    # Also index transcript if this was a media file
                    from formats.audio_handler import AudioHandler
                    from formats.media_handler import MediaHandler
                    _media_exts = {"." + e for e in AudioHandler.EXTENSIONS + MediaHandler.EXTENSIONS}
                    if source_path.suffix.lower() in _media_exts:
                        md_content = actual_output.read_text(encoding="utf-8")
                        await indexer.index_transcript(
                            history_id=str(file_id),
                            title=source_path.stem,
                            raw_text=md_content,
                            source_path=str(source_path),
                            source_format=source_path.suffix.lstrip("."),
                            duration_seconds=None,
                            engine="unknown",
                            whisper_model=None,
                            language=None,
                            word_count=len(md_content.split()),
                        )
                        await db_write_with_retry(
                            lambda: increment_bulk_job_counter(self.job_id, "transcribed")
                        )
            except Exception as exc:
                log.warning("bulk_meili_index_fail", file_id=file_id, error=str(exc))

            # Enqueue image files for LLM vision analysis
            if _should_enqueue_for_analysis(source_path):
                try:
                    from core.db.analysis import enqueue_for_analysis
                    await enqueue_for_analysis(
                        source_path=str(source_path),
                        content_hash=file_dict.get("content_hash"),
                        job_id=self.job_id,
                    )
                except Exception as exc:
                    log.warning(
                        "bulk_worker.analysis_enqueue_failed",
                        path=str(source_path),
                        error=str(exc),
                    )

        else:
            await db_write_with_retry(lambda: update_bulk_file(
                file_id,
                status="failed",
                error_msg=result.error_message,
            ))
            self._failed += 1
            self.dir_stats[top_dir]["failed"] += 1
            await db_write_with_retry(lambda: increment_bulk_job_counter(self.job_id, "failed"))

            _emit_bulk_event(self.job_id, "file_failed", {
                "job_id": self.job_id,
                "file_id": file_id,
                "source_path": str(source_path),
                "error": result.error_message or "Unknown error",
                "failed": self._failed,
                "worker_id": worker_id + 1,
            })

    async def _process_adobe(self, file_dict: dict, worker_id: int = 0) -> None:
        """Index an Adobe file."""
        from core.adobe_indexer import AdobeIndexer

        file_id = file_dict["id"]
        source_path = Path(file_dict["source_path"])

        indexer = AdobeIndexer()
        result = await indexer.index_file(source_path)

        if result.success:
            await update_bulk_file(
                file_id,
                status="adobe_indexed",
                indexed_at=datetime.now(timezone.utc).isoformat(),
            )
            self._adobe_indexed += 1
            await increment_bulk_job_counter(self.job_id, "adobe_indexed")

            _emit_bulk_event(self.job_id, "adobe_indexed", {
                "job_id": self.job_id,
                "file_id": file_id,
                "source_path": str(source_path),
                "format": result.file_ext,
                "adobe_indexed": self._adobe_indexed,
            })

            # Index in Meilisearch (best-effort)
            try:
                from core.search_indexer import get_search_indexer
                search_indexer = get_search_indexer()
                if search_indexer:
                    await search_indexer.index_adobe_file(result, self.job_id)
            except Exception as exc:
                log.warning("bulk_meili_adobe_fail", file_id=file_id, error=str(exc))
        else:
            await update_bulk_file(
                file_id,
                status="adobe_failed",
                error_msg=result.error_msg,
            )
            self._failed += 1
            await increment_bulk_job_counter(self.job_id, "failed")

            _emit_bulk_event(self.job_id, "file_failed", {
                "job_id": self.job_id,
                "file_id": file_id,
                "source_path": str(source_path),
                "error": result.error_msg or "Adobe indexing failed",
                "failed": self._failed,
                "worker_id": worker_id + 1,
            })

    async def pause(self) -> None:
        """Pause all workers."""
        self._pause_event.clear()
        await update_bulk_job_status(
            self.job_id, "paused",
            paused_at=datetime.now(timezone.utc).isoformat(),
        )
        remaining = self._total_pending - self._converted - self._failed
        _emit_bulk_event(self.job_id, "job_paused", {
            "job_id": self.job_id,
            "converted": self._converted,
            "remaining": max(0, remaining),
        })
        log.info("bulk_job_paused", job_id=self.job_id)

    async def resume(self) -> None:
        """Resume paused workers."""
        self._pause_event.set()
        await update_bulk_job_status(self.job_id, "running")
        _emit_bulk_event(self.job_id, "job_resumed", {"job_id": self.job_id})
        log.info("bulk_job_resumed", job_id=self.job_id)

    async def cancel(self, reason: str = "Cancelled by user") -> None:
        """Cancel the job. Workers drain queue and exit."""
        self._cancel_reason = reason
        self._cancel_event.set()
        self._pause_event.set()  # unblock any paused workers so they can drain
        await update_bulk_job_status(self.job_id, "cancelled")
        log.info("bulk_job_cancelled", job_id=self.job_id, reason=reason)


# ── Gap-Fill SSE queues ────────────────────────────────────────────────────
_gap_fill_queues: dict[str, asyncio.Queue] = {}

_active_gap_fills: dict[str, "BulkOcrGapFillJob"] = {}


def get_gap_fill_queue(gap_fill_id: str) -> asyncio.Queue | None:
    return _gap_fill_queues.get(gap_fill_id)


class BulkOcrGapFillJob:
    """
    Scans conversion_history for PDFs converted without OCR stats.
    Runs OCR on each and updates the history record.
    """

    def __init__(
        self,
        gap_fill_id: str,
        job_id: str | None = None,
        worker_count: int = 2,
        dry_run: bool = False,
    ):
        self.gap_fill_id = gap_fill_id
        self.job_id = job_id
        self.worker_count = min(max(worker_count, 1), 8)
        self.dry_run = dry_run

        self._queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._cancel_event = asyncio.Event()

        self._processed = 0
        self._failed = 0
        self._total = 0

    async def run(self) -> dict:
        """Full gap-fill lifecycle. Returns summary dict."""
        t_start = time.perf_counter()
        _active_gap_fills[self.gap_fill_id] = self
        _gap_fill_queues[self.gap_fill_id] = asyncio.Queue(maxsize=500)

        try:
            candidates = await get_ocr_gap_fill_candidates(self.job_id)

            # Filter: source file must still exist and output .md must exist
            valid = []
            for rec in candidates:
                source = Path(rec["source_path"]) if rec.get("source_path") else None
                output = Path(rec["output_path"]) if rec.get("output_path") else None
                if source and source.exists() and output and output.exists():
                    valid.append(rec)

            self._total = len(valid)

            if self.dry_run:
                return {
                    "gap_fill_id": self.gap_fill_id,
                    "files_found": self._total,
                    "dry_run": True,
                }

            # Enqueue
            for rec in valid:
                await self._queue.put(rec)
            for _ in range(self.worker_count):
                await self._queue.put(None)

            _emit_gap_fill_event(self.gap_fill_id, "gap_fill_start", {
                "gap_fill_id": self.gap_fill_id,
                "total": self._total,
            })

            # Start workers
            workers = [
                asyncio.create_task(self._worker(i))
                for i in range(self.worker_count)
            ]
            await asyncio.gather(*workers)

            duration_ms = int((time.perf_counter() - t_start) * 1000)

            _emit_gap_fill_event(self.gap_fill_id, "gap_fill_complete", {
                "gap_fill_id": self.gap_fill_id,
                "processed": self._processed,
                "failed": self._failed,
                "total": self._total,
                "duration_ms": duration_ms,
            })
            _emit_gap_fill_event(self.gap_fill_id, "done", {})

            return {
                "gap_fill_id": self.gap_fill_id,
                "processed": self._processed,
                "failed": self._failed,
                "total": self._total,
                "duration_ms": duration_ms,
            }

        except Exception as exc:
            log.error("gap_fill_fatal", gap_fill_id=self.gap_fill_id, error=str(exc))
            _emit_gap_fill_event(self.gap_fill_id, "done", {})
            return {
                "gap_fill_id": self.gap_fill_id,
                "error": str(exc),
            }
        finally:
            _active_gap_fills.pop(self.gap_fill_id, None)

    async def _worker(self, worker_id: int) -> None:
        while True:
            item = await self._queue.get()
            if item is None:
                break
            if self._cancel_event.is_set():
                continue

            history_id = item["id"]
            source_path = Path(item["source_path"])
            filename = item["source_filename"]

            try:
                await self._run_ocr_on_file(history_id, source_path, filename, item["batch_id"])
                self._processed += 1

                _emit_gap_fill_event(self.gap_fill_id, "ocr_gap_filled", {
                    "gap_fill_id": self.gap_fill_id,
                    "history_id": history_id,
                    "filename": filename,
                    "processed": self._processed,
                    "total": self._total,
                })
            except Exception as exc:
                self._failed += 1
                log.warning("gap_fill_file_failed", history_id=history_id, error=str(exc))

                _emit_gap_fill_event(self.gap_fill_id, "ocr_gap_fill_failed", {
                    "gap_fill_id": self.gap_fill_id,
                    "history_id": history_id,
                    "filename": filename,
                    "error": str(exc),
                    "failed": self._failed,
                })

    async def _run_ocr_on_file(
        self, history_id: int, source_path: Path, filename: str, batch_id: str
    ) -> None:
        """Run OCR on a single PDF and update history stats."""
        from formats.pdf_handler import PdfHandler
        from core.ocr import run_ocr, OCRConfig

        handler = PdfHandler()
        model = await asyncio.to_thread(handler.ingest_with_ocr, source_path, None, batch_id)

        scanned_pages = getattr(model, "_scanned_pages", [])
        if not scanned_pages:
            # No scanned pages — mark as checked (page_count=0 so it won't be a candidate again)
            await update_history_ocr_stats(
                history_id=history_id, mean=100.0, min_conf=100.0,
                page_count=0, pages_below=0,
            )
            return

        threshold_str = await get_preference("ocr_confidence_threshold") or "80"
        unattended_str = await get_preference("unattended_default") or "false"

        config = OCRConfig(
            confidence_threshold=float(threshold_str),
            unattended=(unattended_str == "true"),
        )
        ocr_result = await run_ocr(scanned_pages, config, batch_id, filename)

        valid_confs = [
            w.confidence for p in ocr_result.pages for w in p.words if w.confidence >= 0
        ]
        if valid_confs:
            await update_history_ocr_stats(
                history_id=history_id,
                mean=round(sum(valid_confs) / len(valid_confs), 1),
                min_conf=round(min(valid_confs), 1),
                page_count=len(ocr_result.pages),
                pages_below=sum(
                    1 for c in valid_confs if c < config.confidence_threshold
                ),
            )
        else:
            await update_history_ocr_stats(
                history_id=history_id, mean=0.0, min_conf=0.0,
                page_count=len(ocr_result.pages), pages_below=len(ocr_result.pages),
            )

        log.info(
            "gap_fill_ocr_complete",
            history_id=history_id,
            filename=filename,
            pages=len(ocr_result.pages),
            flags=len(ocr_result.flags),
        )

    async def cancel(self) -> None:
        self._cancel_event.set()


def _emit_gap_fill_event(gap_fill_id: str, event: str, data: dict) -> None:
    q = _gap_fill_queues.get(gap_fill_id)
    if q is not None:
        try:
            q.put_nowait({"event": event, "data": data})
        except asyncio.QueueFull:
            pass


# ── Active jobs serialization ──────────────────────────────────────────────

async def get_all_active_jobs() -> list[dict]:
    """Return serialized state of all jobs in the registry (active + recently finished)."""
    results = []
    for job in _active_jobs.values():
        # Determine status string
        if job._cancel_event.is_set():
            status = "cancelled"
        elif not job._pause_event.is_set():
            status = "paused"
        elif job._scanning:
            status = "scanning"
        elif job._total_pending > 0 and job._converted + job._failed + job._skipped < job._total_pending:
            status = "running"
        else:
            status = "done"

        # Build progress snapshot
        completed = job._converted + job._failed + job._skipped
        snap = job._eta_tracker.snapshot_sync() if hasattr(job, '_eta_tracker') else None
        progress = {
            "completed": completed,
            "total": job._total_pending,
            "count_ready": True,
            "eta_seconds": round(snap.eta_seconds, 1) if snap and snap.eta_seconds is not None else None,
            "files_per_second": round(snap.files_per_second, 2) if snap and snap.files_per_second else None,
            "eta_human": format_eta(snap.eta_seconds) if snap else None,
            "percent": round(min(100.0, completed / job._total_pending * 100), 1) if job._total_pending > 0 else None,
        }

        results.append({
            "job_id":        job.job_id,
            "status":        status,
            "source_path":   str(job.source_path),
            "output_path":   str(job.output_path),
            "total_files":   job._total_pending,
            "converted":     job._converted,
            "failed":        job._failed,
            "skipped":       job._skipped,
            "current_files": list(job.current_files),
            "started_at":    job.started_at.isoformat() if job.started_at else None,
            "options":       job.options,
            "dir_stats":     dict(job.dir_stats),
            "progress":      progress,
        })
    return results
