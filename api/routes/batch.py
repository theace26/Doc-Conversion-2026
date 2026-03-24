"""
Batch status and download endpoints.

GET /api/batch/{batch_id}/status           — Batch progress (per-file status, OCR flags pending).
GET /api/batch/{batch_id}/download         — Download converted files (zip of all files).
GET /api/batch/{batch_id}/download/{filename} — Download single converted file.
GET /api/batch/{batch_id}/manifest         — Retrieve batch manifest JSON.
"""

import asyncio
import io
import json
import zipfile
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from api.models import BatchStatus, FileStatus
from core.converter import OUTPUT_BASE, get_progress_queue, _progress_queues
from core.database import db_fetch_all, get_batch_state

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/batch", tags=["batch"])


def _batch_dir(batch_id: str) -> Path:
    return OUTPUT_BASE / batch_id


def _validate_batch_id(batch_id: str) -> None:
    """Reject batch IDs with path traversal characters."""
    import re
    if not re.match(r"^[\w\-]+$", batch_id):
        raise HTTPException(status_code=400, detail="Invalid batch_id format.")


# ── GET /api/batch/{batch_id}/status ─────────────────────────────────────────

@router.get("/{batch_id}/status", response_model=BatchStatus)
async def batch_status(batch_id: str):
    """Return current batch status and per-file details."""
    _validate_batch_id(batch_id)
    log.info("batch_status_request", batch_id=batch_id)

    state = await get_batch_state(batch_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")

    # Pull per-file records from history
    rows = await db_fetch_all(
        "SELECT * FROM conversion_history WHERE batch_id = ? ORDER BY id",
        (batch_id,),
    )

    files: list[FileStatus] = []
    for row in rows:
        import json as _json
        warnings_raw = row.get("warnings") or "[]"
        try:
            warnings = _json.loads(warnings_raw) if isinstance(warnings_raw, str) else warnings_raw
        except Exception:
            warnings = []
        files.append(FileStatus(
            source=row["source_filename"],
            output=row.get("output_filename", ""),
            format=row["source_format"],
            status=row["status"],
            error=row.get("error_message"),
            warnings=warnings,
            duration_ms=row.get("duration_ms") or 0,
            ocr_applied=bool(row.get("ocr_applied", False)),
            ocr_flags=row.get("ocr_flags_total") or 0,
        ))

    return BatchStatus(
        batch_id=batch_id,
        status=state["status"],
        total_files=state["total_files"],
        completed_files=state.get("completed_files", 0),
        failed_files=state.get("failed_files", 0),
        ocr_flags_pending=state.get("ocr_flags_pending", 0),
        unattended=bool(state.get("unattended", False)),
        created_at=str(state.get("created_at") or ""),
        updated_at=str(state.get("updated_at") or ""),
        files=files,
    )


# ── GET /api/batch/{batch_id}/stream (SSE) ────────────────────────────────────

@router.get("/{batch_id}/stream")
async def batch_stream(batch_id: str, request: Request):
    """
    Server-Sent Events stream for live batch progress.

    Streams file_start, file_complete, file_error, ocr_flag, batch_complete,
    and done events. If the batch is already complete, replays final state
    from DB and closes immediately.
    """
    _validate_batch_id(batch_id)

    state = await get_batch_state(batch_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")

    async def event_generator():
        event_id = 0

        # If batch is already complete, replay from DB
        if state["status"] in ("done", "partial", "failed"):
            rows = await db_fetch_all(
                "SELECT * FROM conversion_history WHERE batch_id = ? ORDER BY id",
                (batch_id,),
            )
            for row in rows:
                event_id += 1
                if row["status"] == "success":
                    yield _format_sse("file_complete", {
                        "file_id": row.get("source_filename", "").rsplit(".", 1)[0],
                        "filename": row["source_filename"],
                        "status": "success",
                        "duration_ms": row.get("duration_ms") or 0,
                        "output_filename": row.get("output_filename", ""),
                        "tier": 1,
                    }, event_id)
                else:
                    yield _format_sse("file_error", {
                        "file_id": row.get("source_filename", "").rsplit(".", 1)[0],
                        "filename": row["source_filename"],
                        "status": "error",
                        "error": row.get("error_message") or "Unknown error",
                    }, event_id)

            success = sum(1 for r in rows if r["status"] == "success")
            failed = len(rows) - success
            event_id += 1
            yield _format_sse("batch_complete", {
                "batch_id": batch_id,
                "success": success,
                "error": failed,
                "total": len(rows),
                "duration_ms": 0,
                "download_url": f"/api/batch/{batch_id}/download",
            }, event_id)

            event_id += 1
            yield _format_sse("done", {}, event_id)
            return

        # Stream live events from progress queue
        queue = get_progress_queue(batch_id)
        if queue is None:
            # Queue doesn't exist yet — wait briefly for it to appear
            for _ in range(10):
                await asyncio.sleep(0.2)
                queue = get_progress_queue(batch_id)
                if queue is not None:
                    break
            if queue is None:
                yield _format_sse("done", {}, 0)
                return

        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send keep-alive comment
                yield ": keepalive\n\n"
                continue

            event_id += 1
            yield _format_sse(msg["event"], msg["data"], event_id)

            if msg["event"] == "done":
                break

        # Cleanup queue after stream ends
        _progress_queues.pop(batch_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse(event: str, data: dict, event_id: int = 0) -> str:
    """Format a single SSE message."""
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


# ── GET /api/batch/{batch_id}/download ────────────────────────────────────────

@router.get("/{batch_id}/download")
async def download_batch(batch_id: str):
    """Download all converted files as a zip archive."""
    _validate_batch_id(batch_id)

    batch_dir = _batch_dir(batch_id)
    if not batch_dir.exists():
        raise HTTPException(status_code=404, detail=f"Batch directory not found: {batch_id}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in batch_dir.rglob("*"):
            if path.is_file() and "_originals" not in path.parts:
                zf.write(path, path.relative_to(batch_dir))
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{batch_id}.zip"'},
    )


# ── GET /api/batch/{batch_id}/download/{filename} ─────────────────────────────

@router.get("/{batch_id}/download/{filename}")
async def download_file(batch_id: str, filename: str):
    """Download a single converted file from a batch."""
    _validate_batch_id(batch_id)

    # Prevent path traversal in filename
    safe_name = Path(filename).name
    file_path = _batch_dir(batch_id) / safe_name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    return FileResponse(
        path=str(file_path),
        filename=safe_name,
        media_type="application/octet-stream",
    )


# ── GET /api/batch/{batch_id}/manifest ────────────────────────────────────────

@router.get("/{batch_id}/manifest")
async def batch_manifest(batch_id: str):
    """Return the batch manifest JSON."""
    _validate_batch_id(batch_id)

    manifest_path = _batch_dir(batch_id) / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail=f"Manifest not found for batch: {batch_id}")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return JSONResponse(content=data)
