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

import asyncio
import mimetypes
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
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


# ── Preview (browser-native + thumbnail fallback, v0.29.7) ───────────────────

# Browser can render these natively — just stream the raw bytes.
_NATIVE_PREVIEW_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
# Browser CAN'T render these — generate a JPEG thumbnail via PIL.
# .eps uses PIL's EpsImagePlugin which shells out to Ghostscript (/usr/bin/gs).
_THUMBNAIL_PREVIEW_EXTS = {".tif", ".tiff", ".eps"}
_ALL_PREVIEW_EXTS = _NATIVE_PREVIEW_EXTS | _THUMBNAIL_PREVIEW_EXTS

_THUMB_MAX_PX = 400
_THUMB_JPEG_QUALITY = 78
_THUMB_CACHE_SIZE = 64  # ~13 MB at 200 KB avg per thumb — bounded and small
_thumb_cache: "OrderedDict[tuple, bytes]" = OrderedDict()


def _ext_lower(ext: str) -> str:
    return ("." + ext.lstrip(".")).lower()


def _is_previewable(ext: str) -> bool:
    return _ext_lower(ext) in _ALL_PREVIEW_EXTS


def _needs_thumbnail(ext: str) -> bool:
    return _ext_lower(ext) in _THUMBNAIL_PREVIEW_EXTS


def _generate_thumbnail_sync(path: Path) -> bytes:
    """Open `path` with PIL, thumbnail to _THUMB_MAX_PX on the longest edge,
    return JPEG bytes. Runs in a worker thread via asyncio.to_thread; must
    not touch async state."""
    # Import lazily so module load doesn't block on PIL for non-preview
    # requests (PIL pulls in C extensions and can be slow to first-import).
    from PIL import Image

    with Image.open(str(path)) as img:
        img.load()
        # Convert to a JPEG-safe mode. EPS can arrive as CMYK; TIFF may be
        # LA/P/I;16 etc. RGB is the safe common denominator for JPEG.
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((_THUMB_MAX_PX, _THUMB_MAX_PX), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=_THUMB_JPEG_QUALITY, optimize=True)
        return buf.getvalue()


async def _get_cached_thumbnail(path: Path, source_file_id: str) -> bytes:
    """Return cached or freshly-rendered JPEG thumbnail bytes.

    Cache key = (source_file_id, st_mtime_ns, st_size). Any edit to the
    file changes the key so stale thumbs are never served. LRU eviction
    with _THUMB_CACHE_SIZE entries.
    """
    try:
        stat = path.stat()
    except OSError as exc:
        raise HTTPException(
            status_code=404, detail=f"File not accessible: {exc}"
        ) from exc

    cache_key = (source_file_id, stat.st_mtime_ns, stat.st_size)
    hit = _thumb_cache.get(cache_key)
    if hit is not None:
        _thumb_cache.move_to_end(cache_key)
        return hit

    try:
        thumb_bytes = await asyncio.to_thread(_generate_thumbnail_sync, path)
    except Exception as exc:
        # PIL errors bubble up as generic Exception; surface as 500 with
        # the error class + message so operators can diagnose from the
        # browser's network tab without log-diving.
        log.warning(
            "analysis.thumbnail_generation_failed",
            source_file_id=source_file_id,
            path=str(path),
            error=f"{type(exc).__name__}: {exc}",
        )
        raise HTTPException(
            status_code=500,
            detail=f"Thumbnail generation failed: {type(exc).__name__}: {exc}",
        ) from exc

    _thumb_cache[cache_key] = thumb_bytes
    _thumb_cache.move_to_end(cache_key)
    while len(_thumb_cache) > _THUMB_CACHE_SIZE:
        _thumb_cache.popitem(last=False)
    return thumb_bytes


@router.get("/files/{source_file_id}/preview")
async def preview_file(
    source_file_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """
    Inline preview for image files, with automatic thumbnailing for
    formats browsers can't render natively.

    Native serve (raw bytes, correct Content-Type):
      .jpg / .jpeg / .png / .gif / .bmp / .webp

    Thumbnail generation (PIL → 400px JPEG, LRU-cached):
      .tif / .tiff   (PIL native)
      .eps           (PIL EpsImagePlugin → Ghostscript /usr/bin/gs)

    Any other extension returns 404. The (source_file_id, mtime, size)
    cache key means unchanged files serve instantly after the first hit
    and edits invalidate automatically.
    """
    path = await _lookup_source_path(source_file_id)
    if not _is_previewable(path.suffix):
        raise HTTPException(
            status_code=404,
            detail="Preview not available for this file type",
        )

    log.info(
        "analysis.file_access",
        user=user.email,
        source_file_id=source_file_id,
        mode="preview",
        needs_thumbnail=_needs_thumbnail(path.suffix),
    )

    if _needs_thumbnail(path.suffix):
        thumb_bytes = await _get_cached_thumbnail(path, source_file_id)
        return Response(
            content=thumb_bytes,
            media_type="image/jpeg",
            headers={
                # Tell the browser it can safely cache the thumbnail for
                # a short window — the server-side cache key already
                # accounts for mtime so there's no risk of stale data.
                "Cache-Control": "private, max-age=300",
            },
        )

    # Browser-native format: stream raw file.
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path=str(path),
        media_type=media_type or "application/octet-stream",
    )
