"""
Upload, preview, and conversion endpoints.

POST /api/convert        — Upload file(s), specify direction + output location. Returns batch ID.
POST /api/convert/preview — Quick analysis: format detection, page count, OCR likelihood, warnings.
"""

import tempfile
from pathlib import Path

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.models import ConvertResponse, PreviewResponse
from core.converter import (
    ConversionOrchestrator,
    new_batch_id,
    sanitize_filename,
    validate_extension,
    validate_file_size,
    check_zip_bomb,
    DEFAULT_MAX_FILE_MB,
)
from core.database import get_preference, set_preference

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/convert", tags=["convert"])

_orchestrator = ConversionOrchestrator()


# ── POST /api/convert ─────────────────────────────────────────────────────────

@router.post("", response_model=ConvertResponse)
async def convert_files(
    files: list[UploadFile] = File(...),
    direction: str = Form(default="to_md"),
    output_dir: str = Form(default=""),
    target_format: str = Form(default="docx"),
    unattended: bool = Form(default=False),
):
    """
    Upload one or more files and start conversion.

    Returns a batch_id immediately; use GET /api/batch/{batch_id}/status to poll progress.
    """
    if direction not in ("to_md", "from_md"):
        raise HTTPException(status_code=422, detail=f"Invalid direction: {direction}")

    max_mb = int(await get_preference("max_upload_size_mb") or DEFAULT_MAX_FILE_MB)

    # ── Validate all files before starting any conversion ─────────────────
    for uf in files:
        safe_name = sanitize_filename(uf.filename or "file")

        err = validate_extension(safe_name)
        if err:
            raise HTTPException(status_code=422, detail=f"{safe_name}: {err}")

        # Read size — UploadFile doesn't have a reliable .size before reading
        content = await uf.read()
        size_err = validate_file_size(len(content), max_mb)
        if size_err:
            raise HTTPException(status_code=413, detail=f"{safe_name}: {size_err}")
        # Rewind for later use
        await uf.seek(0)

    # ── Write uploaded files to temp directory ────────────────────────────
    batch_id = new_batch_id()
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"mf_{batch_id}_"))

    saved_paths: list[Path] = []
    try:
        for uf in files:
            safe_name = sanitize_filename(uf.filename or "file")
            dest = tmp_dir / safe_name
            content = await uf.read()
            dest.write_bytes(content)

            # Zip-bomb check
            bomb_err = check_zip_bomb(dest)
            if bomb_err:
                raise HTTPException(status_code=422, detail=f"{safe_name}: {bomb_err}")

            saved_paths.append(dest)

        # Update last_source_directory preference (use parent of first file if possible)
        if output_dir:
            await set_preference("last_save_directory", output_dir)

    except HTTPException:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # ── Start conversion (async, non-blocking for caller) ────────────────
    import asyncio

    options = {
        "target_format": target_format,
        "unattended": unattended,
    }

    # Fire-and-forget: run in background so we return batch_id immediately
    asyncio.create_task(
        _run_batch_and_cleanup(saved_paths, direction, batch_id, tmp_dir, options)
    )

    log.info(
        "convert.batch_started",
        batch_id=batch_id,
        file_count=len(saved_paths),
        direction=direction,
    )

    return ConvertResponse(
        batch_id=batch_id,
        total_files=len(saved_paths),
        message="Conversion started.",
    )


async def _run_batch_and_cleanup(
    file_paths: list[Path],
    direction: str,
    batch_id: str,
    tmp_dir: Path,
    options: dict,
) -> None:
    """Background task: run batch conversion, then clean up temp dir."""
    import shutil

    try:
        await _orchestrator.convert_batch(
            file_paths=file_paths,
            direction=direction,
            batch_id=batch_id,
            options=options,
        )
    except Exception as exc:
        log.error("convert.batch_failed", batch_id=batch_id, error=str(exc))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── POST /api/convert/preview ─────────────────────────────────────────────────

@router.post("/preview", response_model=PreviewResponse)
async def preview_file(
    file: UploadFile = File(...),
    direction: str = Form(default="to_md"),
):
    """
    Analyze a file without converting it.

    Returns: format, page count, OCR likelihood, element counts, warnings.
    """
    safe_name = sanitize_filename(file.filename or "file")

    err = validate_extension(safe_name)
    if err:
        raise HTTPException(status_code=422, detail=err)

    content = await file.read()
    max_mb = int(await get_preference("max_upload_size_mb") or DEFAULT_MAX_FILE_MB)
    size_err = validate_file_size(len(content), max_mb)
    if size_err:
        raise HTTPException(status_code=413, detail=size_err)

    # Write to temp file for analysis
    with tempfile.NamedTemporaryFile(
        suffix=Path(safe_name).suffix, delete=False
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        result = await _orchestrator.preview_file(tmp_path, direction)
    finally:
        tmp_path.unlink(missing_ok=True)

    return PreviewResponse(
        filename=safe_name,
        format=result.format,
        file_size_bytes=result.file_size_bytes,
        page_count=result.page_count,
        ocr_likely=result.ocr_likely,
        warnings=result.warnings,
        element_counts=result.element_counts,
    )
