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

from core.bulk_scanner import (
    ADOBE_EXTENSIONS,
    CONVERTIBLE_EXTENSIONS,
    BulkFileRecord,
    BulkScanner,
)
from core.database import (
    add_to_review_queue,
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
)

log = structlog.get_logger(__name__)

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
        source_path: Path,
        output_path: Path,
        worker_count: int = 4,
        fidelity_tier: int = 2,
        ocr_mode: str = "auto",
        include_adobe: bool = True,
    ):
        self.job_id = job_id
        self.source_path = Path(source_path)
        self.output_path = Path(output_path)
        self.worker_count = min(max(worker_count, 1), 16)
        self.fidelity_tier = fidelity_tier
        self.ocr_mode = ocr_mode
        self.include_adobe = include_adobe

        self._queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._pause_event = asyncio.Event()
        self._cancel_event = asyncio.Event()
        self._pause_event.set()  # not paused initially

        # Counters for SSE events
        self._converted = 0
        self._skipped = 0
        self._failed = 0
        self._adobe_indexed = 0
        self._total_pending = 0
        self._skip_batch_count = 0
        self._review_queue_count = 0

    async def run(self) -> None:
        """Full job lifecycle."""
        t_start = time.perf_counter()

        register_job(self)
        _bulk_progress_queues[self.job_id] = asyncio.Queue(maxsize=500)

        try:
            # 1. Scanning phase
            await update_bulk_job_status(self.job_id, "scanning")
            scanner = BulkScanner(self.job_id, self.source_path, self.output_path)
            scan_result = await scanner.scan()

            # Store resolved paths for workers
            self._resolved_paths: dict[str, tuple[str | None, str]] = {}
            if scan_result.path_safety_result:
                self._resolved_paths = scan_result.path_safety_result.resolved_paths

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
            self._skipped = scan_result.skipped_count
            await update_bulk_job_status(
                self.job_id, "running",
                total_files=scan_result.total_discovered,
                skipped=scan_result.skipped_count,
            )

            # 2. Enqueue pending files
            pending_files = await get_unprocessed_bulk_files(self.job_id)
            self._total_pending = len(pending_files)

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
            else:
                final_status = "completed"

            duration_ms = int((time.perf_counter() - t_start) * 1000)
            await update_bulk_job_status(
                self.job_id, final_status,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

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

        except Exception as exc:
            log.error("bulk_job_fatal", job_id=self.job_id, error=str(exc))
            await update_bulk_job_status(
                self.job_id, "failed",
                error_msg=str(exc),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            _emit_bulk_event(self.job_id, "done", {})
        finally:
            deregister_job(self.job_id)

    async def _worker(self, worker_id: int) -> None:
        """Pull from queue and process files until sentinel received."""
        log.debug("bulk_worker_start", job_id=self.job_id, worker_id=worker_id)

        while True:
            item = await self._queue.get()
            if item is None:
                break

            # Check cancel
            if self._cancel_event.is_set():
                continue  # drain queue

            # Wait on pause
            await self._pause_event.wait()

            # Check cancel again after resume
            if self._cancel_event.is_set():
                continue

            file_dict = item
            ext = file_dict["file_ext"]
            file_id = file_dict["id"]
            source_path = Path(file_dict["source_path"])

            try:
                # Pre-scan confidence check for PDFs in bulk mode
                if ext == ".pdf" and self.ocr_mode != "force":
                    skip_for_review = await self._check_confidence_prescan(file_dict)
                    if skip_for_review:
                        continue

                if ext in ADOBE_EXTENSIONS:
                    await self._process_adobe(file_dict)
                elif ext in CONVERTIBLE_EXTENSIONS:
                    # Check resolved_paths — skip files flagged by path safety
                    resolved = self._resolved_paths.get(str(source_path))
                    if resolved and resolved[0] is None:
                        # File was flagged (too long, collision skip/error)
                        log.debug("bulk_worker_path_skip", file_id=file_id,
                                  reason=resolved[1])
                        continue
                    await self._process_convertible(file_dict)
            except Exception as exc:
                log.error(
                    "bulk_worker_unhandled",
                    job_id=self.job_id,
                    file_id=file_id,
                    error=str(exc),
                )
                await update_bulk_file(
                    file_id,
                    status="failed",
                    error_msg=str(exc),
                )
                self._failed += 1
                await increment_bulk_job_counter(self.job_id, "failed")

                _emit_bulk_event(self.job_id, "file_failed", {
                    "job_id": self.job_id,
                    "file_id": file_id,
                    "source_path": str(source_path),
                    "error": str(exc),
                    "failed": self._failed,
                })

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
        )
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
        })

        log.info(
            "bulk_file_skipped_for_review",
            job_id=self.job_id, file_id=file_id,
            estimated_confidence=estimated_conf, threshold=threshold,
        )
        return True

    async def _process_convertible(self, file_dict: dict) -> None:
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

        # Run sync conversion in thread
        result = await asyncio.to_thread(
            _convert_file_sync,
            source_path,
            "to_md",
            self.job_id,
            output_md.parent,  # output_dir — the converter creates batch_id subdir
            {"fidelity_tier": self.fidelity_tier, "ocr_mode": self.ocr_mode},
        )

        duration_ms = int((time.perf_counter() - t_start) * 1000)

        if result.status == "success":
            # Compute content hash of output
            content_hash = None
            actual_output = Path(result.output_path) if result.output_path else None
            if actual_output and actual_output.exists():
                content_hash = hashlib.sha256(
                    actual_output.read_bytes()
                ).hexdigest()

            await update_bulk_file(
                file_id,
                status="converted",
                output_path=result.output_path,
                stored_mtime=source_mtime,
                content_hash=content_hash,
                converted_at=datetime.now(timezone.utc).isoformat(),
            )
            self._converted += 1
            await increment_bulk_job_counter(self.job_id, "converted")

            _emit_bulk_event(self.job_id, "file_converted", {
                "job_id": self.job_id,
                "file_id": file_id,
                "source_path": str(source_path),
                "status": "converted",
                "duration_ms": duration_ms,
                "tier": result.fidelity_tier,
                "converted": self._converted,
                "total": self._total_pending,
            })

            # Index in Meilisearch (best-effort)
            try:
                from core.search_indexer import get_search_indexer
                indexer = get_search_indexer()
                if indexer and actual_output and actual_output.exists():
                    await indexer.index_document(actual_output, self.job_id)
            except Exception as exc:
                log.warning("bulk_meili_index_fail", file_id=file_id, error=str(exc))

        else:
            await update_bulk_file(
                file_id,
                status="failed",
                error_msg=result.error_message,
            )
            self._failed += 1
            await increment_bulk_job_counter(self.job_id, "failed")

            _emit_bulk_event(self.job_id, "file_failed", {
                "job_id": self.job_id,
                "file_id": file_id,
                "source_path": str(source_path),
                "error": result.error_message or "Unknown error",
                "failed": self._failed,
            })

    async def _process_adobe(self, file_dict: dict) -> None:
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

    async def cancel(self) -> None:
        """Cancel the job. Workers drain queue and exit."""
        self._cancel_event.set()
        self._pause_event.set()  # unblock any paused workers so they can drain
        await update_bulk_job_status(self.job_id, "cancelled")
        log.info("bulk_job_cancelled", job_id=self.job_id)


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
