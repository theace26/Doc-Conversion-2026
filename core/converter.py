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

from core.database import record_conversion, upsert_batch_state
from core.metadata import generate_manifest, generate_sidecar
import formats  # noqa: F401 — triggers handler self-registration
from formats.base import get_handler_for_path

log = structlog.get_logger(__name__)

# Allowed extensions for upload
ALLOWED_EXTENSIONS = {".docx", ".doc", ".pdf", ".pptx", ".xlsx", ".csv", ".md"}

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
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0


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
        "converter.start",
        stage="start",
        batch_id=batch_id,
        file_name=source_filename,
        direction=direction,
    )

    try:
        # ── Get format handler ────────────────────────────────────────────
        handler = get_handler_for_path(file_path)
        if handler is None:
            raise ValueError(f"No handler registered for .{source_format}")

        # ── Ingest ────────────────────────────────────────────────────────
        log.info("converter.ingest", stage="ingest", file_name=source_filename)
        model = handler.ingest(file_path)
        model.metadata.source_file = source_filename
        model.metadata.source_format = source_format
        model.metadata.converted_at = datetime.now(timezone.utc).isoformat()
        warnings.extend(model.warnings)

        # ── Extract styles ────────────────────────────────────────────────
        log.info("converter.extract_styles", stage="extract_styles", file_name=source_filename)
        try:
            style_data = handler.extract_styles(file_path)
        except Exception as exc:
            log.warning("converter.style_extract_failed", error=str(exc))
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
            model.metadata.fidelity_tier = 2 if style_data.get("elements") else 1

            from formats.markdown_handler import MarkdownHandler
            md_handler = MarkdownHandler()
            md_handler.export(model, output_path)

            log.info(
                "converter.export",
                stage="export",
                file_name=source_filename,
                output=output_filename,
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

            # Look for sidecar next to source
            sidecar: dict | None = None
            possible_sidecar = file_path.parent / (file_path.stem + ".styles.json")
            if possible_sidecar.exists():
                from core.metadata import load_sidecar
                sidecar = load_sidecar(possible_sidecar)

            target_handler.export(model, output_path, sidecar=sidecar)
        else:
            raise ValueError(f"Unknown direction: {direction}")

        duration_ms = int((time.perf_counter() - t_start) * 1000)

        log.info(
            "converter.done",
            stage="done",
            batch_id=batch_id,
            file_name=source_filename,
            output=output_filename,
            duration_ms=duration_ms,
        )

        return ConvertResult(
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
            warnings=warnings,
            duration_ms=duration_ms,
        )

    except Exception as exc:
        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.error(
            "converter.error",
            stage="error",
            batch_id=batch_id,
            file_name=source_filename,
            error=str(exc),
            duration_ms=duration_ms,
        )
        return ConvertResult(
            source_filename=source_filename,
            output_filename="",
            source_format=source_format,
            output_format="",
            direction=direction,
            batch_id=batch_id,
            status="error",
            error_message=str(exc),
            source_path=str(file_path),
            file_size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            warnings=warnings,
            duration_ms=duration_ms,
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
        """
        opts = options or {}

        await upsert_batch_state(
            batch_id,
            status="processing",
            total_files=len(file_paths),
            unattended=opts.get("unattended", False),
        )

        tasks = [
            self._convert_one(fp, direction, batch_id, opts)
            for fp in file_paths
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # Update batch state
        success = sum(1 for r in results if r.status == "success")
        failed = sum(1 for r in results if r.status == "error")
        final_status = "done" if failed == 0 else ("failed" if success == 0 else "partial")

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

        return list(results)

    async def _convert_one(
        self,
        file_path: Path,
        direction: str,
        batch_id: str,
        options: dict[str, Any],
    ) -> ConvertResult:
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
        await record_conversion({
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
        })

        return result

    async def preview_file(self, file_path: Path, direction: str = "to_md") -> PreviewResult:
        """Quick analysis without converting."""
        return await asyncio.to_thread(_preview_file_sync, file_path, direction)
