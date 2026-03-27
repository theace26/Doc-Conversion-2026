"""
Conversion orchestration and concurrency management.

ConversionOrchestrator manages the full pipeline:
  validate → detect format → extract (ingest or parse MD) → build model
  → extract styles → generate output → write metadata → record in DB

Uses asyncio.to_thread() for CPU-bound work and a ProcessPoolExecutor
with max 3 concurrent conversions.
"""

import asyncio
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from core.database import (
    db_execute,
    get_flags_for_batch,
    get_preference,
    record_conversion,
    update_history_ocr_stats,
    upsert_batch_state,
)
from core.logging_config import bind_batch_context, bind_file_context
from core.metadata import generate_manifest, generate_sidecar
import formats  # noqa: F401 — triggers handler self-registration
from formats.base import get_handler_for_path

log = structlog.get_logger(__name__)

# ── SSE progress queues (per batch_id) ────────────────────────────────────────
_progress_queues: dict[str, asyncio.Queue] = {}

def get_progress_queue(batch_id: str) -> asyncio.Queue | None:
    """Return the progress queue for a batch, or None if not active."""
    return _progress_queues.get(batch_id)

def _emit_event(batch_id: str, event: str, data: dict) -> None:
    """Put an SSE event into the batch's progress queue (non-blocking)."""
    q = _progress_queues.get(batch_id)
    if q is not None:
        try:
            q.put_nowait({"event": event, "data": data})
        except asyncio.QueueFull:
            pass  # drop event if queue is full (shouldn't happen)

# Allowed extensions for upload
ALLOWED_EXTENSIONS = {".docx", ".doc", ".pdf", ".pptx", ".xlsx", ".csv", ".tsv", ".md"}

# Max file sizes (in bytes)
DEFAULT_MAX_FILE_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
DEFAULT_MAX_BATCH_MB = int(os.getenv("MAX_BATCH_MB", "500"))

# Output base directory
OUTPUT_BASE = Path(os.getenv("OUTPUT_DIR", "output"))

# Zip-bomb threshold: reject if uncompressed > 200× compressed.
# Normal DOCX (XML) can legitimately reach 20-50×; real zip bombs are 1000×+.
ZIP_BOMB_RATIO = 200

# Semaphore limiting concurrent CPU-bound conversions
_semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_CONVERSIONS", "3")))


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ConvertResult:
    source_filename: str
    output_filename: str
    source_format: str
    output_format: str
    direction: str
    batch_id: str
    status: str = "success"
    error_message: str | None = None
    output_path: str = ""
    source_path: str = ""
    file_size_bytes: int = 0
    ocr_applied: bool = False
    ocr_flags_total: int = 0
    fidelity_tier: int = 1
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0
    protection_type: str = "none"
    password_method: str | None = None
    password_attempts: int = 0


@dataclass
class PreviewResult:
    filename: str
    format: str
    file_size_bytes: int
    page_count: int | None = None
    ocr_likely: bool = False
    warnings: list[str] = field(default_factory=list)
    element_counts: dict[str, int] = field(default_factory=dict)


# ── Validation helpers ────────────────────────────────────────────────────────

def validate_extension(filename: str) -> str | None:
    """Return error message if extension is not allowed, else None."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
    return None


def validate_file_size(size_bytes: int, max_mb: int = DEFAULT_MAX_FILE_MB) -> str | None:
    """Return error message if file exceeds size limit, else None."""
    max_bytes = max_mb * 1024 * 1024
    if size_bytes > max_bytes:
        return f"File too large ({size_bytes // 1024 // 1024} MB). Limit: {max_mb} MB."
    return None


def check_zip_bomb(file_path: Path) -> str | None:
    """
    For zip-based formats (.docx, .pptx, .xlsx), check uncompressed-to-compressed ratio.
    Returns error string if suspicious, None if OK.
    """
    import zipfile

    zip_exts = {".docx", ".pptx", ".xlsx"}
    if file_path.suffix.lower() not in zip_exts:
        return None

    try:
        with zipfile.ZipFile(file_path) as zf:
            compressed = file_path.stat().st_size
            uncompressed = sum(info.file_size for info in zf.infolist())
            if compressed > 0 and uncompressed / compressed > ZIP_BOMB_RATIO:
                return (
                    f"File rejected: suspicious compression ratio "
                    f"({uncompressed / compressed:.0f}×). Possible zip bomb."
                )
    except zipfile.BadZipFile:
        return "File is not a valid zip-based document."
    except Exception:
        pass  # If we can't check, allow it

    return None


def sanitize_filename(name: str) -> str:
    """Remove path traversal and special characters from a filename."""
    import re

    # Extract basename only
    name = Path(name).name
    # Replace dangerous characters
    name = re.sub(r"[^\w\s\-.]", "_", name)
    name = name.strip(". ")
    return name or "file"


# ── Batch ID generation ────────────────────────────────────────────────────────

def new_batch_id() -> str:
    """Generate a timestamped batch ID."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:20]


# ── Synchronous pipeline (runs in thread) ─────────────────────────────────────

def _convert_file_sync(
    file_path: Path,
    direction: str,
    batch_id: str,
    output_dir: Path,
    options: dict[str, Any],
) -> ConvertResult:
    """
    Full conversion pipeline (synchronous — runs in asyncio.to_thread).

    direction: "to_md" or "from_md"
    """
    t_start = time.perf_counter()
    source_filename = file_path.name
    source_format = file_path.suffix.lower().lstrip(".")
    warnings: list[str] = []

    log.info(
        "file_ingest_start",
        filename=source_filename,
        format=source_format,
        size_bytes=file_path.stat().st_size if file_path.exists() else 0,
    )

    pw_result = None
    working_path = file_path

    try:
        # ── Get format handler ────────────────────────────────────────────
        handler = get_handler_for_path(file_path)
        if handler is None:
            raise ValueError(f"No handler registered for .{source_format}")

        # ── Password handling (preprocess before ingest) ──────────────────
        from core.password_handler import PasswordHandler, ProtectionType
        pw_handler = options.get("_password_handler")
        if pw_handler is None:
            pw_handler = PasswordHandler(options.get("_password_settings", {}))
        user_password = options.get("password")
        pw_result = pw_handler.handle_sync(file_path, user_password=user_password)

        if not pw_result.success:
            raise ValueError(f"Password-protected file could not be unlocked: {pw_result.error}")
        working_path = pw_result.output_path or file_path

        if pw_result.protection_type == ProtectionType.RESTRICTION_ONLY:
            warnings.append("Edit/print restrictions removed automatically")
        elif pw_result.protection_type == ProtectionType.ENCRYPTED_DECRYPTED:
            warnings.append(f"File decrypted via {pw_result.method.value} ({pw_result.attempts} attempts)")

        # ── Ingest ────────────────────────────────────────────────────────
        t_ingest = time.perf_counter()
        model = handler.ingest(working_path)
        model.metadata.source_file = source_filename
        model.metadata.source_format = source_format
        model.metadata.converted_at = datetime.now(timezone.utc).isoformat()
        warnings.extend(model.warnings)

        ingest_duration = int((time.perf_counter() - t_ingest) * 1000)
        image_count = len(model.images)
        log.info(
            "file_ingest_complete",
            filename=source_filename,
            element_count=len(model.elements),
            image_count=image_count,
            duration_ms=ingest_duration,
        )

        # ── Extract styles ────────────────────────────────────────────────
        try:
            style_data = handler.extract_styles(working_path)
            log.info(
                "style_extraction_complete",
                filename=source_filename,
                entry_count=len(style_data) - 1,  # exclude document_level key
            )
        except Exception as exc:
            log.warning("style_extraction_failed", filename=source_filename, error=str(exc))
            style_data = {"document_level": {}}

        # ── Prepare output directory ──────────────────────────────────────
        batch_out = output_dir / batch_id
        batch_out.mkdir(parents=True, exist_ok=True)

        assets_dir = batch_out / "assets"
        assets_dir.mkdir(exist_ok=True)

        originals_dir = batch_out / "_originals"
        originals_dir.mkdir(exist_ok=True)

        # Copy original file to _originals/
        shutil.copy2(file_path, originals_dir / source_filename)
        model.metadata.original_preserved = True

        # ── Save extracted images ──────────────────────────────────────────
        for img_name, img_data in model.images.items():
            img_path = assets_dir / img_name
            img_path.write_bytes(img_data.data)

        # ── Generate output ────────────────────────────────────────────────
        if direction == "to_md":
            output_filename = Path(source_filename).stem + ".md"
            output_path = batch_out / output_filename
            output_format = "md"

            # Set style_ref in metadata
            sidecar_filename = Path(source_filename).stem + ".styles.json"
            model.metadata.style_ref = sidecar_filename
            tier = 2 if style_data.get("elements") else 1
            model.metadata.fidelity_tier = tier

            log.info(
                "export_start",
                filename=source_filename,
                target_format="md",
                tier=tier,
            )
            t_export = time.perf_counter()

            from formats.markdown_handler import MarkdownHandler
            md_handler = MarkdownHandler()
            md_handler.export(model, output_path)

            export_duration = int((time.perf_counter() - t_export) * 1000)
            log.info(
                "export_complete",
                filename=source_filename,
                output_size_bytes=output_path.stat().st_size if output_path.exists() else 0,
                duration_ms=export_duration,
            )

            # ── Write sidecar ──────────────────────────────────────────────
            sidecar = generate_sidecar(model, style_data)
            sidecar_path = batch_out / sidecar_filename
            sidecar_path.write_text(
                json.dumps(sidecar, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        elif direction == "from_md":
            target_fmt = options.get("target_format", "docx")
            output_filename = Path(source_filename).stem + f".{target_fmt}"
            output_path = batch_out / output_filename
            output_format = target_fmt

            target_handler = get_handler_for_path(Path(f"out.{target_fmt}"))
            if target_handler is None:
                raise ValueError(f"No handler for target format: {target_fmt}")

            # ── Look for sidecar next to source (Tier 2) ──────────────────
            sidecar: dict | None = None
            possible_sidecar = file_path.parent / (file_path.stem + ".styles.json")
            if possible_sidecar.exists():
                from core.metadata import load_sidecar
                sidecar = load_sidecar(possible_sidecar)

            # ── Look for original next to source (Tier 3) ─────────────────
            # User can upload the original .docx alongside the .md file.
            original_path: Path | None = None
            if sidecar:
                orig_filename = sidecar.get("source_file", "")
                if orig_filename:
                    candidate = file_path.parent / orig_filename
                    if not candidate.exists():
                        # Try same stem as .md with .docx extension
                        candidate = file_path.parent / (file_path.stem + ".docx")
                else:
                    candidate = file_path.parent / (file_path.stem + ".docx")
                if candidate.exists() and candidate.suffix.lower() in (".docx", ".doc"):
                    original_path = candidate

            # ── Determine fidelity tier ────────────────────────────────────
            if original_path:
                fidelity_tier = 3
            elif sidecar:
                fidelity_tier = 2
            else:
                fidelity_tier = 1

            model.metadata.fidelity_tier = fidelity_tier
            log.info(
                "export_start",
                filename=source_filename,
                target_format=target_fmt,
                tier=fidelity_tier,
            )
            t_export = time.perf_counter()

            target_handler.export(
                model,
                output_path,
                sidecar=sidecar,
                original_path=original_path,
            )

            export_duration = int((time.perf_counter() - t_export) * 1000)
            log.info(
                "export_complete",
                filename=source_filename,
                output_size_bytes=output_path.stat().st_size if output_path.exists() else 0,
                duration_ms=export_duration,
            )
        else:
            raise ValueError(f"Unknown direction: {direction}")

        duration_ms = int((time.perf_counter() - t_start) * 1000)

        result = ConvertResult(
            source_filename=source_filename,
            output_filename=output_filename,
            source_format=source_format,
            output_format=output_format,
            direction=direction,
            batch_id=batch_id,
            status="success",
            output_path=str(output_path),
            source_path=str(file_path),
            file_size_bytes=file_path.stat().st_size,
            fidelity_tier=model.metadata.fidelity_tier,
            warnings=warnings,
            duration_ms=duration_ms,
            protection_type=pw_result.protection_type.value if pw_result else "none",
            password_method=pw_result.method.value if pw_result and pw_result.method.value != "none" else None,
            password_attempts=pw_result.attempts if pw_result else 0,
        )

        # Cleanup decrypted temp file
        if pw_result and working_path != file_path:
            try:
                from core.password_handler import PasswordHandler
                pw_handler_obj = options.get("_password_handler") or PasswordHandler()
                pw_handler_obj.cleanup_temp_file(pw_result)
            except Exception:
                pass

        return result

    except Exception as exc:
        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.error(
            "file_conversion_error",
            filename=source_filename,
            error_type=type(exc).__name__,
            error_msg=str(exc),
            duration_ms=duration_ms,
        )

        # Determine status: password_locked if decryption failed
        status = "error"
        ptype = "none"
        if pw_result and not pw_result.success:
            status = "password_locked"
            ptype = pw_result.protection_type.value

        # Cleanup decrypted temp file on error too
        if pw_result and working_path != file_path:
            try:
                working_path.unlink(missing_ok=True)
            except Exception:
                pass

        return ConvertResult(
            source_filename=source_filename,
            output_filename="",
            source_format=source_format,
            output_format="",
            direction=direction,
            batch_id=batch_id,
            status=status,
            error_message=str(exc),
            source_path=str(file_path),
            file_size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            warnings=warnings,
            duration_ms=duration_ms,
            protection_type=ptype,
            password_method=pw_result.method.value if pw_result and pw_result.method.value != "none" else None,
            password_attempts=pw_result.attempts if pw_result else 0,
        )


def _preview_file_sync(file_path: Path, direction: str) -> PreviewResult:
    """Quick analysis without full conversion."""
    source_filename = file_path.name
    source_format = file_path.suffix.lower().lstrip(".")
    warnings: list[str] = []

    handler = get_handler_for_path(file_path)
    if handler is None:
        return PreviewResult(
            filename=source_filename,
            format=source_format,
            file_size_bytes=file_path.stat().st_size,
            warnings=[f"No handler for .{source_format}"],
        )

    try:
        model = handler.ingest(file_path)
        counts: dict[str, int] = {}
        for elem in model.elements:
            counts[elem.type.value] = counts.get(elem.type.value, 0) + 1

        page_count = model.metadata.page_count
        return PreviewResult(
            filename=source_filename,
            format=source_format,
            file_size_bytes=file_path.stat().st_size,
            page_count=page_count,
            ocr_likely=model.metadata.ocr_applied,
            warnings=model.warnings,
            element_counts=counts,
        )
    except Exception as exc:
        return PreviewResult(
            filename=source_filename,
            format=source_format,
            file_size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            warnings=[str(exc)],
        )


# ── Async orchestrator ─────────────────────────────────────────────────────────

class ConversionOrchestrator:
    """Async wrapper around the synchronous conversion pipeline."""

    def __init__(self, output_base: Path = OUTPUT_BASE) -> None:
        self.output_base = Path(output_base)

    async def convert_batch(
        self,
        file_paths: list[Path],
        direction: str,
        batch_id: str,
        options: dict[str, Any] | None = None,
    ) -> list[ConvertResult]:
        """
        Convert a list of files concurrently (up to MAX_CONCURRENT_CONVERSIONS).
        Records results in the DB and updates batch_state.
        Emits SSE progress events if a queue exists for this batch.
        """
        opts = options or {}
        t_batch = time.perf_counter()
        total = len(file_paths)

        # Create progress queue for SSE streaming
        _progress_queues[batch_id] = asyncio.Queue(maxsize=200)

        bind_batch_context(batch_id, total)
        log.info(
            "conversion_start",
            batch_id=batch_id,
            file_count=total,
            fidelity_tier=opts.get("fidelity_tier", 1),
        )

        await upsert_batch_state(
            batch_id,
            status="processing",
            total_files=total,
            unattended=opts.get("unattended", False),
        )

        tasks = [
            self._convert_one(fp, direction, batch_id, opts, idx, total)
            for idx, fp in enumerate(file_paths)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # Update batch state
        success = sum(1 for r in results if r.status == "success")
        failed = sum(1 for r in results if r.status == "error")
        final_status = "done" if failed == 0 else ("failed" if success == 0 else "partial")
        total_duration_ms = int((time.perf_counter() - t_batch) * 1000)

        log.info(
            "batch_complete",
            batch_id=batch_id,
            success_count=success,
            error_count=failed,
            total_duration_ms=total_duration_ms,
        )

        await upsert_batch_state(
            batch_id,
            status=final_status,
            completed_files=success,
            failed_files=failed,
        )

        # Write batch manifest
        manifest_entries = [
            {
                "source": r.source_filename,
                "output": r.output_filename,
                "format": r.source_format,
                "ocr_applied": r.ocr_applied,
                "ocr_flags": r.ocr_flags_total,
                "fidelity_tier": r.fidelity_tier,
                "status": r.status,
                "error": r.error_message,
                "warnings": r.warnings,
                "duration_ms": r.duration_ms,
            }
            for r in results
        ]
        manifest = generate_manifest(batch_id, manifest_entries)
        manifest_path = self.output_base / batch_id / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Emit final SSE events
        _emit_event(batch_id, "batch_complete", {
            "batch_id": batch_id,
            "success": success,
            "error": failed,
            "total": total,
            "duration_ms": total_duration_ms,
            "download_url": f"/api/batch/{batch_id}/download",
        })
        _emit_event(batch_id, "done", {})

        return list(results)

    async def _convert_one(
        self,
        file_path: Path,
        direction: str,
        batch_id: str,
        options: dict[str, Any],
        index: int = 0,
        total: int = 1,
    ) -> ConvertResult:
        file_id = file_path.stem
        filename = file_path.name
        bind_file_context(
            file_id=file_id,
            filename=filename,
            fmt=file_path.suffix.lower().lstrip("."),
        )

        # Emit file_start
        _emit_event(batch_id, "file_start", {
            "file_id": file_id,
            "filename": filename,
            "index": index + 1,
            "total": total,
        })

        async with _semaphore:
            result = await asyncio.to_thread(
                _convert_file_sync,
                file_path,
                direction,
                batch_id,
                self.output_base,
                options,
            )

        # Record in DB (always — success or failure)
        history_id = await record_conversion({
            "batch_id": result.batch_id,
            "source_filename": result.source_filename,
            "source_format": result.source_format,
            "output_filename": result.output_filename,
            "output_format": result.output_format,
            "direction": result.direction,
            "source_path": result.source_path,
            "output_path": result.output_path,
            "file_size_bytes": result.file_size_bytes,
            "ocr_applied": result.ocr_applied,
            "ocr_flags_total": result.ocr_flags_total,
            "status": result.status,
            "error_message": result.error_message,
            "duration_ms": result.duration_ms,
            "warnings": result.warnings,
            "protection_type": result.protection_type,
            "password_method": result.password_method,
            "password_attempts": result.password_attempts,
        })

        # Record OCR confidence stats if OCR flags exist
        if result.ocr_flags_total > 0 and history_id:
            try:
                flags = await get_flags_for_batch(result.batch_id)
                if flags:
                    confs = [f["confidence"] for f in flags if f.get("confidence") is not None]
                    if confs:
                        threshold_str = await get_preference("ocr_confidence_threshold") or "80"
                        threshold = float(threshold_str)
                        # Group by page for page-level stats
                        pages = set(f["page_num"] for f in flags)
                        await update_history_ocr_stats(
                            history_id=history_id,
                            mean=round(sum(confs) / len(confs), 1),
                            min_conf=round(min(confs), 1),
                            page_count=len(pages),
                            pages_below=sum(1 for c in confs if c < threshold),
                        )
            except Exception as exc:
                log.warning("ocr_stats_record_failed", error=str(exc))

        # Deferred OCR for PDFs that were converted without OCR
        if result.source_format == "pdf" and result.status == "success" and result.ocr_flags_total == 0:
            try:
                await self._check_and_run_deferred_ocr(
                    history_id, result, file_path,
                )
            except Exception as exc:
                log.warning("ocr_deferred_check_failed", error=str(exc))

        # Emit file_complete or file_error
        if result.status == "success":
            _emit_event(batch_id, "file_complete", {
                "file_id": file_id,
                "filename": filename,
                "status": "success",
                "duration_ms": result.duration_ms,
                "output_filename": result.output_filename,
                "tier": result.fidelity_tier,
            })
        else:
            _emit_event(batch_id, "file_error", {
                "file_id": file_id,
                "filename": filename,
                "status": "error",
                "error": result.error_message or "Unknown error",
            })

        # Emit ocr_flag if applicable
        if result.ocr_flags_total > 0:
            _emit_event(batch_id, "ocr_flag", {
                "file_id": file_id,
                "filename": filename,
                "flag_count": result.ocr_flags_total,
                "review_url": f"/review.html?batch_id={batch_id}",
            })

        return result

    async def _check_and_run_deferred_ocr(
        self,
        history_id: int,
        result: "ConvertResult",
        source_path: Path,
    ) -> None:
        """
        Called after a PDF conversion completes. If OCR was not run during
        conversion (ocr_page_count is null) and the PDF likely needs OCR
        and ocr_mode preference is not 'skip', run OCR now and update
        the history record's OCR stats.
        """
        if result.source_format != "pdf" or result.status != "success":
            return
        if result.ocr_flags_total > 0:
            return  # OCR already ran

        # Check user preference
        ocr_mode = await get_preference("unattended_default") or "false"
        ocr_skip = (await get_preference("default_direction")) == "skip"  # Not a real pref but check ocr_mode
        # Actually, check if OCR was needed via the pdf handler
        try:
            from formats.pdf_handler import PdfHandler
            handler = PdfHandler()
            model = await asyncio.to_thread(handler.ingest_with_ocr, source_path, None, result.batch_id)

            scanned_pages = getattr(model, "_scanned_pages", [])
            if not scanned_pages:
                return  # No scanned pages — no OCR needed

            log.info(
                "ocr_deferred_run",
                filename=result.source_filename,
                reason="was_skipped",
                scanned_pages=len(scanned_pages),
            )

            from core.ocr import run_ocr, OCRConfig
            threshold_str = await get_preference("ocr_confidence_threshold") or "80"
            unattended_str = await get_preference("unattended_default") or "false"

            config = OCRConfig(
                confidence_threshold=float(threshold_str),
                unattended=(unattended_str == "true"),
            )
            ocr_result = await run_ocr(
                scanned_pages, config, result.batch_id, result.source_filename
            )

            # Update history OCR stats
            if ocr_result.pages:
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
                    log.info(
                        "ocr_deferred_complete",
                        filename=result.source_filename,
                        pages=len(ocr_result.pages),
                        avg_confidence=round(sum(valid_confs) / len(valid_confs), 1),
                        flags=len(ocr_result.flags),
                    )
        except Exception as exc:
            log.warning("ocr_deferred_failed", filename=result.source_filename, error=str(exc))

    async def preview_file(self, file_path: Path, direction: str = "to_md") -> PreviewResult:
        """Quick analysis without converting."""
        return await asyncio.to_thread(_preview_file_sync, file_path, direction)
