"""
Image analysis queue management API.

POST /api/analysis/pause                      — pause batch submission
POST /api/analysis/resume                     — resume batch submission
GET  /api/analysis/status                     — pause flag + per-status counts
POST /api/analysis/cancel-pending             — reset batched rows to pending
GET  /api/analysis/batches                    — list batches
GET  /api/analysis/batches/{batch_id}/files   — files in a batch
POST /api/analysis/exclude                    — mark rows excluded
GET  /api/analysis/files/{source_file_id}/download — stream the source file
GET  /api/analysis/files/{source_file_id}/preview  — serve image file inline

All endpoints require OPERATOR role (admin/manager also permitted via role
hierarchy).

Note: /files/* download + preview endpoints live here (rather than a separate
files router) for cohesion with the batch management UI, which is the sole
consumer. If additional file-serving endpoints accumulate outside the analysis
context, a dedicated `api/routes/files.py` would be the right place to split
them out.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.auth import AuthenticatedUser, UserRole, require_role
from core.database import get_preference, set_preference
from core.db.analysis import (
    cancel_all_batched,
    exclude_files,
    get_analysis_stats,
    get_batch_files,
    get_batches,
)
from core.db.connection import db_fetch_one, db_fetch_all

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ── Pydantic bodies ──────────────────────────────────────────────────────────

class ExcludeRequest(BaseModel):
    file_ids: list[str]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/pause")
async def pause_analysis(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Set analysis_submission_paused=true."""
    await set_preference("analysis_submission_paused", "true")
    log.info("analysis.paused", user=user.email)
    return {"status": "paused"}


@router.post("/resume")
async def resume_analysis(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Set analysis_submission_paused=false."""
    await set_preference("analysis_submission_paused", "false")
    log.info("analysis.resumed", user=user.email)
    return {"status": "running"}


@router.get("/status")
async def analysis_status(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return pause flag + per-status counts (including excluded)."""
    paused = (await get_preference("analysis_submission_paused")) == "true"
    stats = await get_analysis_stats()

    # get_analysis_stats only populates the 4 canonical statuses; query
    # excluded directly.
    excl_row = await db_fetch_one(
        "SELECT COUNT(*) AS cnt FROM analysis_queue WHERE status = 'excluded'"
    )
    excluded_count = excl_row["cnt"] if excl_row else 0

    counts = {
        "pending": stats.get("pending", 0),
        "batched": stats.get("batched", 0),
        "completed": stats.get("completed", 0),
        "failed": stats.get("failed", 0),
        "excluded": excluded_count,
    }
    return {"paused": paused, "counts": counts}


@router.post("/cancel-pending")
async def cancel_pending(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Reset all batched rows back to pending."""
    reset = await cancel_all_batched()
    log.info("analysis.cancel_pending", user=user.email, reset=reset)
    return {"reset": reset}


@router.get("/batches")
async def list_batches(
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """List all analysis batches."""
    batches = await get_batches()
    return {"batches": batches}


@router.get("/batches/{batch_id}/files")
async def batch_files(
    batch_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return files in a batch."""
    files = await get_batch_files(batch_id)
    return {"files": files}


@router.post("/exclude")
async def exclude(
    body: ExcludeRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Mark the given analysis_queue ids as excluded."""
    count = await exclude_files(body.file_ids)
    log.info(
        "analysis.exclude",
        user=user.email,
        requested=len(body.file_ids),
        excluded=count,
    )
    return {"excluded": count}


async def _lookup_source_path(source_file_id: str) -> Path:
    """Return the absolute Path for a source_files.id, or raise 404."""
    row = await db_fetch_one(
        "SELECT source_path FROM source_files WHERE id = ?", (source_file_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    p = Path(row["source_path"])
    if not p.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return p


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp"}


@router.get("/files/{source_file_id}/download")
async def download_file(
    source_file_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> FileResponse:
    """Stream the source file by source_files.id."""
    path = await _lookup_source_path(source_file_id)
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type=media_type or "application/octet-stream",
    )


@router.get("/files/{source_file_id}/preview")
async def preview_file(
    source_file_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> FileResponse:
    """
    Return an inline preview for image files.

    v1: serves the raw image file with proper Content-Type. Non-image files
    return 404. A future enhancement could generate a PIL thumbnail here.
    """
    path = await _lookup_source_path(source_file_id)
    ext = path.suffix.lower()
    if ext not in _IMAGE_EXTS:
        raise HTTPException(status_code=404, detail="Preview not available for this file type")
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path=str(path),
        media_type=media_type or "application/octet-stream",
    )
