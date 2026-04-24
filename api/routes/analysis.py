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
    get_pending_files,
    is_image_extension,
)

_VALID_STATUS_FILTERS = {"pending", "batched", "completed", "failed", "excluded"}


def _parse_status_filter(status: str | None) -> str | None:
    """Return a validated status filter or raise 400."""
    if status is None or status == "":
        return None
    if status not in _VALID_STATUS_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid status; must be one of {sorted(_VALID_STATUS_FILTERS)}",
        )
    return status
from core.db.connection import db_fetch_one, db_fetch_all
from core.path_utils import is_path_under_allowed_root

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
    status: str | None = None,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """List all analysis batches.

    Optional `?status=` filter restricts per-batch counts/sizes to
    rows with that status (v0.29.4). Batches with zero matching rows
    are omitted. Derived batch status is unaffected by the filter.
    """
    filt = _parse_status_filter(status)
    batches = await get_batches(status_filter=filt)
    return {"batches": batches}


@router.get("/batches/{batch_id}/files")
async def batch_files(
    batch_id: str,
    status: str | None = None,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return files in a batch.

    Optional `?status=` filter restricts to rows with that status.
    """
    filt = _parse_status_filter(status)
    files = await get_batch_files(batch_id, status_filter=filt)
    return {"files": files}


@router.get("/pending-files")
async def pending_files(
    limit: int = 100,
    offset: int = 0,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return unbatched pending files, paginated (v0.29.4).

    Pending rows have `batch_id IS NULL` so they're invisible to
    /batches. The batch-management page renders them as a synthetic
    "Pending (not yet batched)" pseudo-batch when the Pending counter
    is clicked.
    """
    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=400, detail="limit must be between 1 and 500"
        )
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    return await get_pending_files(limit=limit, offset=offset)


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


@router.get("/queue/{entry_id}")
async def queue_entry(
    entry_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return the full analysis_queue row for one id (v0.29.5).

    Powers the "View analysis result" context-menu item on the Batch
    Management page. `description` + `extracted_text` are populated for
    completed rows, `error` for failed rows; pending / batched rows
    return status-only info.
    """
    row = await db_fetch_one(
        """SELECT id, source_path, status, batch_id, content_hash,
                  enqueued_at, batched_at, analyzed_at,
                  description, extracted_text, error,
                  provider_id, model, tokens_used, retry_count
           FROM analysis_queue
           WHERE id = ?""",
        (entry_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Analysis entry not found")
    return dict(row)


async def _lookup_source_path(source_file_id: str) -> Path:
    """
    Return the absolute Path for a source_files.id, or raise 404.

    Confines the returned path to one of the configured mount roots
    (BULK_SOURCE_PATH, BULK_OUTPUT_PATH, /host/<drive>) via
    `is_path_under_allowed_root`. If the DB ever contains a crafted or
    symlinked path that resolves outside those roots, we raise 404
    (same response as "not found" — don't leak existence).
    """
    row = await db_fetch_one(
        "SELECT source_path FROM source_files WHERE id = ?", (source_file_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    p = Path(row["source_path"])
    if not p.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    if not is_path_under_allowed_root(p):
        # Don't leak existence — mirror the "not found" response.
        log.warning(
            "analysis.file_access_denied",
            source_file_id=source_file_id,
            reason="path_outside_allowed_roots",
        )
        raise HTTPException(status_code=404, detail="File not found")
    return p


@router.get("/files/{source_file_id}/download")
async def download_file(
    source_file_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> FileResponse:
    """Stream the source file by source_files.id."""
    path = await _lookup_source_path(source_file_id)
    log.info(
        "analysis.file_access",
        user=user.email,
        source_file_id=source_file_id,
        mode="download",
    )
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
    if not is_image_extension(path.suffix):
        raise HTTPException(status_code=404, detail="Preview not available for this file type")
    log.info(
        "analysis.file_access",
        user=user.email,
        source_file_id=source_file_id,
        mode="preview",
    )
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path=str(path),
        media_type=media_type or "application/octet-stream",
    )
